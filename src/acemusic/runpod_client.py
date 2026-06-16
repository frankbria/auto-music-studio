"""HTTP client for RunPod serverless endpoints (US-11.2).

Drives remote GPU generation on a RunPod serverless endpoint running the ACE-Step
worker image (US-11.3). The endpoint's API contract:

- POST ``/run``                 → submit a job; response ``{"id": ..., "status": ...}``
- GET  ``/status/{job_id}``     → poll job status; ``{"status": "IN_QUEUE" | "IN_PROGRESS"
                                   | "COMPLETED" | "FAILED" | ..., "output": ..., "error": ...}``
- GET  ``/health``              → endpoint readiness (used by the routing engine)

The client deliberately mirrors :class:`acemusic.client.AceStepClient`'s *consumer*
interface (``submit_task`` / ``query_result`` / ``download_audio``) and its normalised
``query_result`` return shape so the job processor's existing poll-and-store helpers
work against either backend unchanged. Status values are normalised to the same
``"pending" | "completed" | "failed"`` vocabulary the processor already understands.

Transient server errors (HTTP 5xx) are retried inside the client with exponential
backoff so the processor stays unaware of retry mechanics. 4xx errors fail fast.
"""

from __future__ import annotations

import random
import time
from typing import Any, Callable

import httpx

# Retry policy for transient (5xx) responses. ``_MAX_RETRIES`` retries follow the
# initial attempt, so a persistently-failing endpoint is hit up to 4 times. Delays
# grow as base * 2**attempt (1s, 2s, 4s) with added jitter to avoid synchronised
# retry storms when many jobs poll at once.
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0
_BACKOFF_JITTER = 0.5

# RunPod serverless states normalised onto the processor's status vocabulary. Any
# unknown state is treated as still-pending so the poll loop keeps waiting (and is
# eventually capped by the caller's timeout) rather than failing on a new state.
_STATUS_MAP = {
    "in_queue": "pending",
    "in_progress": "pending",
    "completed": "completed",
    "failed": "failed",
    "cancelled": "failed",
    "timed_out": "failed",
}

DEFAULT_BASE_URL = "https://api.runpod.ai/v2"


class RunPodError(Exception):
    """Raised when the RunPod API returns an error or is unreachable."""


class RunPodConnectionError(RunPodError):
    """Transport-level failure (connection refused, DNS failure, timeout).

    Distinct from API/HTTP-status errors so callers can tell a transient network
    issue from a real server-side error. ``is_timeout`` is True only for a *read*
    timeout — the connection was established but the server was slow to respond
    (e.g. a cold start spinning up a serverless worker). Connect timeouts and
    refused/DNS failures leave it False so an unreachable host still fast-fails.
    """

    def __init__(self, message: str, *, is_timeout: bool = False) -> None:
        super().__init__(message)
        self.is_timeout = is_timeout


def _backoff_delay(attempt: int) -> float:
    """Exponential backoff (1s, 2s, 4s …) plus jitter for the given retry attempt."""
    return _BACKOFF_BASE * (2**attempt) + random.uniform(0, _BACKOFF_JITTER)


class RunPodClient:
    """Reusable HTTP client for a RunPod serverless endpoint."""

    def __init__(self, endpoint_id: str, api_key: str, base_url: str = DEFAULT_BASE_URL) -> None:
        """Initialise the client for ``endpoint_id`` authenticated with ``api_key``."""
        self.endpoint_id = endpoint_id
        self.base_url = f"{base_url.rstrip('/')}/{endpoint_id}"
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def _send_with_retry(
        self,
        method: Callable[..., httpx.Response],
        url: str,
        *,
        timeout: float,
        headers: dict | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Issue an HTTP request, retrying on 5xx with exponential backoff.

        Returns the response untouched (the caller decides how to interpret a
        non-5xx status, e.g. ``raise_for_status`` for a 4xx). Connection errors are
        not retried — they propagate so the caller maps them to
        :class:`RunPodConnectionError`. A 5xx that persists past the retry budget is
        returned so the caller surfaces it as a :class:`RunPodError` like any other.

        ``headers`` defaults to the client's auth headers; callers fetching from a
        pre-authorized URL (e.g. a presigned audio URL) pass ``{}`` to avoid leaking
        the RunPod bearer token to an external host.
        """
        request_headers = self._headers if headers is None else headers
        for attempt in range(_MAX_RETRIES + 1):
            response = method(url, headers=request_headers, timeout=timeout, **kwargs)
            if response.status_code >= 500 and attempt < _MAX_RETRIES:
                time.sleep(_backoff_delay(attempt))
                continue
            return response
        return response  # pragma: no cover - loop always returns on the last attempt

    def submit(self, input_params: dict, timeout: float = 30.0) -> str:
        """Submit a job via POST ``/run`` and return the RunPod job id.

        ``input_params`` is wrapped in the serverless ``{"input": ...}`` envelope the
        worker expects.

        Raises:
            RunPodError: on HTTP error or a response missing the job id.
            RunPodConnectionError: on connection failure or timeout.
        """
        try:
            response = self._send_with_retry(
                httpx.post, f"{self.base_url}/run", json={"input": input_params}, timeout=timeout
            )
            response.raise_for_status()
            data = response.json()
            job_id = data.get("id")
            if not job_id:
                raise RunPodError(f"No job id in RunPod response: {data}")
            return job_id
        except httpx.HTTPStatusError as exc:
            raise RunPodError(f"RunPod submit failed: {exc.response.status_code} {exc.response.text}") from exc
        except httpx.RequestError as exc:
            raise RunPodConnectionError(
                f"RunPod submit failed: {exc}", is_timeout=isinstance(exc, httpx.ReadTimeout)
            ) from exc

    def submit_task(self, **kwargs: Any) -> str:
        """Alias matching :meth:`AceStepClient.submit_task` so the processor can treat
        both backends uniformly: the keyword generation params become the RunPod input."""
        return self.submit(kwargs)

    def query_result(self, job_id: str, timeout: float = 10.0) -> dict:
        """Poll GET ``/status/{job_id}`` and return a normalised result dict.

        Returns:
            dict with keys (mirroring :meth:`AceStepClient.query_result`):
              - status: "pending" | "completed" | "failed"
              - audio_urls: list of audio URLs (empty until completed)
              - error: error message string or None

        Transient 5xx responses are retried with backoff before failing.

        Raises:
            RunPodError: on a 4xx, or a 5xx that survives the retry budget.
            RunPodConnectionError: on connection failure or timeout.
        """
        try:
            response = self._send_with_retry(httpx.get, f"{self.base_url}/status/{job_id}", timeout=timeout)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            raise RunPodError(f"RunPod status failed: {exc.response.status_code} {exc.response.text}") from exc
        except httpx.RequestError as exc:
            raise RunPodConnectionError(
                f"RunPod status failed: {exc}", is_timeout=isinstance(exc, httpx.ReadTimeout)
            ) from exc

        status = _STATUS_MAP.get(str(data.get("status", "")).lower(), "pending")
        error = data.get("error")
        audio_urls = _extract_audio_urls(data.get("output")) if status == "completed" else []
        return {"status": status, "audio_urls": audio_urls, "error": error}

    def download_audio(self, url: str, timeout: float = 120.0) -> bytes:
        """Download raw audio bytes from a URL.

        Transient 5xx responses are retried like the other operations — an audio-CDN
        blip is as recoverable as a status-poll transient. No auth header is sent: the
        URL comes from RunPod's own output and is already pre-authorized (typically a
        presigned/public URL), so attaching the bearer token would only risk leaking
        it to an external host.

        Raises:
            RunPodError: on HTTP error.
            RunPodConnectionError: on connection failure or timeout.
        """
        try:
            response = self._send_with_retry(httpx.get, url, timeout=timeout, headers={}, follow_redirects=True)
            response.raise_for_status()
            return response.content
        except httpx.HTTPStatusError as exc:
            raise RunPodError(f"RunPod download failed: {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise RunPodConnectionError(
                f"RunPod download failed: {exc}", is_timeout=isinstance(exc, httpx.ReadTimeout)
            ) from exc

    def health(self, timeout: float = 5.0) -> bool:
        """Return ``True`` if GET ``/health`` answers with a 2xx.

        Used by the routing engine as a readiness probe, so any connection error or
        non-2xx counts as unavailable rather than raising — remote routing degrades
        to fallback/503 instead of surfacing a 500.
        """
        try:
            response = httpx.get(f"{self.base_url}/health", headers=self._headers, timeout=timeout)
        except httpx.RequestError:
            return False
        return response.is_success


def _extract_audio_urls(output: Any) -> list[str]:
    """Pull audio URLs out of a RunPod ``output`` payload.

    The worker (US-11.3) is not built yet, so this accepts the shapes it is most
    likely to emit: a bare list of URLs, a list of ``{"url"|"file"|"audio_url": ...}``
    objects, or a dict carrying any of those under ``audio_urls``/``clips``/``outputs``.
    """
    if not output:
        return []
    if isinstance(output, dict):
        direct = output.get("audio_urls")
        if isinstance(direct, list):
            return [url for url in direct if url]
        for key in ("clips", "outputs", "output"):
            nested = output.get(key)
            if isinstance(nested, list):
                return _urls_from_list(nested)
        return []
    if isinstance(output, list):
        return _urls_from_list(output)
    return []


def _urls_from_list(items: list) -> list[str]:
    """Extract URL strings from a list of either plain strings or url-bearing dicts."""
    urls: list[str] = []
    for item in items:
        if isinstance(item, str) and item:
            urls.append(item)
        elif isinstance(item, dict):
            url = item.get("url") or item.get("file") or item.get("audio_url")
            if url:
                urls.append(url)
    return urls
