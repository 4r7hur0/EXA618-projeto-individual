import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session, joinedload

from app.cache_busca import (
    aparelho_para_dict,
    buscar_aparelho_e_ofertas_no_banco,
    oferta_para_dict,
)
from app.config import configure_logging
from app.database import get_db, init_db
from app.features import crawlers_enabled
from app.models import Aparelho, OfertaMercado
from app.ofertas_limites import OFERTAS_MAX_POR_LOJA
from app.schemas_filtros import OfertasFiltrosPost
from app.filtros_api import capacidade_para_gb, parece_aparelho, preco_brl_para_float
from app.texto_limpo import sem_emojis

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


def _openapi_tags() -> list[dict[str, str]]:
    tags: list[dict[str, str]] = [
        {"name": "Frontend", "description": "Interface React (servida pelo build estático quando presente)."},
        {"name": "API", "description": "Consulta e filtro de ofertas (JSON)."},
    ]
    if crawlers_enabled():
        tags.insert(
            0,
            {
                "name": "Crawlers",
                "description": "Um endpoint por loja: executa só aquele crawler e grava no banco.",
            },
        )
        tags.insert(
            1,
            {
                "name": "Cadastro",
                "description": "Ingestão em lote: os três crawlers em sequência por termo.",
            },
        )
    return tags


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    init_db()
    yield


app = FastAPI(
    title="Catálogo de aparelhos",
    description=(
        "API JSON e interface React (build em `frontend/dist` ou dev em Vite). "
        "Documentação em **`/docs`** e ReDoc em **`/redoc`**."
    ),
    lifespan=lifespan,
    openapi_tags=_openapi_tags(),
)

_cors_origins = [
    o.strip()
    for o in os.environ.get(
        "CORS_ORIGINS",
        "http://127.0.0.1:5173,http://localhost:5173",
    ).split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins or ["http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _limite_ofertas_por_busca() -> int:
    try:
        n = int(os.environ.get("OFERTAS_POR_BUSCA", "8").strip())
    except ValueError:
        n = 8
    return max(1, min(n, OFERTAS_MAX_POR_LOJA))


def _aparelho_list_item(a: Aparelho) -> dict:
    return {
        "id": a.id,
        "modelo": sem_emojis(a.modelo) if a.modelo else a.modelo,
        "termo_busca": a.termo_busca,
        "extraido_em_texto": a.extraido_em_texto,
        "criado_em": a.criado_em.isoformat() if a.criado_em else None,
    }


def _aparelho_detalhe_api(a: Aparelho) -> dict:
    d = aparelho_para_dict(a)
    d.pop("especificacoes_todas", None)
    d["id"] = a.id
    d["termo_busca"] = a.termo_busca
    d["termo_normalizado"] = a.termo_normalizado
    d["especificacoes_json"] = a.especificacoes_json or {}
    d["criado_em"] = a.criado_em.isoformat() if a.criado_em else None
    return d


def _oferta_list_item(o: OfertaMercado) -> dict:
    nome = o.nome_produto or ""
    if isinstance(nome, str):
        nome = sem_emojis(nome) or nome
    return {
        "id": o.id,
        "origem": o.origem,
        "nome_produto": nome,
        "preco": o.preco,
        "extraido_em_texto": o.extraido_em_texto,
        "criado_em": o.criado_em.isoformat() if o.criado_em else None,
    }


def _oferta_detalhe_api(o: OfertaMercado) -> dict:
    def _s(v):
        return sem_emojis(v) if isinstance(v, str) else v

    out = {
        "id": o.id,
        "origem": o.origem,
        "termo_busca": o.termo_busca,
        "nome_produto": _s(o.nome_produto),
        "memoria": _s(o.memoria),
        "preco": o.preco,
        "link": o.link,
        "imagem_url": o.imagem_url,
        "vendedor": _s(o.vendedor),
        "reputacao": _s(o.reputacao),
        "reputacao_nivel": _s(o.reputacao_nivel),
        "vendas_aprox": _s(o.vendas_aprox),
        "extraido_em_texto": o.extraido_em_texto,
        "aparelho_id": o.aparelho_id,
        "criado_em": o.criado_em.isoformat() if o.criado_em else None,
        "aparelho": None,
    }
    if o.aparelho is not None:
        out["aparelho"] = _aparelho_detalhe_api(o.aparelho)
    return out


def _coerce_limite_ofertas(v) -> int | None:
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        raise HTTPException(status_code=400, detail="limite_ofertas deve ser um inteiro.")
    if isinstance(v, int):
        return max(1, min(int(v), OFERTAS_MAX_POR_LOJA))
    if isinstance(v, float):
        return max(1, min(int(v), OFERTAS_MAX_POR_LOJA))
    try:
        return max(1, min(int(str(v).strip()), OFERTAS_MAX_POR_LOJA))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="limite_ofertas deve ser um inteiro.")


@app.post("/api/buscar", tags=["API"], summary="Buscar no banco (JSON)")
def api_buscar_post(
    body: dict = Body(...),
    db: Session = Depends(get_db),
):
    """
    Busca **no banco** por termo (não roda crawler) e retorna JSON com:
    - `mc`: ficha do aparelho (Mais Celular persistido)
    - `amazon`: ofertas salvas vinculadas
    - `mercadolivre`: ofertas salvas vinculadas

    Body (JSON):
    - `termo` (obrigatório)
    - `limite_ofertas` (opcional): quantas ofertas por loja (1–32). Padrão vem de `OFERTAS_POR_BUSCA`.
    """
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body deve ser um objeto JSON.")
    termo = (body.get("termo") or "").strip()
    if not termo:
        raise HTTPException(status_code=400, detail="Informe o termo de busca.")
    limite = _coerce_limite_ofertas(body.get("limite_ofertas"))
    cap = _limite_ofertas_por_busca() if limite is None else limite

    tripla = buscar_aparelho_e_ofertas_no_banco(db, termo, limite_ofertas=cap)
    if not tripla:
        raise HTTPException(status_code=404, detail="Este aparelho não está na base de dados.")

    ap, oa_rows, ol_rows = tripla
    return {
        "termo": termo,
        "limite_ofertas": cap,
        "mc": aparelho_para_dict(ap),
        "amazon": [oferta_para_dict(o) for o in oa_rows],
        "mercadolivre": [oferta_para_dict(o) for o in ol_rows],
    }


def _filtrar_ofertas(
    # aliases aceitos: marketplace/origem e preco_de/preco_min e preco_ate/preco_max
    termo: str | None = None,
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
    termo_final = (termo or "").strip().lower() or None
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
        if termo_final:
            nome_l = (r.nome_produto or "").lower()
            modelo_l = (r.aparelho.modelo or "").lower() if r.aparelho else ""
            if termo_final not in nome_l and termo_final not in modelo_l:
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
            "termo": termo,
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

    - **termo**: texto contido no modelo ou no nome do produto.

    - **preco_min** / **preco_max**: faixa de preço em reais (inclusive). Ofertas sem preço
      parseável ficam de fora.

    - **memoria_ram_gb**: **apenas** ofertas cuja RAM (ficha do aparelho) seja **exatamente** esse
      valor em GB.

    - **armazenamento_gb**: **apenas** ofertas cuja capacidade seja **exatamente** esse valor (GB);
      prioriza a variante da oferta, senão a ficha.
    """
    mem_min = mem_max = body.memoria_ram_gb
    arm_min = arm_max = body.armazenamento_gb
    return _filtrar_ofertas(
        termo=body.termo,
        marketplace=body.marketplace,
        origem=body.marketplace,
        preco_min=body.preco_min,
        preco_max=body.preco_max,
        memoria_min_gb=mem_min,
        memoria_max_gb=mem_max,
        armazenamento_min_gb=arm_min,
        armazenamento_max_gb=arm_max,
        somente_aparelhos=True,
        limite=body.limite,
        db=db,
    )


@app.get("/api/aparelhos", tags=["API"], summary="Listar fichas salvas")
def api_listar_aparelhos(db: Session = Depends(get_db)):
    rows = db.query(Aparelho).order_by(Aparelho.criado_em.desc()).all()
    return {"total": len(rows), "items": [_aparelho_list_item(a) for a in rows]}


@app.get("/api/aparelhos/{ap_id}", tags=["API"], summary="Detalhe da ficha")
def api_aparelho_detalhe(ap_id: int, db: Session = Depends(get_db)):
    row = db.query(Aparelho).filter(Aparelho.id == ap_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Aparelho não encontrado.")
    return _aparelho_detalhe_api(row)


@app.delete("/api/aparelhos/{ap_id}", status_code=204, tags=["API"], summary="Excluir ficha")
def api_excluir_aparelho(ap_id: int, db: Session = Depends(get_db)):
    row = db.query(Aparelho).filter(Aparelho.id == ap_id).first()
    if row:
        db.delete(row)
        db.commit()


@app.get("/api/ofertas", tags=["API"], summary="Listar ofertas salvas")
def api_listar_ofertas_salvas(db: Session = Depends(get_db)):
    rows = db.query(OfertaMercado).order_by(OfertaMercado.criado_em.desc()).all()
    return {"total": len(rows), "items": [_oferta_list_item(o) for o in rows]}


@app.get("/api/ofertas/{oid}", tags=["API"], summary="Detalhe da oferta")
def api_oferta_detalhe(oid: int, db: Session = Depends(get_db)):
    row = (
        db.query(OfertaMercado)
        .options(joinedload(OfertaMercado.aparelho))
        .filter(OfertaMercado.id == oid)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Oferta não encontrada.")
    return _oferta_detalhe_api(row)


@app.delete("/api/ofertas/{oid}", status_code=204, tags=["API"], summary="Excluir oferta")
def api_excluir_oferta(oid: int, db: Session = Depends(get_db)):
    row = db.query(OfertaMercado).filter(OfertaMercado.id == oid).first()
    if row:
        db.delete(row)
        db.commit()


def _register_frontend(app: FastAPI) -> None:
    index = FRONTEND_DIST / "index.html"
    if not index.is_file():

        @app.get("/", include_in_schema=False, tags=["Frontend"])
        def root_sem_build():
            return JSONResponse(
                {
                    "mensagem": (
                        "API ativa. Interface React: em desenvolvimento use `npm run dev` em frontend/ "
                        "(Vite, porta 5173); em produção rode `npm run build` e sirva frontend/dist."
                    ),
                    "docs": "/docs",
                }
            )

        return

    assets = FRONTEND_DIST / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="vite-assets")

    @app.get("/", include_in_schema=False, tags=["Frontend"])
    def spa_index():
        return FileResponse(index)

    @app.get("/{full_path:path}", include_in_schema=False, tags=["Frontend"])
    def spa_deep_link(full_path: str):
        if full_path.startswith(("api/", "assets/")):
            raise HTTPException(status_code=404, detail="Not found")
        return FileResponse(index)


if crawlers_enabled():
    from app.crawler_routes import register_crawler_routes

    register_crawler_routes(app)

_register_frontend(app)
