"""Remoção de caracteres decorativos (emojis) de textos exibidos ou persistidos."""
from __future__ import annotations

import re

# Blocos comuns de emoji + seletor de variação + ZWJ (inclui 😉 U+1F609)
_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # símbolos e pictogramas
    "\U0001F680-\U0001F6FF"  # transporte e mapas
    "\U0001F900-\U0001F9FF"  # suplemento
    "\U0001FA00-\U0001FAFF"  # extensão A
    "\u2600-\u26FF"  # misc
    "\u2700-\u27BF"  # dingbats
    "\uFE0F"  # variation selector-16
    "\u200D"  # ZWJ (liga sequências emoji)
    "]+",
    flags=re.UNICODE,
)


def sem_emojis(texto: str | None) -> str | None:
    if texto is None:
        return None
    t = _EMOJI_RE.sub("", texto)
    t = re.sub(r"\s+", " ", t).strip()
    return t if t else None
