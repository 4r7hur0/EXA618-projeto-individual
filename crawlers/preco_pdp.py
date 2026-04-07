"""Atualização rápida de preço abrindo apenas a URL do produto (PDP)."""
from __future__ import annotations

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from crawlers.amazon import extrair_preco_amazon
from crawlers.mercado_livre import extrair_preco_mercadolivre
from crawlers.playwright_fast import aplicar_bloqueio_recursos_leves

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


async def extrair_preco_url_pdp(url: str, origem: str) -> str | None:
    """
    Retorna texto de preço ou None se não identificar.
    origem: amazon | mercadolivre
    """
    url = (url or "").strip()
    if not url or origem not in ("amazon", "mercadolivre"):
        return None

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(user_agent=UA)
            page = await context.new_page()
            await aplicar_bloqueio_recursos_leves(page)
            await page.goto(url, wait_until="domcontentloaded", timeout=90000)
            html = await page.content()
        finally:
            await browser.close()

    soup = BeautifulSoup(html, "lxml")
    texto_plano = soup.get_text(" ", strip=True)
    if origem == "amazon":
        preco = extrair_preco_amazon(soup)
    else:
        preco = extrair_preco_mercadolivre(soup, texto_plano)

    if not preco or preco.strip() == "Não identificado":
        return None
    return preco.strip()
