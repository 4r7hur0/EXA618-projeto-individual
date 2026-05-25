"""Monta termos de busca para marketplaces (Amazon / Mercado Livre) com armazenamento."""
from __future__ import annotations

import os
import re

from app.filtros_api import capacidade_para_gb

# 128GB, 128 Gb, 128Gb (re.I)
_RE_ARMAZENAMENTO = re.compile(r"\b\d{1,4}\s*(GB|TB)\b", re.I)

_CAPACIDADES_VALIDAS = frozenset({32, 64, 128, 256, 512, 1024, 2048})


def remover_armazenamento_do_termo(termo: str) -> str:
    """Remove variantes tipo 128GB / 1TB do texto (igual ao crawler Mais Celular)."""
    s = (termo or "").strip()
    s = _RE_ARMAZENAMENTO.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def armazenamento_gb_no_termo(termo: str) -> int | None:
    return capacidade_para_gb(termo)


def _normalizar_lista_gb(valores: list[int] | None) -> list[int]:
    if not valores:
        return []
    out: list[int] = []
    for v in valores:
        g = int(v)
        if g not in _CAPACIDADES_VALIDAS:
            raise ValueError(
                f"armazenamento inválido: {g}GB. Use um de: {sorted(_CAPACIDADES_VALIDAS)}."
            )
        if g not in out:
            out.append(g)
    return out


def montar_termo_marketplace(termo_base: str, armazenamento_gb: int) -> str:
    base = remover_armazenamento_do_termo(termo_base)
    if not base:
        base = (termo_base or "").strip()
    return f"{base} {int(armazenamento_gb)}GB".strip()


def termo_ja_tem_armazenamento(termo: str) -> bool:
    return armazenamento_gb_no_termo(termo) is not None


def parse_termos_usuario(valor: object) -> list[str]:
    """
    Aceita lista ou texto com várias linhas / vírgulas:
    «iphone 16 128Gb», «iphone 16 256 Gb»
    """
    if valor is None:
        return []
    if isinstance(valor, str):
        bruto = [valor]
    elif isinstance(valor, list):
        bruto = list(valor)
    else:
        bruto = [valor]
    out: list[str] = []
    for item in bruto:
        if item is None:
            continue
        s = str(item).strip()
        if not s:
            continue
        if "\n" in s or "," in s or ";" in s:
            pedacos = re.split(r"[\n,;]+", s)
            for p in pedacos:
                t = p.strip()
                if t:
                    out.append(t)
        else:
            out.append(s)
    return out


def armazenamentos_padrao_env() -> list[int] | None:
    """
    Capacidades buscadas quando o termo não traz GB (ex.: só «iphone 16»).
    ARMAZENAMENTOS_BUSCA=128,256,512 no .env
    """
    raw = os.environ.get("ARMAZENAMENTOS_BUSCA", "128,256,512").strip()
    if not raw or raw.lower() in ("0", "false", "none", "off"):
        return None
    out: list[int] = []
    for parte in re.split(r"[,;\s]+", raw):
        parte = parte.strip()
        if not parte:
            continue
        try:
            g = int(parte)
        except ValueError:
            continue
        if g not in out and g in _CAPACIDADES_VALIDAS:
            out.append(g)
    return out or None


def variantes_busca_marketplace(
    termo: str,
    *,
    armazenamento_gb: int | None = None,
    armazenamentos_gb: list[int] | None = None,
    usar_padrao_env: bool = False,
) -> list[tuple[str, int | None]]:
    """
    Retorna pares (termo_para_loja, gb_da_variante).
    - Se o termo já tiver capacidade (ex.: «iphone 16 128Gb»), usa o texto tal qual.
    - Senão, armazenamentos_gb / armazenamento_gb montam variantes no termo base.
    """
    termo = (termo or "").strip()
    if not termo:
        return []

    if termo_ja_tem_armazenamento(termo):
        gb_termo = armazenamento_gb_no_termo(termo)
        return [(termo, gb_termo)]

    lista = _normalizar_lista_gb(armazenamentos_gb)
    # Só expande capacidades com ARMAZENAMENTOS_BUSCA se o chamador pedir (usar_padrao_env).
    if (
        not lista
        and usar_padrao_env
        and not termo_ja_tem_armazenamento(termo)
    ):
        lista = _normalizar_lista_gb(armazenamentos_padrao_env())

    if armazenamento_gb is not None:
        g = int(armazenamento_gb)
        if g not in _CAPACIDADES_VALIDAS:
            raise ValueError(
                f"armazenamento_gb inválido: {g}. Use um de: {sorted(_CAPACIDADES_VALIDAS)}."
            )
        if g not in lista:
            lista = [g, *lista]

    if lista:
        return [(montar_termo_marketplace(termo, g), g) for g in lista]

    gb_termo = armazenamento_gb_no_termo(termo)
    if gb_termo is not None:
        return [(termo, gb_termo)]

    return [(termo, None)]
