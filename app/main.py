import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.cache_busca import (
    aparelho_para_dict,
    buscar_aparelho_e_ofertas_no_banco,
    oferta_para_dict,
)
from app.config import configure_logging
from app.database import get_db, init_db
from app.ingest_crawlers import ingerir_um_termo
from app.models import Aparelho, OfertaMercado
from app.schemas_ingest import (
    IngestAparelhosRequest,
    IngestAparelhosResponse,
    IngestItemResult,
)
from app.texto_limpo import sem_emojis

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["sem_emojis"] = sem_emojis


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    init_db()
    yield


app = FastAPI(
    title="Catálogo de aparelhos",
    description=(
        "Interface web e API JSON. Documentação interativa (Swagger UI) em **`/docs`** "
        "e ReDoc em **`/redoc`**."
    ),
    lifespan=lifespan,
    openapi_tags=[
        {
            "name": "Cadastro",
            "description": "Ingestão em lote: pesquisa nos sites e grava ficha + ofertas no banco.",
        },
        {"name": "Web", "description": "Páginas HTML."},
        {"name": "API", "description": "Endpoints JSON diversos."},
    ],
)


@app.get(
    "/",
    response_class=HTMLResponse,
    tags=["Web"],
    summary="Página inicial",
)
def pagina_inicial(request: Request):
    aviso = None
    if request.query_params.get("sem_resultado") == "1":
        aviso = "Este aparelho não está na base de dados."
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "erro": None,
            "aviso": aviso,
        },
    )


def _limite_ofertas_por_busca() -> int:
    try:
        n = int(os.environ.get("OFERTAS_POR_BUSCA", "4").strip())
    except ValueError:
        n = 4
    return max(1, min(n, 8))


def _template_resultado(
    request: Request,
    termo: str,
    mc,
    mc_erro,
    amz_list,
    amz_erro,
    ml_list,
    ml_erro,
):
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
        },
    )


@app.post(
    "/api/aparelhos/ingest",
    response_model=IngestAparelhosResponse,
    tags=["Cadastro"],
    summary="Ingerir lista de aparelhos (crawlers → banco)",
    description=(
        "Recebe uma lista de termos de busca. Para **cada** termo, executa os crawlers "
        "(Mais Celular, Amazon, Mercado Livre) e persiste no banco. "
        "Pode levar vários minutos por termo; os itens são processados **em sequência**."
    ),
)
async def api_ingest_aparelhos(
    body: IngestAparelhosRequest,
    db: Session = Depends(get_db),
) -> IngestAparelhosResponse:
    resultados: list[IngestItemResult] = []
    for raw in body.termos:
        termo = (raw or "").strip()
        if not termo:
            continue
        item = await ingerir_um_termo(
            db,
            termo,
            ofertas_por_termo=body.ofertas_por_termo,
        )
        resultados.append(item)
    return IngestAparelhosResponse(
        resultados=resultados,
        total_processados=len(resultados),
    )


@app.post("/buscar", response_class=HTMLResponse, tags=["Web"])
def buscar_completo(
    request: Request,
    termo: str = Form(...),
    db: Session = Depends(get_db),
):
    termo = (termo or "").strip()
    if not termo:
        return _index_com_erro(request, "Informe o modelo ou termo de busca.")

    n_ofertas = _limite_ofertas_por_busca()
    tripla = buscar_aparelho_e_ofertas_no_banco(db, termo, limite_ofertas=n_ofertas)
    if not tripla:
        return RedirectResponse(url="/?sem_resultado=1", status_code=303)

    ap, oa_rows, ol_rows = tripla
    return _template_resultado(
        request,
        termo,
        aparelho_para_dict(ap),
        None,
        [oferta_para_dict(o) for o in oa_rows],
        None,
        [oferta_para_dict(o) for o in ol_rows],
        None,
    )


def _index_com_erro(request: Request, mensagem: str):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "erro": mensagem,
            "aviso": None,
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
