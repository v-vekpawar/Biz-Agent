"""Bounded concurrency for independent LLM/network calls inside a scan.

Rules that keep results identical to the sequential path:
- Results and errors come back in INPUT order.
- Exceptions are returned in the result list (not raised) so the caller can
  raise the first failure in original order after every call has finished.
- If concurrency is 1 (or there is a single item), everything runs inline on
  the calling thread — the exact previous, sequential behaviour.

The pool size comes from BIZAGENT_LLM_CONCURRENCY (default 3, capped at 8):
small enough not to self-inflict free-tier rate limits, large enough to cut
scan wall time roughly by the number of parallel calls.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable, TypeVar

from ..integrations.llm.provider import llm_concurrency

T = TypeVar("T")
R = TypeVar("R")


def map_bounded(items: list[T], fn: Callable[[T], R]) -> list[R | Exception]:
    """Apply `fn` to every item, possibly in parallel (bounded pool).

    Returns one entry per input: the result, or the exception that item raised.
    """
    if not items:
        return []
    workers = min(llm_concurrency(), len(items))
    if workers <= 1:
        out: list[R | Exception] = []
        for item in items:
            try:
                out.append(fn(item))
            except Exception as exc:  # returned, not raised: order-preserving
                out.append(exc)
        return out
    results: list[R | Exception] = [None] * len(items)  # type: ignore[list-item]
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="bizagent-llm") as pool:
        futures = {pool.submit(fn, item): index for index, item in enumerate(items)}
        for future, index in futures.items():
            try:
                results[index] = future.result()
            except Exception as exc:  # returned, not raised: order-preserving
                results[index] = exc
    return results
