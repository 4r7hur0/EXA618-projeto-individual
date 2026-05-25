import asyncio
import json
import re
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus, urlparse

import requests
from bs4 import BeautifulSoup
from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from app.filtros_api import (
    armazenamento_compativel_com_busca,
    capacidade_para_gb,
    capacidades_gb_em_texto,
    parece_aparelho,
    preco_brl_para_float,
)
from app.preco_util import extrair_primeiro_preco_brl

from crawlers.filtros_produto import (
    titulo_atende_busca_marketplace,
    titulo_rejeitado_para_busca,
)
from crawlers.html_lxml import escolher_links_ml_listagem
from crawlers.imagem_produto import extrair_imagem_mercadolivre
from crawlers.ofertas_diversidade import (
    limite_ofertas_loja,
    selecionar_ofertas_armazenamento_diverso,
)
from crawlers.playwright_fast import aplicar_bloqueio_recursos_leves

_DEBUG_DIR = Path(__file__).resolve().parent / "debug"
_ML_LISTAGEM_SELECTOR = (
    ".poly-card, .ui-search-layout__item, div.ui-search-result__wrapper"
)
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_STEALTH_INIT = (
    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
)
_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
]

# Seletores comuns no ML (catálogo / PDP); ordem = mais específico primeiro
SELETORES_VENDEDOR = [
    ".ui-pdp-seller__link-trigger",
    ".ui-seller-info__title-main",
    ".ui-pdp-seller__header__title",
    "a.ui-pdp-seller__header__title--link",
    "[data-testid='seller-component'] .ui-pdp-seller__link-trigger",
    ".ui-pdp-seller__header a[href*='perfil']",
]

SELETORES_NIVEL_REPUTACAO = [
    ".ui-seller-info__level",
    ".ui-pdp-seller__status-description",
    ".ui-seller-info__status-info",
    ".ui-pdp-seller__header__subtitle",
]

SELETORES_VENDAS = [
    ".ui-seller-info__sales-description",
    ".ui-pdp-seller__sales-description",
    "[class*='seller-info'] [class*='sales']",
]


def _primeiro_texto(soup: BeautifulSoup, seletores: list[str]) -> str:
    for sel in seletores:
        el = soup.select_one(sel)
        if el:
            t = el.get_text(" ", strip=True)
            if t:
                return t
    return ""


def _vendedor_jsonld(soup: BeautifulSoup) -> str:
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text() or ""
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        candidatos = data if isinstance(data, list) else [data]
        for item in candidatos:
            if not isinstance(item, dict):
                continue
            offers = item.get("offers")
            if isinstance(offers, dict):
                seller = offers.get("seller")
                if isinstance(seller, dict):
                    name = seller.get("name")
                    if isinstance(name, str) and name.strip():
                        return name.strip()
    return ""


def _vendedor_regex(texto: str) -> str:
    # "Vendido por" + nome (uma linha)
    m = re.search(
        r"Vendido\s+por\s*:?\s*(.+?)(?:\n|$)",
        texto,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        linha = re.sub(r"\s+", " ", m.group(1).strip())
        # Corta se vier lixo longo
        if len(linha) > 120:
            linha = linha[:120].rsplit(" ", 1)[0]
        return linha
    return ""


def _nivel_mercadolider(texto: str) -> str:
    m = re.search(
        r"(MercadoL[ií]der\s+[^\n]+|Mercado\s+L[ií]der\s+[^\n]+)",
        texto,
        re.IGNORECASE,
    )
    return m.group(1).strip() if m else ""


def _eh_texto_vendas(s: str) -> bool:
    if not s:
        return False
    return bool(re.search(r"\bvendas?\b", s, re.IGNORECASE))


def _limpar_nome_vendedor(raw: str) -> str:
    raw = re.sub(r"\s+", " ", (raw or "").strip())
    m = re.search(r"Vendido\s+por\s+(.+)", raw, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return raw


def extrair_vendedor_e_reputacao(soup: BeautifulSoup, texto_plano: str) -> dict:
    vendedor = _primeiro_texto(soup, SELETORES_VENDEDOR)
    if not vendedor:
        vendedor = _vendedor_jsonld(soup)
    if not vendedor:
        vendedor = _vendedor_regex(texto_plano)
    vendedor = _limpar_nome_vendedor(vendedor)

    nivel = _primeiro_texto(soup, SELETORES_NIVEL_REPUTACAO)
    vendas = _primeiro_texto(soup, SELETORES_VENDAS)

    # No ML o bloco "status" às vezes é só vendas; não tratar como nível
    if _eh_texto_vendas(nivel):
        if not vendas:
            vendas = nivel
        nivel = ""

    if not nivel:
        nivel = _nivel_mercadolider(texto_plano)

    if not vendas:
        m = re.search(
            r"(\+?\s*[\d.,]+\s*[kKmM]?\s*vendas?)",
            texto_plano,
            re.IGNORECASE,
        )
        if m:
            vendas = m.group(1).strip()

    if nivel and vendas and nivel.strip() == vendas.strip():
        nivel = None

    partes_rep = [p for p in (nivel, vendas) if p]
    reputacao_resumo = (
        " · ".join(partes_rep)
        if partes_rep
        else (nivel or vendas or "Sem informação de nível")
    )

    return {
        "vendedor": vendedor or "Vendedor não identificado",
        "reputacao": reputacao_resumo,
        "reputacao_nivel": nivel or None,
        "vendas_aprox": vendas or None,
    }


def _preco_jsonld_product(soup: BeautifulSoup) -> str:
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text() or ""
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        candidatos = data if isinstance(data, list) else [data]
        for item in candidatos:
            if not isinstance(item, dict):
                continue
            types = item.get("@type")
            if types == "Product" or (
                isinstance(types, list) and "Product" in types
            ):
                offers = item.get("offers")
                if isinstance(offers, dict) and offers.get("price") is not None:
                    p = offers["price"]
                    cur = (offers.get("priceCurrency") or "BRL").upper()
                    if cur == "BRL":
                        return f"R$ {p}"
    return ""


def extrair_preco_mercadolivre(soup: BeautifulSoup, texto_plano: str) -> str:
    def _só_valor(raw: str) -> str:
        limpo = extrair_primeiro_preco_brl(raw)
        return limpo if limpo else raw.strip()

    for sel in (
        ".ui-pdp-price__second-line",
        ".ui-pdp-price__main-container",
        ".ui-pdp-price .andes-money-amount",
        "[data-testid='price']",
        ".ui-pdp-price__part .andes-money-amount",
    ):
        el = soup.select_one(sel)
        if el:
            t = el.get_text(" ", strip=True)
            if t and re.search(r"\d", t):
                return _só_valor(t)
    meta = soup.find("meta", {"itemprop": "price"})
    if meta and meta.get("content"):
        return _só_valor(f"R$ {meta['content']}")
    preco_ld = _preco_jsonld_product(soup)
    if preco_ld:
        return _só_valor(preco_ld)
    for m in re.finditer(
        r"R\$\s*[\d]{1,3}(?:\.[\d]{3})*(?:,\d{2})?",
        texto_plano,
    ):
        cand = m.group(0).strip()
        if 6 < len(cand) < 28:
            return _só_valor(cand)
    return "Não identificado"


def _norm_max_produtos(max_produtos: int) -> int:
    return limite_ofertas_loja(max_produtos)


def _limite_ml_links_candidatos(max_produtos: int) -> int:
    n = _norm_max_produtos(max_produtos)
    return min(60, max(n * 6, n + 12))


def _parece_link_produto_ml(url: str) -> bool:
    u = (url or "").strip()
    if not u:
        return False
    ul = u.lower()
    if "mercadolivre.com.br" not in ul:
        return False
    if "click1" in ul or "slip" in ul or "javascript:" in ul:
        return False
    # PDP (catálogo) e itens (MLB-xxxx / /MLBxxxx).
    return ("/p/" in ul and "mlb" in ul) or ("mlb" in ul)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _screenshot_habilitado() -> bool:
    return _env_bool("ML_DEBUG_SCREENSHOT", True)


async def _screenshot_debug(page: Page | None, nome: str) -> str | None:
    if not page or not _screenshot_habilitado():
        return None
    try:
        _DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = _DEBUG_DIR / f"ml_{nome}_{ts}.png"
        await page.screenshot(path=str(path), full_page=True)
        return str(path)
    except Exception:
        return None


def _msg_bloqueio_ml(headless: bool) -> str:
    if headless:
        return (
            "Erro: Mercado Livre retornou CAPTCHA/bloqueio. "
            "Use ML_HEADLESS=0 e ML_PROFILE=1, resolva na janela do Chromium "
            "e rode de novo (cookies ficam salvos)."
        )
    return (
        "Erro: CAPTCHA/bloqueio no Mercado Livre. Resolva na janela aberta; "
        "o script aguarda até ML_CAPTCHA_WAIT_SECONDS."
    )


def _pagina_ml_url_login(url: str) -> bool:
    u = (url or "").lower()
    return any(
        x in u
        for x in (
            "/login",
            "/lgz/",
            "registration",
            "sign-in",
            "ingresa",
            "account-verification",
            "auth.mercadolivre",
            "jms/mlb/lgz",
            "/gz/account",
        )
    )


def _pagina_ml_html_auth(html: str) -> bool:
    """Textos das telas de login / verificação de conta (evita falso 'listagem OK')."""
    h = (html or "").lower()
    return any(
        t in h
        for t in (
            "para continuar, acesse sua conta",
            "para continuar, faça login",
            "para continuar, fazer login",
            "digite seu e-mail ou telefone",
            "digite seu e-mail",
            "insira seu e-mail",
            "insira seu e mail",
            "insira seu telefone",
            "entrar na sua conta",
            "entre na sua conta",
            "crie a sua conta",
            "iniciar sessão",
            "iniciar sesion",
            "já tenho conta",
            "ja tenho conta",
            "sou novo",
            "account-verification",
        )
    )


async def _ml_tem_login_visivel(page: Page, html: str) -> bool:
    """Login ou verificação de conta — não usar links do HTML como sinal de sucesso."""
    if _pagina_ml_url_login(page.url or ""):
        return True
    if _pagina_ml_html_auth(html):
        return True
    try:
        if (
            await page.locator(
                'input[name="user_id"]:visible, #user_id:visible, '
                'input[name="password"]:visible, '
                '[data-testid="username"]:visible, '
                'form[action*="login"] input:visible'
            ).count()
            > 0
        ):
            return True
    except Exception:
        pass
    return False


def _pagina_ml_eh_home(url: str) -> bool:
    """Home (não é listagem nem produto) — não deve travar o crawler aqui."""
    try:
        p = urlparse(url or "")
    except Exception:
        return False
    host = (p.netloc or "").lower()
    if "mercadolivre.com.br" not in host:
        return False
    path = (p.path or "/").rstrip("/") or "/"
    return path in ("", "/")


def _ml_profile_dir() -> str:
    """Mesmo perfil do teste.py (.ml_profile na raiz do projeto)."""
    custom = os.environ.get("ML_PROFILE_DIR", "").strip()
    if custom:
        return custom
    raiz = Path(__file__).resolve().parent.parent
    return str(raiz / ".ml_profile")


def _url_busca_ml(nome_produto: str) -> str:
    """URL da listagem (igual teste.py: quote_plus no path)."""
    termo = quote_plus((nome_produto or "").strip())
    return f"https://lista.mercadolivre.com.br/{termo}"


def _extrair_cards_listagem_ml(html: str, *, max_cards: int) -> list[dict]:
    """
    Extrai anúncios do HTML da listagem (poly-card / ui-search-layout__item).
    Mesma lógica do teste.py que está funcionando.
    """
    soup = BeautifulSoup(html, "lxml")
    cards = soup.find_all("div", class_="poly-card")
    if not cards:
        cards = soup.find_all("li", class_="ui-search-layout__item")

    data_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    out: list[dict] = []
    for item in cards[: max(1, max_cards)]:
        titulo_el = item.find(
            ["h2", "a"],
            class_=["poly-component__title", "ui-search-item__title"],
        )
        titulo = titulo_el.get_text(strip=True) if titulo_el else ""
        if not titulo:
            continue

        link_el = item.find("a", href=True)
        link = (link_el.get("href") or "").strip() if link_el else ""
        if not link:
            continue

        preco_el = item.find("span", class_="andes-money-amount__fraction")
        if preco_el:
            preco = f"R$ {preco_el.get_text(strip=True)}"
        else:
            preco = extrair_primeiro_preco_brl(item.get_text(" ", strip=True)) or "Não identificado"

        vendedor = "Desconhecido/Pessoa Física"
        vendedor_el = item.find("p", class_="poly-component__seller") or item.find(
            "p", class_="ui-search-official-store-label"
        )
        if vendedor_el:
            vendedor = (
                vendedor_el.get_text(strip=True)
                .replace("Por", "")
                .replace("Vendido por", "")
                .strip()
            )

        img_el = item.find("img", src=True)
        imagem_url = (img_el.get("src") or "").strip() or None

        out.append(
            {
                "nome": titulo,
                "memoria": _memoria_do_titulo(titulo),
                "preco": preco,
                "imagem_url": imagem_url,
                "vendedor": vendedor,
                "reputacao": "Sem informação de nível",
                "reputacao_nivel": None,
                "vendas_aprox": None,
                "link": link,
                "data": data_str,
            }
        )
    return out


async def _ml_pagina_pronta(page: Page, html: str) -> bool:
    """Página utilizável para raspar (listagem ou PDP — nunca a home)."""
    url = page.url or ""
    if _pagina_ml_eh_home(url):
        return False
    if await _ml_tem_login_visivel(page, html):
        return False
    ul = url.lower()
    if "lista.mercadolivre.com.br" in ul and _pagina_ml_tem_listagem(html):
        return True
    if "/p/" in ul and "mlb" in ul:
        if "ui-pdp" in (html or "").lower() or 'id="product-title"' in (html or "").lower():
            try:
                if await page.locator("h1.ui-pdp-title, h1").count() > 0:
                    return True
            except Exception:
                pass
    if "lista.mercadolivre.com.br" in ul:
        links = await _links_listagem_playwright(page, max_links=2)
        return len(links) >= 2
    return False


async def _ml_precisa_intervencao_manual(page: Page, html: str) -> bool:
    """Login, verificação de conta, CAPTCHA ou bloqueio."""
    return not await _ml_pagina_pronta(page, html)


async def _aguardar_captcha_manual(
    page: Page, *, headless: bool, contexto: str = "busca"
) -> bool:
    if headless:
        return False
    try:
        wait_s = int(
            os.environ.get(
                "ML_LOGIN_WAIT_SECONDS",
                os.environ.get("ML_CAPTCHA_WAIT_SECONDS", "240"),
            ).strip()
        )
    except ValueError:
        wait_s = 240
    wait_s = max(45, min(wait_s, 900))
    html0 = await page.content()
    if await _ml_tem_login_visivel(page, html0):
        acao = "faça login"
    elif _pagina_ml_bloqueada(html0):
        acao = "resolva o CAPTCHA/bloqueio"
    else:
        acao = "faça login ou resolva o CAPTCHA"
    print(
        f"Mercado Livre ({contexto}): {acao} na janela do navegador "
        f"(aguardando até {wait_s}s). Não clique em voltar — conclua o login na página atual."
    )
    pronto_consecutivo = 0
    ultima_url = ""
    for _ in range(wait_s // 3):
        await asyncio.sleep(3)
        html = await page.content()
        url_atual = page.url or ""
        if _pagina_ml_url_login(url_atual) and ultima_url and _pagina_ml_url_login(ultima_url):
            if url_atual != ultima_url:
                print(
                    "Mercado Livre: detectado vai-e-volta entre telas de login. "
                    "Fique na janela e termine o login (ou use 'Já tenho conta')."
                )
        ultima_url = url_atual
        if await _ml_pagina_pronta(page, html):
            pronto_consecutivo += 1
            if pronto_consecutivo >= 2:
                print("Mercado Livre: sessão liberada, continuando.")
                return True
        else:
            pronto_consecutivo = 0
    return False


async def _ml_goto_e_aguardar_auth(
    page: Page,
    url: str,
    *,
    headless: bool,
    contexto: str,
    wait_until: str = "domcontentloaded",
) -> bool:
    """Navega só se, após auth, a URL de destino estiver acessível (evita loop)."""
    await page.goto(url, wait_until=wait_until, timeout=60000)
    await asyncio.sleep(0.6)
    html = await page.content()
    if not await _ml_precisa_intervencao_manual(page, html):
        return True
    if not await _aguardar_captcha_manual(page, headless=headless, contexto=contexto):
        return False
    # Reabre o destino após login (não reutiliza HTML da tela de auth)
    if _pagina_ml_url_login(page.url or ""):
        await page.goto(url, wait_until=wait_until, timeout=60000)
        await asyncio.sleep(0.6)
    html = await page.content()
    return await _ml_pagina_pronta(page, html)


async def _ml_aguardar_login_inicial(
    page: Page,
    *,
    headless: bool,
    nome_produto: str | None = None,
) -> bool:
    """Login/CAPTCHA são tratados no wait da listagem (como teste.py)."""
    return True


async def _abrir_navegador_ml(p):
    """Abre Chromium visível por padrão; perfil persistente se ML_PROFILE=1."""
    use_profile = _env_bool("ML_PROFILE", True)
    headless = _env_bool("ML_HEADLESS", False)
    if use_profile:
        headless = False

    try:
        slow_mo_ms = int(os.environ.get("ML_SLOWMO_MS", "0").strip())
    except ValueError:
        slow_mo_ms = 0
    slow_mo_ms = max(0, min(slow_mo_ms, 2000))

    channel = os.environ.get("ML_BROWSER_CHANNEL", "").strip() or None

    if use_profile:
        profile_dir = _ml_profile_dir()
        kw: dict = {
            "headless": headless,
            "user_agent": _USER_AGENT,
            "viewport": {"width": 1280, "height": 800},
            "locale": "pt-BR",
            "timezone_id": "America/Sao_Paulo",
            "args": _LAUNCH_ARGS,
            "slow_mo": slow_mo_ms or None,
        }
        if channel:
            kw["channel"] = channel
        context = await p.chromium.launch_persistent_context(profile_dir, **kw)
        page = context.pages[0] if context.pages else await context.new_page()
        browser = None
    else:
        launch_kw: dict = {
            "headless": headless,
            "args": _LAUNCH_ARGS,
            "slow_mo": slow_mo_ms or None,
        }
        if channel:
            launch_kw["channel"] = channel
        browser = await p.chromium.launch(**launch_kw)
        context = await browser.new_context(
            user_agent=_USER_AGENT,
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()

    await context.add_init_script(_STEALTH_INIT)
    if headless:
        await aplicar_bloqueio_recursos_leves(page)

    return browser, context, page, headless


async def _fechar_navegador_ml(
    browser: Browser | None, context: BrowserContext | None
) -> None:
    try:
        if context:
            await context.close()
        elif browser:
            await browser.close()
    except Exception:
        pass


def _pagina_ml_tem_listagem(html: str) -> bool:
    """Página de busca com produtos — não é tela de CAPTCHA."""
    if not html:
        return False
    h = html.lower()
    if any(
        m in h
        for m in (
            "ui-search-layout",
            "ui-search-item",
            "ui-search-result",
            "poly-card",
            "poly-component__title",
            "andes-card",
            "ui-search-results",
            "results-list",
        )
    ):
        return True
    if "lista.mercadolivre.com.br" in h and re.search(
        r"\d+\s+resultados?", h
    ):
        return True
    if "ui-pdp" in h or 'id="product-title"' in h or 'class="ui-pdp-' in h:
        return True
    return False


def _pagina_ml_bloqueada(html: str) -> bool:
    """
    Só bloqueio real. Scripts com 'recaptcha' na listagem normal NÃO contam.
    """
    if not html:
        return True
    if _pagina_ml_tem_listagem(html):
        return False
    h = html.lower()
    if "micro-landing" in h:
        return True
    if "account-verification" in h or "account_verification" in h:
        return True
    if "access denied" in h or "acesso negado" in h:
        return True
    if "forbidden" in h and "status" in h and "error" in h:
        return True
    if any(
        t in h
        for t in (
            "não sou um robô",
            "nao sou um robo",
            "not a robot",
            "sou humano",
            "digite os caracteres",
            "type the characters",
        )
    ):
        return True
    if ("recaptcha" in h or "hcaptcha" in h) and (
        "robot" in h or "robô" in h or "robo" in h
    ):
        return True
    return False


async def _links_listagem_playwright(page, *, max_links: int) -> list[str]:
    """
    Extrai URLs de produtos diretamente do DOM (mais robusto que parsear HTML estático).
    """
    cap = max(1, min(int(max_links), 60))
    try:
        hrefs = await page.eval_on_selector_all(
            "a[href]",
            "els => els.map(e => e.href).filter(Boolean)",
        )
    except Exception:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for h in hrefs:
        if not isinstance(h, str):
            continue
        if not _parece_link_produto_ml(h):
            continue
        if h in seen:
            continue
        seen.add(h)
        out.append(h)
        if len(out) >= cap:
            break
    return out


_ML_API_TIMEOUT = 25
_ML_API_SEARCH_URL = "https://api.mercadolibre.com/sites/MLB/search"
_ML_API_USER_URL = "https://api.mercadolibre.com/users/{seller_id}"


def _formatar_preco_brl(v: float | int | None) -> str:
    if v is None:
        return "Não identificado"
    try:
        return (
            "R$ "
            + f"{float(v):,.2f}"
            .replace(",", "X")
            .replace(".", ",")
            .replace("X", ".")
        )
    except Exception:
        return f"R$ {v}"


def _memoria_do_titulo(nome_full: str) -> str:
    mem_match = re.search(r"(\d+\s?GB|\d+\s?TB)", nome_full, re.IGNORECASE)
    return mem_match.group(1) if mem_match else "Ver no link"


def _montar_reputacao_user(user: dict) -> tuple[str, str | None, str | None]:
    rep = user.get("seller_reputation") if isinstance(user, dict) else None
    if not isinstance(rep, dict):
        return ("Sem informação de nível", None, None)
    nivel = rep.get("level_id")
    trans = rep.get("transactions") if isinstance(rep.get("transactions"), dict) else {}
    total = trans.get("total")
    vendas = f"{total} vendas" if isinstance(total, int) and total > 0 else None
    partes = [p for p in (nivel, vendas) if p]
    resumo = " · ".join(partes) if partes else "Sem informação de nível"
    return (resumo, nivel if isinstance(nivel, str) else None, vendas)


def buscar_produto_ml_api(
    nome_produto: str, max_resultados: int = 50
) -> list[dict] | str:
    """
    Busca produtos na API pública do Mercado Livre (sites/MLB/search + users/{id}).
    Mesmo fluxo do script de referência: requests, permalink, preço BRL, nickname.
    """
    termo = (nome_produto or "").strip()
    if not termo:
        return "Erro: termo vazio."

    termo_busca = quote_plus(termo)
    url_busca = f"{_ML_API_SEARCH_URL}?q={termo_busca}&limit={max_resultados}"

    try:
        response = requests.get(url_busca, timeout=_ML_API_TIMEOUT)
        response.raise_for_status()
        dados = response.json()
    except requests.RequestException as e:
        return f"Erro ao consultar a API: {e}"
    except Exception as e:
        return f"Erro ao consultar a API: {e}"

    if not isinstance(dados, dict):
        return "Erro: resposta inesperada da API do Mercado Livre."

    resultados_api = dados.get("results") or []
    if not resultados_api:
        return "Nenhum anúncio encontrado."

    data_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    seller_cache: dict[int, dict] = {}
    anuncios_extraidos: list[dict] = []

    for item in resultados_api:
        if not isinstance(item, dict):
            continue

        titulo = (item.get("title") or "Sem título").strip()
        preco_num = item.get("price", 0.0)
        if not isinstance(preco_num, (int, float)):
            preco_num = 0.0
        preco_formatado = _formatar_preco_brl(preco_num)
        link = (item.get("permalink") or "Sem link").strip()
        img = (item.get("thumbnail") or item.get("secure_thumbnail") or "").strip() or None

        vendedor_nome = "Desconhecido"
        reputacao = "Sem informação de nível"
        reputacao_nivel = None
        vendas_aprox = None

        seller = item.get("seller") if isinstance(item.get("seller"), dict) else None
        seller_id = seller.get("id") if isinstance(seller, dict) else None
        if isinstance(seller_id, int):
            if seller_id not in seller_cache:
                try:
                    url_seller = _ML_API_USER_URL.format(seller_id=seller_id)
                    resp_seller = requests.get(url_seller, timeout=_ML_API_TIMEOUT)
                    resp_seller.raise_for_status()
                    seller_cache[seller_id] = resp_seller.json()
                except Exception:
                    seller_cache[seller_id] = {}
            user = seller_cache.get(seller_id) or {}
            if isinstance(user, dict):
                nick = (user.get("nickname") or "").strip()
                if nick:
                    vendedor_nome = nick
                reputacao, reputacao_nivel, vendas_aprox = _montar_reputacao_user(user)

        anuncios_extraidos.append(
            {
                "nome": titulo,
                "memoria": _memoria_do_titulo(titulo),
                "preco": preco_formatado,
                "imagem_url": img,
                "vendedor": vendedor_nome,
                "reputacao": reputacao,
                "reputacao_nivel": reputacao_nivel,
                "vendas_aprox": vendas_aprox,
                "link": link,
                "data": data_str,
            }
        )

    return anuncios_extraidos


async def _crawler_mercadolivre_via_api(
    nome_produto: str, max_produtos: int
) -> list[dict] | str:
    """
    API via buscar_produto_ml_api + filtros do projeto (título, aparelho, diversidade).
    """
    limite_api = max(10, min(50, _norm_max_produtos(max_produtos) * 12))
    raw = await asyncio.to_thread(buscar_produto_ml_api, nome_produto, limite_api)
    if isinstance(raw, str):
        return raw

    candidatos = _ml_filtrar_candidatos(raw, nome_produto, None)
    if not candidatos and raw:
        print(
            "Mercado Livre API: filtros removeram tudo; usando resultados brutos da API."
        )
        candidatos = [
            a
            for a in raw
            if (a.get("nome") or "").strip() and (a.get("link") or "").strip()
        ]

    if not candidatos:
        return "Erro: nenhum anúncio retornado pela API."
    return selecionar_ofertas_armazenamento_diverso(candidatos, max_produtos)


def _memoria_para_variante_ml(nome_full: str, gb_busca: int | None) -> str:
    if gb_busca is not None:
        for m in re.findall(r"(\d+\s?(?:GB|TB))", nome_full, re.I):
            if capacidade_para_gb(m) == gb_busca:
                return m
        return f"{gb_busca} GB"
    return _memoria_do_titulo(nome_full)


async def _raspar_uma_busca_ml_playwright(
    page: Page,
    *,
    headless: bool,
    nome_produto: str,
    max_produtos: int,
    gb_busca: int | None = None,
) -> list[dict] | str:
    """
    Raspa na listagem (poly-card), como teste.py — sem abrir cada PDP.
    """
    max_produtos = _norm_max_produtos(max_produtos)
    search_url = _url_busca_ml(nome_produto)
    try:
        timeout_ms = int(os.environ.get("ML_LISTAGEM_TIMEOUT_MS", "60000").strip())
    except ValueError:
        timeout_ms = 60000
    timeout_ms = max(15000, min(timeout_ms, 120000))
    pool = max(max_produtos * 6, 18)

    print(f"Mercado Livre (navegador): buscando {nome_produto!r}...")
    print(f"Acessando: {search_url}")

    try:
        await page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
        print(
            "Aguardando listagem... "
            "(Se aparecer CAPTCHA, resolva na janela do Chrome)"
        )
        await page.wait_for_selector(_ML_LISTAGEM_SELECTOR, timeout=timeout_ms)
    except Exception as e:
        print(f"[Aviso] Timeout ou bloqueio na listagem: {e}")
        shot = await _screenshot_debug(page, f"timeout_{nome_produto[:18]}")
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
            html_erro = await page.content()
            path_html = _DEBUG_DIR / "ml_erro_debug.html"
            _DEBUG_DIR.mkdir(parents=True, exist_ok=True)
            path_html.write_text(html_erro, encoding="utf-8")
            print(f"HTML salvo em {path_html}")
        except Exception as e_inner:
            print(f"Não foi possível salvar HTML de debug: {e_inner}")
        msg = f"Erro na listagem ({nome_produto}): {e}"
        return msg + (f" Screenshot: {shot}" if shot else "")

    try:
        await page.wait_for_load_state("domcontentloaded", timeout=5000)
    except Exception:
        pass

    try:
        html = await page.content()
    except Exception as e:
        return f"Erro ao ler HTML da listagem ({nome_produto}): {e}"

    brutos = _extrair_cards_listagem_ml(html, max_cards=pool)
    if not brutos:
        shot = await _screenshot_debug(page, f"sem_cards_{nome_produto[:18]}")
        return (
            f"Página carregou, mas não encontrou anúncios na listagem para "
            f"'{nome_produto}'."
            + (f" Screenshot: {shot}" if shot else "")
        )

    print(f"Mercado Livre: {len(brutos)} card(s) na listagem para {nome_produto!r}")

    candidatos = _ml_filtrar_candidatos(brutos, nome_produto, gb_busca)
    if not candidatos and brutos:
        print(
            f"Mercado Livre: filtros estritos removeram os {len(brutos)} cards; "
            "usando listagem bruta (ML_FILTROS=0)."
        )
        candidatos = [
            x
            for x in brutos
            if (x.get("nome") or "").strip() and (x.get("link") or "").strip()
        ]

    if not candidatos:
        msg = f"Erro: nenhum anúncio na listagem para '{nome_produto}'."
        return msg

    if _ml_filtros_estritos() and gb_busca is not None:
        com_gb = [
            c
            for c in candidatos
            if gb_busca
            in capacidades_gb_em_texto(f"{c.get('nome')} {c.get('memoria')}")
        ]
        resto = [c for c in candidatos if c not in com_gb]
        candidatos = com_gb + resto

    selecionados = selecionar_ofertas_armazenamento_diverso(candidatos, max_produtos)
    print(
        f"Mercado Livre: {len(selecionados)} oferta(s) salva(s) "
        f"(filtros={'on' if _ml_filtros_estritos() else 'off'})"
    )
    return selecionados


def _ml_filtros_estritos() -> bool:
    """ML_FILTROS=1 ativa título/GB/aparelho; padrão 0 = como teste.py (pega os cards)."""
    return _env_bool("ML_FILTROS", False)


def _ml_usar_api_primeiro() -> bool:
    """Padrão: API pública (rápida, sem CAPTCHA). ML_USE_API=0 força só navegador."""
    return _env_bool("ML_USE_API", True)


def _ml_filtrar_candidatos(
    brutos: list[dict],
    nome_produto: str,
    gb_busca: int | None,
) -> list[dict]:
    """Com ML_FILTROS=0 aceita os cards da listagem (só título + link)."""
    out: list[dict] = []
    for item in brutos:
        nome_full = (item.get("nome") or "").strip()
        link = (item.get("link") or "").strip()
        if not nome_full or not link:
            continue
        if not _ml_filtros_estritos():
            out.append(item)
            continue
        if titulo_rejeitado_para_busca(nome_produto, nome_full):
            continue
        if not titulo_atende_busca_marketplace(nome_produto, nome_full):
            continue
        memoria = _memoria_para_variante_ml(nome_full, gb_busca)
        if not armazenamento_compativel_com_busca(nome_full, memoria, gb_busca):
            continue
        preco = item.get("preco") or ""
        mem_gb = gb_busca if gb_busca is not None else capacidade_para_gb(memoria)
        if not parece_aparelho(
            nome_full,
            preco_valor=preco_brl_para_float(preco),
            oferta_memoria_gb=mem_gb,
        ):
            continue
        out.append(item)
    return out


def _filtrar_ofertas_api_por_gb(
    ofertas: list[dict], gb_busca: int | None
) -> list[dict]:
    if not _ml_filtros_estritos() or gb_busca is None or not ofertas:
        return ofertas
    out = [
        o
        for o in ofertas
        if armazenamento_compativel_com_busca(
            o.get("nome") or "", o.get("memoria"), gb_busca
        )
    ]
    return out or ofertas


async def _crawler_ml_uma_busca(
    nome_produto: str,
    max_produtos: int,
    gb_busca: int | None = None,
) -> list[dict] | str:
    """Tenta API primeiro; se falhar, abre navegador (CAPTCHA manual)."""
    if _ml_usar_api_primeiro():
        print(f"Mercado Livre API: buscando {nome_produto!r}...")
        api_res = await _crawler_mercadolivre_via_api(nome_produto, max_produtos)
        if isinstance(api_res, list) and api_res:
            filtradas = _filtrar_ofertas_api_por_gb(api_res, gb_busca)
            print(f"Mercado Livre API: {len(filtradas)} oferta(s)")
            return selecionar_ofertas_armazenamento_diverso(
                filtradas, max_produtos
            )
        if isinstance(api_res, str):
            print(f"Mercado Livre API: {api_res[:120]} → tentando navegador...")

    async with async_playwright() as p:
        browser, context, page, headless = await _abrir_navegador_ml(p)
        try:
            return await _raspar_uma_busca_ml_playwright(
                page,
                headless=headless,
                nome_produto=nome_produto,
                max_produtos=max_produtos,
                gb_busca=gb_busca,
            )
        finally:
            await _fechar_navegador_ml(browser, context)


async def crawler_mercadolivre_completo(
    nome_produto,
    max_produtos: int = 4,
    gb_busca: int | None = None,
):
    return await _crawler_ml_uma_busca(nome_produto, max_produtos, gb_busca)


async def crawler_mercadolivre_sequencia(
    buscas: list[tuple[str, int | None]],
    max_produtos: int = 4,
) -> list[list[dict] | str]:
    """Várias buscas: API por termo; o que falhar vai no mesmo navegador."""
    if not buscas:
        return []

    resultados: list[list[dict] | str | None] = [None] * len(buscas)
    falhas_playwright: list[int] = []

    if _ml_usar_api_primeiro():
        for i, (nome, gb) in enumerate(buscas):
            print(f"Mercado Livre API [{i + 1}/{len(buscas)}]: {nome!r}")
            r = await _crawler_mercadolivre_via_api(nome, max_produtos)
            if isinstance(r, list) and r:
                filtradas = _filtrar_ofertas_api_por_gb(r, gb)
                resultados[i] = selecionar_ofertas_armazenamento_diverso(
                    filtradas, max_produtos
                )
            else:
                msg = r if isinstance(r, str) else "API sem resultados"
                print(f"  → {msg[:100]}")
                falhas_playwright.append(i)

        if not falhas_playwright:
            return [x for x in resultados if x is not None]

    indices = falhas_playwright if _ml_usar_api_primeiro() else list(range(len(buscas)))

    async with async_playwright() as p:
        browser, context, page, headless = await _abrir_navegador_ml(p)
        try:
            for j, i in enumerate(indices):
                if j > 0:
                    await asyncio.sleep(1.2)
                nome, gb = buscas[i]
                resultados[i] = await _raspar_uma_busca_ml_playwright(
                    page,
                    headless=headless,
                    nome_produto=nome,
                    max_produtos=max_produtos,
                    gb_busca=gb,
                )
        finally:
            await _fechar_navegador_ml(browser, context)

    return [
        r if r is not None else "Erro: busca sem resultado"
        for r in resultados
    ]


if __name__ == "__main__":
    os.environ.setdefault("ML_USE_API", "1")
    busca = "iPhone 15 Pro 512GB"
    print(f"Buscando anúncios para: {busca!r}...\n")

    if _ml_usar_api_primeiro():
        resultados = buscar_produto_ml_api(busca, max_resultados=10)
        if isinstance(resultados, list) and resultados:
            resultados = selecionar_ofertas_armazenamento_diverso(resultados, 3)
    else:
        resultados = asyncio.run(crawler_mercadolivre_completo(busca, max_produtos=3))

    if isinstance(resultados, list):
        for i, item in enumerate(resultados, 1):
            print("=" * 60)
            print(f"#{i} {item['nome']}")
            print(f"PREÇO:    {item['preco']}")
            print(f"VENDEDOR: {item['vendedor']}")
            if item.get("memoria"):
                print(f"MEMÓRIA:  {item['memoria']}")
            print(f"LINK:     {item['link']}")
            print(f"EXTRAÍDO: {item['data']}")
        print("=" * 60)
    else:
        print(resultados)