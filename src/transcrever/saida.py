"""Geração dos arquivos de saída: .txt, .srt, .md, .json."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from .transcricao import Segmento


def _fmt_ts(segundos: float) -> str:
    """HH:MM:SS,mmm para SRT."""
    if segundos < 0:
        segundos = 0.0
    h = int(segundos // 3600)
    m = int((segundos % 3600) // 60)
    s = segundos - (h * 3600) - (m * 60)
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def _fmt_ts_curto(segundos: float) -> str:
    """MM:SS para MD inline."""
    m = int(segundos // 60)
    s = int(segundos % 60)
    return f"{m:02d}:{s:02d}"


def escrever_txt(texto: str, destino: Path) -> None:
    destino.write_text(texto.strip() + "\n", encoding="utf-8")


def escrever_srt(segmentos: Iterable[Segmento], destino: Path) -> None:
    linhas: list[str] = []
    for i, seg in enumerate(segmentos, start=1):
        linhas.append(str(i))
        linhas.append(f"{_fmt_ts(seg.inicio)} --> {_fmt_ts(seg.fim)}")
        linhas.append(seg.texto)
        linhas.append("")  # linha em branco
    destino.write_text("\n".join(linhas), encoding="utf-8")


def escrever_md(segmentos: Iterable[Segmento], destino: Path) -> None:
    """Markdown com timestamps inline entre colchetes, agrupado em parágrafos."""
    paragrafos: list[str] = []
    buffer_segmentos: list[Segmento] = []
    TAMANHO_BLOCO = 5  # agrupa ~5 segmentos por parágrafo

    def fechar_bloco():
        if not buffer_segmentos:
            return
        primeiro = buffer_segmentos[0]
        ts = _fmt_ts_curto(primeiro.inicio)
        texto = " ".join(s.texto for s in buffer_segmentos if s.texto).strip()
        if texto:
            paragrafos.append(f"**[{ts}]** {texto}")
        buffer_segmentos.clear()

    for seg in segmentos:
        buffer_segmentos.append(seg)
        if len(buffer_segmentos) >= TAMANHO_BLOCO:
            fechar_bloco()
    fechar_bloco()

    destino.write_text("\n\n".join(paragrafos) + "\n", encoding="utf-8")


def escrever_json(payload: dict, destino: Path) -> None:
    destino.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def escrever_transcricao(
    *,
    segmentos: list[Segmento],
    texto: str,
    idioma: str,
    duracao: float,
    origem_video: Path,
    destino_dir: Path,
    modelo_whisper: str,
    modelo_llm: str | None,
    revisado: bool,
    revisao_meta: dict | None = None,
) -> dict[str, Path]:
    """Gera todos os formatos. Retorna {formato: caminho}."""
    destino_dir.mkdir(parents=True, exist_ok=True)

    caminhos: dict[str, Path] = {}

    p_txt = destino_dir / "transcricao.txt"
    escrever_txt(texto, p_txt)
    caminhos["txt"] = p_txt

    p_srt = destino_dir / "transcricao.srt"
    escrever_srt(segmentos, p_srt)
    caminhos["srt"] = p_srt

    p_md = destino_dir / "transcricao.md"
    escrever_md(segmentos, p_md)
    caminhos["md"] = p_md

    p_json = destino_dir / "transcricao_final.json"
    payload = {
        "origem_video": str(origem_video),
        "idioma_detectado": idioma,
        "duracao_segundos": duracao,
        "modelo_whisper": modelo_whisper,
        "modelo_llm": modelo_llm,
        "revisado_por_llm": revisado,
        "revisao_meta": revisao_meta or {},
        "texto": texto,
        "segmentos": [asdict(s) for s in segmentos],
    }
    escrever_json(payload, p_json)
    caminhos["json"] = p_json

    return caminhos
