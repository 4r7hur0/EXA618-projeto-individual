"""Normalização de termo para cache e extração de trecho de preço BRL dos crawlers."""
from __future__ import annotations

import re


def normalizar_termo_cache(termo: str) -> str:
    """Alinhado ao crawler (sem GB/TB no texto) + minúsculas para chave única."""
    s = (termo or "").strip().lower()
    s = re.sub(
        r"\b\d{1,4}\s*(GB|TB|gb|tb)\b",
        " ",
        s,
        flags=re.I,
    )
    s = re.sub(r"\s+", " ", s).strip()
    return s


def extrair_primeiro_preco_brl(texto: str | None) -> str | None:
    """
    Isola só o trecho do valor (ex.: 'R$ 4.587').
    Evita que 'R$ 4.587 41% OFF' vire '4.58741' ao colar dígitos.
    """
    if not texto:
        return None
    s = texto.strip()
    s = s.split("%", 1)[0].strip()
    s = re.split(r"\bOFF\b", s, maxsplit=1, flags=re.I)[0].strip()
    m = re.search(
        r"R\$\s*(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)",
        s,
        re.I,
    )
    if m:
        return f"R$ {m.group(1).strip()}"
    m = re.search(r"(\d{1,3}(?:\.\d{3})+,\d{2})(?!\d)", s)
    if m:
        return f"R$ {m.group(1)}"
    return None
