"""Atualização periódica de preços das ofertas salvas (uma PDP por vez)."""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import OfertaMercado
from app.preco_util import registrar_snapshot_preco
from crawlers.preco_pdp import extrair_preco_url_pdp

logger = logging.getLogger(__name__)


def _run_async(coro_fn, *args):
    try:
        return asyncio.run(coro_fn(*args))
    except BaseException as e:
        return e


def rodar_um_ciclo_atualizacao_precos(db: Session | None = None) -> None:
    own = db is None
    if own:
        db = SessionLocal()
    assert db is not None
    try:
        ofertas = (
            db.query(OfertaMercado)
            .filter(OfertaMercado.link.isnot(None))
            .all()
        )
        for o in ofertas:
            link = (o.link or "").strip()
            if not link or o.origem not in ("amazon", "mercadolivre"):
                continue
            res = _run_async(extrair_preco_url_pdp, link, o.origem)
            if isinstance(res, Exception):
                logger.warning("Oferta %s: %s", o.id, res)
                continue
            if not res:
                continue
            if res == (o.preco or "").strip():
                continue
            o.preco = res
            registrar_snapshot_preco(db, o.id, res)
            db.commit()
    finally:
        if own:
            db.close()


async def loop_job_precos(interval_minutes: float) -> None:
    await asyncio.sleep(90)
    while True:
        try:
            await asyncio.to_thread(rodar_um_ciclo_atualizacao_precos)
        except Exception:
            logger.exception("Falha no job de preços")
        await asyncio.sleep(max(interval_minutes, 1) * 60)
