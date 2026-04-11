"""Modelos Pydantic para o endpoint de ingestão em lote (OpenAPI / Swagger)."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class IngestAparelhosRequest(BaseModel):
    """Lista de termos a pesquisar nos sites e gravar no banco."""

    termos: list[str] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Termos de busca (ex.: modelo do aparelho). Máximo 50 itens por requisição.",
        json_schema_extra={"example": ["iPhone 16", "Galaxy S25"]},
    )
    ofertas_por_termo: int | None = Field(
        None,
        ge=1,
        le=8,
        description="Quantas ofertas buscar na Amazon e no ML por termo. "
        "Se omitido, usa a variável OFERTAS_POR_BUSCA (padrão 4).",
    )

    @field_validator("termos", mode="before")
    @classmethod
    def _limpar_termos(cls, v: object) -> object:
        if not isinstance(v, list):
            return v
        limpos = [str(x).strip() for x in v if x is not None and str(x).strip()]
        if not limpos:
            raise ValueError("Informe ao menos um termo não vazio.")
        if len(limpos) > 50:
            raise ValueError("No máximo 50 termos.")
        return limpos


class IngestItemResult(BaseModel):
    termo: str
    ok: bool = Field(description="True se salvou ficha e pelo menos uma oferta em alguma loja, ou só ficha.")
    aparelho_id: int | None = None
    ofertas_amazon_salvas: int = 0
    ofertas_ml_salvas: int = 0
    erros: list[str] = Field(default_factory=list, description="Mensagens de falha parcial (crawler/validação).")


class IngestAparelhosResponse(BaseModel):
    resultados: list[IngestItemResult]
    total_processados: int
