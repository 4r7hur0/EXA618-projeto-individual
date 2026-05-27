"""Limites de ofertas por loja (API e ingestão; sem importar pacote `crawlers`)."""
from __future__ import annotations

from app.filtros_api import capacidade_para_gb

OFERTAS_MAX_POR_LOJA = 32


def limite_ofertas_loja(n: int) -> int:
    return max(1, min(int(n), OFERTAS_MAX_POR_LOJA))


def selecionar_ofertas_armazenamento_diverso(ofertas: list[dict], max_n: int) -> list[dict]:
    max_n = max(0, int(max_n))
    if max_n <= 0 or not ofertas:
        return []

    out: list[dict] = []
    seen_links: set[str] = set()
    seen_gb: set[int] = set()

    for it in ofertas:
        if len(out) >= max_n:
            break
        link = (it.get("link") or "").strip()
        if not link or link in seen_links:
            continue
        g = capacidade_para_gb(it.get("memoria")) or capacidade_para_gb(it.get("nome"))
        if g is not None:
            if g in seen_gb:
                continue
            seen_gb.add(g)
        seen_links.add(link)
        out.append(it)

    return out
