"""
Engine and session factories for the relational store.

- Default database: SQLite at backend/bizagent.db (zero infra). Override with
  the DATABASE_URL env var for any other SQLAlchemy-compatible backend.
- SQLite runs with PRAGMA foreign_keys=ON; without it SQLite silently ignores
  FK constraints and nothing enforces case-scoping/delete cascades.
"""

import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_DEFAULT_SQLITE_URL = f"sqlite:///{(_BACKEND_DIR / 'bizagent.db').as_posix()}"


def _normalize_sqlite_url(raw_url: str) -> str:
    """Resolve relative SQLite URLs defensively so the app works regardless of cwd
    (e.g. running from repo root vs from backend/ directory)."""
    if not raw_url.strip().lower().startswith("sqlite:///"):
        return raw_url

    path_part = raw_url[len("sqlite:///"):]
    if path_part in (":memory:", ""):
        return raw_url

    p = Path(path_part)
    # Already absolute (e.g. C:/... or /tmp/...)
    if p.is_absolute() or (len(path_part) > 1 and path_part[0] in ("/", "\\")):
        return f"sqlite:///{p.as_posix()}"

    # If it exists relative to current working directory, resolve it
    if p.exists():
        return f"sqlite:///{p.resolve().as_posix()}"

    # If it was specified as "backend/bizagent.db" but cwd is already backend/
    clean_part = path_part.replace("\\", "/")
    if clean_part.startswith("backend/"):
        sub_rel = clean_part[8:]
        if (_BACKEND_DIR / sub_rel).exists():
            return f"sqlite:///{(_BACKEND_DIR / sub_rel).resolve().as_posix()}"

    # Check relative to _BACKEND_DIR
    if (_BACKEND_DIR / clean_part).exists():
        return f"sqlite:///{(_BACKEND_DIR / clean_part).resolve().as_posix()}"

    # Fallback: resolve relative to backend directory
    return f"sqlite:///{(_BACKEND_DIR / p.name).resolve().as_posix()}"


DATABASE_URL = _normalize_sqlite_url(os.getenv("DATABASE_URL", _DEFAULT_SQLITE_URL))
"""
Resolve a SQLAlchemy engine URL. Supports the sqlite:// relative URLs Alembic
produces (relative to the backend directory) plus absolute file URLs.
"""

_IS_SQLITE = DATABASE_URL.strip().lower().startswith("sqlite")


def make_engine(url: str | None = None) -> Engine:
    engine_url = url or DATABASE_URL
    engine = create_engine(
        engine_url,
        connect_args={"check_same_thread": False} if _IS_SQLITE else {},
        pool_pre_ping=True,
    )
    if _IS_SQLITE:
        @event.listens_for(engine, "connect")
        def _enable_sqlite_fk(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def default_engine() -> Engine:
    return make_engine(DATABASE_URL)
