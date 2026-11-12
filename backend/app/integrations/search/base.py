"""
Search provider abstraction (Phase 3, SYSTEM_DESIGN §7/§8).

Structural protocol so tests inject lightweight fakes without any provider
SDK. Providers NEVER fabricate metadata: a hit carries only what the
provider returned (title, url, snippet, and any publish date it reports).
A search snippet is a lead, not proof (PRODUCT_SPEC §8).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit


@dataclass
class SearchHit:
    """One raw candidate source as returned by a provider."""

    title: str
    url: str | None
    snippet: str | None = None
    published_at: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class SearchProvider(Protocol):
    provider_name: str

    def search(self, query: str, *, max_results: int = 5) -> list[SearchHit]: ...


def normalize_url(url: str | None) -> str | None:
    """Canonical dedupe key for URLs: lowercase scheme/host, no fragment, no
    trailing slash, no default port. Preserves path/query (fragments hold in-
    page anchors; trailing slashes are cosmetic)."""
    if not url:
        return None
    url = url.strip()
    if not url:
        return None
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if not host:
        return None
    path = parts.path.rstrip("/") or "/"
    netloc = host
    if parts.port and not (scheme == "http" and parts.port == 80) and not (scheme == "https" and parts.port == 443):
        netloc = f"{host}:{parts.port}"
    if parts.username:
        userinfo = parts.username
        if parts.password:
            userinfo += f":{parts.password}"
        netloc = f"{userinfo}@{netloc}"
    query = parts.query
    return urlunsplit((scheme, netloc, path, query, ""))
