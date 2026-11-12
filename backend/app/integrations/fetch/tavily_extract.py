"""Tavily extract adapter: page content for source verification (lazy)."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .base import FetchFailure, FetchUnavailable


class TavilyExtractFetcher:
    provider_name = "tavily-extract"

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key
        self._client = None

    def _get(self):
        if self._client is None:
            from tavily import TavilyClient

            key = self._api_key if self._api_key is not None else os.getenv("TAVILY_API_KEY")
            if not key:
                raise FetchUnavailable(
                    "Content fetcher unavailable: TAVILY_API_KEY is not set (see .env.example)"
                )
            self._client = TavilyClient(api_key=key)
        return self._client

    def fetch(self, url: str) -> str:
        """Extract one URL's text. Defensive against documented response
        shapes: results[].raw_content and failed_results[].url/error."""
        client = self._get()
        try:
            response: dict[str, Any] = client.extract(urls=[url], format="text")
        except Exception as exc:  # SDK/network errors — specific-URL failure
            raise FetchFailure(f"extract call failed for {url}: {type(exc).__name__}: {exc}") from exc

        results = response.get("results") or []
        failed = response.get("failed_results") or []
        def canonical_url(value: str) -> str:
            """Normalize only URL components that do not change the resource.

            Fragments are client-side navigation; host casing and default ports
            are equivalent. Paths, query strings and trailing slashes remain
            untouched so distinct resources are never silently conflated.
            """
            try:
                parts = urlsplit(str(value).strip())
                scheme = parts.scheme.lower()
                hostname = (parts.hostname or "").lower()
                port = parts.port
                netloc = hostname
                if port and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
                    netloc = f"{hostname}:{port}"
                if parts.username or parts.password:
                    return ""
                return urlunsplit((scheme, netloc, parts.path, parts.query, ""))
            except (TypeError, ValueError):
                return ""

        requested_key = canonical_url(url)
        matched_results = [
            item for item in results
            if requested_key and canonical_url(item.get("url", "")) == requested_key
        ]
        failed_hits = [
            item for item in failed
            if requested_key and canonical_url(item.get("url", "")) == requested_key
        ]

        if failed_hits and not matched_results:
            detail = failed_hits[0].get("error") or "extractor reported failure"
            raise FetchFailure(f"source not extractable: {detail}")

        raw = ""
        if matched_results:
            raw = matched_results[0].get("raw_content") or ""
        if not raw and results and not matched_results:
            # Never verify a requested source using content returned for a
            # different URL. This must remain an indeterminate/failure path.
            returned = ", ".join(str(item.get("url") or "unknown URL") for item in results[:3])
            raise FetchFailure(
                f"extractor did not return the requested URL; refusing unrelated content (returned: {returned})"
            )
        content = str(raw).strip()
        if not content:
            raise FetchFailure("no content extracted (empty or unrenderable page)")
        return content


def get_content_fetcher() -> TavilyExtractFetcher | None:
    """None = the deployment has no fetch tool (verification cannot run and
    the routes surface that as 503 — technical, discoverable, honest)."""
    if not os.getenv("TAVILY_API_KEY"):
        return None
    return TavilyExtractFetcher()
