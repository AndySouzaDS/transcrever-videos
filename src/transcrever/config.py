"""Configurações, defaults e carregamento de .env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Carrega .env do diretório do projeto (se existir)
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env")


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

DEFAULT_MODELO_WHISPER = "large-v3"
DEFAULT_MODELO_LLM = "meta-llama/llama-3.3-70b-instruct:free"
DEFAULT_SAIDA = "./saidas"


@dataclass(frozen=True)
class Config:
    """Configurações consolidadas para uma execução."""

    openrouter_api_key: str | None
    modelo_llm: str
    modelo_whisper: str
    device: str
    compute_type: str
    sem_revisao: bool
    forcar: bool

    @classmethod
    def from_env(
        cls,
        *,
        modelo_whisper: str = DEFAULT_MODELO_WHISPER,
        modelo_llm: str | None = None,
        device: str = "auto",
        compute_type: str = "auto",
        sem_revisao: bool = False,
        forcar: bool = False,
    ) -> "Config":
        return cls(
            openrouter_api_key=os.getenv("OPENROUTER_API_KEY"),
            modelo_llm=modelo_llm or os.getenv("OPENROUTER_MODEL", DEFAULT_MODELO_LLM),
            modelo_whisper=modelo_whisper,
            device=device,
            compute_type=compute_type,
            sem_revisao=sem_revisao,
            forcar=forcar,
        )


def projeto_root() -> Path:
    """Raiz do projeto (onde está o pyproject.toml)."""
    return _PROJECT_ROOT
