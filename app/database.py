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


_MIGRATION_EXTRAIDO_EM_V1 = "backfill_extraido_em_v1"


def _ensure_app_migrations_table():
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    names = {t.lower() for t in insp.get_table_names()}
    if "app_migrations" in names:
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE app_migrations (
                    id VARCHAR(128) PRIMARY KEY,
                    applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )


def _backfill_extraido_em_vazio_uma_vez():
    """
    Registros antigos sem data de extração recebem a data/hora do momento da migração.
    Roda uma única vez por banco (incl. produção): evita UPDATE em todo restart do deploy.
    """
    from sqlalchemy import text

    from app.datas import agora_texto_br

    _ensure_app_migrations_table()
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT 1 FROM app_migrations WHERE id = :i LIMIT 1"),
            {"i": _MIGRATION_EXTRAIDO_EM_V1},
        ).fetchone()
        if row:
            return
        hoje = agora_texto_br()
        conn.execute(
            text(
                'UPDATE aparelhos SET extraido_em_texto = :t '
                "WHERE extraido_em_texto IS NULL OR trim(extraido_em_texto) = ''"
            ),
            {"t": hoje},
        )
        conn.execute(
            text(
                'UPDATE ofertas_mercado SET extraido_em_texto = :t '
                "WHERE extraido_em_texto IS NULL OR trim(extraido_em_texto) = ''"
            ),
            {"t": hoje},
        )
        conn.execute(
            text("INSERT INTO app_migrations (id) VALUES (:i)"),
            {"i": _MIGRATION_EXTRAIDO_EM_V1},
        )


_MIGRATION_DROP_PRECOS_HISTORICO_V1 = "drop_precos_historico_v1"


def _drop_tabela_precos_historico_uma_vez():
    """Remove tabela legada de histórico de preço (uma vez por banco)."""
    from sqlalchemy import text

    _ensure_app_migrations_table()
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT 1 FROM app_migrations WHERE id = :i LIMIT 1"),
            {"i": _MIGRATION_DROP_PRECOS_HISTORICO_V1},
        ).fetchone()
        if row:
            return
        conn.execute(text("DROP TABLE IF EXISTS precos_historico"))
        conn.execute(
            text("INSERT INTO app_migrations (id) VALUES (:i)"),
            {"i": _MIGRATION_DROP_PRECOS_HISTORICO_V1},
        )


def init_db():
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_imagem_columns()
    _ensure_termo_normalizado_columns()
    _backfill_extraido_em_vazio_uma_vez()
    _drop_tabela_precos_historico_uma_vez()
