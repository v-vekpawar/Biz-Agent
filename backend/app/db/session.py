"""
SQLAlchemy engine/session setup.

SQLite remains the local default. Set DATABASE_URL to a PostgreSQL URL in
hosted environments. Pooling is intentionally small for free-tier services.
"""
import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_DEFAULT_SQLITE_URL = f"sqlite:///{(_BACKEND_DIR / 'bizagent.db').as_posix()}"


def normalize_database_url(raw_url: str) -> str:
    """Normalize SQLite relative paths and common Neon postgres URL schemes."""
    value = raw_url.strip()
    if value.startswith("postgres://"):
        value = "postgresql://" + value[len("postgres://"):]
    if value.startswith("postgresql://") and "+psycopg" not in value:
        value = value.replace("postgresql://", "postgresql+psycopg://", 1)
    if not value.lower().startswith("sqlite:///"):
        return value

    path_part = value[len("sqlite:///"):]
    if path_part in (":memory:", ""):
        return value
    path = Path(path_part)
    if path.is_absolute() or (len(path_part) > 1 and path_part[0] in ("/", "\\\\")):
        return f"sqlite:///{path.as_posix()}"
    if path.exists():
        return f"sqlite:///{path.resolve().as_posix()}"
    clean_part = path_part.replace("\\\\", "/")
    if clean_part.startswith("backend/"):
        sub_rel = clean_part[8:]
        if (_BACKEND_DIR / sub_rel).exists():
            return f"sqlite:///{(_BACKEND_DIR / sub_rel).resolve().as_posix()}"
    if (_BACKEND_DIR / clean_part).exists():
        return f"sqlite:///{(_BACKEND_DIR / clean_part).resolve().as_posix()}"
    return f"sqlite:///{(_BACKEND_DIR / path.name).resolve().as_posix()}"


DATABASE_URL = normalize_database_url(os.getenv("DATABASE_URL", _DEFAULT_SQLITE_URL))


def is_sqlite_url(url: str) -> bool:
    return make_url(url).get_backend_name() == "sqlite"


def make_engine(url: str | None = None) -> Engine:
    engine_url = normalize_database_url(url or DATABASE_URL)
    sqlite_backend = is_sqlite_url(engine_url)
    options = {
        "pool_pre_ping": True,
    }
    if sqlite_backend:
        options["connect_args"] = {"check_same_thread": False}
        if engine_url.endswith(":memory:"):
            options["poolclass"] = __import__("sqlalchemy").pool.StaticPool
    else:
        # Small connection footprint for Render's low-memory free instance and
        # Neon connection limits. NullPool is intentionally not used per request.
        options.update(pool_size=2, max_overflow=1, pool_timeout=15, pool_recycle=300)

    engine = create_engine(engine_url, **options)
    if sqlite_backend:
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
