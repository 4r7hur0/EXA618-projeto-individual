"""Rotas de ingestão via crawlers (só registradas se `crawlers_enabled()`)."""

from fastapi import Depends, FastAPI
from sqlalchemy.orm import Session

from app.database import get_db
from app.ingest_crawlers import ingerir_um_termo
from app.routes_crawlers import router as crawlers_router
from app.schemas_ingest import (
    IngestAparelhosRequest,
    IngestAparelhosResponse,
    IngestItemResult,
)


def register_crawler_routes(app: FastAPI) -> None:
    app.include_router(crawlers_router)

    @app.post(
        "/api/aparelhos/ingest",
        response_model=IngestAparelhosResponse,
        tags=["Cadastro"],
        summary="Ingerir lista de aparelhos (crawlers → banco)",
        description=(
            "Recebe uma lista de termos. Para **cada** termo, roda os três crawlers **em sequência** "
            "(Mais Celular → Amazon → Mercado Livre). Crawlers isolados: "
            "`POST /api/crawlers/mais-celular` (lista), `/api/crawlers/amazon`, `/api/crawlers/mercadolivre`."
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
                armazenamento_gb=body.armazenamento_gb,
                armazenamentos_gb=body.armazenamentos_gb,
            )
            resultados.append(item)
        return IngestAparelhosResponse(
            resultados=resultados,
            total_processados=len(resultados),
        )
