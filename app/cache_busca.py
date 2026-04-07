"""Reconstrói dicts de resultado a partir do banco (busca já feita)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Aparelho, OfertaMercado
from app.preco_util import cutoff_datetime, normalizar_termo_cache


def aparelho_para_dict(a: Aparelho) -> dict:
    return {
        "modelo": a.modelo,
        "antutu": a.antutu,
        "geekbench": a.geekbench,
        "processador": a.processador,
        "sistema_operacional": a.sistema_operacional,
        "memoria_ram": a.memoria_ram,
        "armazenamento": a.armazenamento,
        "tela": a.tela,
        "camera_traseira": a.camera_traseira,
        "camera_frontal": a.camera_frontal,
        "conectividade": a.conectividade,
        "bateria": a.bateria,
        "carregamento": a.carregamento,
        "dimensoes": a.dimensoes,
        "peso": a.peso,
        "audio": a.audio,
        "biometria": a.biometria,
        "especificacoes_todas": a.especificacoes_json or {},
        "data": a.extraido_em_texto,
        "url": a.url_fonte,
        "imagem_url": a.imagem_url,
    }


def oferta_para_dict(o: OfertaMercado) -> dict:
    d: dict = {
        "nome": o.nome_produto,
        "memoria": o.memoria,
        "preco": o.preco,
        "link": o.link,
        "imagem_url": o.imagem_url,
    }
    if o.origem == "amazon":
        d["data_extracao"] = o.extraido_em_texto
    else:
        d["data"] = o.extraido_em_texto
        d["vendedor"] = o.vendedor
        d["reputacao"] = o.reputacao
        d["reputacao_nivel"] = o.reputacao_nivel
        d["vendas_aprox"] = o.vendas_aprox
    return d


def buscar_tripla_em_cache(
    db: Session, termo: str, *, limite_ofertas: int = 4
) -> tuple[Aparelho, list[OfertaMercado], list[OfertaMercado]] | None:
    """
    Retorna (aparelho, ofertas_amazon, ofertas_ml) se existir busca completa recente
    com o mesmo termo normalizado. Ordem das ofertas = ordem de inserção (melhor primeiro).
    """
    cap = max(1, min(int(limite_ofertas), 24))
    key = normalizar_termo_cache(termo)
    lim = cutoff_datetime()

    ap = (
        db.query(Aparelho)
        .filter(
            Aparelho.termo_normalizado == key,
            Aparelho.criado_em >= lim,
        )
        .order_by(Aparelho.criado_em.desc())
        .first()
    )
    if not ap:
        return None

    oa_rows = (
        db.query(OfertaMercado)
        .filter(
            OfertaMercado.aparelho_id == ap.id,
            OfertaMercado.origem == "amazon",
        )
        .order_by(OfertaMercado.id.asc())
        .limit(cap)
        .all()
    )
    ol_rows = (
        db.query(OfertaMercado)
        .filter(
            OfertaMercado.aparelho_id == ap.id,
            OfertaMercado.origem == "mercadolivre",
        )
        .order_by(OfertaMercado.id.asc())
        .limit(cap)
        .all()
    )
    if not oa_rows or not ol_rows:
        return None
    return ap, oa_rows, ol_rows
