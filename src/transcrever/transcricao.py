"""Transcrição com faster-whisper, usando tema e glossário como initial_prompt."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterator

from faster_whisper import WhisperModel
from faster_whisper.transcribe import Segment, Word


@dataclass
class Segmento:
    """Segmento de fala com timestamps."""

    inicio: float
    fim: float
    texto: str
    palavras: list[dict] = field(default_factory=list)
    probabilidade_media: float = 0.0


@dataclass
class Transcricao:
    """Resultado consolidado da transcrição."""

    idioma: str
    duracao: float
    segmentos: list[Segmento]
    texto_completo: str

    def to_dict(self) -> dict:
        return {
            "idioma": self.idioma,
            "duracao": self.duracao,
            "texto_completo": self.texto_completo,
            "segmentos": [asdict(s) for s in self.segmentos],
        }


def montar_initial_prompt(tema: str, glossario: list[str]) -> str:
    """
    Constrói o initial_prompt do Whisper.

    O Whisper usa isso como "frase anterior" — influencia fortemente a grafia
    e a tendência vocabular do modelo. Injetamos tema + glossário.
    """
    partes: list[str] = []

    if tema:
        partes.append(f"Tema: {tema}.")

    if glossario:
        termos = ", ".join(glossario)
        partes.append(f"Termos e nomes próprios relevantes: {termos}.")

    partes.append(
        "Esta é uma transcrição em português brasileiro, com vocabulário técnico "
        "e nomes próprios preservados com grafia exata."
    )

    prompt = " ".join(partes)
    # Whisper aceita até ~224 tokens no initial_prompt; truncamos com folga.
    if len(prompt) > 800:
        prompt = prompt[:800].rsplit(" ", 1)[0]
    return prompt


def _segmento_from(s: Segment) -> Segmento:
    palavras: list[dict] = []
    if s.words:
        for w in s.words:  # type: ignore[union-attr]
            palavras.append(
                {
                    "palavra": w.word,
                    "inicio": float(w.start) if w.start is not None else None,
                    "fim": float(w.end) if w.end is not None else None,
                    "probabilidade": float(w.probability) if w.probability is not None else None,
                }
            )
    return Segmento(
        inicio=float(s.start),
        fim=float(s.end),
        texto=s.text.strip(),
        palavras=palavras,
        probabilidade_media=float(getattr(s, "avg_logprob", 0.0) or 0.0),
    )


def transcrever(
    audio_wav: Path,
    *,
    modelo: str = "large-v3",
    tema: str,
    glossario: list[str] | None = None,
    device: str = "auto",
    compute_type: str = "auto",
    on_progress=None,
) -> Transcricao:
    """
    Transcreve o WAV com faster-whisper.

    Args:
        audio_wav: caminho do WAV 16kHz mono.
        modelo: nome do modelo (tiny, base, small, medium, large-v3, ...).
        tema: tema do vídeo, usado no initial_prompt.
        glossario: termos com grafia obrigatória.
        device: "cpu", "cuda" ou "auto".
        compute_type: "int8", "float16", "float32" ou "auto".
        on_progress: callback(segmento_dict) para reportar progresso.
    """
    inicial_prompt = montar_initial_prompt(tema, glossario or [])

    # device/compute_type "auto" deixa o faster-whisper decidir
    kwargs: dict = {}
    if device != "auto":
        kwargs["device"] = device
    if compute_type != "auto":
        kwargs["compute_type"] = compute_type

    modelo_whisper = WhisperModel(modelo, **kwargs)

    segments_iter, info = modelo_whisper.transcribe(
        str(audio_wav),
        language="pt",
        initial_prompt=inicial_prompt,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        word_timestamps=True,
        condition_on_previous_text=True,
    )

    segmentos: list[Segmento] = []
    buffer_texto: list[str] = []

    for seg in _with_progress(segments_iter, info.duration, on_progress):
        s = _segmento_from(seg)
        segmentos.append(s)
        if s.texto:
            buffer_texto.append(s.texto)
        if on_progress is not None:
            on_progress(s)

    texto = " ".join(buffer_texto).strip()
    return Transcricao(
        idioma=info.language,
        duracao=float(info.duration),
        segmentos=segmentos,
        texto_completo=texto,
    )


def _with_progress(
    segments_iter: Iterator[Segment],
    duracao_total: float,
    on_progress,
) -> Iterator[Segment]:
    """Wrapper que loga progresso via rich (se disponível)."""
    if on_progress is None:
        yield from segments_iter
        return

    from rich.progress import (
        BarColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]Transcrevendo"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        transient=True,
    ) as progress:
        task = progress.add_task("transcrevendo", total=int(duracao_total) or 1)
        for seg in segments_iter:
            yield seg
            avancado = max(0.0, float(seg.end) - float(seg.start))
            progress.update(task, advance=int(avancado))
