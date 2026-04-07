"""Sobe o servidor sem precisar do executável `uvicorn` no PATH."""
import os

import uvicorn

if __name__ == "__main__":
    # No Windows, --reload costuma causar falhas ao reimportar (Playwright/multiprocessing).
    reload = os.environ.get("WEB_RELOAD", "").strip().lower() in ("1", "true", "yes")
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=reload,
    )
