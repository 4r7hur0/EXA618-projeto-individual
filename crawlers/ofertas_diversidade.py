"""Reexporta limites/seleção em `app` (crawlers locais continuam importando daqui)."""
from app.ofertas_limites import (  # noqa: F401
    OFERTAS_MAX_POR_LOJA,
    limite_ofertas_loja,
    selecionar_ofertas_armazenamento_diverso,
)
