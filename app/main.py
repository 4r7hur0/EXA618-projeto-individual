import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
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
from app.schemas_filtros import OfertasFiltrosPost
from app.schemas_ingest import (
    IngestAparelhosRequest,
    IngestAparelhosResponse,
    IngestItemResult,
)
from app.filtros_api import capacidade_para_gb, parece_aparelho, preco_brl_para_float
from app.texto_limpo import sem_emojis
from crawlers.ofertas_diversidade import OFERTAS_MAX_POR_LOJA

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
        "Interface web e API de filtros. Documentação (Swagger UI) em **`/docs`** e ReDoc em **`/redoc`**."
    ),
    lifespan=lifespan,
    openapi_tags=[
        {
            "name": "Cadastro",
            "description": "Ingestão em lote: pesquisa nos sites e grava ficha + ofertas no banco.",
        },
        {"name": "Web", "description": "Páginas HTML."},
        {"name": "API", "description": "Filtro de ofertas (JSON)."},
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
        n = int(os.environ.get("OFERTAS_POR_BUSCA", "8").strip())
    except ValueError:
        n = 8
    return max(1, min(n, OFERTAS_MAX_POR_LOJA))


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


def _filtrar_ofertas(
    # aliases aceitos: marketplace/origem e preco_de/preco_min e preco_ate/preco_max
    marketplace: str | None = None,
    origem: str | None = None,
    preco_de: float | None = None,
    preco_min: float | None = None,
    preco_ate: float | None = None,
    preco_max: float | None = None,
    # memoria_* agora é RAM (Aparelho.memoria_ram). Para a "memória" da oferta (ex.: 128GB),
    # use oferta_memoria_*_gb.
    memoria_min_gb: int | None = None,
    memoria_max_gb: int | None = None,
    oferta_memoria_min_gb: int | None = None,
    oferta_memoria_max_gb: int | None = None,
    armazenamento_min_gb: int | None = None,
    armazenamento_max_gb: int | None = None,
    somente_aparelhos: bool = True,
    limite: int | None = 50,
    *,
    db: Session,
):
    """
    Filtros:
    - origem (ou marketplace): amazon | mercadolivre
    - preco_min / preco_max (ou preco_de / preco_ate): reais (float)
    - memoria_min_gb / memoria_max_gb: RAM do aparelho vinculado (Aparelho.memoria_ram)
    - oferta_memoria_*_gb: texto de armazenamento na oferta (OfertaMercado.memoria), ex. 128GB
    - armazenamento_*_gb: capacidade **da variante** (prioriza texto da oferta; senão ficha do aparelho)
    """
    cap = 50 if limite is None else max(1, min(int(limite), 200))
    # resolve aliases
    origem_final = (origem or marketplace)
    preco_min_final = preco_min if preco_min is not None else preco_de
    preco_max_final = preco_max if preco_max is not None else preco_ate
    q = db.query(OfertaMercado).outerjoin(Aparelho, OfertaMercado.aparelho_id == Aparelho.id)
    if origem_final:
        o = origem_final.strip().lower()
        if o not in ("amazon", "mercadolivre"):
            raise HTTPException(status_code=400, detail="origem deve ser amazon ou mercadolivre")
        q = q.filter(OfertaMercado.origem == o)
    # Amostra recente maior que cap: muitos registros são descartados (preço ilegível, parece_aparelho, filtros RAM).
    fetch_n = min(3000, max(100, cap * 25))
    q = q.order_by(OfertaMercado.criado_em.desc()).limit(fetch_n)

    rows = q.all()
    out: list[dict] = []
    for r in rows:
        pv = preco_brl_para_float(r.preco)
        oferta_mem_gb = capacidade_para_gb(r.memoria)
        if somente_aparelhos and not parece_aparelho(
            r.nome_produto, preco_valor=pv, oferta_memoria_gb=oferta_mem_gb
        ):
            continue
        if preco_min_final is not None and (pv is None or pv < float(preco_min_final)):
            continue
        if preco_max_final is not None and (pv is None or pv > float(preco_max_final)):
            continue

        # RAM vem do aparelho vinculado
        ram_gb = capacidade_para_gb(r.aparelho.memoria_ram) if r.aparelho else None
        if memoria_min_gb is not None and (ram_gb is None or ram_gb < int(memoria_min_gb)):
            continue
        if memoria_max_gb is not None and (ram_gb is None or ram_gb > int(memoria_max_gb)):
            continue

        # "memoria" da oferta costuma ser armazenamento (ex.: 128GB)
        if oferta_memoria_min_gb is not None and (
            oferta_mem_gb is None or oferta_mem_gb < int(oferta_memoria_min_gb)
        ):
            continue
        if oferta_memoria_max_gb is not None and (
            oferta_mem_gb is None or oferta_mem_gb > int(oferta_memoria_max_gb)
        ):
            continue

        ag_ficha = capacidade_para_gb(r.aparelho.armazenamento) if r.aparelho else None
        # Variante vendida (ex.: 64 GB no título) prevalece sobre a ficha agregada (ex.: "até 256 GB").
        ag = oferta_mem_gb if oferta_mem_gb is not None else ag_ficha
        if armazenamento_min_gb is not None and (ag is None or ag < int(armazenamento_min_gb)):
            continue
        if armazenamento_max_gb is not None and (ag is None or ag > int(armazenamento_max_gb)):
            continue

        d = oferta_para_dict(r)
        d["id"] = r.id
        d["origem"] = r.origem
        d["preco_valor"] = pv
        d["memoria_ram_gb"] = ram_gb
        d["oferta_memoria_gb"] = oferta_mem_gb
        d["armazenamento_gb"] = ag
        if ag_ficha is not None and ag_ficha != ag:
            d["armazenamento_ficha_gb"] = ag_ficha
        if r.aparelho:
            d["aparelho"] = {
                "id": r.aparelho.id,
                "modelo": sem_emojis(r.aparelho.modelo) or r.aparelho.modelo,
                "armazenamento": sem_emojis(r.aparelho.armazenamento) if r.aparelho.armazenamento else None,
                "memoria_ram": sem_emojis(r.aparelho.memoria_ram) if r.aparelho.memoria_ram else None,
            }
        out.append(d)
        if len(out) >= cap:
            break

    return {
        "filtros": {
            "marketplace": marketplace,
            "origem": origem,
            "preco_de": preco_de,
            "preco_min": preco_min,
            "preco_ate": preco_ate,
            "preco_max": preco_max,
            "memoria_min_gb": memoria_min_gb,
            "memoria_max_gb": memoria_max_gb,
            "oferta_memoria_min_gb": oferta_memoria_min_gb,
            "oferta_memoria_max_gb": oferta_memoria_max_gb,
            "armazenamento_min_gb": armazenamento_min_gb,
            "armazenamento_max_gb": armazenamento_max_gb,
            "somente_aparelhos": somente_aparelhos,
            "limite": cap,
        },
        "total": len(out),
        "items": out,
    }


@app.post("/api/ofertas/filtros", tags=["API"], summary="Filtrar ofertas (POST JSON opcional)")
def api_filtrar_ofertas_opcional(body: OfertasFiltrosPost, db: Session = Depends(get_db)):
    """
    Corpo JSON com filtros opcionais; omita campos que não importam (pode enviar objeto vazio).

    - **marketplace**: `amazon` ou `mercadolivre` (omitido = ambos)

    - **preco_max**: faixa de preço **de 0 até** esse valor (reais, inclusive). Ofertas sem preço
      parseável ficam de fora.

    - **memoria_ram_gb**: **apenas** ofertas cuja RAM (ficha do aparelho) seja **exatamente** esse
      valor em GB.

    - **armazenamento_gb**: **apenas** ofertas cuja capacidade seja **exatamente** esse valor (GB);
      prioriza a variante da oferta, senão a ficha.
    """
    mem_min = mem_max = body.memoria_ram_gb
    arm_min = arm_max = body.armazenamento_gb
    return _filtrar_ofertas(
        marketplace=body.marketplace,
        origem=body.marketplace,
        preco_max=body.preco_max,
        memoria_min_gb=mem_min,
        memoria_max_gb=mem_max,
        armazenamento_min_gb=arm_min,
        armazenamento_max_gb=arm_max,
        somente_aparelhos=True,
        limite=body.limite,
        db=db,
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
