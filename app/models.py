from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class Aparelho(Base):
    __tablename__ = "aparelhos"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    termo_busca: Mapped[str] = mapped_column(String(512), index=True)
    termo_normalizado: Mapped[str | None] = mapped_column(
        String(512), nullable=True, index=True
    )
    modelo: Mapped[str] = mapped_column(String(512))
    url_fonte: Mapped[str | None] = mapped_column(Text, nullable=True)
    imagem_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    antutu: Mapped[str | None] = mapped_column(Text, nullable=True)
    geekbench: Mapped[str | None] = mapped_column(Text, nullable=True)
    processador: Mapped[str | None] = mapped_column(Text, nullable=True)
    sistema_operacional: Mapped[str | None] = mapped_column(Text, nullable=True)
    memoria_ram: Mapped[str | None] = mapped_column(Text, nullable=True)
    armazenamento: Mapped[str | None] = mapped_column(Text, nullable=True)
    tela: Mapped[str | None] = mapped_column(Text, nullable=True)
    camera_traseira: Mapped[str | None] = mapped_column(Text, nullable=True)
    camera_frontal: Mapped[str | None] = mapped_column(Text, nullable=True)
    conectividade: Mapped[str | None] = mapped_column(Text, nullable=True)
    bateria: Mapped[str | None] = mapped_column(Text, nullable=True)
    carregamento: Mapped[str | None] = mapped_column(Text, nullable=True)
    dimensoes: Mapped[str | None] = mapped_column(Text, nullable=True)
    peso: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio: Mapped[str | None] = mapped_column(Text, nullable=True)
    biometria: Mapped[str | None] = mapped_column(Text, nullable=True)
    especificacoes_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    extraido_em_texto: Mapped[str | None] = mapped_column(String(64), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    ofertas: Mapped[list["OfertaMercado"]] = relationship(
        "OfertaMercado", back_populates="aparelho"
    )


class OfertaMercado(Base):
    __tablename__ = "ofertas_mercado"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    origem: Mapped[str] = mapped_column(String(32), index=True)  # amazon | mercadolivre
    termo_busca: Mapped[str] = mapped_column(String(512), index=True)
    termo_normalizado: Mapped[str | None] = mapped_column(
        String(512), nullable=True, index=True
    )
    nome_produto: Mapped[str] = mapped_column(Text)
    memoria: Mapped[str | None] = mapped_column(Text, nullable=True)
    preco: Mapped[str | None] = mapped_column(Text, nullable=True)
    link: Mapped[str | None] = mapped_column(Text, nullable=True)
    imagem_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    vendedor: Mapped[str | None] = mapped_column(Text, nullable=True)
    reputacao: Mapped[str | None] = mapped_column(Text, nullable=True)
    reputacao_nivel: Mapped[str | None] = mapped_column(Text, nullable=True)
    vendas_aprox: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraido_em_texto: Mapped[str | None] = mapped_column(String(64), nullable=True)
    aparelho_id: Mapped[int | None] = mapped_column(
        ForeignKey("aparelhos.id", ondelete="SET NULL"), nullable=True, index=True
    )
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    aparelho: Mapped["Aparelho | None"] = relationship(
        "Aparelho", back_populates="ofertas"
    )
    historicos_precos: Mapped[list["PrecoHistorico"]] = relationship(
        "PrecoHistorico", back_populates="oferta", passive_deletes=True
    )


class PrecoHistorico(Base):
    __tablename__ = "precos_historico"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    oferta_mercado_id: Mapped[int] = mapped_column(
        ForeignKey("ofertas_mercado.id", ondelete="CASCADE"),
        index=True,
    )
    preco_texto: Mapped[str | None] = mapped_column(Text, nullable=True)
    preco_valor: Mapped[float | None] = mapped_column(Float, nullable=True)
    registrado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    oferta: Mapped["OfertaMercado"] = relationship(
        "OfertaMercado", back_populates="historicos_precos"
    )
