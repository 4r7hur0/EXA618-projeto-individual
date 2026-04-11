"""Formato de texto para data/hora de extração (alinhado aos crawlers: dd/mm/AAAA HH:MM)."""
from __future__ import annotations

from datetime import datetime


def agora_texto_br() -> str:
    """Momento atual no formato usado na interface e nos crawlers."""
    return datetime.now().strftime("%d/%m/%Y %H:%M")
