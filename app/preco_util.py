"""Normalização de termo para cache e parse de preço BRL para gráficos."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone


def normalizar_termo_cache(termo: str) -> str:
    """Alinhado ao crawler (sem GB/TB no texto) + minúsculas para chave única."""
    s = (termo or "").strip().lower()
    s = re.sub(
        r"\b\d{1,4}\s*(GB|TB|gb|tb)\b",
        " ",
        s,
        flags=re.I,
    )
    s = re.sub(r"\s+", " ", s).strip()
    return s


def extrair_primeiro_preco_brl(texto: str | None) -> str | None:
    """
    Isola só o trecho do valor (ex.: 'R$ 4.587').
    Evita que 'R$ 4.587 41% OFF' vire '4.58741' ao colar dígitos e gere ~58 mil no gráfico.
    """
    if not texto:
        return None
    s = texto.strip()
    s = s.split("%", 1)[0].strip()
    s = re.split(r"\bOFF\b", s, maxsplit=1, flags=re.I)[0].strip()
    m = re.search(
        r"R\$\s*(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)",
        s,
        re.I,
    )
    if m:
        return f"R$ {m.group(1).strip()}"
    m = re.search(r"(\d{1,3}(?:\.\d{3})+,\d{2})(?!\d)", s)
    if m:
        return f"R$ {m.group(1)}"
    return None


def texto_preco_para_exibicao(texto: str | None) -> str:
    """Texto curto para tooltip (sem '% OFF' / Pix)."""
    e = extrair_primeiro_preco_brl(texto)
    return e if e else (texto or "").strip()


def parse_preco_para_float(texto: str | None) -> float | None:
    """
    Converte texto de preço BRL para float (valor em reais).
    Trata 1.234,56; 5.199 (milhar sem centavos); inteiros; e evita confundir
    5.199 com 5,199 (decimal inglês) quando o padrão é claramente milhar BR.
    """
    if not texto:
        return None
    limpo = extrair_primeiro_preco_brl(texto)
    if limpo:
        t = re.sub(r"R\$\s*", "", limpo, flags=re.I)
    else:
        t = re.sub(r"R\$\s*", "", texto.strip(), flags=re.I)
    t = re.sub(r"\s+", "", t)

    def _try_float(s: str) -> float | None:
        try:
            return float(s)
        except ValueError:
            return None

    # 1.234,56 ou 12.345,67
    m = re.search(r"(\d{1,3}(?:\.\d{3})+,\d{2})", t)
    if m:
        num = m.group(1).replace(".", "").replace(",", ".")
        v = _try_float(num)
        if v is not None:
            return v

    # Milhares só com ponto: 5.199 / 12.345 (sem vírgula de centavos)
    m = re.search(r"(\d{1,3}(?:\.\d{3})+)(?![,\d])", t)
    if m:
        num = m.group(1).replace(".", "")
        v = _try_float(num)
        if v is not None:
            return v

    # 1234,56 (sem separador de milhar)
    m = re.search(r"(\d+,\d{2})(?!\d)", t)
    if m:
        num = m.group(1).replace(".", "").replace(",", ".")
        v = _try_float(num)
        if v is not None:
            return v

    # Estilo internacional no JSON: 5199.90
    m = re.search(r"(\d+)\.(\d{2})(?!\d)", t)
    if m:
        a, b = m.group(1), m.group(2)
        if len(a) >= 4 or (len(a) >= 1 and int(a) > 100):
            v = _try_float(f"{a}.{b}")
            if v is not None:
                return v

    # Inteiro grande (ex.: meta price=5199)
    m = re.search(r"(\d{4,})(?![,\d])", t)
    if m:
        v = _try_float(m.group(1))
        if v is not None:
            return v

    # Um único ponto ambíguo: 5.199 → 5199 se 3 dígitos após; senão decimal
    m = re.search(r"(\d+)\.(\d+)", t)
    if m:
        a, b = m.group(1), m.group(2)
        if len(b) == 3 and len(a) <= 3:
            return _try_float(a + b)
        if len(b) <= 2:
            return _try_float(f"{a}.{b}")

    # Fallback: primeiro número “simples”
    m = re.search(r"(\d+)", t)
    if m:
        return _try_float(m.group(1))
    return None


def registrar_snapshot_preco(db, oferta_id: int, preco_texto: str | None) -> None:
    from app.models import PrecoHistorico

    if not preco_texto:
        return
    v = parse_preco_para_float(preco_texto)
    texto_gravar = extrair_primeiro_preco_brl(preco_texto) or preco_texto[:2000]
    db.add(
        PrecoHistorico(
            oferta_mercado_id=oferta_id,
            preco_texto=texto_gravar,
            preco_valor=v,
        )
    )


def historico_oferta_json(db, oferta_id: int | None) -> dict:
    """Dados para Chart.js: labels + valores numéricos."""
    from app.models import PrecoHistorico

    if not oferta_id:
        return {"labels": [], "valores": [], "textos": []}
    rows = (
        db.query(PrecoHistorico)
        .filter(PrecoHistorico.oferta_mercado_id == oferta_id)
        .order_by(PrecoHistorico.registrado_em.asc())
        .all()
    )
    labels: list[str] = []
    valores: list[float | None] = []
    textos: list[str] = []
    for r in rows:
        labels.append(r.registrado_em.strftime("%d/%m %H:%M"))
        raw = r.preco_texto or ""
        pv = parse_preco_para_float(raw)
        if pv is None:
            pv = r.preco_valor
        valores.append(pv)
        textos.append(texto_preco_para_exibicao(raw) or raw)
    return {"labels": labels, "valores": valores, "textos": textos}


def cache_cutoff_horas() -> float:
    import os

    return float(os.environ.get("CACHE_BUSCA_HORAS", "72"))


def cutoff_datetime() -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=cache_cutoff_horas())
