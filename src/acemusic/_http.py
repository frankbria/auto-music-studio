"""Shared HTTP request + retry helper for the backend clients (US-15.3).

The external clients (ACE-Step, RunPod, Dolby, LANDR, Bakuage, ElevenLabs) all
issue synchronous :mod:`httpx` calls with the same transient-error policy: retry
a 5xx response a few times with exponential backoff, but let connection errors
propagate (the caller maps them to its own typed error) and let a 4xx fail fast.
This module is the single home for that policy and the backoff formula so each
client no longer carries its own copy.

The helper returns the raw response — each client keeps its own ``raise_for_status``
+ error-wrapping at the call site, because the error messages and exception types
differ per client/operation.
"""

from __future__ import annotations

import random
import time
from typing import Any, Callable

import httpx

# Retry policy for transient (5xx) responses: the initial attempt plus
# ``MAX_RETRIES`` retries, so a persistently-failing endpoint is hit up to 4
# times. Delays grow as ``base * 2**attempt`` (1s, 2s, 4s) with added jitter to
# avoid synchronised retry storms when many jobs poll at once.
MAX_RETRIES = 3
_BACKOFF_BASE = 1.0
_BACKOFF_JITTER = 0.5


def backoff_delay(attempt: int) -> float:
    """Exponential backoff (1s, 2s, 4s …) plus jitter for the given retry attempt."""
    return _BACKOFF_BASE * (2**attempt) + random.uniform(0, _BACKOFF_JITTER)


def request(
    method: Callable[..., httpx.Response],
    url: str,
    *,
    timeout: httpx.Timeout | float,
    headers: dict | None = None,
    retries: int = MAX_RETRIES,
    **kwargs: Any,
) -> httpx.Response:
    """Issue an HTTP request, retrying on 5xx with exponential backoff.

    Returns the response untouched so the caller decides how to interpret a
    non-5xx status (e.g. ``raise_for_status`` for a 4xx). Connection errors are
    not retried — they propagate so the caller maps them to its own typed error.
    A 5xx that survives the retry budget is returned like any other response so
    the caller surfaces it the same way.

    ``retries`` defaults to :data:`MAX_RETRIES`; pass ``0`` for a single attempt
    (clients that must not auto-retry, e.g. credit-billed generation calls).
    """
    response = None
    for attempt in range(retries + 1):
        response = method(url, headers=headers, timeout=timeout, **kwargs)
        if response.status_code >= 500 and attempt < retries:
            time.sleep(backoff_delay(attempt))
            continue
        return response
    return response  # pragma: no cover - loop always returns on the last attempt
