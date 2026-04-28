import asyncio
import json
import re
from datetime import datetime
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

from app.filtros_api import capacidade_para_gb, parece_aparelho, preco_brl_para_float

from crawlers.filtros_produto import titulo_atende_tokens_exatos
from crawlers.html_lxml import escolher_links_amazon_busca
from crawlers.imagem_produto import extrair_imagem_amazon
from crawlers.ofertas_diversidade import (
    limite_ofertas_loja,
    selecionar_ofertas_armazenamento_diverso,
)
from crawlers.playwright_fast import aplicar_bloqueio_recursos_leves


def extrair_preco_amazon(soup: BeautifulSoup) -> str:
    for sel in (
        "#corePriceDisplay_desktop_feature_div .a-price .a-offscreen",
        "#corePrice_feature_div .a-price .a-offscreen",
        "#apex_desktop .a-price .a-offscreen",
        ".reinventPricePriceToPayMargin .a-offscreen",
        "span.a-price.a-text-price .a-offscreen",
        "#priceblock_ourprice",
        "#priceblock_dealprice",
        "span.a-price[data-a-size] .a-offscreen",
    ):
        el = soup.select_one(sel)
        if el:
            t = el.get_text(strip=True)
            if t and re.search(r"\d", t):
                return t
    for wrap in soup.select(
        "#corePrice_feature_div .a-price, #corePriceDisplay_desktop_feature_div .a-price"
    ):
        whole = wrap.select_one(".a-price-whole")
        if not whole:
            continue
        ftxt = (wrap.select_one(".a-price-fraction") or None)
        ftxt = ftxt.get_text(strip=True) if ftxt else ""
        w = whole.get_text(strip=True)
        if w and ftxt:
            return f"R$ {w},{ftxt}"
        if w:
            return f"R$ {w}"
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text() or ""
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        items = data if isinstance(data, list) else [data]
        for it in items:
            if not isinstance(it, dict):
                continue
            off = it.get("offers")
            if isinstance(off, dict) and off.get("price") is not None:
                if (off.get("priceCurrency") or "BRL").upper() == "BRL":
                    return f"R$ {off['price']}"
    for box in (
        soup.select_one("#centerCol"),
        soup.select_one("#corePrice_feature_div"),
        soup.select_one("#unifiedPrice_feature_div"),
    ):
        if box:
            trecho = box.get_text(" ", strip=True)
            m = re.search(
                r"R\$\s*[\d]{1,3}(?:\.[\d]{3})*,\d{2}",
                trecho,
            )
            if m:
                return m.group(0).strip()
    return "Não identificado"


def _limite_amazon_links_candidatos(max_produtos: int) -> int:
    n = limite_ofertas_loja(max_produtos)
    return min(60, max(n * 6, n + 12))


async def crawler_amazon_essencial(nome_produto, max_produtos: int = 4):
    max_produtos = limite_ofertas_loja(max_produtos)
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    base_url = "https://www.amazon.com.br"
    search_url = f"{base_url}/s?k={nome_produto.replace(' ', '+')}"
    pool = _limite_amazon_links_candidatos(max_produtos)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=user_agent)
        page = await context.new_page()
        await aplicar_bloqueio_recursos_leves(page)

        try:
            await page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_selector(
                '.s-result-item, div[data-component-type="s-search-result"]',
                timeout=12000,
            )

            links = escolher_links_amazon_busca(
                await page.content(), nome_produto, base_url, max_links=pool
            )

            if not links:
                await browser.close()
                return "❌ Produto não encontrado."

            candidatos: list[dict] = []
            data_extracao = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

            for link_final in links:
                try:
                    await page.goto(link_final, wait_until="domcontentloaded", timeout=60000)
                    try:
                        await page.wait_for_selector(
                            "#corePrice_feature_div, #corePriceDisplay_desktop_feature_div, "
                            "#priceblock_ourprice, #productTitle, #dp, #centerCol",
                            timeout=18000,
                        )
                    except Exception:
                        pass
                    await asyncio.sleep(0.55)

                    soup = BeautifulSoup(await page.content(), "lxml")
                    obj_titulo = soup.find(id="productTitle")
                    nome_completo = (
                        obj_titulo.get_text(strip=True) if obj_titulo else "Indisponível"
                    )
                    if nome_completo == "Indisponível" or not titulo_atende_tokens_exatos(
                        nome_produto, nome_completo
                    ):
                        continue

                    memorias = [
                        btn.get_text(strip=True)
                        for btn in soup.select(
                            "#variation_size_name .swatch-button, "
                            "#variation_storage_capacity .swatch-button"
                        )
                    ]
                    if not memorias:
                        match_mem = re.search(
                            r"(\d+\s?GB|\d+\s?TB)", nome_completo, re.IGNORECASE
                        )
                        if match_mem:
                            memorias = [match_mem.group(1)]

                    preco = extrair_preco_amazon(soup)
                    img_amz = extrair_imagem_amazon(soup)

                    mem_join = (
                        ", ".join(sorted(list(set(memorias))))
                        if memorias
                        else "Não identificada"
                    )
                    if not parece_aparelho(
                        nome_completo,
                        preco_valor=preco_brl_para_float(preco),
                        oferta_memoria_gb=capacidade_para_gb(mem_join),
                    ):
                        continue

                    candidatos.append(
                        {
                            "nome": nome_completo,
                            "memoria": mem_join,
                            "preco": preco,
                            "link": link_final,
                            "imagem_url": img_amz,
                            "data_extracao": data_extracao,
                        }
                    )
                except Exception:
                    continue

            await browser.close()

            if not candidatos:
                return (
                    "❌ Nenhum produto da lista passou na validação do título "
                    f"para a busca '{nome_produto}'."
                )
            return selecionar_ofertas_armazenamento_diverso(candidatos, max_produtos)

        except Exception as e:
            await browser.close()
            return f"💥 Erro: {e}"

if __name__ == "__main__":
    busca = "iphone 17"
    res = asyncio.run(crawler_amazon_essencial(busca, max_produtos=3))

    if isinstance(res, list):
        for i, item in enumerate(res, 1):
            print("\n" + "=" * 50)
            print(f"📦 #{i} {item['nome']}")
            print(f"💾 MEMÓRIA: {item['memoria']}")
            print(f"💰 PREÇO: {item['preco']}")
            print(f"🔗 LINK: {item['link']}")
            print(f"📅 EXTRAÍDO EM: {item['data_extracao']}")
        print("=" * 50)
    else:
        print(res)