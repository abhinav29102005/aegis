"""Database engine and session management (PostgreSQL and SQLite)."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from database.orm import (
    PG_AUDIT_TRIGGER_CREATE_SQL,
    PG_AUDIT_TRIGGER_DROP_SQL,
    PG_AUDIT_TRIGGER_FUNCTION_SQL,
    Base,
)


def create_db_engine(database_url: str, *, echo: bool = False) -> Engine:
    is_sqlite = database_url.startswith("sqlite")
    connect_args = {"check_same_thread": False, "timeout": 30} if is_sqlite else {}
    engine = create_engine(
        database_url,
        echo=echo,
        pool_pre_ping=True,
        connect_args=connect_args,
    )
    if is_sqlite:
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _connection_record):
            # Disable pysqlite implicit BEGIN so SQLAlchemy controls transaction
            # boundaries explicitly and SAVEPOINT/ROLLBACK remain atomic.
            dbapi_conn.isolation_level = None
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

        @event.listens_for(engine, "begin")
        def _do_sqlite_begin(conn):
            # Acquire SQLite's write lock up front to avoid read-to-write lock
            # upgrade SQLITE_BUSY deadlocks while keeping SAVEPOINT/ROLLBACK atomic.
            conn.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def ensure_pg_audit_triggers(engine: Engine) -> None:
    """Install PostgreSQL append-only immutability triggers on financial_events (no-op on SQLite)."""
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        conn.execute(text(PG_AUDIT_TRIGGER_FUNCTION_SQL))
        conn.execute(text(PG_AUDIT_TRIGGER_DROP_SQL))
        conn.execute(text(PG_AUDIT_TRIGGER_CREATE_SQL))


def init_db(engine: Engine) -> None:
    """Create all tables and install DB-level audit triggers (Postgres uses Alembic in prod)."""
    Base.metadata.create_all(bind=engine)
    ensure_pg_audit_triggers(engine)

