"""Uma oferta por capacidade (GB) — exibição e persistência."""
from __future__ import annotations

from app.filtros_api import capacidade_para_gb, preco_brl_para_float
from app.models import OfertaMercado


def _gb_oferta_dict(item: dict) -> int | None:
    return capacidade_para_gb(item.get("memoria")) or capacidade_para_gb(
        item.get("nome")
    )


def _gb_oferta_row(o: OfertaMercado) -> int | None:
    return capacidade_para_gb(o.memoria) or capacidade_para_gb(o.nome_produto)


def _preco_sort_key_dict(item: dict) -> float:
    p = preco_brl_para_float(item.get("preco"))
    return p if p is not None else float("inf")


def _preco_sort_key_row(o: OfertaMercado) -> float:
    p = preco_brl_para_float(o.preco)
    return p if p is not None else float("inf")


def uma_oferta_dict_por_memoria(ofertas: list[dict]) -> list[dict]:
    """Mantém só a oferta mais barata por capacidade (GB) distinta."""
    por_gb: dict[int, dict] = {}
    sem_gb: list[dict] = []
    for it in ofertas:
        g = _gb_oferta_dict(it)
        if g is None:
            sem_gb.append(it)
            continue
        if g not in por_gb or _preco_sort_key_dict(it) < _preco_sort_key_dict(por_gb[g]):
            por_gb[g] = it
    out = [por_gb[k] for k in sorted(por_gb)]
    if not out and sem_gb:
        return [min(sem_gb, key=_preco_sort_key_dict)]
    return out


def uma_oferta_por_memoria(rows: list[OfertaMercado]) -> list[OfertaMercado]:
    """Mantém só a oferta mais barata por GB distinto (para a tela /buscar)."""
    por_gb: dict[int, OfertaMercado] = {}
    sem_gb: list[OfertaMercado] = []
    for o in rows:
        g = _gb_oferta_row(o)
        if g is None:
            sem_gb.append(o)
            continue
        if g not in por_gb or _preco_sort_key_row(o) < _preco_sort_key_row(por_gb[g]):
            por_gb[g] = o
    out = [por_gb[k] for k in sorted(por_gb)]
    if not out and sem_gb:
        return [min(sem_gb, key=_preco_sort_key_row)]
    return out


def rotulo_memoria_gb(gb: int | None, memoria_txt: str | None) -> str:
    if gb is not None:
        return f"{gb} GB"
    if memoria_txt and str(memoria_txt).strip():
        return str(memoria_txt).strip()
    return "Capacidade não informada"
