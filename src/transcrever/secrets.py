"""Sincroniza Secrets do Google Colab (ou valores em memória) para o .env local.

Uso:
    uv run pull-secrets                    # lê do Colab se estiver rodando lá
    uv run pull-secrets --manual           # prompt interativo (sem Colab)
    uv run pull-secrets --dry-run          # mostra o que seria escrito, sem alterar .env
    uv run pull-secrets --force            # sobrescreve chaves já existentes no .env

Por padrão, chaves já presentes no .env são preservadas (use --force para sobrescrever).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# Mapeamento: nome do Secret (Colab) → chave no .env
SECRETS_MAP: dict[str, str] = {
    "OPENROUTER_API_KEY": "OPENROUTER_API_KEY",
    "OPENROUTER_MODEL": "OPENROUTER_MODEL",
}


def _ler_env_existente(env_path: Path) -> dict[str, str]:
    """Lê o .env atual. Retorna {CHAVE: valor}."""
    if not env_path.exists():
        return {}
    out: dict[str, str] = {}
    for linha in env_path.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        k, _, v = linha.partition("=")
        out[k.strip()] = v.strip()
    return out


def _escrever_env(env_path: Path, valores: dict[str, str], header: str) -> None:
    """Escreve o .env preservando ordem e comentários."""
    linhas: list[str] = []
    if header:
        linhas.append(header)
    for k, v in valores.items():
        linhas.append(f"{k}={v}")
    env_path.write_text("\n".join(linhas) + "\n", encoding="utf-8")


def _valor_do_colab(nome_secret: str) -> str | None:
    """Lê um Secret do Colab. Retorna None se não estiver rodando no Colab
    ou se o Secret não estiver configurado."""
    try:
        from google.colab import userdata  # type: ignore
    except ImportError:
        return None
    try:
        return userdata.get(nome_secret)
    except Exception:
        return None


def _valor_da_variavel_ambiente(nome: str) -> str | None:
    """Fallback: lê de os.environ (caso o usuário já tenha exportado)."""
    v = os.environ.get(nome)
    return v if v else None


def _prompt_manual(nome: str) -> str:
    """Pede a chave no terminal (input fica invisível)."""
    import getpass
    return getpass.getpass(f"  {nome}: ").strip()


def coletar_valores(
    *,
    origem: str = "auto",
    dry_run: bool = False,
) -> dict[str, str]:
    """Coleta os valores dos Secrets. origem ∈ {auto, colab, manual, env}.

    Retorna {NOME_ENV: valor} apenas para os Secrets que foram efetivamente
    encontrados (Secrets ausentes são silenciosamente omitidos).
    """
    encontrados: dict[str, str] = {}

    for secret_name, env_name in SECRETS_MAP.items():
        valor: str | None = None

        if origem in ("auto", "colab"):
            valor = _valor_do_colab(secret_name)
            if valor and not dry_run:
                print(f"  ✓ {secret_name}: lido do Colab Secrets")

        if not valor and origem in ("auto", "env"):
            valor = _valor_da_variavel_ambiente(secret_name)
            if valor and not dry_run:
                print(f"  ✓ {secret_name}: lido de os.environ")

        if not valor and origem == "manual":
            valor = _prompt_manual(secret_name)
            if valor:
                print(f"  ✓ {secret_name}: informado manualmente")

        if valor:
            encontrados[env_name] = valor
        elif not dry_run and origem != "manual":
            # Não é erro — chaves opcionais. Mas avisa.
            opcional = secret_name != "OPENROUTER_API_KEY"
            tag = " (opcional)" if opcional else ""
            print(f"  · {secret_name}{tag}: não encontrado — pulando")

    return encontrados


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sincroniza Secrets do Colab para o .env local.",
    )
    parser.add_argument(
        "--origem",
        choices=["auto", "colab", "env", "manual"],
        default="auto",
        help="Onde buscar os valores (default: auto — Colab > env).",
    )
    parser.add_argument(
        "--env-path",
        type=Path,
        default=None,
        help="Caminho do .env (default: <projeto>/.env).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostra o que seria escrito, sem alterar o .env.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Sobrescreve chaves já existentes no .env (default: preserva).",
    )
    args = parser.parse_args(argv)

    # Localiza o .env (default = raiz do projeto, ao lado do pyproject.toml)
    if args.env_path is None:
        projeto_root = Path(__file__).resolve().parents[2]
        args.env_path = projeto_root / ".env"

    print(f"📥 Sincronizando Secrets → {args.env_path}")
    if args.dry_run:
        print("   (dry-run: nada será escrito)")

    existentes = _ler_env_existente(args.env_path)
    novos = coletar_valores(origem=args.origem, dry_run=args.dry_run)

    if not novos:
        print("\n⚠ Nenhum Secret foi encontrado.")
        if args.origem == "auto":
            print("  Você está rodando fora do Colab e sem as variáveis no shell?")
            print("  Tente:  uv run pull-secrets --manual")
        return 1

    # Mescla: preserva chaves existentes que não estão em `novos`,
    # e adiciona/sobrescreve as de `novos` (respeitando --force).
    finais = dict(existentes)
    for k, v in novos.items():
        if k in finais and not args.force and finais[k]:
            if not args.dry_run:
                print(f"  ⤷ {k}: já existe no .env (use --force para sobrescrever)")
            continue
        finais[k] = v

    # Escreve (preserva comentários heurística simples: só mantém cabeçalho se já existia)
    header = ""
    if args.env_path.exists():
        # Mantém as linhas de comentário do início
        comentarios: list[str] = []
        for linha in args.env_path.read_text(encoding="utf-8").splitlines():
            if linha.strip().startswith("#") or not linha.strip():
                comentarios.append(linha)
            else:
                break
        if comentarios:
            header = "\n".join(comentarios)

    if args.dry_run:
        print("\n--- Conteúdo que seria escrito ---")
        for k, v in finais.items():
            if k not in novos:
                continue  # chave que veio do .env e não seria tocada
            ja_existia = k in existentes
            # Sem --force, chaves existentes não são sobrescritas → mantém valor atual
            if ja_existia and not args.force:
                status = "(preservado — use --force para sobrescrever)"
                v_display = existentes[k]
            else:
                status = "(novo)" if not ja_existia else "(sobrescrito)"
                v_display = v
            if "KEY" in k or "TOKEN" in k or "SECRET" in k:
                if len(v_display) > 12:
                    v_display = v_display[:6] + "…" + v_display[-4:]
                else:
                    v_display = "***"
            print(f"  {k}={v_display}  {status}")
        print("---------------------------------")
        return 0

    _escrever_env(args.env_path, finais, header=header)
    print(f"\n✓ {args.env_path} atualizado com {len(novos)} chave(s).")
    print("  Próximo passo:  uv run transcrever video.mkv --tema '...' --glossario g.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
