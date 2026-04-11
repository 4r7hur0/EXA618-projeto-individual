import logging
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv

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


def get_settings() -> Settings:
    return Settings(
        db_connection=os.environ.get("DB_CONNECTION", "pgsql").strip().lower(),
        db_host=os.environ.get("DB_HOST", "localhost").strip(),
        db_port=os.environ.get("DB_PORT", "5432").strip(),
        db_database=os.environ.get("DB_DATABASE", "smartphones").strip(),
        db_username=os.environ.get("DB_USERNAME", "postgres").strip(),
        db_password=os.environ.get("DB_PASSWORD", ""),
        db_ssl=_env_truthy("DB_SSL"),
        log_level=os.environ.get("LOG_LEVEL", "INFO").strip().upper(),
    )


def build_database_url() -> str:
    """Monta URL SQLAlchemy para PostgreSQL a partir de DB_* ou DATABASE_URL legado."""
    legacy = os.environ.get("DATABASE_URL", "").strip()
    if legacy:
        return legacy

    s = get_settings()
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
