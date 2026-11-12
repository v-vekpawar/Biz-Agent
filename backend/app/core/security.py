"""Password hashing (scrypt, stdlib) and signed access tokens (PyJWT, HS256)."""

from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import hmac
import os
import re

import jwt

from . import config

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1
_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,189}\.[^@\s.]{2,}$")

MIN_PASSWORD_LENGTH = 8


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def is_valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email or "")) and len(email) <= 254


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return "scrypt${}${}${}${}${}".format(
        _SCRYPT_N, _SCRYPT_R, _SCRYPT_P,
        base64.b64encode(salt).decode(), base64.b64encode(digest).decode(),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.scrypt(password.encode(), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected))
        return hmac.compare_digest(actual, expected)
    except Exception:  # noqa: BLE001 - malformed hash never authenticates
        return False


def create_access_token(user_id: int) -> str:
    now = _dt.datetime.now(_dt.timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + _dt.timedelta(hours=config.token_ttl_hours()),
    }
    return jwt.encode(payload, config.secret_key(), algorithm="HS256")


def decode_access_token(token: str) -> int | None:
    """Return the user id for a valid, unexpired token; otherwise None."""
    try:
        payload = jwt.decode(token, config.secret_key(), algorithms=["HS256"], options={"require": ["exp", "sub"]})
        return int(payload["sub"])
    except (jwt.PyJWTError, ValueError, KeyError):
        return None


def visitor_hash(slug: str, visitor_id: str) -> str:
    """Salted hash of a browser-generated id. The raw id is never stored."""
    return hmac.new(config.secret_key().encode(), f"{slug}:{visitor_id}".encode(), hashlib.sha256).hexdigest()
