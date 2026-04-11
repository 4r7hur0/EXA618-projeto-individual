import asyncio
import os
import re
from datetime import datetime
from urllib.parse import quote_plus, urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from crawlers.imagem_produto import extrair_imagem_mais_celular


def _mc_nav_timeout_ms() -> int:
    try:
        v = int(os.environ.get("MAISCELULAR_NAV_TIMEOUT_MS", "90000").strip())
    except ValueError:
        v = 90000
    return max(25000, min(v, 180000))


MC_SPECS_SELECTOR = (
    "#specs, #especificacoes, [id*='spec'], "
    "section[class*='spec'], .ficha-tecnica, "
    "main table, article table, [class*='resumo'], .entry-content"
)


async def _mc_goto(
    page,
    url: str,
    *,
    specs_selector: str | None,
) -> object | None:
    """
    Navegação no Mais Celular: wait_until='commit' costuma evitar timeout que ocorre
    com 'domcontentloaded' quando o site demora em scripts/recursos. Não usamos
    bloqueio de imagem/fonte aqui — o site pode reagir mal a isso.
    """
    ms = _mc_nav_timeout_ms()
    page.set_default_navigation_timeout(ms)
    page.set_default_timeout(ms)
    response = None
    for attempt in range(2):
        try:
            response = await page.goto(url, wait_until="commit", timeout=ms)
            break
        except Exception:
            if attempt == 0:
                await asyncio.sleep(1.5)
                continue
            raise
    if response is not None and response.status == 404:
        return response
    if specs_selector:
        try:
            await page.wait_for_selector(
                specs_selector, timeout=min(ms, 45000), state="attached"
            )
        except Exception:
            await asyncio.sleep(2.5)
        await asyncio.sleep(0.6)
    else:
        try:
            await page.wait_for_selector(
                "main, article, .entry-content, #content, ol",
                timeout=22000,
                state="attached",
            )
        except Exception:
            pass
        await asyncio.sleep(1.0)
    return response


def _montar_urls_maiscelular(marca: str, slug: str) -> list[str]:
    """Uma única URL de ficha (especificação é única; evita vários page.goto seguidos)."""
    base = f"https://www.maiscelular.com.br/fichas-tecnicas/{marca}/{slug}"
    return [f"{base}/"]


def _coletar_pares(soup: BeautifulSoup) -> dict[str, str]:
    """Junta label → valor de tabelas, dl/dt/dd e blocos típicos de ficha."""
    pares: dict[str, str] = {}

    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) >= 2:
                k = cells[0].get_text(" ", strip=True)
                v = cells[-1].get_text(" ", strip=True)
                if k and v and len(k) < 200:
                    pares[k] = v

    for dl in soup.find_all("dl"):
        for dt in dl.find_all("dt"):
            dd = dt.find_next_sibling("dd")
            if dd:
                k = dt.get_text(" ", strip=True)
                v = dd.get_text(" ", strip=True)
                if k and v:
                    pares[k] = v

    for sec in soup.select("[class*='resumo'], [class*='summary'], .specs, [class*='ficha']"):
        for row in sec.find_all(["div", "li", "p"]):
            txt = row.get_text(" ", strip=True)
            m = re.match(r"^(.{2,80}?)[\s:]+(.{1,500})$", txt)
            if m:
                pares[m.group(1).strip()] = m.group(2).strip()

    return pares


def _buscar_valor(pares: dict[str, str], *candidatos: str) -> str | None:
    """Primeira chave que contenha todas as substrings (case insensitive)."""
    for chave, val in pares.items():
        cl = chave.lower()
        if all(c.lower() in cl for c in candidatos):
            return val
    return None


def _buscar_valor_regex(pares: dict[str, str], pattern: str) -> str | None:
    rx = re.compile(pattern, re.I)
    for chave, val in pares.items():
        if rx.search(chave):
            return val
    return None


def _chave_contem(pares: dict[str, str], *trechos: str) -> str | None:
    """Valor cuja chave contém todos os trechos (AND)."""
    for k, val in pares.items():
        kl = k.lower()
        if all(t.lower() in kl for t in trechos):
            return val
    return None


def _primeira_chave(pares: dict[str, str], *substrings: str) -> str | None:
    """Primeira entrada cuja chave contém qualquer uma das substrings (OR)."""
    for sub in substrings:
        sl = sub.lower()
        for k, val in pares.items():
            if sl in k.lower():
                return val
    return None


def _extrair_antutu_texto(texto: str) -> str | None:
    m = re.search(
        r"AnTuTu\s*[:\s]*([0-9][0-9.,]*)\s*(?:\([^)]*\))?",
        texto,
        re.I,
    )
    if m:
        return m.group(0).strip()
    m = re.search(r"([0-9]{5,7})\s*(?:\([^)]*v?\d[^)]*\))?", texto)
    if m and "antutu" in texto.lower():
        return m.group(1)
    return None


def _normalizar_antutu(val: str) -> str:
    """Só a pontuação AnTuTu; remove Geekbench e texto extra na mesma célula."""
    if not val or val == "N/A":
        return val
    m = re.search(
        r"AnTuTu\s*:?\s*([0-9.,]+)\s*(?:\([^)]+\))?",
        val,
        re.I,
    )
    if m:
        resto = re.search(r"\(v[^)]+\)", val, re.I)
        suf = resto.group(0) if resto else ""
        return f"AnTuTu: {m.group(1).replace(',', '')} {suf}".strip()
    return val.split("Geekbench")[0].strip()


def _extrair_geekbench(texto: str) -> str | None:
    m = re.search(
        r"Geekbench\s*:?\s*(\d[\d,]*)\s*(\([^)]+\))?",
        texto,
        re.I,
    )
    if m:
        return f"Geekbench: {m.group(1)} {m.group(2) or ''}".strip()
    return None


def _limpar_modelo_h1(texto: str) -> str:
    from app.texto_limpo import sem_emojis

    s = re.sub(r"Ficha\s*T[eé]cnica", "", texto, flags=re.I)
    s = re.sub(r"\)([A-Za-zÀ-ÿ])", r") \1", s)
    s = re.sub(r"\s+", " ", s).strip()
    return sem_emojis(s) or ""


def _buscar_valor_chipset_tabela(pares: dict[str, str]) -> str | None:
    """Prioriza linha cujo rótulo é claramente Chipset/SOC."""
    for k, v in pares.items():
        kl = re.sub(r"\s+", " ", k.lower().strip())
        if kl in ("chipset", "soc", "processador (chipset)"):
            return v.strip()
        if "chipset" in kl and "gráfic" not in kl and "gpu" not in kl:
            return v.strip()
    return None


def _extrair_somente_chipset(texto: str) -> str:
    """Recorta só o nome do SoC (ex.: Apple A18) a partir de texto longo de CPU."""
    if not texto or texto == "N/A":
        return texto
    t = texto.strip()
    # Já parece só o nome do chip (sem bloco de núcleos)
    if len(t) <= 55 and not re.search(
        r"hexa|octa|dual|quad|core|ghz|nm\s|processador\s*:", t, re.I
    ):
        return t

    patterns = [
        r"\b(Apple\s+A\d+(?:\s+Bionic|\s+Pro)?)\b",
        r"\b(Snapdragon\s+(?:8s\s+)?(?:8\s+)?(?:Gen\s*\d+\s*(?:\w+)?|[\w\+\d]+)(?:\s+5G)?)\b",
        r"\b(MediaTek\s+(?:Dimensity\s+[\d\w]+|Helio\s+[\w\d]+|MT\d+))\b",
        r"\b(Dimensity\s+\d+(?:\s*\w+)?)\b",
        r"\b(Exynos\s+\d+(?:\s*\w+)?)\b",
        r"\b(Google\s+Tensor\s*[\w\d]*)\b",
        r"\b(Unisoc\s+[\w\d\-]+)\b",
        r"\b(Kirin\s+[\w\d]+)\b",
        r"\b(AMD\s+[\w\d]+)\b",
    ]
    for pat in patterns:
        m = re.search(pat, t, re.I)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip()

    m = re.search(r"\b(A\d{1,2}(?:\s+Bionic|\s+Pro)?)\b", t, re.I)
    if m and ("apple" in t.lower() or "a1" in t or "a2" in t):
        return m.group(1).strip()

    # Primeiro segmento antes de vírgula/parenteses em descrições genéricas
    corte = re.split(r"[,;]\s*(?:\d+\s*x|Hexa|Octa|Dual|Quad)", t, maxsplit=1, flags=re.I)
    if corte[0] and len(corte[0]) < len(t):
        return corte[0].strip()[:90]

    return t.split(",")[0].split("(")[0].strip()[:90]


def _armazenamento_de_url(url: str) -> str | None:
    m = re.search(r"/(\d{2,4})gb/?", url, re.I)
    if m:
        return f"{m.group(1)}GB"
    return None


def _extrair_armazenamento(pares: dict[str, str], url: str) -> str:
    """Evita 'rom' pegar linha errada; prioriza GB no valor e chaves de ROM interna."""
    excluir_chave = (
        "expansível",
        "expansivel",
        "cartão",
        "cartao",
        "microsd",
        "slot",
        "nm card",
    )
    candidatos: list[tuple[int, str]] = []

    for k, v in pares.items():
        kl = k.lower()
        if any(x in kl for x in excluir_chave):
            continue
        if re.search(r"\bnão\s+suporta\b", v, re.I) and not re.search(
            r"\d+\s*GB", v, re.I
        ):
            continue
        if not re.search(r"\d+\s*GB", v, re.I):
            continue
        score = 0
        if "intern" in kl or "interna" in kl:
            score += 5
        if "armazen" in kl:
            score += 4
        if "rom" in kl and "cart" not in kl:
            score += 3
        if "capacidade" in kl and "bateria" not in kl:
            score += 2
        candidatos.append((score, v.strip()))

    if candidatos:
        candidatos.sort(key=lambda x: -x[0])
        return candidatos[0][1]

    from_url = _armazenamento_de_url(url)
    if from_url:
        return from_url

    return "N/A"


def _extrair_bateria_capacidade(pares: dict[str, str], texto_pagina: str) -> str:
    for k, v in pares.items():
        kl = k.lower()
        if "bateria" in kl or "capacidade" in kl:
            if re.search(r"\d{3,5}\s*mAh", v, re.I):
                m = re.search(r"(\d{3,5}\s*mAh)", v, re.I)
                if m:
                    return m.group(1)
        if "mah" in v.lower() and "bater" in kl:
            return v.strip()
    m = re.search(r"(\d{3,5}\s*mAh)", texto_pagina, re.I)
    return m.group(1) if m else "N/A"


def _extrair_carregamento(pares: dict[str, str], texto_pagina: str) -> str:
    for k, v in pares.items():
        kl = k.lower()
        if any(
            x in kl
            for x in ("carregamento", "carga rápida", "fast charge", "potência", "carregador")
        ):
            if re.search(r"\d+\s*W", v, re.I) or "wireless" in v.lower():
                return v.strip()
    m = re.search(
        r"(?:carregamento|carga)[^\n]{0,40}(\d+\s*W)",
        texto_pagina,
        re.I,
    )
    if m:
        return m.group(1)
    return "N/A"


def _conectividade_resumida(pares: dict[str, str]) -> str:
    """Wi‑Fi / Bluetooth / NFC; ignora células gigantes (bandas 5G por SKU)."""
    partes: list[str] = []
    vistos: set[str] = set()

    def add(v: str | None, lim: int = 200) -> None:
        if not v or v in vistos:
            return
        if len(v) > lim:
            return
        vistos.add(v)
        partes.append(v)

    for k, v in pares.items():
        kl = k.lower()
        if "802.11" in v and len(v) < 260 and ("wi" in kl or "wireless" in kl or "wlan" in kl):
            add(v, 260)
            break

    add(_primeira_chave(pares, "bluetooth"), 130)
    add(_primeira_chave(pares, "nfc"), 90)

    if not partes:
        add(_primeira_chave(pares, "wi-fi"), 260)
        add(_primeira_chave(pares, "wifi"), 260)

    v5 = _primeira_chave(pares, "5g")
    if v5 and len(v5) < 160 and "SA/NSA" not in v5[:80]:
        add(v5, 160)

    return " | ".join(partes) if partes else "N/A"


def _normalizar_nome_produto(nome: str) -> str:
    """Remove variante de armazenamento do texto (evita slug galaxy-s25-256-gb)."""
    s = nome.strip()
    s = re.sub(
        r"\b\d{1,4}\s*(GB|TB|gb|tb)\b",
        " ",
        s,
        flags=re.I,
    )
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _montar_marca_slug(nome_aparelho: str) -> tuple[str, str]:
    nome_limpo = nome_aparelho.lower().strip()
    marca = "apple" if "iphone" in nome_limpo else nome_limpo.split()[0]
    slug = re.sub(r"[^a-z0-9\-]", "", nome_limpo.replace(" ", "-"))
    return marca, slug


def _slug_variacoes(nome: str) -> list[str]:
    low = nome.lower().strip()
    low = re.sub(r"[^a-z0-9\s\-]", "", low)
    palavras = [p for p in low.split() if p]
    slugs: list[str] = []
    if not palavras:
        return []
    slugs.append("-".join(palavras))
    if len(palavras) >= 2:
        slugs.append("-".join(palavras[1:]))
        slugs.append("-".join(palavras[-2:]))
    out: list[str] = []
    for s in slugs:
        s = re.sub(r"-+", "-", s).strip("-")
        if s and s not in out:
            out.append(s)
    return out


def _candidatos_samsung_galaxy_s(nome: str) -> list[tuple[str, str]]:
    """
    Galaxy S quando o usuário não escreve 'Galaxy' (ex.: só 'S25').
    Rota canônica no site: /fichas-tecnicas/samsung/galaxy-s25/ (sem /128gb/ na URL).
    """
    low = re.sub(r"\s+", " ", nome.strip().lower())
    if re.search(r"\bmoto|motorola\b", low, re.I):
        return []
    m = re.search(r"\b(s\d{1,2})\b", low, re.I)
    if not m:
        return []
    sn = m.group(1).lower()
    out: list[tuple[str, str]] = []
    if "ultra" in low:
        out.append(("samsung", f"galaxy-{sn}-ultra"))
    elif re.search(r"\bplus\b", low, re.I):
        out.append(("samsung", f"galaxy-{sn}-plus"))
    elif re.search(r"\bfe\b", low, re.I):
        out.append(("samsung", f"galaxy-{sn}-fe"))
    out.append(("samsung", f"galaxy-{sn}"))
    if "galaxy" in low or "samsung" in low:
        return out
    core = re.sub(r"[^a-z0-9]", "", low)
    if core == sn or (core.startswith(sn) and len(core) <= len(sn) + 10):
        return out
    return []


def _pares_marca_slug_candidatos(nome: str) -> list[tuple[str, str]]:
    """Várias combinações marca + slug para URLs diretas (antes da busca no site)."""
    nome = _normalizar_nome_produto(nome)
    low = nome.lower().strip()
    marcas_slugs: list[tuple[str, str]] = []
    marcas_slugs.extend(_candidatos_samsung_galaxy_s(nome))
    for slug in _slug_variacoes(nome):
        if "iphone" in low or "ipad" in low:
            marcas_slugs.append(("apple", slug))
        if "galaxy" in low or "samsung" in low:
            sg = re.sub(r"^samsung-", "", slug)
            marcas_slugs.append(("samsung", sg))
        if any(x in low for x in ("xiaomi", "redmi", "poco")):
            sg = re.sub(r"^(xiaomi|redmi|poco)-", "", slug)
            marcas_slugs.append(("xiaomi", sg))
        if "motorola" in low or low.startswith("moto"):
            sg = re.sub(r"^motorola-", "", slug)
            marcas_slugs.append(("motorola", sg))
        if "google" in low or "pixel" in low:
            sg = re.sub(r"^google-", "", slug)
            marcas_slugs.append(("google", sg))
        pri = low.split()[0] if low.split() else ""
        if pri and pri not in ("apple", "samsung", "galaxy"):
            marcas_slugs.append((pri, slug))

    visto: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for m, s in marcas_slugs:
        if s and (m, s) not in visto:
            visto.add((m, s))
            out.append((m, s))
    if not out:
        m, s = _montar_marca_slug(nome)
        out.append((m, s))
    return out


def _montar_urls_tentativa(nome: str) -> list[str]:
    """
    Uma URL canônica por par (sem /128gb/ etc. — o site não separa armazenamento na rota).
    Vários pares na ordem de prioridade até acertar (ex.: S25 → samsung/galaxy-s25/ antes de s25/s25/).
    """
    pares = _pares_marca_slug_candidatos(nome)
    if not pares:
        m, s = _montar_marca_slug(nome)
        pares = [(m, s)]
    visto: set[str] = set()
    ordem: list[str] = []
    for marca, slug in pares:
        for u in _montar_urls_maiscelular(marca, slug):
            if u not in visto:
                visto.add(u)
                ordem.append(u)
    return ordem


def _abs_maiscelular(href: str) -> str:
    if href.startswith("http"):
        return href.split("#")[0]
    return urljoin("https://www.maiscelular.com.br/", href)


def _base_ficha_de_url(url: str) -> str | None:
    """https://.../fichas-tecnicas/MARCA/SLUG/... → base com barra final."""
    m = re.search(
        r"(https://www\.maiscelular\.com\.br/fichas-tecnicas/[\w-]+/[\w-]+)",
        url,
        re.I,
    )
    if m:
        return m.group(1).rstrip("/") + "/"
    return None


def _tokens_relevantes_busca(nome_busca: str) -> list[str]:
    """Evita números só de armazenamento (256, 128) virarem match falso."""
    out: list[str] = []
    for t in re.split(r"[^a-z0-9]+", nome_busca.lower()):
        if len(t) < 2:
            continue
        if t.isdigit():
            if int(t) in (64, 128, 256, 512, 1024, 32, 16, 8, 12):
                continue
        out.append(t)
    return out


def _pontuacao_busca(href: str, titulo: str, nome_busca: str) -> int:
    h = (href + " " + titulo).lower()
    q = nome_busca.lower()
    tokens = _tokens_relevantes_busca(nome_busca)
    sc = 0
    for t in tokens:
        if len(t) >= 3 and t in h:
            sc += 6
        elif len(t) == 2 and t in h:
            sc += 2

    if re.search(r"/fichas-tecnicas/[\w-]+/[\w-]+", href, re.I):
        sc += 8

    if "ficha" in titulo.lower() or "especific" in titulo.lower():
        sc += 2

    # Marca no path deve bater com o pedido
    if "galaxy" in q or "samsung" in q:
        if "/samsung/" in href.lower():
            sc += 40
        for exc in ("/motorola/", "/apple/", "/xiaomi/", "/lg/"):
            if exc in href.lower():
                sc -= 80
    if "iphone" in q or "ipad" in q:
        if "/apple/" in href.lower():
            sc += 40
        if "/samsung/" in href.lower() or "/motorola/" in href.lower():
            sc -= 80
    if "motorola" in q or q.startswith("moto ") or " moto " in f" {q} ":
        if "/motorola/" in href.lower():
            sc += 40
        if "/samsung/" in href.lower():
            sc -= 60

    # S25, Note 20, etc. no slug
    md = re.search(r"\b(s\d{1,2})\b", q, re.I)
    if md:
        sn = md.group(1).lower()
        if sn in href.lower().replace("-", ""):
            sc += 22

    return sc


async def _buscar_url_ficha_no_site(page, nome: str) -> str | None:
    """Usa a busca WordPress (?s=) do Mais Celular."""
    nome_n = _normalizar_nome_produto(nome)
    q = quote_plus(nome_n)
    url_busca = f"https://www.maiscelular.com.br/?s={q}"
    print(f"🔎 Buscando no site: {nome_n!r} → {url_busca}")
    await _mc_goto(page, url_busca, specs_selector=None)
    soup = BeautifulSoup(await page.content(), "lxml")
    por_base: dict[str, int] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if "/fichas-tecnicas/" not in href:
            continue
        if any(
            x in href.lower()
            for x in ("comparar", "blog", "noticias", "wp-", "javascript")
        ):
            continue
        full = _abs_maiscelular(href)
        if urlparse(full).netloc and "maiscelular.com.br" not in full:
            continue
        base = _base_ficha_de_url(full)
        if not base:
            continue
        tit = a.get_text(" ", strip=True)
        sc = _pontuacao_busca(full, tit, nome_n)
        if base not in por_base or sc > por_base[base]:
            por_base[base] = sc

    if not por_base:
        return None
    melhor_base, melhor_sc = max(por_base.items(), key=lambda x: x[1])
    minimo = 18
    if melhor_sc < minimo:
        return None
    return melhor_base


async def crawler_maiscelular_blindado(nome_aparelho: str):
    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    nome_busca = _normalizar_nome_produto(nome_aparelho)
    if nome_busca != nome_aparelho.strip():
        print(f"ℹ️ Nome para busca/slug (sem armazenamento): {nome_busca!r}\n")
    urls = _montar_urls_tentativa(nome_busca)

    headless = os.environ.get("MAISCELULAR_HEADLESS", "1").lower() not in (
        "0",
        "false",
        "no",
    )

    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(
                headless=headless,
                channel="chrome",
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-infobars",
                ],
            )
        except Exception:
            browser = await p.chromium.launch(
                headless=headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
            )

        context = await browser.new_context(
            user_agent=user_agent,
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=1,
            locale="pt-BR",
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = await context.new_page()

        try:
            html_final = ""
            url_usada = urls[0] if urls else ""

            def _pagina_valida(html: str) -> bool:
                sp = BeautifulSoup(html, "lxml")
                return bool(sp.find("h1")) and len(html) > 8000

            for url_alvo in urls:
                print(f"🚀 Acessando: {url_alvo}")
                try:
                    response = await _mc_goto(
                        page, url_alvo, specs_selector=MC_SPECS_SELECTOR
                    )
                except Exception:
                    continue
                if response is not None and response.status == 404:
                    continue

                html_final = await page.content()
                if _pagina_valida(html_final):
                    url_usada = url_alvo
                    break

            if not html_final or not _pagina_valida(html_final):
                base_busca = await _buscar_url_ficha_no_site(page, nome_busca)
                if base_busca:
                    b = base_busca.rstrip("/")
                    url_alvo = f"{b}/"
                    print(f"🚀 Acessando (após busca): {url_alvo}")
                    try:
                        response = await _mc_goto(
                            page, url_alvo, specs_selector=MC_SPECS_SELECTOR
                        )
                    except Exception:
                        pass
                    else:
                        if response is None or response.status != 404:
                            html_final = await page.content()
                            if _pagina_valida(html_final):
                                url_usada = url_alvo
                else:
                    await browser.close()
                    return (
                        "❌ Não encontrei a ficha para esse nome. "
                        "Tente o modelo exato (ex.: Galaxy S24 Ultra) ou MAISCELULAR_HEADLESS=0."
                    )

            if not html_final or not _pagina_valida(html_final):
                await browser.close()
                return "❌ Página vazia ou bloqueada. Tente MAISCELULAR_HEADLESS=0."

            soup = BeautifulSoup(html_final, "lxml")
            await browser.close()

            pares = _coletar_pares(soup)
            texto_pagina = soup.get_text("\n", strip=True)

            def gv(*rotulos: str) -> str:
                r = _buscar_valor(pares, *rotulos)
                return r if r else "N/A"

            def grx(pat: str) -> str:
                r = _buscar_valor_regex(pares, pat)
                return r if r else "N/A"

            antutu = _primeira_chave(pares, "antutu", "AnTuTu", "benchmark")
            if not antutu:
                antutu = grx(r"antutu|benchmark")
            if not antutu or antutu == "N/A":
                at = _extrair_antutu_texto(texto_pagina)
                antutu = at if at else "N/A"
            raw_benchmark = antutu
            antutu = _normalizar_antutu(antutu)
            geekbench = _extrair_geekbench(
                (raw_benchmark or "") + "\n" + texto_pagina
            )

            camera_t = (
                _primeira_chave(pares, "câmera traseira", "camera traseira", "rear")
                or _chave_contem(pares, "câmera", "dupla")
                or _chave_contem(pares, "câmera", "principal")
                or _primeira_chave(pares, "traseira")
            )
            if not camera_t:
                camera_t = gv("câmera")

            camera_f = (
                _primeira_chave(pares, "câmera frontal", "camera frontal", "selfie")
                or _primeira_chave(pares, "frontal")
            )

            tela_partes = [
                x
                for x in (
                    _primeira_chave(pares, "tamanho da tela"),
                    _primeira_chave(pares, "tipo da tela"),
                    _primeira_chave(pares, "resolução")
                    or _primeira_chave(pares, "resolucao"),
                )
                if x
            ]
            tela_txt = " ".join(tela_partes).strip() or _primeira_chave(
                pares, "tela", "display", "super retina"
            )
            if not tela_txt:
                tela_txt = "N/A"

            conectividade = _conectividade_resumida(pares)

            raw_chip = (
                _buscar_valor_chipset_tabela(pares)
                or _primeira_chave(pares, "chipset")
                or _primeira_chave(pares, "processador", "cpu")
                or grx(r"processador|cpu|chipset")
            )
            processador = (
                _extrair_somente_chipset(raw_chip)
                if raw_chip and raw_chip != "N/A"
                else "N/A"
            ) or "N/A"

            h1_raw = soup.find("h1").get_text(strip=True) if soup.find("h1") else nome_aparelho
            img_mc = extrair_imagem_mais_celular(soup, url_usada)

            return {
                "modelo": _limpar_modelo_h1(h1_raw),
                "imagem_url": img_mc,
                "antutu": antutu,
                "geekbench": geekbench or "N/A",
                "processador": processador,
                "sistema_operacional": (
                    _primeira_chave(
                        pares,
                        "sistema operacional",
                        "android",
                        "ios",
                    )
                    or gv("sistema")
                    or "N/A"
                ),
                "memoria_ram": (
                    _primeira_chave(pares, "memória ram", "memoria ram")
                    or _primeira_chave(pares, "ram")
                    or "N/A"
                ),
                "armazenamento": _extrair_armazenamento(pares, url_usada),
                "tela": tela_txt,
                "camera_traseira": camera_t or "N/A",
                "camera_frontal": camera_f or "N/A",
                "conectividade": conectividade,
                "bateria": _extrair_bateria_capacidade(pares, texto_pagina),
                "carregamento": _extrair_carregamento(pares, texto_pagina),
                "dimensoes": _primeira_chave(pares, "dimensões", "dimensoes") or "N/A",
                "peso": _primeira_chave(pares, "peso") or "N/A",
                "audio": _primeira_chave(pares, "áudio", "audio") or "N/A",
                "biometria": (
                    _primeira_chave(
                        pares,
                        "digital",
                        "face id",
                        "desbloqueio",
                        "touch id",
                    )
                    or "N/A"
                ),
                "especificacoes_todas": pares,
                "data": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                "url": url_usada,
            }

        except Exception as e:
            await browser.close()
            return f"💥 Bloqueio ou Erro: {e}"


if __name__ == "__main__":
    import sys

    nome_cli = " ".join(sys.argv[1:]).strip()
    aparelho = nome_cli if nome_cli else "iPhone 16"
    print(f"📱 Modelo: {aparelho}\n")
    resultado = asyncio.run(crawler_maiscelular_blindado(aparelho))

    if isinstance(resultado, dict):
        print("\n" + "=" * 60)
        print(f"📦 APARELHO: {resultado['modelo']}")
        print(f"🚀 AnTuTu: {resultado['antutu']}")
        print(f"📊 Geekbench: {resultado.get('geekbench', 'N/A')}")
        print(f"⚙️ CHIPSET: {resultado['processador']}")
        print(f"💿 SO: {resultado['sistema_operacional']}")
        print(f"🧠 RAM: {resultado['memoria_ram']}")
        print(f"💾 ARMAZENAMENTO: {resultado['armazenamento']}")
        print(f"📺 TELA: {resultado['tela']}")
        print(f"📸 CÂMERA TRASEIRA: {resultado['camera_traseira']}")
        print(f"🤳 CÂMERA FRONTAL: {resultado['camera_frontal']}")
        print(f"📶 CONECTIVIDADE: {resultado['conectividade']}")
        print(f"🔋 BATERIA: {resultado['bateria']}")
        print(f"🔌 CARREGAMENTO: {resultado['carregamento']}")
        print(f"📐 DIMENSÕES/PESO: {resultado['dimensoes']} | {resultado['peso']}")
        print(f"📅 EXTRAÍDO EM: {resultado['data']}")
        print(f"🔗 FONTE: {resultado['url']}")
        n = len(resultado.get("especificacoes_todas") or {})
        print(f"📋 Pares extraídos da página: {n}")
        print("=" * 60)
    else:
        print(resultado)
