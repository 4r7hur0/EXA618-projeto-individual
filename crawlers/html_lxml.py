"""
Parse leve com lxml.html (libxml2 em C).

HTML de páginas reais não costuma usar SAX de XML; lxml é a alternativa rápida
a BeautifulSoup para varrer tags/atributos em massa.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from lxml import html as lhtml

from crawlers.filtros_produto import (
    pontuacao_relevancia,
    titulo_atende_tokens_exatos,
    titulo_rejeitado_para_busca,
)

ML_BASE = "https://www.mercadolivre.com.br"


def _candidatos_ml_listagem(html: str, nome_produto: str) -> list[tuple[int, str, str]]:
    """Lista (score, url, título) dos anúncios aceitos na página de resultados do ML."""
    doc = lhtml.fromstring(html)
    candidatos: list[tuple[int, str, str]] = []
    seen: set[str] = set()

    for a in doc.xpath("//a[@href]"):
        href = (a.get("href") or "").strip()
        if not href or "click1" in href:
            continue
        if "/p/MLB" not in href and "/MLB-" not in href:
            continue
        full = href if href.startswith("http") else urljoin(ML_BASE, href)
        if full in seen:
            continue
        title = "".join(a.itertext()).strip()
        if len(title) < 12:
            title = (a.get("title") or "").strip()
        if len(title) < 12:
            continue
        if titulo_rejeitado_para_busca(nome_produto, title):
            continue
        if not titulo_atende_tokens_exatos(nome_produto, title):
            continue
        seen.add(full)
        sc = pontuacao_relevancia(nome_produto, title)
        candidatos.append((sc, full, title))

    if candidatos:
        candidatos.sort(key=lambda x: -x[0])
        return candidatos

    seen.clear()
    for a in doc.xpath("//a[@href]"):
        href = (a.get("href") or "").strip()
        if not href or "click1" in href:
            continue
        if "/p/MLB" not in href and "/MLB-" not in href:
            continue
        full = href if href.startswith("http") else urljoin(ML_BASE, href)
        if full in seen:
            continue
        title = "".join(a.itertext()).strip()
        if len(title) < 12:
            title = (a.get("title") or "").strip()
        if len(title) < 12:
            continue
        if titulo_rejeitado_para_busca(nome_produto, title):
            continue
        if not titulo_atende_tokens_exatos(nome_produto, title):
            continue
        seen.add(full)
        sc = pontuacao_relevancia(nome_produto, title)
        candidatos.append((sc, full, title))

    candidatos.sort(key=lambda x: -x[0])
    return candidatos


def escolher_links_ml_listagem(
    html: str, nome_produto: str, *, max_links: int = 12
) -> list[str]:
    """Vários links de anúncios (melhor score primeiro), URLs únicas."""
    cap = max(1, min(int(max_links), 24))
    candidatos = _candidatos_ml_listagem(html, nome_produto)
    if not candidatos:
        return []
    melhor_por_url: dict[str, tuple[int, str]] = {}
    for sc, full, _title in candidatos:
        if full not in melhor_por_url or sc > melhor_por_url[full][0]:
            melhor_por_url[full] = (sc, full)
    ordenados = sorted(melhor_por_url.values(), key=lambda x: -x[0])
    return [u for _sc, u in ordenados[:cap]]


def escolher_link_ml_listagem(html: str, nome_produto: str) -> str | None:
    """Escolhe melhor anúncio na página de resultados do Mercado Livre."""
    links = escolher_links_ml_listagem(html, nome_produto, max_links=1)
    return links[0] if links else None


def escolher_links_amazon_busca(
    html: str, nome_produto: str, base_url: str, *, max_links: int = 12
) -> list[str]:
    """
    Vários ASIN/links de busca (melhor score primeiro), sem duplicar URL.
    """
    doc = lhtml.fromstring(html)
    base_url = base_url.rstrip("/")
    qnorm = re.sub(r"\s+", " ", (nome_produto or "").lower().strip())

    containers = doc.xpath('//div[@data-component-type="s-search-result"]')
    if not containers:
        containers = doc.xpath(
            '//div[@data-asin and string-length(@data-asin)>0 and not(contains(@class,"AdHolder"))]'
        )
    if not containers:
        containers = doc.xpath('//div[contains(@class, "s-result-item")]')

    candidatos: list[tuple[int, str]] = []

    for div in containers:
        titulo_txt = ""
        h2s = div.xpath(".//h2")
        if h2s:
            titulo_txt = "".join(h2s[0].itertext()).strip()
        if len(titulo_txt) < 5:
            for a in div.xpath('.//a[contains(@href, "/dp/")]'):
                titulo_txt = "".join(a.itertext()).strip() or (a.get("title") or "").strip()
                if len(titulo_txt) >= 8:
                    break
        if len(titulo_txt) < 3:
            continue

        if titulo_rejeitado_para_busca(nome_produto, titulo_txt):
            continue
        if not titulo_atende_tokens_exatos(nome_produto, titulo_txt):
            continue

        titulo_lower = titulo_txt.lower()
        sc = pontuacao_relevancia(nome_produto, titulo_txt)
        if re.search(r"\biphone\b", qnorm) and re.search(r"\biphone\s*\d+", titulo_lower):
            sc += 40
        if qnorm in titulo_lower:
            sc += 200
        else:
            toks = [x for x in qnorm.split() if len(x) > 1]
            if toks and all(tok in titulo_lower for tok in toks):
                sc += 120

        href_escolhido = None
        for a in div.xpath('.//a[contains(@href, "/dp/") and @href]'):
            href = (a.get("href") or "").strip()
            if not href or "slredirect" in href or "javascript:" in href:
                continue
            href_escolhido = href
            break
        if not href_escolhido:
            for a in div.xpath('.//a[contains(@class, "a-link-normal") and @href]'):
                href = (a.get("href") or "").strip()
                if "/dp/" in href and "slredirect" not in href:
                    href_escolhido = href
                    break
        if not href_escolhido:
            continue

        full = (
            href_escolhido
            if href_escolhido.startswith("http")
            else urljoin(base_url + "/", href_escolhido.lstrip("/"))
        )
        candidatos.append((sc, full))

    if not candidatos:
        return []
    melhor_url: dict[str, int] = {}
    for sc, full in candidatos:
        if full not in melhor_url or sc > melhor_url[full]:
            melhor_url[full] = sc
    ordenados = sorted(melhor_url.items(), key=lambda x: -x[1])
    cap = max(1, min(int(max_links), 24))
    return [u for u, _sc in ordenados[:cap]]


def escolher_link_amazon_busca(html: str, nome_produto: str, base_url: str) -> str | None:
    """
    Melhor resultado na página de busca da Amazon.
    Antes: exigia substring exata e filtrava com 'pro' in título (falso em "promoção").
    """
    links = escolher_links_amazon_busca(html, nome_produto, base_url, max_links=1)
    return links[0] if links else None
