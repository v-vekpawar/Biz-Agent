"""Tiny in-process sliding-window rate limiter (single-worker deployments).

Good enough to blunt password guessing and signup spam on a one-process
deployment. For multi-worker hosting, put a shared limiter (reverse proxy or
Redis) in front instead.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from . import config

_lock = threading.Lock()
_hits: dict[str, deque] = defaultdict(deque)


def client_ip(request: Request) -> str:
    if config.trust_proxy_headers():
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def reset() -> None:
    with _lock:
        _hits.clear()


def limit(name: str, max_calls, window_seconds: int):
    """FastAPI dependency factory: at most `max_calls` (int or zero-arg callable, read per
    request so env changes apply) per `window_seconds` per client IP."""

    def dependency(request: Request) -> None:
        if not config.rate_limit_enabled():
            return
        key = f"{name}:{client_ip(request)}"
        now = time.monotonic()
        with _lock:
            q = _hits[key]
            while q and now - q[0] > window_seconds:
                q.popleft()
            if len(q) >= (max_calls() if callable(max_calls) else max_calls):
                retry = max(1, int(window_seconds - (now - q[0])))
                raise HTTPException(
                    status_code=429,
                    detail="Too many requests. Try again shortly.",
                    headers={"Retry-After": str(retry)},
                )
            q.append(now)

    return dependency
