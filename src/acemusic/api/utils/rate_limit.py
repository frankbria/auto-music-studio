"""In-memory per-client rate limiting for the streaming endpoint (US-14.2).

A fixed-window counter keyed by client IP. Deliberately tiny and dependency-free:
the public ``/clips/{id}/stream`` endpoint only needs a single-process ceiling to
curb abuse. Swap for a Redis-backed limiter (e.g. slowapi) if the API ever runs
multiple workers that must share one limit.
"""

import time
from threading import Lock

from fastapi import HTTPException, Request, status


class FixedWindowRateLimiter:
    """Count requests per key within fixed wall-clock windows; reject over the cap."""

    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        self._limit = limit
        self._window = window_seconds
        self._hits: dict[str, tuple[float, int]] = {}
        self._lock = Lock()

    def check(self, key: str) -> None:
        """Record one hit for ``key``; raise 429 once it exceeds the limit."""
        now = time.monotonic()
        with self._lock:
            window_start, count = self._hits.get(key, (now, 0))
            if now - window_start >= self._window:  # window elapsed — reset
                window_start, count = now, 0
            count += 1
            self._hits[key] = (window_start, count)
            if count > self._limit:
                retry_after = max(1, int(self._window - (now - window_start)))
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many streaming requests; slow down.",
                    headers={"Retry-After": str(retry_after)},
                )


def _client_key(request: Request) -> str:
    # ponytail: keyed by the raw socket peer IP. Behind a trusted reverse proxy,
    # parse a validated X-Forwarded-For here — spoofable headers are intentionally
    # not trusted by default.
    return request.client.host if request.client else "anonymous"


def enforce_stream_rate_limit(request: Request) -> None:
    """FastAPI dependency: rate-limit by client IP using the app's limiter."""
    limiter: FixedWindowRateLimiter = request.app.state.stream_limiter
    limiter.check(_client_key(request))
