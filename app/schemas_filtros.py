"""Corpo JSON opcional para o POST simplificado de ofertas."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OfertasFiltrosPost(BaseModel):
    """
    Todos os campos são opcionais. Envie apenas o que quiser filtrar
    (ex.: só `preco_max` ou só `marketplace`).
    """

    marketplace: str | None = Field(
        None,
        description='Onde comprar: "amazon" ou "mercadolivre". Omitido = todas as origens.',
    )
    preco_max: float | None = Field(
        None,
        ge=0,
        description=(
            "Teto de preço: entram ofertas com preço **de 0 até este valor** (reais, inclusive), "
            "conforme valor parseado do texto."
        ),
    )
    memoria_ram_gb: int | None = Field(
        None,
        ge=1,
        description="RAM **exata** (GB) na ficha do aparelho vinculado; só entra se bater com o número pedido.",
    )
    armazenamento_gb: int | None = Field(
        None,
        ge=1,
        description=(
            "Armazenamento **exato** (GB): prioriza a variante na oferta (SKU); se não der, usa a ficha."
        ),
    )
    limite: int | None = Field(
        50,
        ge=1,
        le=200,
        description="Máximo de ofertas retornadas.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {},
                {"marketplace": "mercadolivre", "preco_max": 2500},
                {
                    "marketplace": "amazon",
                    "preco_max": 4000,
                    "memoria_ram_gb": 8,
                    "armazenamento_gb": 128,
                },
            ]
        },
    )

    @field_validator("marketplace", mode="before")
    @classmethod
    def _normalizar_marketplace(cls, v: object) -> object:
        if v is None:
            return None
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("marketplace")
    @classmethod
    def _validar_marketplace(cls, v: str | None) -> str | None:
        if v is None:
            return None
        o = str(v).strip().lower()
        if o not in ("amazon", "mercadolivre"):
            raise ValueError(
                'marketplace deve ser "amazon" ou "mercadolivre" (ou omitido).'
            )
        return o

