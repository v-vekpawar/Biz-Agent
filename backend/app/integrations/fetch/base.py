"""
Source-content fetch abstraction for the EvidenceVerifier.

Phase 4 requires actually inspecting source content where feasible snipped
search hits are leads, not proof). Structural protocol so tests inject
fakes. Fetched content is UNTRUSTED INPUT to verification — callers must
treat it as data, never as instructions (SYSTEM_DESIGN §12).
"""

from __future__ import annotations

from typing import Protocol


class FetchUnavailable(RuntimeError):
    """No fetcher configured for this deployment (missing tools/keys)."""


class FetchFailure(RuntimeError):
    """The specific URL could not be fetched/extracted (404, timeout,
    paywall, extractor refusal) — technically distinct from 'no evidence'."""


class ContentFetcher(Protocol):
    provider_name: str

    def fetch(self, url: str) -> str:
        """Return the page's text content. Raises FetchFailure for a failed
        specific URL — an inability to fetch is a verification FAILURE, not
        automatically indeterminacy of the claim."""
