"""Tavily web search adapter (lazy construction — no import-time keys, D-15)."""

from __future__ import annotations

import os
import threading
from typing import Any

from .base import SearchHit


class TavilySearchProvider:
    """Adapter over tavily-python. Built lazily; a missing key raises at the
    point of use instead of at import."""

    provider_name = "tavily"

    def __init__(self, api_key: str | None = None, max_results: int = 5):
        self._api_key = api_key
        self._max_results_default = max_results
        self._client = None
        self._client_lock = threading.Lock()

    def _get(self):
        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    from tavily import TavilyClient

                    key = self._api_key if self._api_key is not None else _env_api_key()
                    if not key:
                        raise RuntimeError(
                            "Search provider unavailable: TAVILY_API_KEY is not set "
                            "(see .env.example)"
                        )
                    self._client = TavilyClient(api_key=key)
        return self._client

    def search(self, query: str, *, max_results: int | None = None) -> list[SearchHit]:
        """Map provider results to SearchHit. Missing metadata stays missing —
        only fields the provider actually returns are populated."""
        count = max_results or self._max_results_default
        response: dict[str, Any] = self._get().search(query=query, max_results=count)
        hits: list[SearchHit] = []
        for item in response.get("results", []):
            title = str(item.get("title") or "").strip() or "Untitled source"
            hits.append(
                SearchHit(
                    title=title,
                    url=item.get("url") or None,
                    snippet=item.get("content") or None,
                    published_at=item.get("published_date") or None,
                    raw=item if isinstance(item, dict) else {},
                )
            )

        return hits

    def describe(self) -> dict[str, Any]:
        return {"provider": self.provider_name}


def _env_api_key() -> str | None:
    """Env contract is TAVILY_API_KEY (.env.example). v1.config stores the same
    value under a typo'd attribute name (TAVILIY); v2 never depends on it."""
    return os.getenv("TAVILY_API_KEY")


def get_search_provider() -> TavilySearchProvider | None:
    """None means "search unavailable for this deployment" — the caller records
    an explicit gap instead of pretending to have sources."""
    if not _env_api_key():
        return None
    return TavilySearchProvider()
