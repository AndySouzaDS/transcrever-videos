"""Extração de áudio via ffmpeg (com bypass se a entrada já for .wav)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def ffmpeg_disponivel() -> bool:
    return shutil.which("ffmpeg") is not None


def ja_e_wav_valido(caminho: Path) -> bool:
    """Heurística simples: extensão .wav e tamanho > 0."""
    return caminho.suffix.lower() == ".wav" and caminho.exists() and caminho.stat().st_size > 0


def extrair_wav(video: Path, saida_wav: Path) -> Path:
    """
    Garante um WAV 16kHz mono PCM em `saida_wav`.

    - Se a entrada já for `.wav`, apenas copia (pula ffmpeg).
    - Caso contrário, extrai via ffmpeg.
    """
    if ja_e_wav_valido(video):
        saida_wav.parent.mkdir(parents=True, exist_ok=True)
        if saida_wav.resolve() != video.resolve():
            shutil.copy2(video, saida_wav)
        return saida_wav

    if saida_wav.exists():
        saida_wav.unlink()

    cmd = [
        "ffmpeg",
        "-y",                  # sobrescreve saída
        "-i", str(video),      # entrada
        "-vn",                 # descarta vídeo
        "-ac", "1",            # mono
        "-ar", "16000",        # 16 kHz
        "-acodec", "pcm_s16le",
        "-f", "wav",
        str(saida_wav),
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg falhou (código {result.returncode}).\n"
            f"stderr:\n{result.stderr[-2000:]}"
        )

    if not saida_wav.exists():
        raise RuntimeError("ffmpeg terminou sem erro, mas o arquivo de saída não foi criado.")

    return saida_wav
