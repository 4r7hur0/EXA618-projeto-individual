"""Modelos Pydantic para ingestão (crawlers individuais e lote)."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator


class IngestTermoRequest(BaseModel):
    """Um termo de busca para rodar um único crawler."""

    termo: str = Field(
        ...,
        min_length=1,
        description=(
            "Modelo (ex.: iPhone 16). Na Amazon e no Mercado Livre, use "
            "`armazenamento_gb` / `armazenamentos_gb` ou escreva a capacidade no termo "
            "(ex.: iPhone 16 128GB)."
        ),
        json_schema_extra={"example": "iPhone 16"},
    )
    armazenamento_gb: int | None = Field(
        None,
        description=(
            "Amazon e Mercado Livre: capacidade exata da variante (ex.: 128). "
            "Monta a busca como «termo + NGB»."
        ),
        json_schema_extra={"example": 128},
    )
    armazenamentos_gb: list[int] | None = Field(
        None,
        min_length=1,
        max_length=8,
        description=(
            "Amazon e Mercado Livre: várias buscas em sequência (ex.: [128, 512] → "
            "«iPhone 16 128GB» e «iPhone 16 512GB»)."
        ),
        json_schema_extra={"example": [128, 512]},
    )
    ofertas_por_termo: int | None = Field(
        None,
        ge=1,
        le=32,
        description="Amazon e Mercado Livre: quantas ofertas salvar por variante. Omitido = OFERTAS_POR_BUSCA.",
    )

    @field_validator("termo", mode="before")
    @classmethod
    def _limpar_termo(cls, v: object) -> object:
        if v is None:
            raise ValueError("Informe o termo de busca.")
        s = str(v).strip()
        if not s:
            raise ValueError("Informe o termo de busca.")
        return s

    @field_validator("armazenamentos_gb", mode="before")
    @classmethod
    def _limpar_armazenamentos(cls, v: object) -> object:
        if v is None:
            return v
        if not isinstance(v, list):
            return v
        out: list[int] = []
        for x in v:
            if x is None:
                continue
            out.append(int(x))
        if not out:
            raise ValueError("Informe ao menos uma capacidade em armazenamentos_gb.")
        return out


class IngestMarketplaceLoteRequest(BaseModel):
    """
    Vários aparelhos na mesma requisição (Amazon ou Mercado Livre).
    Escreva cada busca completa em `termos` (modelo + capacidade no mesmo texto).
    """

    termos: list[str] | str | None = Field(
        None,
        description=(
            "Uma busca por item — modelo e capacidade no mesmo texto. "
            "Ex.: «iphone 16 128Gb», «iphone 16 256Gb». Lista ou texto com vírgulas/linhas. Máximo 50."
        ),
        json_schema_extra={
            "example": ["iphone 16 128Gb", "iphone 16 256Gb"]
        },
    )
    termo: str | None = Field(
        None,
        min_length=1,
        description="Atalho: uma busca com capacidade no texto (ex.: iphone 16 128Gb).",
        json_schema_extra={"example": "iphone 16 128Gb"},
    )
    armazenamento_gb: int | None = Field(
        None,
        description="Opcional: força uma capacidade se o termo não trouxer GB no texto.",
    )
    armazenamentos_gb: list[int] | None = Field(
        None,
        min_length=1,
        max_length=8,
        description="Opcional: várias capacidades só se o termo não tiver GB (ex.: iphone 16 + [128,256]).",
    )
    ofertas_por_termo: int | None = Field(
        None,
        ge=1,
        le=32,
        description="Ofertas salvas por aparelho e por variante de armazenamento.",
    )

    @field_validator("termo", mode="before")
    @classmethod
    def _limpar_termo_unico(cls, v: object) -> object:
        if v is None:
            return v
        s = str(v).strip()
        if not s:
            raise ValueError("termo não pode ser vazio.")
        return s

    @field_validator("termos", mode="before")
    @classmethod
    def _limpar_termos_lote(cls, v: object) -> object:
        if v is None:
            return v
        from app.termo_busca import parse_termos_usuario

        limpos = parse_termos_usuario(v)
        if not limpos:
            raise ValueError("Informe ao menos um termo não vazio em termos.")
        if len(limpos) > 50:
            raise ValueError("No máximo 50 termos.")
        return limpos

    @field_validator("armazenamentos_gb", mode="before")
    @classmethod
    def _limpar_armazenamentos_mp(cls, v: object) -> object:
        if v is None:
            return v
        if not isinstance(v, list):
            return v
        out: list[int] = []
        for x in v:
            if x is None:
                continue
            out.append(int(x))
        if not out:
            raise ValueError("Informe ao menos uma capacidade em armazenamentos_gb.")
        return out

    @model_validator(mode="before")
    @classmethod
    def _resolver_lista_termos(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        termos = data.get("termos")
        termo = data.get("termo")
        if termos:
            return data
        if termo and str(termo).strip():
            data = {**data, "termos": [str(termo).strip()]}
            return data
        raise ValueError("Informe termos (lista) ou termo (um aparelho).")


class IngestMaisCelularRequest(BaseModel):
    """Lista de aparelhos para o crawler Mais Celular (um por vez, em sequência)."""

    termos: list[str] | str = Field(
        ...,
        description=(
            "Lista ou texto (linhas/vírgulas). Ex.: iphone 16 128Gb, iphone 16 256 Gb. "
            "Máximo 50."
        ),
        json_schema_extra={
            "example": ["iphone 16 128Gb", "iphone 16 256 Gb"]
        },
    )

    @field_validator("termos", mode="before")
    @classmethod
    def _limpar_termos(cls, v: object) -> object:
        from app.termo_busca import parse_termos_usuario

        limpos = parse_termos_usuario(v)
        if not limpos:
            raise ValueError("Informe ao menos um termo não vazio.")
        if len(limpos) > 50:
            raise ValueError("No máximo 50 termos.")
        return limpos


class IngestMaisCelularResponse(BaseModel):
    crawler: str = "mais_celular"
    termo: str
    ok: bool
    aparelho_id: int | None = None
    ficha_salva: bool = False
    erros: list[str] = Field(default_factory=list)


class IngestMaisCelularLoteResponse(BaseModel):
    crawler: str = "mais_celular"
    resultados: list[IngestMaisCelularResponse]
    total_processados: int


class IngestAmazonResponse(BaseModel):
    crawler: str = "amazon"
    termo: str
    termos_loja: list[str] = Field(
        default_factory=list,
        description="Termos enviados à Amazon (uma entrada por variante de armazenamento).",
    )
    ok: bool
    aparelho_id: int | None = None
    ofertas_salvas: int = 0
    erros: list[str] = Field(default_factory=list)


class IngestAmazonLoteResponse(BaseModel):
    crawler: str = "amazon"
    resultados: list[IngestAmazonResponse]
    total_processados: int


class IngestMercadoLivreResponse(BaseModel):
    crawler: str = "mercadolivre"
    termo: str
    termos_loja: list[str] = Field(
        default_factory=list,
        description="Termos enviados ao Mercado Livre (uma entrada por variante).",
    )
    ok: bool
    aparelho_id: int | None = None
    ofertas_salvas: int = 0
    erros: list[str] = Field(default_factory=list)


class IngestMercadoLivreLoteResponse(BaseModel):
    crawler: str = "mercadolivre"
    resultados: list[IngestMercadoLivreResponse]
    total_processados: int


class IngestAparelhosRequest(BaseModel):
    """Lista de termos; cada termo passa pelos três crawlers em sequência."""

    termos: list[str] | str = Field(
        ...,
        description=(
            "Um modelo por item (ex.: iphone 16). Capacidades vêm do .env se o termo não tiver GB. "
            "Máximo 50."
        ),
        json_schema_extra={"example": ["iphone 16 128Gb", "iphone 16 256Gb"]},
    )
    armazenamento_gb: int | None = Field(
        None,
        description="Opcional: mesma capacidade extra para todos os termos.",
    )
    armazenamentos_gb: list[int] | None = Field(
        None,
        min_length=1,
        max_length=8,
        description="Opcional: expande termo sem GB (ex.: iphone 16 + [128,256]).",
    )
    ofertas_por_termo: int | None = Field(
        None,
        ge=1,
        le=32,
        description="Máx. 1 oferta salva por capacidade por loja. Omitido = OFERTAS_POR_BUSCA.",
    )

    @field_validator("termos", mode="before")
    @classmethod
    def _limpar_termos_ingest(cls, v: object) -> object:
        from app.termo_busca import parse_termos_usuario

        limpos = parse_termos_usuario(v)
        if not limpos:
            raise ValueError("Informe ao menos um termo não vazio.")
        if len(limpos) > 50:
            raise ValueError("No máximo 50 termos.")
        return limpos

    @field_validator("armazenamentos_gb", mode="before")
    @classmethod
    def _limpar_armazenamentos_lote(cls, v: object) -> object:
        if v is None:
            return v
        if not isinstance(v, list):
            return v
        out: list[int] = []
        for x in v:
            if x is None:
                continue
            out.append(int(x))
        if not out:
            raise ValueError("Informe ao menos uma capacidade em armazenamentos_gb.")
        return out


class IngestItemResult(BaseModel):
    termo: str
    ok: bool = Field(
        description="True se salvou ficha e/ou ofertas em pelo menos uma etapa."
    )
    aparelho_id: int | None = None
    ofertas_amazon_salvas: int = 0
    ofertas_ml_salvas: int = 0
    erros: list[str] = Field(default_factory=list)


class IngestAparelhosResponse(BaseModel):
    resultados: list[IngestItemResult]
    total_processados: int
