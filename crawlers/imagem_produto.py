"""Extrai URL da imagem principal do HTML (og:image, galeria, etc.)."""
from __future__ import annotations

import json
from urllib.parse import urljoin

from bs4 import BeautifulSoup


def _absolutizar(url: str | None, base: str | None) -> str | None:
    if not url or url.startswith("data:"):
        return None
    u = url.strip()
    if u.startswith("//"):
        u = "https:" + u
    if u.startswith("http"):
        return u
    if base:
        return urljoin(base, u)
    return u


def _og_image(soup: BeautifulSoup) -> str | None:
    for prop in ("og:image", "og:image:url"):
        m = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
        if m and m.get("content"):
            c = m["content"].strip()
            if c and not c.startswith("data:"):
                return c
    m = soup.find("meta", attrs={"name": "twitter:image"})
    if m and m.get("content"):
        return m["content"].strip()
    return None


def extrair_imagem_mais_celular(soup: BeautifulSoup, page_url: str | None) -> str | None:
    u = _og_image(soup)
    if u:
        return _absolutizar(u, page_url)

    for sel in (
        "article img",
        ".entry-content img",
        "main img",
        ".wp-post-image",
        "img[class*='attachment']",
    ):
        img = soup.select_one(sel)
        if img and img.get("src"):
            cand = _absolutizar(img["src"], page_url)
            if cand and "spacer" not in cand.lower() and "pixel" not in cand.lower():
                return cand

    for img in soup.find_all("img", src=True):
        src = img["src"]
        if any(x in src.lower() for x in ("logo", "icon", "avatar", "spacer", "1x1")):
            continue
        cand = _absolutizar(src, page_url)
        if cand and len(cand) > 30:
            return cand
    return None


def extrair_imagem_amazon(soup: BeautifulSoup) -> str | None:
    u = _og_image(soup)
    if u:
        return u

    el = soup.select_one("#landingImage")
    if el:
        hi = el.get("data-old-hires")
        if hi and hi.startswith("http"):
            return hi
        di = el.get("data-a-dynamic-image")
        if di:
            try:
                data = json.loads(di)
                if isinstance(data, dict):
                    for key in sorted(data.keys(), key=len, reverse=True):
                        if isinstance(key, str) and key.startswith("http"):
                            return key
            except (json.JSONDecodeError, TypeError):
                pass
        src = el.get("src")
        if src:
            return _absolutizar(src, "https://www.amazon.com.br")

    img = soup.select_one("#imgTagWrapperId img[src], #main-image-container img[src]")
    if img and img.get("src"):
        return _absolutizar(img["src"], "https://www.amazon.com.br")
    return None


def extrair_imagem_mercadolivre(soup: BeautifulSoup) -> str | None:
    u = _og_image(soup)
    if u:
        return u

    for sel in (
        ".ui-pdp-gallery img",
        "figure.ui-pdp-gallery img",
        "[data-testid='picture'] img",
        ".ui-pdp-image img",
    ):
        img = soup.select_one(sel)
        if img:
            src = img.get("src") or img.get("data-src")
            if src:
                return _absolutizar(src, "https://www.mercadolivre.com.br")

    for img in soup.find_all("img", src=True):
        src = img["src"]
        if "MLA" in src or "MLB" in src or "http" in src:
            if "logo" not in src.lower():
                return _absolutizar(src, "https://www.mercadolivre.com.br")
    return None
