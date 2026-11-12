"""Database URL and lightweight SQLite engine configuration tests."""

from sqlalchemy import text

from app.db.session import make_engine, normalize_database_url


def test_postgres_urls_are_normalized_for_psycopg():
    assert normalize_database_url("postgres://user:pass@host/db?sslmode=require") == (
        "postgresql+psycopg://user:pass@host/db?sslmode=require"
    )
    assert normalize_database_url("postgresql://user:pass@host/db") == (
        "postgresql+psycopg://user:pass@host/db"
    )
    assert normalize_database_url("postgresql+psycopg://user:pass@host/db") == (
        "postgresql+psycopg://user:pass@host/db"
    )


def test_sqlite_memory_engine_enforces_foreign_keys():
    engine = make_engine("sqlite:///:memory:")
    try:
        with engine.connect() as connection:
            assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
    finally:
        engine.dispose()
