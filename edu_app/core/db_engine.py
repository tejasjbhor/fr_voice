"""
core/db_engine.py — DATABASE_URL resolution + SQLAlchemy engine/session
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent


def resolve_database_url() -> str:
    """
    Prefer DATABASE_URL.
    Fallback: sqlite from DB_PATH (local PoC default).
    """
    url = (os.getenv("DATABASE_URL") or "").strip()
    if url:
        # Heroku-style postgres:// → SQLAlchemy needs postgresql://
        if url.startswith("postgres://"):
            url = "postgresql+psycopg://" + url[len("postgres://") :]
        elif url.startswith("postgresql://") and "+psycopg" not in url:
            url = "postgresql+psycopg://" + url[len("postgresql://") :]
        return url

    db_path = (os.getenv("DB_PATH") or "sathi_poc.db").strip()
    path = Path(db_path)
    if not path.is_absolute():
        path = ROOT / path
    return f"sqlite:///{path.as_posix()}"


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    url = resolve_database_url()
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    engine = create_engine(
        url,
        future=True,
        pool_pre_ping=True,
        connect_args=connect_args,
    )

    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_fk(dbapi_conn, _connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, future=True)


def session_scope() -> Session:
    """Caller must close; prefer `with get_session_factory()() as s:`."""
    return get_session_factory()()


def reset_engine_cache() -> None:
    """Used in tests after changing DATABASE_URL."""
    get_engine.cache_clear()
