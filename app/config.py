import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus, urlparse

from dotenv import load_dotenv

_log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent
# env.example primeiro; .env sobrescreve (valores reais ficam no .gitignore)
load_dotenv(_ROOT / "env.example")
load_dotenv(_ROOT / ".env", override=True)


@dataclass(frozen=True)
class Settings:
    db_connection: str
    db_host: str
    db_port: str
    db_database: str
    db_username: str
    db_password: str
    db_ssl: bool
    log_level: str


def _env_truthy(name: str, default: bool = False) -> bool:
    v = os.environ.get(name, "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "on")


def _strip_env_quotes(value: str) -> str:
    v = value.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        return v[1:-1]
    return v


def _normalize_database_url(url: str) -> str:
    """Aceita `postgres://` (Render/Heroku) e força driver psycopg2 para SQLAlchemy."""
    url = _strip_env_quotes(url)
    if url.startswith("postgres://"):
        url = "postgresql+psycopg2://" + url[len("postgres://") :]
    elif url.startswith("postgresql://") and "+psycopg2" not in url.split("://", 1)[0]:
        url = "postgresql+psycopg2://" + url[len("postgresql://") :]
    return url


def _warn_render_db_host(host: str) -> None:
    """Hostname interno do Render Postgres sem domínio costuma falhar fora da rede deles."""
    if re.match(r"^dpg-[a-z0-9]+-a$", host):
        _log.warning(
            "DB_HOST=%s parece hostname interno do Render (sem sufixo .region-postgres.render.com). "
            "No painel do Postgres use **External Database URL** em DATABASE_URL, "
            "ou as variáveis DB_* do Supabase (pooler.supabase.com).",
            host,
        )


def get_settings() -> Settings:
    return Settings(
        db_connection=os.environ.get("DB_CONNECTION", "pgsql").strip().lower(),
        db_host=_strip_env_quotes(os.environ.get("DB_HOST", "localhost")),
        db_port=os.environ.get("DB_PORT", "5432").strip(),
        db_database=os.environ.get("DB_DATABASE", "smartphones").strip(),
        db_username=os.environ.get("DB_USERNAME", "postgres").strip(),
        db_password=_strip_env_quotes(os.environ.get("DB_PASSWORD", "")),
        db_ssl=_env_truthy("DB_SSL"),
        log_level=os.environ.get("LOG_LEVEL", "INFO").strip().upper(),
    )


def build_database_url() -> str:
    """Monta URL SQLAlchemy para PostgreSQL a partir de DB_* ou DATABASE_URL legado."""
    legacy = os.environ.get("DATABASE_URL", "").strip()
    if legacy:
        url = _normalize_database_url(legacy)
        try:
            host = urlparse(url).hostname or ""
        except Exception:
            host = ""
        if host:
            _warn_render_db_host(host)
        return url

    s = get_settings()
    _warn_render_db_host(s.db_host)
    if s.db_connection not in ("pgsql", "postgres", "postgresql"):
        raise ValueError(
            f"DB_CONNECTION deve ser pgsql/postgres/postgresql; recebido: {s.db_connection!r}"
        )

    user = quote_plus(s.db_username)
    if s.db_password:
        auth = f"{user}:{quote_plus(s.db_password)}"
    else:
        auth = user

    url = f"postgresql+psycopg2://{auth}@{s.db_host}:{s.db_port}/{s.db_database}"
    if s.db_ssl:
        url = f"{url}?sslmode=require"
    return url


def configure_logging() -> None:
    s = get_settings()
    level = getattr(logging, s.log_level, logging.INFO)
    if not isinstance(level, int):
        level = logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
