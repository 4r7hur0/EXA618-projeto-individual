"""
Apaga todas as ofertas e aparelhos (PostgreSQL).

Na pasta do projeto:
  python scripts/zerar_banco.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.database import zerar_dados_catalogo  # noqa: E402


def main() -> None:
    zerar_dados_catalogo()
    print("Banco zerado: tabelas aparelhos e ofertas_mercado limpas (ids reiniciados).")


if __name__ == "__main__":
    main()
