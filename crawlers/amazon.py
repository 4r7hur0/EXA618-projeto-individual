import asyncio
import json
import os
import re
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from app.filtros_api import (
    armazenamento_compativel_com_busca,
    capacidade_para_gb,
    capacidades_gb_em_texto,
    parece_aparelho,
    preco_brl_para_float,
)
from crawlers.filtros_produto import (
    titulo_atende_tokens_exatos,
    titulo_rejeitado_para_busca,
)
from crawlers.html_lxml import escolher_links_amazon_busca
from crawlers.imagem_produto import extrair_imagem_amazon
from crawlers.ofertas_diversidade import (
    limite_ofertas_loja,
    selecionar_ofertas_armazenamento_diverso,
)
from crawlers.playwright_fast import aplicar_bloqueio_recursos_leves

_DEBUG_DIR = Path(__file__).resolve().parent / "debug"
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
        ftxt = wrap.select_one(".a-price-fraction")
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


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _screenshot_habilitado() -> bool:
    return _env_bool("AMAZON_DEBUG_SCREENSHOT", True)


def pagina_amazon_bloqueada(html: str) -> bool:
    """Captcha, robot check ou página sem grade de resultados."""
    if not html:
        return True
    h = html.lower()
    if any(
        x in h
        for x in (
            "captchacharacters",
            "api.captcha.amazon",
            "opfcaptcha",
            "type the characters you see",
            "digite os caracteres",
            "robot check",
            "enter the characters you see",
            "sorry, we just need to make sure you're not a robot",
        )
    ):
        return True
    tem_grade = (
        "s-search-result" in h
        or 'data-component-type="s-search-result"' in h
        or "s-result-item" in h
    )
    tem_pdp = "producttitle" in h or 'id="productTitle"' in h
    if not tem_grade and not tem_pdp:
        if "amazon.com.br" in h or "amazon.com" in h:
            if "continue shopping" in h or "click the button below" in h:
                return True
    return False


async def _screenshot_debug(page: Page | None, nome: str) -> str | None:
    if not page or not _screenshot_habilitado():
        return None
    try:
        _DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = _DEBUG_DIR / f"amazon_{nome}_{ts}.png"
        await page.screenshot(path=str(path), full_page=True)
        return str(path)
    except Exception:
        return None


def _msg_bloqueio_amazon(headless: bool) -> str:
    if headless:
        return (
            "Erro: Amazon retornou CAPTCHA ou bloqueio anti-bot. "
            "Rode com AMAZON_HEADLESS=0 (e opcional AMAZON_PROFILE=1) para resolver "
            "no navegador e reutilizar cookies. Veja crawlers/debug/*.png se existir."
        )
    return (
        "Erro: CAPTCHA/bloqueio na Amazon. Resolva na janela do Chromium "
        "(AMAZON_PROFILE=1 guarda cookies para as próximas buscas)."
    )


async def _aguardar_captcha_manual(
    page: Page, *, headless: bool, contexto: str = "busca"
) -> bool:
    if headless:
        return False
    try:
        wait_s = int(os.environ.get("AMAZON_CAPTCHA_WAIT_SECONDS", "180").strip())
    except ValueError:
        wait_s = 180
    wait_s = max(30, min(wait_s, 900))
    print(
        f"Amazon ({contexto}): CAPTCHA detectado. Resolva na janela "
        f"(aguardando até {wait_s}s)..."
    )
    for _ in range(wait_s // 3):
        await asyncio.sleep(3)
        html = await page.content()
        if not pagina_amazon_bloqueada(html):
            print("Amazon: CAPTCHA resolvido, continuando.")
            return True
    return False


async def _abrir_navegador_amazon(p):
    """
    Retorna (browser | None, context, page, headless).
    browser é None quando usa perfil persistente.
    """
    # Padrão: janela visível (facilita CAPTCHA). AMAZON_HEADLESS=1 para invisível.
    headless = _env_bool("AMAZON_HEADLESS", False)
    use_profile = _env_bool("AMAZON_PROFILE", False)
    try:
        slow_mo_ms = int(os.environ.get("AMAZON_SLOWMO_MS", "0").strip())
    except ValueError:
        slow_mo_ms = 0
    slow_mo_ms = max(0, min(slow_mo_ms, 2000))

    if use_profile:
        profile_dir = os.path.join(os.path.dirname(__file__), ".playwright-amazon-profile")
        context = await p.chromium.launch_persistent_context(
            profile_dir,
            headless=headless,
            user_agent=_USER_AGENT,
            viewport={"width": 1280, "height": 720},
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            args=_LAUNCH_ARGS,
            slow_mo=slow_mo_ms or None,
        )
        page = context.pages[0] if context.pages else await context.new_page()
        browser = None
    else:
        browser = await p.chromium.launch(
            headless=headless,
            args=_LAUNCH_ARGS,
            slow_mo=slow_mo_ms or None,
        )
        context = await browser.new_context(
            user_agent=_USER_AGENT,
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            viewport={"width": 1280, "height": 720},
        )
        page = await context.new_page()

    await context.add_init_script(_STEALTH_INIT)
    if headless:
        await aplicar_bloqueio_recursos_leves(page)

    return browser, context, page, headless


async def _fechar_navegador(
    browser: Browser | None, context: BrowserContext | None
) -> None:
    try:
        if context:
            await context.close()
        elif browser:
            await browser.close()
    except Exception:
        pass


def _memoria_para_variante(
    memorias: list[str], nome_completo: str, gb_busca: int | None
) -> str:
    if gb_busca is not None:
        for m in memorias:
            if capacidade_para_gb(m) == gb_busca:
                return m
        for m in re.findall(r"(\d+\s?(?:GB|TB))", nome_completo, re.I):
            if capacidade_para_gb(m) == gb_busca:
                return m
        return f"{gb_busca} GB"
    if memorias:
        return ", ".join(sorted(set(memorias)))
    match_mem = re.search(r"(\d+\s?(?:GB|TB))", nome_completo, re.I)
    if match_mem:
        return match_mem.group(1)
    return "Não identificada"


async def _links_da_busca(
    page: Page, html: str, nome_produto: str, base_url: str, pool: int
) -> list[str]:
    links = escolher_links_amazon_busca(
        html, nome_produto, base_url, max_links=pool, relaxar_tokens=False
    )
    if links:
        return links
    return escolher_links_amazon_busca(
        html, nome_produto, base_url, max_links=pool, relaxar_tokens=True
    )


async def _raspar_uma_busca_amazon(
    page: Page,
    *,
    headless: bool,
    nome_produto: str,
    max_produtos: int,
    gb_busca: int | None = None,
    base_url: str = "https://www.amazon.com.br",
) -> list[dict] | str:
    max_produtos = limite_ofertas_loja(max_produtos)
    search_url = f"{base_url}/s?k={nome_produto.replace(' ', '+')}"
    pool = _limite_amazon_links_candidatos(max_produtos)

    try:
        await page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(0.4)

        html_busca = await page.content()
        if pagina_amazon_bloqueada(html_busca):
            shot = await _screenshot_debug(page, f"bloqueio_{nome_produto[:20]}")
            if not await _aguardar_captcha_manual(
                page, headless=headless, contexto=f"busca:{nome_produto}"
            ):
                msg = _msg_bloqueio_amazon(headless)
                return f"{msg} Busca: {nome_produto}." + (
                    f" Screenshot: {shot}" if shot else ""
                )
            html_busca = await page.content()

        try:
            await page.wait_for_selector(
                'div[data-component-type="s-search-result"], '
                ".s-result-item, #productTitle",
                timeout=18000 if not headless else 12000,
            )
        except Exception as wait_err:
            shot = await _screenshot_debug(page, f"timeout_{nome_produto[:20]}")
            html_busca = await page.content()
            if pagina_amazon_bloqueada(html_busca):
                if await _aguardar_captcha_manual(
                    page, headless=headless, contexto=f"busca:{nome_produto}"
                ):
                    try:
                        await page.wait_for_selector(
                            'div[data-component-type="s-search-result"], .s-result-item',
                            timeout=18000,
                        )
                    except Exception:
                        pass
                else:
                    msg = _msg_bloqueio_amazon(headless)
                    return f"{msg} Busca: {nome_produto}." + (
                        f" Screenshot: {shot}" if shot else ""
                    )
            else:
                msg = f"💥 Erro ({nome_produto}): {wait_err}"
                return msg + (f" (screenshot: {shot})" if shot else "")

        html_busca = await page.content()
        links = await _links_da_busca(page, html_busca, nome_produto, base_url, pool)

        if not links:
            shot = await _screenshot_debug(page, f"sem_links_{nome_produto[:20]}")
            msg = (
                f"❌ Produto não encontrado para '{nome_produto}' "
                "(nenhum link na grade)."
            )
            return msg + (f" Veja {shot}." if shot else "")

        candidatos: list[dict] = []
        data_extracao = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        rejeitados_tokens = 0

        for link_final in links:
            try:
                await page.goto(
                    link_final, wait_until="domcontentloaded", timeout=60000
                )
                try:
                    await page.wait_for_selector(
                        "#corePrice_feature_div, #corePriceDisplay_desktop_feature_div, "
                        "#priceblock_ourprice, #productTitle, #dp, #centerCol",
                        timeout=18000,
                    )
                except Exception:
                    pass
                await asyncio.sleep(0.55)

                html_pdp = await page.content()
                if pagina_amazon_bloqueada(html_pdp):
                    if not await _aguardar_captcha_manual(
                        page, headless=headless, contexto="produto"
                    ):
                        continue
                    html_pdp = await page.content()

                soup = BeautifulSoup(html_pdp, "lxml")
                obj_titulo = soup.find(id="productTitle")
                nome_completo = (
                    obj_titulo.get_text(strip=True) if obj_titulo else "Indisponível"
                )
                if nome_completo == "Indisponível":
                    continue
                if titulo_rejeitado_para_busca(nome_produto, nome_completo):
                    continue
                if not titulo_atende_tokens_exatos(nome_produto, nome_completo):
                    rejeitados_tokens += 1
                    continue

                memorias = [
                    btn.get_text(strip=True)
                    for btn in soup.select(
                        "#variation_size_name .swatch-button, "
                        "#variation_storage_capacity .swatch-button"
                    )
                ]

                mem_join = _memoria_para_variante(memorias, nome_completo, gb_busca)

                if not armazenamento_compativel_com_busca(
                    nome_completo, mem_join, gb_busca
                ):
                    continue

                preco = extrair_preco_amazon(soup)
                img_amz = extrair_imagem_amazon(soup)

                mem_gb = (
                    gb_busca
                    if gb_busca is not None
                    else capacidade_para_gb(mem_join)
                )
                if not parece_aparelho(
                    nome_completo,
                    preco_valor=preco_brl_para_float(preco),
                    oferta_memoria_gb=mem_gb,
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

        if not candidatos:
            msg = (
                f"❌ Nenhum produto passou na validação para '{nome_produto}'."
            )
            if rejeitados_tokens:
                msg += f" ({rejeitados_tokens} título(s) sem tokens da busca.)"
            if gb_busca:
                msg += f" Variante pedida: {gb_busca}GB."
            return msg

        if gb_busca is not None:
            com_gb = [
                c
                for c in candidatos
                if gb_busca in capacidades_gb_em_texto(
                    f"{c.get('nome')} {c.get('memoria')}"
                )
            ]
            resto = [c for c in candidatos if c not in com_gb]
            candidatos = com_gb + resto

        return selecionar_ofertas_armazenamento_diverso(candidatos, max_produtos)

    except Exception as e:
        shot = await _screenshot_debug(page, "erro")
        msg = f"💥 Erro ({nome_produto}): {e}"
        return msg + (f" (screenshot: {shot})" if shot else "")


async def crawler_amazon_essencial(
    nome_produto,
    max_produtos: int = 4,
    gb_busca: int | None = None,
):
    async with async_playwright() as p:
        browser, context, page, headless = await _abrir_navegador_amazon(p)
        try:
            return await _raspar_uma_busca_amazon(
                page,
                headless=headless,
                nome_produto=nome_produto,
                max_produtos=max_produtos,
                gb_busca=gb_busca,
            )
        finally:
            await _fechar_navegador(browser, context)


async def crawler_amazon_sequencia(
    buscas: list[tuple[str, int | None]],
    max_produtos: int = 4,
) -> list[list[dict] | str]:
    """
    Várias buscas na mesma sessão do navegador (ex.: 128GB e 256GB).
    Cada item: (termo_loja, gb_variante).
    """
    if not buscas:
        return []

    async with async_playwright() as p:
        browser, context, page, headless = await _abrir_navegador_amazon(p)
        resultados: list[list[dict] | str] = []
        try:
            for i, (nome_produto, gb_busca) in enumerate(buscas):
                if i > 0:
                    await asyncio.sleep(1.2)
                print(f"Amazon [{i + 1}/{len(buscas)}]: {nome_produto!r}")
                r = await _raspar_uma_busca_amazon(
                    page,
                    headless=headless,
                    nome_produto=nome_produto,
                    max_produtos=max_produtos,
                    gb_busca=gb_busca,
                )
                resultados.append(r)
        finally:
            await _fechar_navegador(browser, context)
        return resultados


if __name__ == "__main__":
    busca = "iphone 16 128Gb"
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
