from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import build_database_url

engine = create_engine(build_database_url(), pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _ensure_imagem_columns():
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    for table, col in (
        ("aparelhos", "imagem_url"),
        ("ofertas_mercado", "imagem_url"),
    ):
        if table not in insp.get_table_names():
            continue
        cols = {c["name"] for c in insp.get_columns(table)}
        if col not in cols:
            with engine.begin() as conn:
                conn.execute(
                    text(f'ALTER TABLE "{table}" ADD COLUMN {col} TEXT')
                )


def _ensure_termo_normalizado_columns():
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    for table in ("aparelhos", "ofertas_mercado"):
        if table not in insp.get_table_names():
            continue
        cols = {c["name"] for c in insp.get_columns(table)}
        if "termo_normalizado" not in cols:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        f'ALTER TABLE "{table}" ADD COLUMN termo_normalizado VARCHAR(512)'
                    )
                )
            with engine.begin() as conn:
                conn.execute(
                    text(
                        f'CREATE INDEX IF NOT EXISTS ix_{table}_termo_normalizado '
                        f'ON "{table}" (termo_normalizado)'
                    )
                )


def init_db():
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_imagem_columns()
    _ensure_termo_normalizado_columns()
