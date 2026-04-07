"""Reduz peso da página bloqueando imagem/fonte/mídia (Playwright)."""
from playwright.async_api import Page


async def aplicar_bloqueio_recursos_leves(page: Page) -> None:
    async def _route(route):
        if route.request.resource_type in ("image", "font", "media"):
            await route.abort()
        else:
            await route.continue_()

    await page.route("**/*", _route)
