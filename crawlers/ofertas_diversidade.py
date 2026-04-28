"""Seleção de ofertas priorizando variantes de armazenamento diferentes."""
from __future__ import annotations

from app.filtros_api import capacidade_para_gb

# Teto por loja (Amazon / ML) por termo de ingestão; alinhado a `app.ingest_crawlers`.
OFERTAS_MAX_POR_LOJA = 32


def limite_ofertas_loja(n: int) -> int:
    return max(1, min(int(n), OFERTAS_MAX_POR_LOJA))


def selecionar_ofertas_armazenamento_diverso(ofertas: list[dict], max_n: int) -> list[dict]:
    """
    Mantém filtros já aplicados no crawler; apenas escolhe *quais* ofertas salvar:

    1. Primeiro: no máximo um anúncio por cada GB parseável distinto na memória.
    2. Depois: completa até `max_n` com os demais (pode repetir mesmo GB).

    Assim aumenta variedade de 64/128/256 GB numa única ingestão quando a listagem trouxer vários PDPs.
    """
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
        g = capacidade_para_gb(it.get("memoria"))
        if g is not None and g in seen_gb:
            continue
        if g is not None:
            seen_gb.add(g)
        seen_links.add(link)
        out.append(it)

    for it in ofertas:
        if len(out) >= max_n:
            break
        link = (it.get("link") or "").strip()
        if not link or link in seen_links:
            continue
        seen_links.add(link)
        out.append(it)

    return out
