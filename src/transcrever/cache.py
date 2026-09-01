"""Cache baseado em hash do áudio: pula transcrição se o WAV não mudou."""

from __future__ import annotations

import hashlib
from pathlib import Path


def hash_arquivo(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """SHA-256 do arquivo, em chunks (não carrega o arquivo inteiro na memória)."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            bloco = f.read(chunk_size)
            if not bloco:
                break
            h.update(bloco)
    return h.hexdigest()


def caminho_cache(saida_dir: Path) -> Path:
    """Arquivo que guarda o hash do último áudio processado."""
    return saida_dir / ".cache_hash"


def cache_valido(saida_dir: Path, hash_audio: str) -> bool:
    """True se o cache existir e o hash do áudio não mudou."""
    c = caminho_cache(saida_dir)
    if not c.exists():
        return False
    return c.read_text().strip() == hash_audio


def gravar_cache(saida_dir: Path, hash_audio: str) -> None:
    caminho_cache(saida_dir).write_text(hash_audio)
