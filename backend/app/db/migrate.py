"""Run Alembic migrations programmatically (used at startup and in tests)."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

_BACKEND_DIR = Path(__file__).resolve().parents[2]


def upgrade_to_head(database_url: str | None = None) -> None:
    cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    if database_url:
        import os
        os.environ["DATABASE_URL"] = database_url
    command.upgrade(cfg, "head")
