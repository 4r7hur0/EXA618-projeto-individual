import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.cache_busca import (
    aparelho_para_dict,
    buscar_tripla_em_cache,
    oferta_para_dict,
)
from app.config import configure_logging
from app.database import get_db, init_db
from app.job_precos import loop_job_precos
from app.models import Aparelho, OfertaMercado
from app.persist import (
    aparelho_from_mais_celular,
    oferta_from_amazon,
    oferta_from_mercadolivre,
)
from app.preco_util import historico_oferta_json, registrar_snapshot_preco
from crawlers.amazon import crawler_amazon_essencial
from crawlers.mais_celular import crawler_maiscelular_blindado
from crawlers.mercado_livre import crawler_mercadolivre_completo

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    init_db()
    task = None
    try:
        job_min = float(os.environ.get("PRECOS_JOB_INTERVAL_MINUTES", "360"))
    except ValueError:
        job_min = 360.0
    if job_min > 0:
        task = asyncio.create_task(loop_job_precos(job_min))
    yield
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Catálogo de aparelhos", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
def pagina_inicial(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "erro": None,
        },
    )


def _normalizar_saida_mc(val):
    """Mais Celular: um único dict de ficha (não envolver em lista)."""
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
    """lista de dicts → sucesso; dict único → [dict]; str → erro; Exception → exceção."""
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


def _limite_ofertas_por_busca() -> int:
    try:
        n = int(os.environ.get("OFERTAS_POR_BUSCA", "4").strip())
    except ValueError:
        n = 4
    return max(1, min(n, 8))


def _preco_texto_snapshot(v) -> str | None:
    """Garante string para histórico de preço (evita lista/objeto vindo do crawler)."""
    if v is None:
        return None
    if isinstance(v, list):
        for x in v:
            t = _preco_texto_snapshot(x)
            if t:
                return t
        return None
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v).strip()
    return s if s else None


def _crawler_paralelo() -> bool:
    return os.environ.get("CRAWLER_PARALLEL", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _run_crawler_em_loop_proprio(coro_fn, *args):
    """Playwright no Windows falha no loop do Uvicorn (NotImplementedError). Roda o async em loop novo no thread worker."""
    try:
        return asyncio.run(coro_fn(*args))
    except BaseException as e:
        return e


async def _executar_crawler_isolado(coro_fn, *args):
    return await asyncio.to_thread(_run_crawler_em_loop_proprio, coro_fn, *args)


def _template_resultado(
    request: Request,
    db: Session,
    termo: str,
    mc,
    mc_erro,
    amz_list,
    amz_erro,
    ml_list,
    ml_erro,
    oferta_amazon_id,
    oferta_ml_id,
    *,
    from_cache: bool = False,
):
    ha = historico_oferta_json(db, oferta_amazon_id)
    hm = historico_oferta_json(db, oferta_ml_id)
    return templates.TemplateResponse(
        request,
        "resultado_busca.html",
        {
            "request": request,
            "termo": termo,
            "mc": mc,
            "mc_erro": mc_erro,
            "amz_list": amz_list or [],
            "amz_erro": amz_erro,
            "ml_list": ml_list or [],
            "ml_erro": ml_erro,
            "oferta_amazon_id": oferta_amazon_id,
            "oferta_ml_id": oferta_ml_id,
            "from_cache": from_cache,
            "hist_amazon_json": json.dumps(ha, ensure_ascii=False),
            "hist_ml_json": json.dumps(hm, ensure_ascii=False),
        },
    )


@app.post("/buscar", response_class=HTMLResponse)
async def buscar_completo(
    request: Request,
    termo: str = Form(...),
    forcar: str | None = Form(None),
    db: Session = Depends(get_db),
):
    termo = (termo or "").strip()
    if not termo:
        return _index_com_erro(request, "Informe o modelo ou termo de busca.")

    ignorar_cache = forcar in ("1", "on", "true", "yes")
    n_ofertas = _limite_ofertas_por_busca()

    if not ignorar_cache:
        tripla = buscar_tripla_em_cache(db, termo, limite_ofertas=n_ofertas)
        if tripla:
            ap, oa_rows, ol_rows = tripla
            oa_ids = [o.id for o in oa_rows]
            ol_ids = [o.id for o in ol_rows]
            return _template_resultado(
                request,
                db,
                termo,
                aparelho_para_dict(ap),
                None,
                [oferta_para_dict(o) for o in oa_rows],
                None,
                [oferta_para_dict(o) for o in ol_rows],
                None,
                oa_ids[0] if oa_ids else None,
                ol_ids[0] if ol_ids else None,
                from_cache=True,
            )

    if _crawler_paralelo():
        mc_raw, amz_raw, ml_raw = await asyncio.gather(
            _executar_crawler_isolado(crawler_maiscelular_blindado, termo),
            _executar_crawler_isolado(crawler_amazon_essencial, termo, n_ofertas),
            _executar_crawler_isolado(crawler_mercadolivre_completo, termo, n_ofertas),
        )
    else:
        mc_raw = await _executar_crawler_isolado(crawler_maiscelular_blindado, termo)
        amz_raw = await _executar_crawler_isolado(
            crawler_amazon_essencial, termo, n_ofertas
        )
        ml_raw = await _executar_crawler_isolado(
            crawler_mercadolivre_completo, termo, n_ofertas
        )

    mc, mc_erro = _normalizar_saida_mc(mc_raw)
    amz_list, amz_erro = _normalizar_saida_crawler(amz_raw)
    ml_list, ml_erro = _normalizar_saida_crawler(ml_raw)
    # Só dicts (defesa contra payload aninhado ou processo antigo sem reload).
    if amz_list:
        amz_list = [x for x in amz_list if isinstance(x, dict)]
    if ml_list:
        ml_list = [x for x in ml_list if isinstance(x, dict)]

    aparelho_id = None
    oferta_amazon_id = None
    oferta_ml_id = None
    oferta_amazon_ids: list[int] = []
    oferta_ml_ids: list[int] = []

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
                oferta_amazon_ids.append(oa.id)
                if oferta_amazon_id is None:
                    oferta_amazon_id = oa.id
                pt = _preco_texto_snapshot(item.get("preco"))
                if pt:
                    registrar_snapshot_preco(db, oa.id, pt)
        if ml_list:
            for item in ml_list:
                ol = oferta_from_mercadolivre(termo, item)
                ol.aparelho_id = aparelho_id
                db.add(ol)
                db.flush()
                oferta_ml_ids.append(ol.id)
                if oferta_ml_id is None:
                    oferta_ml_id = ol.id
                pt = _preco_texto_snapshot(item.get("preco"))
                if pt:
                    registrar_snapshot_preco(db, ol.id, pt)
        db.commit()
    except Exception as e:
        db.rollback()
        return _index_com_erro(request, f"Erro ao salvar no banco: {e}")

    return _template_resultado(
        request,
        db,
        termo,
        mc,
        mc_erro,
        amz_list,
        amz_erro,
        ml_list,
        ml_erro,
        oferta_amazon_id,
        oferta_ml_id,
        from_cache=False,
    )


def _index_com_erro(request: Request, mensagem: str):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "erro": mensagem,
        },
        status_code=400,
    )


@app.get("/aparelhos", response_class=HTMLResponse)
def listar_aparelhos(request: Request, db: Session = Depends(get_db)):
    rows = db.query(Aparelho).order_by(Aparelho.criado_em.desc()).all()
    return templates.TemplateResponse(
        request,
        "aparelhos_lista.html",
        {"request": request, "aparelhos": rows},
    )


@app.get("/aparelhos/{ap_id}", response_class=HTMLResponse)
def ver_aparelho(ap_id: int, request: Request, db: Session = Depends(get_db)):
    row = db.query(Aparelho).filter(Aparelho.id == ap_id).first()
    if not row:
        return templates.TemplateResponse(
            request,
            "erro.html",
            {"request": request, "mensagem": "Aparelho não encontrado."},
            status_code=404,
        )
    return templates.TemplateResponse(
        request,
        "aparelho_detalhe.html",
        {"request": request, "a": row},
    )


@app.get("/ofertas", response_class=HTMLResponse)
def listar_ofertas(request: Request, db: Session = Depends(get_db)):
    rows = db.query(OfertaMercado).order_by(OfertaMercado.criado_em.desc()).all()
    return templates.TemplateResponse(
        request,
        "ofertas_lista.html",
        {"request": request, "ofertas": rows},
    )


@app.get("/ofertas/{oid}", response_class=HTMLResponse)
def ver_oferta(oid: int, request: Request, db: Session = Depends(get_db)):
    row = db.query(OfertaMercado).filter(OfertaMercado.id == oid).first()
    if not row:
        return templates.TemplateResponse(
            request,
            "erro.html",
            {"request": request, "mensagem": "Oferta não encontrada."},
            status_code=404,
        )
    return templates.TemplateResponse(
        request,
        "oferta_detalhe.html",
        {"request": request, "o": row},
    )


@app.get("/api/ofertas/{oid}/historico.json")
def api_historico_oferta(oid: int, db: Session = Depends(get_db)):
    row = db.query(OfertaMercado).filter(OfertaMercado.id == oid).first()
    if not row:
        return JSONResponse({"detail": "Oferta não encontrada."}, status_code=404)
    return historico_oferta_json(db, oid)


@app.post("/aparelhos/{ap_id}/excluir")
def excluir_aparelho(ap_id: int, db: Session = Depends(get_db)):
    row = db.query(Aparelho).filter(Aparelho.id == ap_id).first()
    if row:
        db.delete(row)
        db.commit()
    return RedirectResponse(url="/aparelhos", status_code=303)


@app.post("/ofertas/{oid}/excluir")
def excluir_oferta(oid: int, db: Session = Depends(get_db)):
    row = db.query(OfertaMercado).filter(OfertaMercado.id == oid).first()
    if row:
        db.delete(row)
        db.commit()
    return RedirectResponse(url="/ofertas", status_code=303)
