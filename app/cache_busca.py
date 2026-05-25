"""Reconstrói dicts de resultado a partir do banco (busca já feita)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Aparelho, OfertaMercado
from app.filtros_api import capacidade_para_gb
from app.ofertas_exibir import rotulo_memoria_gb, uma_oferta_por_memoria
from app.preco_util import normalizar_termo_cache
from app.termo_busca import armazenamento_gb_no_termo, remover_armazenamento_do_termo
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
    gb = capacidade_para_gb(o.memoria) or capacidade_para_gb(o.nome_produto)
    d: dict = {
        "nome": _s(o.nome_produto),
        "memoria": _s(o.memoria),
        "memoria_gb": gb,
        "rotulo_memoria": rotulo_memoria_gb(gb, _s(o.memoria)),
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
    gb_busca = armazenamento_gb_no_termo(termo)
    key = normalizar_termo_cache(termo)
    key_base = normalizar_termo_cache(remover_armazenamento_do_termo(termo))

    ap = (
        db.query(Aparelho)
        .filter(Aparelho.termo_normalizado.in_([key, key_base]))
        .order_by(Aparelho.criado_em.desc())
        .first()
    )
    if not ap:
        return None

    fetch_n = 80

    def _carregar_e_dedup(origem: str) -> list[OfertaMercado]:
        rows = (
            db.query(OfertaMercado)
            .filter(
                OfertaMercado.aparelho_id == ap.id,
                OfertaMercado.origem == origem,
            )
            .order_by(OfertaMercado.criado_em.desc())
            .limit(fetch_n)
            .all()
        )
        if gb_busca is not None:
            filtradas: list[OfertaMercado] = []
            for o in rows:
                og = capacidade_para_gb(o.memoria) or capacidade_para_gb(
                    o.nome_produto
                )
                if og is None or og == gb_busca:
                    filtradas.append(o)
            rows = filtradas
        return uma_oferta_por_memoria(rows)

    oa_rows = _carregar_e_dedup("amazon")
    ol_rows = _carregar_e_dedup("mercadolivre")
    return ap, oa_rows, ol_rows
