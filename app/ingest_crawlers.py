"""Executa crawlers e grava aparelho + ofertas no banco (uso pelo endpoint de ingestão)."""
from __future__ import annotations

import asyncio
import os

from sqlalchemy.orm import Session

from app.persist import (
    aparelho_from_mais_celular,
    oferta_from_amazon,
    oferta_from_mercadolivre,
)
from crawlers.amazon import crawler_amazon_essencial
from crawlers.mais_celular import crawler_maiscelular_blindado
from crawlers.mercado_livre import crawler_mercadolivre_completo


def _limite_ofertas(n_override: int | None) -> int:
    if n_override is not None:
        return max(1, min(int(n_override), 8))
    try:
        n = int(os.environ.get("OFERTAS_POR_BUSCA", "4").strip())
    except ValueError:
        n = 4
    return max(1, min(n, 8))


def _normalizar_saida_mc(val):
    if isinstance(val, Exception):
        return None, f"{type(val).__name__}: {val}"
    if isinstance(val, dict):
        return val, None
    if isinstance(val, list):
        dicts = [x for x in val if isinstance(x, dict)]
        if dicts:
            return dicts[0], None
        return None, "Nenhum dado de ficha retornado."
    return None, str(val)


def _normalizar_saida_crawler(val):
    if isinstance(val, Exception):
        return None, f"{type(val).__name__}: {val}"
    if isinstance(val, dict):
        return [val], None
    if isinstance(val, list):
        itens = [x for x in val if isinstance(x, dict)]
        if itens:
            return itens, None
        return None, "Nenhum produto retornado."
    return None, str(val)


def _crawler_paralelo() -> bool:
    return os.environ.get("CRAWLER_PARALLEL", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _run_crawler_em_loop_proprio(coro_fn, *args):
    try:
        return asyncio.run(coro_fn(*args))
    except BaseException as e:
        return e


async def _executar_crawler_isolado(coro_fn, *args):
    return await asyncio.to_thread(_run_crawler_em_loop_proprio, coro_fn, *args)


async def ingerir_um_termo(
    db: Session,
    termo: str,
    *,
    ofertas_por_termo: int | None = None,
) -> IngestItemResult:
    from app.schemas_ingest import IngestItemResult

    termo = (termo or "").strip()
    if not termo:
        return IngestItemResult(termo=termo, ok=False, erros=["Termo vazio."])

    n = _limite_ofertas(ofertas_por_termo)
    erros: list[str] = []

    if _crawler_paralelo():
        mc_raw, amz_raw, ml_raw = await asyncio.gather(
            _executar_crawler_isolado(crawler_maiscelular_blindado, termo),
            _executar_crawler_isolado(crawler_amazon_essencial, termo, n),
            _executar_crawler_isolado(crawler_mercadolivre_completo, termo, n),
        )
    else:
        mc_raw = await _executar_crawler_isolado(crawler_maiscelular_blindado, termo)
        amz_raw = await _executar_crawler_isolado(
            crawler_amazon_essencial, termo, n
        )
        ml_raw = await _executar_crawler_isolado(
            crawler_mercadolivre_completo, termo, n
        )

    mc, mc_erro = _normalizar_saida_mc(mc_raw)
    amz_list, amz_erro = _normalizar_saida_crawler(amz_raw)
    ml_list, ml_erro = _normalizar_saida_crawler(ml_raw)

    if mc_erro:
        erros.append(f"Mais Celular: {mc_erro}")
    if amz_erro:
        erros.append(f"Amazon: {amz_erro}")
    if ml_erro:
        erros.append(f"Mercado Livre: {ml_erro}")

    if amz_list:
        amz_list = [x for x in amz_list if isinstance(x, dict)]
    if ml_list:
        ml_list = [x for x in ml_list if isinstance(x, dict)]

    aparelho_id = None
    n_amz = 0
    n_ml = 0

    try:
        if mc:
            a = aparelho_from_mais_celular(termo, mc)
            db.add(a)
            db.flush()
            aparelho_id = a.id
        if amz_list:
            for item in amz_list:
                oa = oferta_from_amazon(termo, item)
                oa.aparelho_id = aparelho_id
                db.add(oa)
                db.flush()
                n_amz += 1
        if ml_list:
            for item in ml_list:
                ol = oferta_from_mercadolivre(termo, item)
                ol.aparelho_id = aparelho_id
                db.add(ol)
                db.flush()
                n_ml += 1
        db.commit()
    except Exception as e:
        db.rollback()
        erros.append(f"Banco: {e}")
        return IngestItemResult(
            termo=termo,
            ok=False,
            aparelho_id=None,
            ofertas_amazon_salvas=0,
            ofertas_ml_salvas=0,
            erros=erros,
        )

    ok = bool(mc) or n_amz > 0 or n_ml > 0
    return IngestItemResult(
        termo=termo,
        ok=ok,
        aparelho_id=aparelho_id,
        ofertas_amazon_salvas=n_amz,
        ofertas_ml_salvas=n_ml,
        erros=erros,
    )
