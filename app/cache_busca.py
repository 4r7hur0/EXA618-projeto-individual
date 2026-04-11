"""Reconstrói dicts de resultado a partir do banco (busca já feita)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Aparelho, OfertaMercado
from app.preco_util import normalizar_termo_cache
from app.texto_limpo import sem_emojis


def _s(v):
    return sem_emojis(v) if isinstance(v, str) else v


def aparelho_para_dict(a: Aparelho) -> dict:
    return {
        "modelo": _s(a.modelo),
        "antutu": _s(a.antutu),
        "geekbench": _s(a.geekbench),
        "processador": _s(a.processador),
        "sistema_operacional": _s(a.sistema_operacional),
        "memoria_ram": _s(a.memoria_ram),
        "armazenamento": _s(a.armazenamento),
        "tela": _s(a.tela),
        "camera_traseira": _s(a.camera_traseira),
        "camera_frontal": _s(a.camera_frontal),
        "conectividade": _s(a.conectividade),
        "bateria": _s(a.bateria),
        "carregamento": _s(a.carregamento),
        "dimensoes": _s(a.dimensoes),
        "peso": _s(a.peso),
        "audio": _s(a.audio),
        "biometria": _s(a.biometria),
        "especificacoes_todas": a.especificacoes_json or {},
        "data": _s(a.extraido_em_texto),
        "url": a.url_fonte,
        "imagem_url": a.imagem_url,
    }


def oferta_para_dict(o: OfertaMercado) -> dict:
    d: dict = {
        "nome": _s(o.nome_produto),
        "memoria": _s(o.memoria),
        "preco": _s(o.preco),
        "link": o.link,
        "imagem_url": o.imagem_url,
    }
    if o.origem == "amazon":
        d["data_extracao"] = _s(o.extraido_em_texto)
    else:
        d["data"] = _s(o.extraido_em_texto)
        d["vendedor"] = _s(o.vendedor)
        d["reputacao"] = _s(o.reputacao)
        d["reputacao_nivel"] = _s(o.reputacao_nivel)
        d["vendas_aprox"] = _s(o.vendas_aprox)
    return d


def buscar_aparelho_e_ofertas_no_banco(
    db: Session, termo: str, *, limite_ofertas: int = 4
) -> tuple[Aparelho, list[OfertaMercado], list[OfertaMercado]] | None:
    """
    Retorna (aparelho, ofertas_amazon, ofertas_ml) se existir aparelho salvo com o mesmo
    termo normalizado (cadastro mais recente). Ofertas podem ser listas vazias.
    """
    cap = max(1, min(int(limite_ofertas), 24))
    key = normalizar_termo_cache(termo)

    ap = (
        db.query(Aparelho)
        .filter(Aparelho.termo_normalizado == key)
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
    return ap, oa_rows, ol_rows
