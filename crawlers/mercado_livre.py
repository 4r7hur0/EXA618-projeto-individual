import asyncio
import json
import re
import os
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from app.filtros_api import capacidade_para_gb, parece_aparelho, preco_brl_para_float
from app.preco_util import extrair_primeiro_preco_brl

from crawlers.filtros_produto import (
    titulo_atende_tokens_exatos,
    titulo_rejeitado_para_busca,
)
from crawlers.html_lxml import escolher_links_ml_listagem
from crawlers.imagem_produto import extrair_imagem_mercadolivre
from crawlers.ofertas_diversidade import (
    limite_ofertas_loja,
    selecionar_ofertas_armazenamento_diverso,
)
from crawlers.playwright_fast import aplicar_bloqueio_recursos_leves

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


def _pagina_ml_bloqueada(html: str) -> bool:
    """
    Detector de bloqueio/captcha do Mercado Livre.
    Evita falsos positivos procurando marcadores típicos da página de bloqueio.
    """
    if not html:
        return False
    h = html.lower()
    # A "micro landing" de bloqueio costuma conter essas classes/textos.
    if "micro-landing" in h:
        return True
    if "g-recaptcha" in h or "recaptcha" in h:
        return True
    if "forbidden" in h and "status" in h and "error" in h:
        return True
    if "access denied" in h or "acesso negado" in h:
        return True
    # "robot" sozinho dá muito falso positivo; exige contexto.
    if "robot" in h and ("verify" in h or "verifica" in h or "captcha" in h):
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


def _ml_api_get_json(url: str) -> dict | list:
    req = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
            "Cache-Control": "no-cache",
        },
        method="GET",
    )
    with urlopen(req, timeout=25) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8", errors="replace"))


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


async def _crawler_mercadolivre_via_api(
    nome_produto: str, max_produtos: int
) -> list[dict] | str:
    """
    Usa API pública do Mercado Livre (evita captcha do HTML/Playwright).
    Mantém filtros `titulo_atende_tokens_exatos` e `parece_aparelho`.
    """
    q = quote_plus((nome_produto or "").strip())
    if not q:
        return "Erro: termo vazio."

    url = f"https://api.mercadolibre.com/sites/MLB/search?q={q}&limit=50"
    try:
        data = await asyncio.to_thread(_ml_api_get_json, url)
    except (HTTPError, URLError, TimeoutError) as e:
        return f"Erro API ML: {type(e).__name__}: {e}"
    except Exception as e:
        return f"Erro API ML: {e}"

    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        return "Erro: resposta inesperada da API do Mercado Livre."

    results = data.get("results") or []
    data_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    seller_cache: dict[int, dict] = {}
    candidatos: list[dict] = []

    for r in results:
        if not isinstance(r, dict):
            continue
        nome_full = (r.get("title") or "").strip()
        if not nome_full:
            continue
        if titulo_rejeitado_para_busca(nome_produto, nome_full):
            continue
        if not titulo_atende_tokens_exatos(nome_produto, nome_full):
            continue

        link_final = (r.get("permalink") or "").strip()
        if not link_final:
            continue

        preco_num = r.get("price")
        preco = _formatar_preco_brl(preco_num if isinstance(preco_num, (int, float)) else None)
        memoria = _memoria_do_titulo(nome_full)
        img = (r.get("thumbnail") or r.get("secure_thumbnail") or "").strip() or None

        if not parece_aparelho(
            nome_full,
            preco_valor=preco_brl_para_float(preco),
            oferta_memoria_gb=capacidade_para_gb(memoria),
        ):
            continue

        vendedor = "Vendedor não identificado"
        reputacao = "Sem informação de nível"
        reputacao_nivel = None
        vendas_aprox = None

        seller = r.get("seller") if isinstance(r.get("seller"), dict) else None
        sid = seller.get("id") if isinstance(seller, dict) else None
        if isinstance(sid, int):
            if sid not in seller_cache:
                try:
                    seller_cache[sid] = await asyncio.to_thread(
                        _ml_api_get_json, f"https://api.mercadolibre.com/users/{sid}"
                    )
                except Exception:
                    seller_cache[sid] = {}
            u = seller_cache.get(sid) or {}
            if isinstance(u.get("nickname"), str) and u["nickname"].strip():
                vendedor = u["nickname"].strip()
            reputacao, reputacao_nivel, vendas_aprox = _montar_reputacao_user(u)

        candidatos.append(
            {
                "nome": nome_full,
                "memoria": memoria,
                "preco": preco,
                "imagem_url": img,
                "vendedor": vendedor,
                "reputacao": reputacao,
                "reputacao_nivel": reputacao_nivel,
                "vendas_aprox": vendas_aprox,
                "link": link_final,
                "data": data_str,
            }
        )

    if not candidatos:
        return "Erro: nenhum anúncio retornado pela API passou nos filtros."
    return selecionar_ofertas_armazenamento_diverso(candidatos, max_produtos)


async def crawler_mercadolivre_completo(nome_produto, max_produtos: int = 4):
    max_produtos = _norm_max_produtos(max_produtos)
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    search_url = f"https://lista.mercadolivre.com.br/{nome_produto.replace(' ', '-')}"
    pool = _limite_ml_links_candidatos(max_produtos)

    # Tenta via API pública primeiro (quando disponível); alguns ambientes retornam 403.
    api_res = await _crawler_mercadolivre_via_api(nome_produto, max_produtos)
    if isinstance(api_res, list) and api_res:
        return api_res

    async with async_playwright() as p:
        headless = os.environ.get("ML_HEADLESS", "1").strip().lower() in ("1", "true", "yes")
        use_profile = os.environ.get("ML_PROFILE", "").strip().lower() in ("1", "true", "yes")
        try:
            slow_mo_ms = int(os.environ.get("ML_SLOWMO_MS", "0").strip())
        except ValueError:
            slow_mo_ms = 0
        slow_mo_ms = max(0, min(slow_mo_ms, 2000))
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
        ]

        if use_profile:
            # Perfil persistente ajuda a passar captcha manualmente 1x e reutilizar cookies.
            profile_dir = os.path.join(os.path.dirname(__file__), ".playwright-ml-profile")
            context = await p.chromium.launch_persistent_context(
                profile_dir,
                headless=headless,
                user_agent=ua,
                viewport={"width": 1280, "height": 720},
                locale="pt-BR",
                timezone_id="America/Sao_Paulo",
                args=launch_args,
                slow_mo=slow_mo_ms or None,
            )
            page = context.pages[0] if context.pages else await context.new_page()
            browser = None
        else:
            browser = await p.chromium.launch(
                headless=headless,
                args=launch_args,
                slow_mo=slow_mo_ms or None,
            )
            context = await browser.new_context(
                user_agent=ua,
                locale="pt-BR",
                timezone_id="America/Sao_Paulo",
                viewport={"width": 1280, "height": 720},
            )
            page = await context.new_page()

        # Em headless aceleramos; em headful não bloqueia (captcha pode depender de imagens/fontes).
        if headless:
            await aplicar_bloqueio_recursos_leves(page)

        # Pequeno "stealth" para reduzir detecção básica.
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )

        try:
            print(f"Buscando '{nome_produto}'...")
            await page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_selector("a[href], main, body", timeout=12000)
            await asyncio.sleep(0.35)

            html0 = await page.content()
            if _pagina_ml_bloqueada(html0):
                if headless:
                    # Dica prática: abrir com profile + headless=0 para resolver captcha e salvar cookies.
                    return (
                        "Erro: Mercado Livre retornou captcha/bloqueio. "
                        "Rode com ML_PROFILE=1 e ML_HEADLESS=0 uma vez para resolver o captcha "
                        "no navegador e reaproveitar o perfil."
                    )

                # Headless=0: dá chance de resolver manualmente e continuar.
                try:
                    wait_s = int(os.environ.get("ML_CAPTCHA_WAIT_SECONDS", "180").strip())
                except ValueError:
                    wait_s = 180
                wait_s = max(30, min(wait_s, 900))

                print(
                    "Captcha/bloqueio detectado. Resolva na janela do Chromium "
                    f"(aguardando ate {wait_s}s)..."
                )
                for _ in range(wait_s // 3):
                    await asyncio.sleep(3)
                    html0 = await page.content()
                    if not _pagina_ml_bloqueada(html0):
                        print("Captcha resolvido, continuando...")
                        break
                else:
                    return (
                        "Erro: captcha/bloqueio ainda ativo apos espera. "
                        "Tente novamente (ML_PROFILE=1, ML_HEADLESS=0)."
                    )

            # Primeiro tenta extrair direto do DOM (página é bem dinâmica).
            links = await _links_listagem_playwright(page, max_links=pool)
            if not links:
                # Fallback: parser lxml em HTML estático.
                links = escolher_links_ml_listagem(html0, nome_produto, max_links=pool)

            if not links:
                await context.close()
                t = ""
                try:
                    t = await page.title()
                except Exception:
                    pass
                return f"Erro: link não encontrado. title={t!r} url={page.url!r}"

            candidatos: list[dict] = []
            data_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

            for idx, link_final in enumerate(links):
                try:
                    print(f"Extraindo anúncio {idx + 1}...")
                    await page.goto(link_final, wait_until="domcontentloaded", timeout=60000)
                    # Se o ML bloquear no PDP, pode não renderizar h1.
                    html_pdp = await page.content()
                    if _pagina_ml_bloqueada(html_pdp):
                        if headless:
                            continue
                        try:
                            wait_s = int(os.environ.get("ML_CAPTCHA_WAIT_SECONDS", "180").strip())
                        except ValueError:
                            wait_s = 180
                        wait_s = max(30, min(wait_s, 900))
                        print(f"Captcha no PDP. Resolva na janela (aguardando ate {wait_s}s)...")
                        for _ in range(wait_s // 3):
                            await asyncio.sleep(3)
                            html_pdp = await page.content()
                            if not _pagina_ml_bloqueada(html_pdp):
                                print("Captcha resolvido no PDP, continuando...")
                                break
                        else:
                            continue

                    await page.wait_for_selector("h1", timeout=12000)
                    try:
                        await page.wait_for_selector(
                            ".ui-pdp-price, .ui-pdp-seller__header, .ui-seller-info",
                            timeout=12000,
                        )
                    except Exception:
                        pass
                    await asyncio.sleep(0.3)

                    html = await page.content()
                    soup = BeautifulSoup(html, "lxml")
                    texto_plano = soup.get_text("\n", strip=True)
                    h1 = soup.find("h1")
                    if not h1:
                        continue
                    nome_full = h1.get_text(strip=True)
                    if titulo_rejeitado_para_busca(nome_produto, nome_full):
                        continue
                    if not titulo_atende_tokens_exatos(nome_produto, nome_full):
                        continue

                    mem_match = re.search(
                        r"(\d+\s?GB|\d+\s?TB)", nome_full, re.IGNORECASE
                    )
                    memoria = mem_match.group(1) if mem_match else "Ver no link"

                    seller_info = extrair_vendedor_e_reputacao(soup, texto_plano)
                    preco = extrair_preco_mercadolivre(soup, texto_plano)
                    img_ml = extrair_imagem_mercadolivre(soup)

                    if not parece_aparelho(
                        nome_full,
                        preco_valor=preco_brl_para_float(preco),
                        oferta_memoria_gb=capacidade_para_gb(memoria),
                    ):
                        continue

                    candidatos.append(
                        {
                            "nome": nome_full,
                            "memoria": memoria,
                            "preco": preco,
                            "imagem_url": img_ml,
                            "vendedor": seller_info["vendedor"],
                            "reputacao": seller_info["reputacao"],
                            "reputacao_nivel": seller_info["reputacao_nivel"],
                            "vendas_aprox": seller_info["vendas_aprox"],
                            "link": link_final,
                            "data": data_str,
                        }
                    )
                except Exception:
                    continue

            await context.close()

            if not candidatos:
                return (
                    "Erro: nenhum anúncio passou na validação do título "
                    f"para a busca '{nome_produto}'."
                )
            return selecionar_ofertas_armazenamento_diverso(candidatos, max_produtos)

        except Exception as e:
            try:
                await context.close()
            except Exception:
                pass
            return f"Erro: {e}"


if __name__ == "__main__":
    busca = "iPhone 16"
    res = asyncio.run(crawler_mercadolivre_completo(busca, max_produtos=3))

    if isinstance(res, list):
        for i, item in enumerate(res, 1):
            print("\n" + "=" * 60)
            print(f"#{i} {item['nome']}")
            print(f"MEMORIA: {item['memoria']}")
            print(f"PRECO: {item['preco']}")
            print(f"VENDEDOR: {item['vendedor']}")
            print(f"REPUTACAO: {item['reputacao']}")
            if item.get("reputacao_nivel"):
                print(f"   └ Nível: {item['reputacao_nivel']}")
            if item.get("vendas_aprox"):
                print(f"   └ Vendas: {item['vendas_aprox']}")
            print(f"LINK: {item['link']}")
            print(f"EXTRAIDO EM: {item['data']}")
        print("=" * 60)
    else:
        print(res)