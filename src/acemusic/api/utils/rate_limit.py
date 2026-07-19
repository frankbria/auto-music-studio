"""In-memory per-client rate limiting for the streaming endpoint (US-14.2).

A fixed-window counter keyed by client IP. Deliberately tiny and dependency-free:
the public ``/clips/{id}/stream`` endpoint only needs a single-process ceiling to
curb abuse. Swap for a Redis-backed limiter (e.g. slowapi) if the API ever runs
multiple workers that must share one limit.
"""

import ipaddress
import time
from collections.abc import Collection
from threading import Lock

from fastapi import HTTPException, Request, status


def _normalize_ip(value: str) -> str:
    """Canonicalize an IP so an IPv4-mapped form (``::ffff:127.0.0.1``) compares
    equal to its plain IPv4 (``127.0.0.1``); pass non-IP values (``"anonymous"``,
    a hostname) through raw."""
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return value
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return str(ip.ipv4_mapped)
    return str(ip)


class FixedWindowRateLimiter:
    """Count requests per key within fixed wall-clock windows; reject over the cap."""

    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        self._limit = limit
        self._window = window_seconds
        self._hits: dict[str, tuple[float, int]] = {}
        self._last_prune = 0.0
        self._lock = Lock()

    def check(self, key: str) -> None:
        """Record one hit for ``key``; raise 429 once it exceeds the limit."""
        now = time.monotonic()
        with self._lock:
            # A public endpoint sees many one-off IPs; without pruning, _hits
            # grows unbounded. Sweep expired windows at most once per window.
            if now - self._last_prune >= self._window:
                cutoff = now - self._window
                self._hits = {k: v for k, v in self._hits.items() if v[0] > cutoff}
                self._last_prune = now
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


def _client_key(request: Request, trusted_proxies: Collection[str]) -> str:
    """Rate-limit key: the real client IP.

    Keyed by the raw socket peer IP, except when that peer is a configured
    trusted proxy (#283): a same-origin BFF proxies every visitor server-side,
    so they'd all share the proxy's egress IP. When the peer is trusted, key on
    the client it forwarded in ``X-Forwarded-For`` (leftmost = original client)
    instead.

    The header is honored *only* when the immediate peer is trusted, so a
    directly reachable backend can't be evaded by a spoofed header (AC2/AC3).
    The forwarded *value* is only as trustworthy as that proxy: the trusted
    proxy MUST set/replace ``X-Forwarded-For`` with the real client and not pass
    through a client-supplied one — otherwise a client could still choose its
    own key. That sanitizing is a property of the deployment's edge, not of this
    function; see ``ACEMUSIC_API_TRUSTED_PROXIES`` in ``.env.example``.
    """
    peer = _normalize_ip(request.client.host) if request.client else "anonymous"
    trusted = {_normalize_ip(ip) for ip in trusted_proxies}
    if peer in trusted:
        forwarded = request.headers.get("x-forwarded-for", "")
        client = forwarded.split(",")[0].strip()
        if client:
            # Normalize like the peer so an edge that emits both ::ffff:1.1.1.1
            # and 1.1.1.1 for one visitor keys a single bucket, not two.
            return _normalize_ip(client)
    return peer


def enforce_stream_rate_limit(request: Request) -> None:
    """FastAPI dependency: rate-limit by client IP using the app's limiter."""
    limiter: FixedWindowRateLimiter = request.app.state.stream_limiter
    trusted = request.app.state.settings.trusted_proxy_set
    limiter.check(_client_key(request, trusted))
