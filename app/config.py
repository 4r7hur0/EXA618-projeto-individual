import logging
import os
from dataclasses import dataclass
from urllib.parse import quote_plus

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    db_connection: str
    db_host: str
    db_port: str
    db_database: str
    db_username: str
    db_password: str
    log_level: str


def get_settings() -> Settings:
    return Settings(
        db_connection=os.environ.get("DB_CONNECTION", "pgsql").strip().lower(),
        db_host=os.environ.get("DB_HOST", "localhost").strip(),
        db_port=os.environ.get("DB_PORT", "5432").strip(),
        db_database=os.environ.get("DB_DATABASE", "smartphones").strip(),
        db_username=os.environ.get("DB_USERNAME", "postgres").strip(),
        db_password=os.environ.get("DB_PASSWORD", ""),
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

    return (
        f"postgresql+psycopg2://{auth}@{s.db_host}:{s.db_port}/{s.db_database}"
    )


def configure_logging() -> None:
    s = get_settings()
    level = getattr(logging, s.log_level, logging.INFO)
    if not isinstance(level, int):
        level = logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
