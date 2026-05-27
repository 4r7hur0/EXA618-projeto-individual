"""Flags de ambiente (produção vs desenvolvimento local)."""
import os


def _env_truthy(name: str) -> bool | None:
    v = os.environ.get(name, "").strip().lower()
    if not v:
        return None
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return None


def crawlers_enabled() -> bool:
    """
    Crawlers (Playwright/Selenium) e rotas `/api/crawlers/*` e `/api/aparelhos/ingest`.

    - `ENABLE_CRAWLERS=1|0` força ligado/desligado.
    - No Render (`RENDER=true`), padrão é **desligado**.
    - Localmente, padrão é **ligado** (desenvolvimento).
    """
    explicit = _env_truthy("ENABLE_CRAWLERS")
    if explicit is not None:
        return explicit
    on_render = _env_truthy("RENDER")
    if on_render is True:
        return False
    return True
