import asyncio
import json
import re
from datetime import datetime
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from app.preco_util import extrair_primeiro_preco_brl

from crawlers.filtros_produto import titulo_atende_tokens_exatos
from crawlers.html_lxml import escolher_links_ml_listagem
from crawlers.imagem_produto import extrair_imagem_mercadolivre
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


def _limite_ml_links_candidatos(max_produtos: int) -> int:
    n = max(1, min(int(max_produtos), 8))
    return min(24, max(n * 4, n + 6))


async def crawler_mercadolivre_completo(nome_produto, max_produtos: int = 4):
    max_produtos = max(1, min(int(max_produtos), 8))
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    search_url = f"https://lista.mercadolivre.com.br/{nome_produto.replace(' ', '-')}"
    pool = _limite_ml_links_candidatos(max_produtos)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=ua)
        page = await context.new_page()
        await aplicar_bloqueio_recursos_leves(page)

        try:
            print(f"🔍 Buscando '{nome_produto}'...")
            await page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_selector("ol", timeout=12000)
            await asyncio.sleep(0.35)

            links = escolher_links_ml_listagem(
                await page.content(), nome_produto, max_links=pool
            )

            if not links:
                await browser.close()
                return "❌ Link não encontrado."

            resultados: list[dict] = []
            data_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

            for idx, link_final in enumerate(links):
                if len(resultados) >= max_produtos:
                    break
                try:
                    print(f"🔗 Extraindo anúncio {idx + 1}...")
                    await page.goto(link_final, wait_until="domcontentloaded", timeout=60000)
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
                    if not titulo_atende_tokens_exatos(nome_produto, nome_full):
                        continue

                    mem_match = re.search(
                        r"(\d+\s?GB|\d+\s?TB)", nome_full, re.IGNORECASE
                    )
                    memoria = mem_match.group(1) if mem_match else "Ver no link"

                    seller_info = extrair_vendedor_e_reputacao(soup, texto_plano)
                    preco = extrair_preco_mercadolivre(soup, texto_plano)
                    img_ml = extrair_imagem_mercadolivre(soup)

                    resultados.append(
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

            await browser.close()

            if not resultados:
                return (
                    "❌ Nenhum anúncio passou na validação do título "
                    f"para a busca '{nome_produto}'."
                )
            return resultados

        except Exception as e:
            await browser.close()
            return f"💥 Erro: {e}"


if __name__ == "__main__":
    busca = "iPhone 16"
    res = asyncio.run(crawler_mercadolivre_completo(busca, max_produtos=3))

    if isinstance(res, list):
        for i, item in enumerate(res, 1):
            print("\n" + "=" * 60)
            print(f"📦 #{i} {item['nome']}")
            print(f"💾 MEMÓRIA: {item['memoria']}")
            print(f"💰 PREÇO: {item['preco']}")
            print(f"👤 VENDEDOR: {item['vendedor']}")
            print(f"🏆 REPUTAÇÃO: {item['reputacao']}")
            if item.get("reputacao_nivel"):
                print(f"   └ Nível: {item['reputacao_nivel']}")
            if item.get("vendas_aprox"):
                print(f"   └ Vendas: {item['vendas_aprox']}")
            print(f"🔗 LINK: {item['link']}")
            print(f"📅 EXTRAÍDO EM: {item['data']}")
        print("=" * 60)
    else:
        print(res)