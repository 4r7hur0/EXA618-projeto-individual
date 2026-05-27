"""Executa um crawler por vez e grava no banco."""
from __future__ import annotations

import asyncio
import os

from sqlalchemy.orm import Session

from app.filtros_api import (
    armazenamento_compativel_com_busca,
    capacidade_para_gb,
    capacidades_gb_em_texto,
    ficha_maiscelular_tem_especificacoes,
    parece_aparelho,
    preco_brl_para_float,
)
from app.models import Aparelho
from app.persist import (
    aparelho_from_mais_celular,
    oferta_from_amazon,
    oferta_from_mercadolivre,
)
from app.preco_util import normalizar_termo_cache
from app.ofertas_exibir import uma_oferta_dict_por_memoria
from app.termo_busca import (
    remover_armazenamento_do_termo,
    variantes_busca_marketplace,
)
from app.schemas_ingest import (
    IngestAmazonLoteResponse,
    IngestAmazonResponse,
    IngestItemResult,
    IngestMaisCelularLoteResponse,
    IngestMaisCelularResponse,
    IngestMercadoLivreLoteResponse,
    IngestMercadoLivreResponse,
)
from crawlers.amazon import crawler_amazon_essencial, crawler_amazon_sequencia
from crawlers.mais_celular import crawler_maiscelular_blindado
from crawlers.mercado_livre import (
    crawler_mercadolivre_completo,
    crawler_mercadolivre_sequencia,
)
from app.ofertas_limites import OFERTAS_MAX_POR_LOJA


def _limite_ofertas(n_override: int | None) -> int:
    if n_override is not None:
        return max(1, min(int(n_override), OFERTAS_MAX_POR_LOJA))
    try:
        n = int(os.environ.get("OFERTAS_POR_BUSCA", "8").strip())
    except ValueError:
        n = 8
    return max(1, min(n, OFERTAS_MAX_POR_LOJA))


def _normalizar_saida_mc(val):
    if isinstance(val, Exception):
        return None, f"{type(val).__name__}: {val}"
    if isinstance(val, dict):
        return val, None
    if isinstance(val, list):
        dicts = [x for x in val if isinstance(x, dict)]
        if dicts:
            return dicts[0], None
        return None, "Nenhum dado de ficha retornado."
    return None, str(val)


def _normalizar_saida_crawler(val):
    if isinstance(val, Exception):
        return None, f"{type(val).__name__}: {val}"
    if isinstance(val, dict):
        return [val], None
    if isinstance(val, list):
        itens = [x for x in val if isinstance(x, dict)]
        if itens:
            return itens, None
        return None, "Nenhum produto retornado."
    return None, str(val)


def _run_crawler_em_loop_proprio(coro_fn, *args):
    try:
        return asyncio.run(coro_fn(*args))
    except BaseException as e:
        return e


async def _executar_crawler_isolado(coro_fn, *args):
    return await asyncio.to_thread(_run_crawler_em_loop_proprio, coro_fn, *args)


def _aparelho_existente(db: Session, termo: str) -> Aparelho | None:
    key = normalizar_termo_cache(termo)
    return (
        db.query(Aparelho)
        .filter(Aparelho.termo_normalizado == key)
        .order_by(Aparelho.criado_em.desc())
        .first()
    )


def _ml_ingest_filtros_estritos() -> bool:
    raw = os.environ.get("ML_FILTROS", "0")
    if raw is None or not str(raw).strip():
        return False
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _oferta_eh_aparelho(item: dict, *, armazenamento_gb: int | None = None) -> bool:
    nome = item.get("nome") or ""
    preco_txt = item.get("preco")
    mem_txt = item.get("memoria")
    if not armazenamento_compativel_com_busca(nome, mem_txt, armazenamento_gb):
        return False
    caps = capacidades_gb_em_texto(f"{nome} {mem_txt or ''}")
    mem_gb = (
        int(armazenamento_gb)
        if armazenamento_gb is not None and armazenamento_gb in caps
        else capacidade_para_gb(mem_txt)
    )
    return parece_aparelho(
        nome,
        preco_valor=preco_brl_para_float(preco_txt),
        oferta_memoria_gb=mem_gb,
    )


def _termo_base_cadastro(termo: str) -> str:
    base = remover_armazenamento_do_termo(termo)
    return base or (termo or "").strip()


def _variantes_loja(
    termo: str,
    *,
    armazenamento_gb: int | None = None,
    armazenamentos_gb: list[int] | None = None,
) -> list[tuple[str, int | None]]:
    try:
        return variantes_busca_marketplace(
            termo,
            armazenamento_gb=armazenamento_gb,
            armazenamentos_gb=armazenamentos_gb,
        )
    except ValueError as e:
        raise ValueError(str(e)) from e


async def ingerir_mais_celular(db: Session, termo: str) -> IngestMaisCelularResponse:
    termo = (termo or "").strip()
    if not termo:
        return IngestMaisCelularResponse(
            termo=termo, ok=False, erros=["Termo vazio."]
        )

    erros: list[str] = []
    mc_raw = await _executar_crawler_isolado(
        crawler_maiscelular_blindado, _termo_base_cadastro(termo)
    )
    mc, mc_erro = _normalizar_saida_mc(mc_raw)
    if mc_erro:
        erros.append(mc_erro)

    termo_mc = _termo_base_cadastro(termo)
    ap_existente = _aparelho_existente(db, termo_mc)
    aparelho_id = ap_existente.id if ap_existente else None
    ficha_salva = False

    if mc and not ficha_maiscelular_tem_especificacoes(mc):
        erros.append(
            "Ficha sem especificações suficientes (não gravado)."
        )
        mc = None

    try:
        if ap_existente is None and mc:
            a = aparelho_from_mais_celular(termo_mc, mc)
            db.add(a)
            db.flush()
            aparelho_id = a.id
            ficha_salva = True
        elif ap_existente is not None and mc:
            ficha_salva = False
            erros.append(
                "Aparelho já existe para este termo; ficha não substituída."
            )
        db.commit()
    except Exception as e:
        db.rollback()
        erros.append(f"Banco: {e}")
        return IngestMaisCelularResponse(
            termo=termo,
            ok=False,
            aparelho_id=None,
            ficha_salva=False,
            erros=erros,
        )

    ok = ficha_salva or (ap_existente is not None)
    if not ok and not erros:
        erros.append("Nenhuma ficha válida para gravar.")
    return IngestMaisCelularResponse(
        termo=termo,
        ok=ok,
        aparelho_id=aparelho_id,
        ficha_salva=ficha_salva,
        erros=erros,
    )


async def ingerir_mais_celular_lote(
    db: Session,
    termos: list[str],
) -> IngestMaisCelularLoteResponse:
    """Pesquisa cada termo no Mais Celular, um após o outro."""
    resultados: list[IngestMaisCelularResponse] = []
    for raw in termos:
        termo = (raw or "").strip()
        if not termo:
            continue
        resultados.append(await ingerir_mais_celular(db, termo))
    return IngestMaisCelularLoteResponse(
        resultados=resultados,
        total_processados=len(resultados),
    )


async def ingerir_amazon(
    db: Session,
    termo: str,
    *,
    ofertas_por_termo: int | None = None,
    armazenamento_gb: int | None = None,
    armazenamentos_gb: list[int] | None = None,
) -> IngestAmazonResponse:
    termo = (termo or "").strip()
    if not termo:
        return IngestAmazonResponse(termo=termo, ok=False, erros=["Termo vazio."])

    try:
        variantes = _variantes_loja(
            termo,
            armazenamento_gb=armazenamento_gb,
            armazenamentos_gb=armazenamentos_gb,
        )
    except ValueError as e:
        return IngestAmazonResponse(termo=termo, ok=False, erros=[str(e)])

    n = _limite_ofertas(ofertas_por_termo)
    erros: list[str] = []
    termos_loja: list[str] = []
    termo_cadastro = _termo_base_cadastro(termo)
    ap_existente = _aparelho_existente(db, termo_cadastro)
    aparelho_id = ap_existente.id if ap_existente else None
    n_salvas = 0

    termos_loja = [tl for tl, _ in variantes]

    async def _persistir_lista(termo_loja: str, gb_variante: int | None, amz_raw) -> None:
        nonlocal n_salvas
        amz_list, amz_erro = _normalizar_saida_crawler(amz_raw)
        if amz_erro:
            erros.append(f"[{termo_loja}] {amz_erro}")
            return
        if not amz_list:
            erros.append(f"[{termo_loja}] Nenhuma oferta retornada.")
            return
        amz_list = [x for x in amz_list if isinstance(x, dict)]
        amz_list = [
            x
            for x in amz_list
            if _oferta_eh_aparelho(x, armazenamento_gb=gb_variante)
        ]
        amz_list = uma_oferta_dict_por_memoria(amz_list)
        for item in amz_list:
            oa = oferta_from_amazon(termo_loja, item)
            if aparelho_id is not None:
                oa.aparelho_id = aparelho_id
            db.add(oa)
            db.flush()
            n_salvas += 1

    try:
        if len(variantes) > 1:
            buscas = [(tl, gb) for tl, gb in variantes]
            raw_seq = await _executar_crawler_isolado(
                crawler_amazon_sequencia, buscas, n
            )
            if not isinstance(raw_seq, list):
                raw_seq = [raw_seq]
            for i, (termo_loja, gb_variante) in enumerate(variantes):
                res = raw_seq[i] if i < len(raw_seq) else "Erro: resposta incompleta."
                await _persistir_lista(termo_loja, gb_variante, res)
            db.commit()
        else:
            termo_loja, gb_variante = variantes[0]
            amz_raw = await _executar_crawler_isolado(
                crawler_amazon_essencial, termo_loja, n, gb_variante
            )
            await _persistir_lista(termo_loja, gb_variante, amz_raw)
            db.commit()
    except Exception as e:
        db.rollback()
        erros.append(f"Banco: {e}")
        return IngestAmazonResponse(
            termo=termo,
            termos_loja=termos_loja,
            ok=False,
            aparelho_id=aparelho_id,
            ofertas_salvas=n_salvas,
            erros=erros,
        )

    ok = n_salvas > 0
    if not ok and not erros:
        erros.append("Nenhuma oferta válida retornada.")
    return IngestAmazonResponse(
        termo=termo,
        termos_loja=termos_loja,
        ok=ok,
        aparelho_id=aparelho_id,
        ofertas_salvas=n_salvas,
        erros=erros,
    )


async def ingerir_amazon_lote(
    db: Session,
    termos: list[str],
    *,
    ofertas_por_termo: int | None = None,
    armazenamento_gb: int | None = None,
    armazenamentos_gb: list[int] | None = None,
) -> IngestAmazonLoteResponse:
    """Vários aparelhos na Amazon; reutiliza um único navegador para todas as buscas."""
    n = _limite_ofertas(ofertas_por_termo)
    plano: list[tuple[str, str, int | None]] = []
    for raw in termos:
        termo = (raw or "").strip()
        if not termo:
            continue
        try:
            variantes = _variantes_loja(
                termo,
                armazenamento_gb=armazenamento_gb,
                armazenamentos_gb=armazenamentos_gb,
            )
        except ValueError:
            continue
        for termo_loja, gb in variantes:
            plano.append((termo, termo_loja, gb))

    if not plano:
        return IngestAmazonLoteResponse(resultados=[], total_processados=0)

    if len(plano) == 1:
        termo_orig, termo_loja, gb = plano[0]
        unico = await ingerir_amazon(
            db,
            termo_orig,
            ofertas_por_termo=ofertas_por_termo,
            armazenamento_gb=armazenamento_gb,
            armazenamentos_gb=armazenamentos_gb,
        )
        return IngestAmazonLoteResponse(
            resultados=[unico],
            total_processados=1,
        )

    buscas = [(tl, gb) for _orig, tl, gb in plano]
    raw_seq = await _executar_crawler_isolado(crawler_amazon_sequencia, buscas, n)
    if not isinstance(raw_seq, list):
        raw_seq = [raw_seq]

    por_termo: dict[str, IngestAmazonResponse] = {}
    idx = 0
    for termo_orig, termo_loja, gb in plano:
        res = raw_seq[idx] if idx < len(raw_seq) else "Erro: resposta incompleta do crawler."
        idx += 1

        if termo_orig not in por_termo:
            termo_cadastro = _termo_base_cadastro(termo_orig)
            ap = _aparelho_existente(db, termo_cadastro)
            por_termo[termo_orig] = IngestAmazonResponse(
                termo=termo_orig,
                termos_loja=[],
                ok=False,
                aparelho_id=ap.id if ap else None,
                ofertas_salvas=0,
                erros=[],
            )

        entry = por_termo[termo_orig]
        entry.termos_loja.append(termo_loja)

        amz_list, amz_erro = _normalizar_saida_crawler(res)
        if amz_erro:
            entry.erros.append(f"[{termo_loja}] {amz_erro}")
            continue
        if not amz_list:
            entry.erros.append(f"[{termo_loja}] Nenhuma oferta retornada.")
            continue

        amz_list = [x for x in amz_list if isinstance(x, dict)]
        amz_list = [
            x
            for x in amz_list
            if _oferta_eh_aparelho(x, armazenamento_gb=gb)
        ]
        amz_list = uma_oferta_dict_por_memoria(amz_list)
        try:
            for item in amz_list:
                oa = oferta_from_amazon(termo_loja, item)
                if entry.aparelho_id is not None:
                    oa.aparelho_id = entry.aparelho_id
                db.add(oa)
                db.flush()
                entry.ofertas_salvas += 1
            db.commit()
            if entry.ofertas_salvas > 0:
                entry.ok = True
        except Exception as e:
            db.rollback()
            entry.erros.append(f"Banco ({termo_loja}): {e}")

    resultados = list(por_termo.values())
    for r in resultados:
        if not r.ok and not r.erros:
            r.erros.append("Nenhuma oferta válida retornada.")
    return IngestAmazonLoteResponse(
        resultados=resultados,
        total_processados=len(resultados),
    )


async def ingerir_mercadolivre(
    db: Session,
    termo: str,
    *,
    ofertas_por_termo: int | None = None,
    armazenamento_gb: int | None = None,
    armazenamentos_gb: list[int] | None = None,
) -> IngestMercadoLivreResponse:
    termo = (termo or "").strip()
    if not termo:
        return IngestMercadoLivreResponse(
            termo=termo, ok=False, erros=["Termo vazio."]
        )

    try:
        variantes = _variantes_loja(
            termo,
            armazenamento_gb=armazenamento_gb,
            armazenamentos_gb=armazenamentos_gb,
        )
    except ValueError as e:
        return IngestMercadoLivreResponse(termo=termo, ok=False, erros=[str(e)])

    n = _limite_ofertas(ofertas_por_termo)
    erros: list[str] = []
    termos_loja: list[str] = []
    termo_cadastro = _termo_base_cadastro(termo)
    ap_existente = _aparelho_existente(db, termo_cadastro)
    aparelho_id = ap_existente.id if ap_existente else None
    n_salvas = 0
    termos_loja = [tl for tl, _ in variantes]

    async def _persistir_ml(termo_loja: str, gb_variante: int | None, ml_raw) -> None:
        nonlocal n_salvas
        ml_list, ml_erro = _normalizar_saida_crawler(ml_raw)
        if ml_erro:
            erros.append(f"[{termo_loja}] {ml_erro}")
            return
        if not ml_list:
            erros.append(f"[{termo_loja}] Nenhuma oferta retornada.")
            return
        ml_list = [x for x in ml_list if isinstance(x, dict)]
        if _ml_ingest_filtros_estritos():
            ml_list = [
                x
                for x in ml_list
                if _oferta_eh_aparelho(x, armazenamento_gb=gb_variante)
            ]
        ml_list = uma_oferta_dict_por_memoria(ml_list)
        for item in ml_list:
            ol = oferta_from_mercadolivre(termo_loja, item)
            if aparelho_id is not None:
                ol.aparelho_id = aparelho_id
            db.add(ol)
            db.flush()
            n_salvas += 1

    try:
        if len(variantes) > 1:
            buscas = [(tl, gb) for tl, gb in variantes]
            raw_seq = await _executar_crawler_isolado(
                crawler_mercadolivre_sequencia, buscas, n
            )
            if not isinstance(raw_seq, list):
                raw_seq = [raw_seq]
            for i, (termo_loja, gb_variante) in enumerate(variantes):
                res = raw_seq[i] if i < len(raw_seq) else "Erro: resposta incompleta."
                await _persistir_ml(termo_loja, gb_variante, res)
            db.commit()
        else:
            termo_loja, gb_variante = variantes[0]
            ml_raw = await _executar_crawler_isolado(
                crawler_mercadolivre_completo, termo_loja, n, gb_variante
            )
            await _persistir_ml(termo_loja, gb_variante, ml_raw)
            db.commit()
    except Exception as e:
        db.rollback()
        erros.append(f"Banco: {e}")
        return IngestMercadoLivreResponse(
            termo=termo,
            termos_loja=termos_loja,
            ok=False,
            aparelho_id=aparelho_id,
            ofertas_salvas=n_salvas,
            erros=erros,
        )

    ok = n_salvas > 0
    if not ok and not erros:
        erros.append("Nenhuma oferta válida retornada.")
    return IngestMercadoLivreResponse(
        termo=termo,
        termos_loja=termos_loja,
        ok=ok,
        aparelho_id=aparelho_id,
        ofertas_salvas=n_salvas,
        erros=erros,
    )


async def ingerir_mercadolivre_lote(
    db: Session,
    termos: list[str],
    *,
    ofertas_por_termo: int | None = None,
    armazenamento_gb: int | None = None,
    armazenamentos_gb: list[int] | None = None,
) -> IngestMercadoLivreLoteResponse:
    """Vários termos no ML; reutiliza uma janela do navegador para todas as buscas."""
    n = _limite_ofertas(ofertas_por_termo)
    plano: list[tuple[str, str, int | None]] = []
    for raw in termos:
        termo = (raw or "").strip()
        if not termo:
            continue
        try:
            variantes = _variantes_loja(
                termo,
                armazenamento_gb=armazenamento_gb,
                armazenamentos_gb=armazenamentos_gb,
            )
        except ValueError:
            continue
        for termo_loja, gb in variantes:
            plano.append((termo, termo_loja, gb))

    if not plano:
        return IngestMercadoLivreLoteResponse(resultados=[], total_processados=0)

    if len(plano) == 1:
        termo_orig, _, _ = plano[0]
        unico = await ingerir_mercadolivre(
            db,
            termo_orig,
            ofertas_por_termo=ofertas_por_termo,
            armazenamento_gb=armazenamento_gb,
            armazenamentos_gb=armazenamentos_gb,
        )
        return IngestMercadoLivreLoteResponse(
            resultados=[unico],
            total_processados=1,
        )

    buscas = [(tl, gb) for _orig, tl, gb in plano]
    raw_seq = await _executar_crawler_isolado(
        crawler_mercadolivre_sequencia, buscas, n
    )
    if not isinstance(raw_seq, list):
        raw_seq = [raw_seq]

    por_termo: dict[str, IngestMercadoLivreResponse] = {}
    idx = 0
    for termo_orig, termo_loja, gb in plano:
        res = raw_seq[idx] if idx < len(raw_seq) else "Erro: resposta incompleta."
        idx += 1
        if termo_orig not in por_termo:
            ap = _aparelho_existente(db, _termo_base_cadastro(termo_orig))
            por_termo[termo_orig] = IngestMercadoLivreResponse(
                termo=termo_orig,
                termos_loja=[],
                ok=False,
                aparelho_id=ap.id if ap else None,
                ofertas_salvas=0,
                erros=[],
            )
        entry = por_termo[termo_orig]
        entry.termos_loja.append(termo_loja)
        ml_list, ml_erro = _normalizar_saida_crawler(res)
        if ml_erro:
            entry.erros.append(f"[{termo_loja}] {ml_erro}")
            continue
        if not ml_list:
            entry.erros.append(f"[{termo_loja}] Nenhuma oferta retornada.")
            continue
        ml_list = [x for x in ml_list if isinstance(x, dict)]
        if _ml_ingest_filtros_estritos():
            ml_list = [
                x for x in ml_list if _oferta_eh_aparelho(x, armazenamento_gb=gb)
            ]
        ml_list = uma_oferta_dict_por_memoria(ml_list)
        try:
            for item in ml_list:
                ol = oferta_from_mercadolivre(termo_loja, item)
                if entry.aparelho_id is not None:
                    ol.aparelho_id = entry.aparelho_id
                db.add(ol)
                db.flush()
                entry.ofertas_salvas += 1
            db.commit()
            if entry.ofertas_salvas > 0:
                entry.ok = True
        except Exception as e:
            db.rollback()
            entry.erros.append(f"Banco ({termo_loja}): {e}")

    resultados = list(por_termo.values())
    for r in resultados:
        if not r.ok and not r.erros:
            r.erros.append("Nenhuma oferta válida retornada.")
    return IngestMercadoLivreLoteResponse(
        resultados=resultados,
        total_processados=len(resultados),
    )


async def ingerir_um_termo(
    db: Session,
    termo: str,
    *,
    ofertas_por_termo: int | None = None,
    armazenamento_gb: int | None = None,
    armazenamentos_gb: list[int] | None = None,
) -> IngestItemResult:
    """Roda os três crawlers em sequência (um após o outro)."""
    termo = (termo or "").strip()
    if not termo:
        return IngestItemResult(termo=termo, ok=False, erros=["Termo vazio."])

    termo_mc = _termo_base_cadastro(termo)
    erros: list[str] = []
    mc_res = await ingerir_mais_celular(db, termo_mc)
    erros.extend(mc_res.erros)
    aparelho_id = mc_res.aparelho_id

    amz_res = await ingerir_amazon(
        db,
        termo,
        ofertas_por_termo=ofertas_por_termo,
        armazenamento_gb=armazenamento_gb,
        armazenamentos_gb=armazenamentos_gb,
    )
    erros.extend(amz_res.erros)
    if amz_res.aparelho_id is not None:
        aparelho_id = amz_res.aparelho_id

    ml_res = await ingerir_mercadolivre(
        db,
        termo,
        ofertas_por_termo=ofertas_por_termo,
        armazenamento_gb=armazenamento_gb,
        armazenamentos_gb=armazenamentos_gb,
    )
    erros.extend(ml_res.erros)
    if ml_res.aparelho_id is not None:
        aparelho_id = ml_res.aparelho_id

    ok = (
        mc_res.ok
        or amz_res.ok
        or ml_res.ok
        or aparelho_id is not None
    )
    return IngestItemResult(
        termo=termo,
        ok=ok,
        aparelho_id=aparelho_id,
        ofertas_amazon_salvas=amz_res.ofertas_salvas,
        ofertas_ml_salvas=ml_res.ofertas_salvas,
        erros=erros,
    )
