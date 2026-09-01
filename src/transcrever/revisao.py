"""Revisão de transcrição via OpenRouter (modelo de linguagem)."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

import httpx

from .config import OPENROUTER_URL


SYSTEM_PROMPT = """Você é um revisor técnico de transcrições em português brasileiro.

Regras:
- Mantenha fidelidade absoluta ao conteúdo falado. Não invente, não resuma, não omita.
- Use EXATAMENTE as grafias do glossário fornecido pelo usuário (nomes próprios, termos técnicos, marcas, siglas).
- Corrija APENAS erros óbvios de grafia, pontuação, acentuação e segmentação de frases.
- Preserve a estrutura de parágrafos do texto original.
- Se o original estiver razoável, altere o mínimo possível.

Saída: apenas o texto revisado, sem comentários, sem marcadores."""


def montar_user_prompt(tema: str, glossario: list[str], texto: str) -> str:
    partes: list[str] = []

    partes.append(f"TEMA DO VÍDEO: {tema}")

    if glossario:
        termos = "\n".join(f"- {t}" for t in glossario)
        partes.append(f"\nGLOSSÁRIO (use estas grafias exatas):\n{termos}")
    else:
        partes.append("\n(Nenhum glossário fornecido.)")

    partes.append(f"\nTRANSCRIÇÃO BRUTA:\n{texto}")
    partes.append("\nSAÍDA: o texto revisado, sem comentários.")

    return "\n".join(partes)


@dataclass
class ResultadoRevisao:
    texto: str
    modelo: str
    duracao_segundos: float
    tentativas: int


def revisar_com_openrouter(
    texto: str,
    *,
    tema: str,
    glossario: list[str] | None = None,
    modelo: str | None = None,
    api_key: str | None = None,
    max_tentativas: int = 3,
    timeout_seg: float = 180.0,
) -> ResultadoRevisao:
    """
    Envia a transcrição bruta para o OpenRouter revisar.

    Estratégia:
    - system prompt: regras de fidelidade
    - user prompt: tema + glossário + texto bruto
    - retry com backoff exponencial em caso de erro de rede/limite
    - se o texto for muito grande (> 80k chars), divide em pedaços
    """
    api_key = api_key or os.getenv("OPENROUTER_API_KEY")
    modelo = modelo or os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")

    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY não definida. "
            "Defina no .env ou use --sem-revisao para pular esta etapa."
        )

    # Se for muito grande, divide em chunks com sobreposição pequena
    MAX_CHARS = 80_000
    if len(texto) <= MAX_CHARS:
        return _chamar_openrouter(
            texto,
            tema=tema,
            glossario=glossario or [],
            modelo=modelo,
            api_key=api_key,
            max_tentativas=max_tentativas,
            timeout_seg=timeout_seg,
        )

    # Texto grande: divide por sentenças (heurística simples)
    pedacos = _dividir_texto(texto, MAX_CHARS)
    textos_revisados: list[str] = []
    total_tempo = 0.0
    tentativas_total = 0

    from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold magenta]Revisando"),
        TimeElapsedColumn(),
        transient=True,
    ) as progress:
        task = progress.add_task("revisando", total=len(pedacos))
        for pedaco in pedacos:
            res = _chamar_openrouter(
                pedaco,
                tema=tema,
                glossario=glossario or [],
                modelo=modelo,
                api_key=api_key,
                max_tentativas=max_tentativas,
                timeout_seg=timeout_seg,
            )
            textos_revisados.append(res.texto)
            total_tempo += res.duracao_segundos
            tentativas_total += res.tentativas
            progress.update(task, advance=1)

    return ResultadoRevisao(
        texto="\n\n".join(textos_revisados).strip(),
        modelo=modelo,
        duracao_segundos=total_tempo,
        tentativas=tentativas_total,
    )


def _chamar_openrouter(
    texto: str,
    *,
    tema: str,
    glossario: list[str],
    modelo: str,
    api_key: str,
    max_tentativas: int,
    timeout_seg: float,
) -> ResultadoRevisao:
    user_prompt = montar_user_prompt(tema, glossario, texto)

    payload = {
        "model": modelo,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,  # baixa temperatura → revisão mais determinística
        "max_tokens": 4000,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        # recomendado pela OpenRouter para identificar a app
        "HTTP-Referer": "https://github.com/local/script-transcricao-videos",
        "X-Title": "script-transcricao-videos",
    }

    inicio = time.time()
    ultimo_erro: Exception | None = None
    for tentativa in range(1, max_tentativas + 1):
        try:
            with httpx.Client(timeout=timeout_seg) as client:
                resp = client.post(OPENROUTER_URL, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()

            conteudo = data["choices"][0]["message"]["content"]
            return ResultadoRevisao(
                texto=conteudo.strip(),
                modelo=modelo,
                duracao_segundos=time.time() - inicio,
                tentativas=tentativa,
            )
        except (httpx.HTTPError, KeyError, ValueError) as e:
            ultimo_erro = e
            if tentativa < max_tentativas:
                espera = 2 ** tentativa  # 2s, 4s, 8s...
                time.sleep(espera)
                continue
            break

    raise RuntimeError(
        f"Falha ao chamar OpenRouter após {max_tentativas} tentativas: {ultimo_erro}"
    )


def _dividir_texto(texto: str, max_chars: int) -> list[str]:
    """Divide o texto em pedaços de até max_chars, quebrando em sentenças."""
    sentencas = texto.replace("\n", " ").split(". ")
    pedacos: list[str] = []
    atual: list[str] = []
    tamanho = 0

    for s in sentencas:
        s_norm = s.strip()
        if not s_norm:
            continue
        s_norm = s_norm if s_norm.endswith((".", "!", "?")) else s_norm + "."
        pedaco_len = len(s_norm) + 2  # ". "
        if tamanho + pedaco_len > max_chars and atual:
            pedacos.append(" ".join(atual).strip())
            atual = [s_norm]
            tamanho = pedaco_len
        else:
            atual.append(s_norm)
            tamanho += pedaco_len

    if atual:
        pedacos.append(" ".join(atual).strip())

    return pedacos
