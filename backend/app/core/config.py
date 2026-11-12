"""
Small settings helpers (env-driven, read at call time so tests and deploy
environments can override without module reload).
"""

import logging
import os
import secrets
from pathlib import Path

from .. import config as _config  # noqa: F401  (ensures dotenv is loaded)

log = logging.getLogger("bizagent")

BACKEND_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = BACKEND_DIR.parent / "frontend"
if not FRONTEND_DIR.exists():  # Docker layout: /app/frontend next to /app/app
    FRONTEND_DIR = BACKEND_DIR / "frontend"

# Upload restrictions.
DEFAULT_UPLOAD_MAX_BYTES = 10 * 1024 * 1024  # 10MB
ALLOWED_DOCUMENT_EXTENSIONS = {".pdf", ".txt", ".md", ".csv", ".docx", ".xlsx"}

_EPHEMERAL_SECRET = secrets.token_urlsafe(48)


def is_production() -> bool:
    return os.getenv("BIZAGENT_ENV", "development").lower() == "production"


def secret_key() -> str:
    """Signing key for auth tokens and visitor-id hashing.

    Production refuses to run without BIZAGENT_SECRET_KEY. In development an
    ephemeral key is generated per process (tokens die on restart) and a
    warning is logged once.
    """
    value = os.getenv("BIZAGENT_SECRET_KEY")
    if value:
        return value
    if is_production():
        raise RuntimeError("BIZAGENT_SECRET_KEY must be set when BIZAGENT_ENV=production.")
    return _EPHEMERAL_SECRET


def allow_registration() -> bool:
    return os.getenv("BIZAGENT_ALLOW_REGISTRATION", "true").lower() not in {"0", "false", "no", "off"}


def token_ttl_hours() -> int:
    raw = os.getenv("BIZAGENT_TOKEN_TTL_HOURS", "")
    return int(raw) if raw.isdigit() and int(raw) > 0 else 24 * 7


def public_base_url(fallback: str = "") -> str:
    """Base URL used when building share links (public test page, dossier)."""
    return (os.getenv("BIZAGENT_PUBLIC_URL") or fallback).rstrip("/")


def rate_limit_enabled() -> bool:
    return os.getenv("BIZAGENT_RATE_LIMIT", "on").lower() not in {"0", "false", "no", "off"}


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "")
    return int(raw) if raw.isdigit() and int(raw) > 0 else default


def signup_limit() -> int:
    """Signups per client IP per 10 minutes. Generous by default: a classroom or college
    network shares one IP, so a tight limit would block real people."""
    return _int_env("BIZAGENT_SIGNUP_LIMIT", 40)


def visit_limit() -> int:
    """Page visits per client IP per minute."""
    return _int_env("BIZAGENT_VISIT_LIMIT", 300)


def trust_proxy_headers() -> bool:
    return os.getenv("BIZAGENT_TRUST_PROXY", "").lower() in {"1", "true", "yes", "on"}


def upload_max_bytes() -> int:
    raw = os.getenv("BIZAGENT_UPLOAD_MAX_BYTES")
    if raw and raw.isdigit():
        return int(raw)
    return DEFAULT_UPLOAD_MAX_BYTES


def uploads_dir() -> Path:
    """Root folder where uploaded business-case documents are stored."""
    override = os.getenv("BIZAGENT_UPLOADS_DIR")
    if override:
        return Path(override)
    return BACKEND_DIR / "uploads"


def document_storage_reference(case_id: int, stored_name: str) -> str:
    """Relative storage token recorded in the DB (never an absolute path)."""
    return f"documents/{int(case_id)}/{stored_name}"
