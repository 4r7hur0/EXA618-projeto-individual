"""Rotas HTTP: um endpoint por crawler."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.ingest_crawlers import (
    ingerir_amazon_lote,
    ingerir_mais_celular_lote,
    ingerir_mercadolivre_lote,
)
from app.schemas_ingest import (
    IngestAmazonLoteResponse,
    IngestMaisCelularLoteResponse,
    IngestMaisCelularRequest,
    IngestMarketplaceLoteRequest,
    IngestMercadoLivreLoteResponse,
)

router = APIRouter(prefix="/api/crawlers", tags=["Crawlers"])


@router.post(
    "/mais-celular",
    response_model=IngestMaisCelularLoteResponse,
    summary="Crawler Mais Celular (lote)",
    description=(
        "Lista de aparelhos: pesquisa cada um no Mais Celular **em sequência** "
        "(ficha no banco). Máximo 50 termos. Não roda Amazon nem Mercado Livre."
    ),
)
async def api_crawler_mais_celular(
    body: IngestMaisCelularRequest,
    db: Session = Depends(get_db),
) -> IngestMaisCelularLoteResponse:
    return await ingerir_mais_celular_lote(db, body.termos)


@router.post(
    "/amazon",
    response_model=IngestAmazonLoteResponse,
    summary="Crawler Amazon (lote)",
    description=(
        "Lista de buscas com capacidade no texto (ex.: `iphone 16 128Gb`, `iphone 16 256Gb`). "
        "Cada item é uma pesquisa separada; salva **1 anúncio** por item. Máximo 50."
    ),
)
async def api_crawler_amazon(
    body: IngestMarketplaceLoteRequest,
    db: Session = Depends(get_db),
) -> IngestAmazonLoteResponse:
    return await ingerir_amazon_lote(
        db,
        body.termos or [],
        ofertas_por_termo=body.ofertas_por_termo,
        armazenamento_gb=body.armazenamento_gb,
        armazenamentos_gb=body.armazenamentos_gb,
    )


@router.post(
    "/mercadolivre",
    response_model=IngestMercadoLivreLoteResponse,
    summary="Crawler Mercado Livre (lote)",
    description=(
        "Igual à Amazon: `termos` com modelo + memória. **API primeiro** (ML_USE_API=1); "
        "se falhar, navegador visível (CAPTCHA). 1 anúncio por busca."
    ),
)
async def api_crawler_mercadolivre(
    body: IngestMarketplaceLoteRequest,
    db: Session = Depends(get_db),
) -> IngestMercadoLivreLoteResponse:
    return await ingerir_mercadolivre_lote(
        db,
        body.termos or [],
        ofertas_por_termo=body.ofertas_por_termo,
        armazenamento_gb=body.armazenamento_gb,
        armazenamentos_gb=body.armazenamentos_gb,
    )
