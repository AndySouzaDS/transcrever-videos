"""CLI principal: costura o pipeline de transcrição + revisão."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import audio, cache, revisao, saida, transcricao
from .config import (
    DEFAULT_MODELO_LLM,
    DEFAULT_MODELO_WHISPER,
    Config,
    projeto_root,
)

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Transcrição fiel de vídeos (.mkv) com Whisper local + revisão via OpenRouter.",
)
console = Console()


def _carregar_glossario(caminho: Optional[Path]) -> list[str]:
    if caminho is None:
        return []
    if not caminho.exists():
        raise typer.BadParameter(f"Glossário não encontrado: {caminho}")

    termos: list[str] = []
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        t = linha.strip()
        if t and not t.startswith("#"):
            termos.append(t)
    return termos


def _formatar_duracao(segundos: float) -> str:
    h = int(segundos // 3600)
    m = int((segundos % 3600) // 60)
    s = int(segundos % 60)
    if h:
        return f"{h}h{m:02d}m{s:02d}s"
    return f"{m}m{s:02d}s"


@app.command()
def main(
    video: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Caminho do vídeo (.mkv, .mp4, etc.) ou áudio .wav já extraído.",
    ),
    tema: str = typer.Option(
        ...,
        "--tema",
        "-t",
        help="Tema do vídeo (obrigatório — melhora a fidelidade de termos técnicos).",
    ),
    glossario: Optional[Path] = typer.Option(
        None,
        "--glossario",
        "-g",
        help="Arquivo .txt com 1 termo por linha (nomes próprios, marcas, termos técnicos).",
    ),
    modelo_whisper: str = typer.Option(
        DEFAULT_MODELO_WHISPER,
        "--modelo-whisper",
        help="Modelo do Whisper: tiny, base, small, medium, large-v3.",
    ),
    device: str = typer.Option(
        "auto",
        "--device",
        help="Device do Whisper: cpu, cuda ou auto.",
    ),
    compute_type: str = typer.Option(
        "auto",
        "--compute-type",
        help="Compute type: int8, float16, float32 ou auto. Use int8 em CPU p/ velocidade.",
    ),
    modelo_llm: str = typer.Option(
        DEFAULT_MODELO_LLM,
        "--modelo-llm",
        help="Modelo OpenRouter para a revisão.",
    ),
    saida_dir: Path = typer.Option(
        None,
        "--saida",
        "-o",
        help="Diretório de saída. Default: ./saidas/<nome-do-video>/",
    ),
    sem_revisao: bool = typer.Option(
        False,
        "--sem-revisao",
        help="Pula a etapa de revisão via LLM (só usa o Whisper).",
    ),
    forcar: bool = typer.Option(
        False,
        "--forcar",
        help="Ignora cache e reprocessa o áudio do zero.",
    ),
) -> None:
    """Transcreve um vídeo com fidelidade de termos técnicos e nomes próprios."""
    cfg = Config.from_env(
        modelo_whisper=modelo_whisper,
        modelo_llm=modelo_llm,
        device=device,
        compute_type=compute_type,
        sem_revisao=sem_revisao,
        forcar=forcar,
    )

    # Validações iniciais
    if not audio.ja_e_wav_valido(video) and not audio.ffmpeg_disponivel():
        raise typer.BadParameter(
            "ffmpeg não encontrado no PATH. Instale com: sudo apt install ffmpeg"
        )

    if not cfg.sem_revisao and not cfg.openrouter_api_key:
        console.print(
            "[yellow]⚠ OPENROUTER_API_KEY não definida — revisão via LLM será pulada.[/]"
        )
        console.print(
            "[yellow]  Defina no .env ou use --sem-revisao para silenciar este aviso.[/]"
        )
        cfg = Config(
            openrouter_api_key=cfg.openrouter_api_key,
            modelo_llm=cfg.modelo_llm,
            modelo_whisper=cfg.modelo_whisper,
            device=cfg.device,
            compute_type=cfg.compute_type,
            sem_revisao=True,
            forcar=cfg.forcar,
        )

    # Setup
    glossario_termos = _carregar_glossario(glossario)
    saida_dir = (saida_dir or Path("./saidas") / video.stem).resolve()
    saida_dir.mkdir(parents=True, exist_ok=True)

    console.print(Panel.fit(
        f"[bold]Vídeo:[/] {video.name}\n"
        f"[bold]Tema:[/] {tema}\n"
        f"[bold]Glossário:[/] {len(glossario_termos)} termo(s)\n"
        f"[bold]Whisper:[/] {cfg.modelo_whisper} "
        f"(device={cfg.device}, compute={cfg.compute_type})\n"
        f"[bold]LLM:[/] {cfg.modelo_llm} {'(desligado)' if cfg.sem_revisao else ''}\n"
        f"[bold]Saída:[/] {saida_dir}",
        title="Transcrição de vídeo",
    ))

    inicio_total = time.time()

    # ── 1) Extrair áudio (ou copiar se já for .wav) ──
    wav_path = saida_dir / "audio.wav"
    if audio.ja_e_wav_valido(video):
        console.print(f"\n[bold cyan]1/4[/] Entrada já é .wav — pulando ffmpeg…")
        t0 = time.time()
        audio.extrair_wav(video, wav_path)
        console.print(f"   ✓ {wav_path.name} ({_formatar_duracao(time.time() - t0)})")
    else:
        console.print("\n[bold cyan]1/4[/] Extraindo áudio com ffmpeg…")
        t0 = time.time()
        audio.extrair_wav(video, wav_path)
        console.print(f"   ✓ {wav_path.name} ({_formatar_duracao(time.time() - t0)})")

    # ── 2) Hash + cache ──
    console.print("\n[bold cyan]2/4[/] Verificando cache…")
    hash_audio = cache.hash_arquivo(wav_path)
    json_bruto = saida_dir / "transcricao_bruta.json"
    transcricao_obj: transcricao.Transcricao | None = None

    if not cfg.forcar and cache.cache_valido(saida_dir, hash_audio) and json_bruto.exists():
        console.print("   ✓ Cache válido — pulando transcrição do Whisper.")
        transcricao_obj = _carregar_transcricao(json_bruto)
    else:
        # ── 3) Transcrição com Whisper ──
        console.print(
            f"\n[bold cyan]3/4[/] Transcrevendo com faster-whisper ({cfg.modelo_whisper})…"
        )
        t0 = time.time()
        transcricao_obj = transcricao.transcrever(
            wav_path,
            modelo=cfg.modelo_whisper,
            tema=tema,
            glossario=glossario_termos,
            device=cfg.device,
            compute_type=cfg.compute_type,
        )
        dur_whisper = time.time() - t0
        console.print(
            f"   ✓ {len(transcricao_obj.segmentos)} segmentos, "
            f"idioma={transcricao_obj.idioma}, "
            f"duração={_formatar_duracao(transcricao_obj.duracao)}"
        )
        console.print(f"   ✓ Whisper levou {_formatar_duracao(dur_whisper)}")

        # Salva JSON bruto (sempre)
        json_bruto.write_text(
            json.dumps(transcricao_obj.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        cache.gravar_cache(saida_dir, hash_audio)

    # ── 4) Revisão com LLM (opcional) ──
    texto_final = transcricao_obj.texto_completo
    revisao_meta: dict | None = None
    if not cfg.sem_revisao:
        console.print(
            f"\n[bold cyan]4/4[/] Revisando com OpenRouter ({cfg.modelo_llm})…"
        )
        t0 = time.time()
        try:
            resultado = revisao.revisar_com_openrouter(
                transcricao_obj.texto_completo,
                tema=tema,
                glossario=glossario_termos,
                modelo=cfg.modelo_llm,
                api_key=cfg.openrouter_api_key,
            )
            texto_final = resultado.texto
            revisao_meta = {
                "modelo": resultado.modelo,
                "duracao_segundos": resultado.duracao_segundos,
                "tentativas": resultado.tentativas,
            }
            console.print(
                f"   ✓ Revisão concluída em {_formatar_duracao(resultado.duracao_segundos)}"
            )
        except Exception as e:
            console.print(f"[red]⚠ Falha na revisão LLM: {e}[/]")
            console.print("   Seguindo com a transcrição bruta do Whisper.")
            texto_final = transcricao_obj.texto_completo
            revisao_meta = {"erro": str(e)}
    else:
        console.print("\n[bold cyan]4/4[/] Revisão via LLM pulada (--sem-revisao).")

    # ── 5) Gerar saídas ──
    caminhos = saida.escrever_transcricao(
        segmentos=transcricao_obj.segmentos,
        texto=texto_final,
        idioma=transcricao_obj.idioma,
        duracao=transcricao_obj.duracao,
        origem_video=video,
        destino_dir=saida_dir,
        modelo_whisper=cfg.modelo_whisper,
        modelo_llm=cfg.modelo_llm,
        revisado=not cfg.sem_revisao,
        revisao_meta=revisao_meta,
    )

    # ── Resumo final ──
    duracao_total = time.time() - inicio_total
    palavras = len(texto_final.split())

    tabela = Table(title="Resumo", show_header=False, padding=(0, 2))
    tabela.add_column("Métrica", style="cyan")
    tabela.add_column("Valor", style="bold")
    tabela.add_row("Duração do áudio", _formatar_duracao(transcricao_obj.duracao))
    tabela.add_row("Palavras", str(palavras))
    tabela.add_row("Segmentos", str(len(transcricao_obj.segmentos)))
    tabela.add_row("Tempo total de processamento", _formatar_duracao(duracao_total))
    tabela.add_row("Revisado por LLM", "sim" if not cfg.sem_revisao and not revisao_meta.get("erro") else "não")
    console.print()
    console.print(tabela)

    console.print("\n[bold green]Arquivos gerados:[/]")
    for formato, p in caminhos.items():
        console.print(f"   .{formato}  →  {p}")


def _carregar_transcricao(json_path: Path) -> transcricao.Transcricao:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    segmentos = [
        transcricao.Segmento(
            inicio=s["inicio"],
            fim=s["fim"],
            texto=s["texto"],
            palavras=s.get("palavras", []),
            probabilidade_media=s.get("probabilidade_media", 0.0),
        )
        for s in data["segmentos"]
    ]
    return transcricao.Transcricao(
        idioma=data["idioma"],
        duracao=data["duracao"],
        segmentos=segmentos,
        texto_completo=data["texto_completo"],
    )


if __name__ == "__main__":
    app()
