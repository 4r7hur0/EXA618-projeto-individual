"""Evita confundir variantes (ex.: Galaxy S25 vs S25 FE) quando a busca não pede a variante."""
import re


def titulo_atende_tokens_exatos(busca: str, titulo: str) -> bool:
    """
    Cada token (≥2 caracteres) da busca deve aparecer no título como palavra inteira.
    Evita confundir 'iPhone 17' com 'iPhone 17e' (17 não casa com limite antes de 'e').
    """
    q = re.sub(r"\s+", " ", (busca or "").strip())
    tl = (titulo or "").strip()
    if not q or not tl:
        return False
    q = q.lower()
    padded = " " + re.sub(r"\s+", " ", tl.lower()) + " "
    for tok in q.split():
        if len(tok) < 2:
            continue
        pat = r"(?<!\w)" + re.escape(tok) + r"(?!\w)"
        if not re.search(pat, padded, re.IGNORECASE):
            return False
    return True


def titulo_rejeitado_para_busca(busca: str, titulo: str) -> bool:
    """
    True = descartar este resultado.
    Ex.: busca 'galaxy s25' → rejeita título com 'S25 FE' / 'S25 Fe'.
    """
    q = (busca or "").lower()
    t = (titulo or "").lower()
    if not t:
        return True

    # FE / Fan Edition: só aceita se o usuário mencionou fe / fan
    if not re.search(r"\bfe\b|fan\s*edition", q):
        if re.search(
            r"\bs\d{1,2}\s*fe\b|galaxy\s+s\d{1,2}\s+fe\b|s\d{1,2}fe\b",
            t,
            re.I,
        ):
            return True

    # Ultra: se não pediu ultra, evita listar Ultra como resultado “base”
    if "ultra" not in q and re.search(r"\bs\d{1,2}\s+ultra\b|galaxy\s+s\d{1,2}\s+ultra", t):
        return True

    # Apple: variantes Plus / Pro / Pro Max — não usar "pro" solto (cai em "promoção", "product").
    if "iphone" in q or "ipad" in q:
        if not re.search(r"\bplus\b", q):
            if re.search(r"\biphone\s+\d+.*\bplus\b|\bipad\b.*\bplus\b", t, re.I):
                return True
        if not re.search(r"\bpro\b", q):
            if re.search(
                r"\biphone\s+\d+\s+pro\b(?!\s*max)|\bipad\b.*\bpro\b(?!\s*max)",
                t,
                re.I,
            ):
                return True
        if not re.search(r"\bmax\b", q):
            if re.search(r"\biphone\s+\d+\s+pro\s+max\b|\biphone\s+\d+\s+max\b", t, re.I):
                return True

    return False


def pontuacao_relevancia(busca: str, titulo: str) -> int:
    """Maior = mais relevante."""
    q = re.sub(r"[^\w\s]", " ", (busca or "").lower())
    tokens = [x for x in q.split() if len(x) > 1]
    tl = (titulo or "").lower()
    sc = sum(15 for tok in tokens if tok in tl)
    # ligação forte galaxy + número
    if re.search(r"galaxy", q) and re.search(r"galaxy", tl):
        sc += 8
    m = re.search(r"\b(s\d{1,2})\b", q)
    if m and m.group(1) in tl:
        sc += 12
    if re.search(r"\biphone\b", q) and re.search(r"\biphone\s*\d+", tl):
        sc += 20
    return sc
