"""Helpers para endpoints de filtro (API JSON)."""
from __future__ import annotations

import re


def preco_brl_para_float(texto: str | None) -> float | None:
    """
    Converte preço textual BR (ex.: 'R$ 5.199', 'R$ 5.199,90') para float.
    Retorna None se não conseguir interpretar.
    """
    if not texto:
        return None
    s = str(texto).strip()
    s = s.split("\n", 1)[0].strip()
    s = re.sub(r"(?i)r\$\s*", "", s)
    s = re.sub(r"\s+", "", s)

    # ML e outros: "12x199,90" ou "12x2.499" — o primeiro número não é o preço (parcelas).
    while re.match(r"(?i)^\d{1,3}x(?=\d)", s):
        s = re.sub(r"(?i)^\d{1,3}x", "", s, count=1)

    # pega primeiro número com separadores BR
    m = re.search(r"(\d{1,3}(?:\.\d{3})*(?:,\d{2})?|\d+(?:,\d{2})?)", s)
    if not m:
        return None
    n = m.group(1)
    if "," in n:
        n = n.replace(".", "").replace(",", ".")
    else:
        # '5.199' -> 5199 (milhar)
        if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", n):
            n = n.replace(".", "")
    try:
        return float(n)
    except ValueError:
        return None


def capacidade_para_gb(texto: str | None) -> int | None:
    """
    Extrai capacidade em GB de textos como:
    '8GB', '8 GB', '1TB', '128GB (104GB disponível)'.
    """
    if not texto:
        return None
    s = str(texto)
    m = re.search(r"(\d{1,4})\s*(TB|GB)\b", s, re.I)
    if not m:
        return None
    v = int(m.group(1))
    u = m.group(2).upper()
    return v * 1024 if u == "TB" else v


_ACESSORIO_RE = re.compile(
    r"\b("
    r"capa|capinha|case|bumper|flip\s*cover|smart\s*cover|pel[ií]cula|protetor|vidro|glass|nano\s*shield|"
    r"carregador|cabo|adaptador|fonte|tomada|charger|cable|"
    r"suporte|stand|dock|"
    r"livro|book|guia|guide|manual|for\s+dummies|"
    r"mag\s*safe|magsafe|"
    r"carteira|wallet|"
    r"fones?|headphone|earbuds|"
    r"pel[ií]cula\s+traseira|"
    r"popsocket|pop\s*socket|pel[ií]cula\s+3d|"
    r"linping|spigen|otterbox|uag|ringke|nillkin|baseus|ugreen|hprime|gshield"
    r")\b",
    flags=re.I,
)


def parece_aparelho(
    nome_produto: str | None,
    *,
    preco_valor: float | None = None,
    oferta_memoria_gb: int | None = None,
) -> bool:
    """
    Heurística simples para filtrar acessórios/livros.
    Retorna False para itens que parecem capa/película/cabo/livro etc.
    """
    if not nome_produto:
        return False
    s = str(nome_produto).strip()
    if not s:
        return False
    if _ACESSORIO_RE.search(s):
        return False

    sl = s.lower()
    # Título típico de PDP no ML: "Samsung Galaxy S24 5G..." sem a palavra "celular".
    # Preço às vezes é só a parcela (< 500); não confundir com capa barata.
    titulo_handset_explicito = bool(
        re.search(
            r"\b("
            r"iphone\s*\d|"
            r"galaxy\s+s\d{1,2}\b|galaxy\s+[anz]\d|"
            r"note\s*\d|redmi\s|poco\s|"
            r"moto\s*[gGeE]\d|motorola|"
            r"xiaomi\s|(?:^|[\s,])(?:mi|redmi)\s+\d|"
            r"zenfone|pixel\s*\d|oneplus|realme\s"
            r")\b",
            sl,
            re.I,
        )
    )

    # Heurística: preço muito baixo + menciona modelo + sem capacidade => quase sempre acessório.
    if preco_valor is not None and preco_valor > 0 and preco_valor < 500:
        menciona_modelo = any(x in sl for x in ("iphone", "galaxy", "xiaomi", "motorola", "redmi", "poco"))
        tem_pistas_aparelho = any(x in sl for x in ("smartphone", "celular", "telefone", "mobile", "desbloque"))
        if (
            menciona_modelo
            and not tem_pistas_aparelho
            and oferta_memoria_gb is None
            and not titulo_handset_explicito
        ):
            return False
    return True


def ficha_maiscelular_tem_especificacoes(d: dict | None) -> bool:
    """
    True se a ficha do Mais Celular trouxe dados utilizáveis (tabela de specs ou campos principais).
    Evita gravar aparelho quando a página não tem ficha técnica parseável.
    """
    if not isinstance(d, dict):
        return False
    esp = d.get("especificacoes_todas")
    n_esp = len(esp) if isinstance(esp, dict) else 0

    campos = (
        d.get("processador"),
        d.get("tela"),
        d.get("memoria_ram"),
        d.get("armazenamento"),
        d.get("bateria"),
        d.get("camera_traseira"),
        d.get("sistema_operacional"),
    )

    def _campo_util(v) -> bool:
        if v is None:
            return False
        s = str(v).strip()
        return bool(s) and s.upper() != "N/A"

    n_campos = sum(1 for v in campos if _campo_util(v))

    if n_esp >= 5:
        return True
    if n_esp >= 3 and n_campos >= 2:
        return True
    if n_campos >= 3:
        return True
    return False

