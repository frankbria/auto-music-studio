"""HTTP client for the external AI video generation provider (US-22.1).

The platform submits a source song plus a visual prompt/options to a hosted
video-rendering API (Runway/Pika-class), polls the job to completion, and
downloads the rendered MP4 (audio muxed in by the provider). No provider
credentials exist in this environment, so — like ``dolby_client`` before its
live verification — the request/response shape is provider-generic: base URL
and bearer key come from settings, and the three-call workflow
(``submit`` -> ``get_status`` -> ``download``) is the contract the job handler
programs against via the :class:`VideoGenerationService` protocol.

Conventions mirror the other external clients: synchronous :mod:`httpx` (the
job processor calls it from a worker thread via ``asyncio.to_thread``),
module-level timeouts, one exception type, and the shared :mod:`acemusic._http`
transient-retry policy (up to 3 retries with backoff on 5xx — the story's
"retry up to 3 attempts on transient provider failure").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from acemusic import _http

# Submit uploads a whole song; download streams a whole video.
_API_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=300.0, pool=10.0)
_DOWNLOAD_TIMEOUT = httpx.Timeout(connect=10.0, read=600.0, write=10.0, pool=10.0)

# The platform's rendering-state vocabulary (US-22.1):
# queued -> rendering -> encoding -> complete | failed.
# Provider spellings are normalised onto it; anything unrecognised is treated as
# still-rendering so the poll loop keeps waiting until its timeout.
COMPLETE = "complete"
FAILED = "failed"
_STATE_ALIASES = {
    "queued": "queued",
    "pending": "queued",
    "rendering": "rendering",
    "processing": "rendering",
    "running": "rendering",
    "encoding": "encoding",
    "complete": COMPLETE,
    "completed": COMPLETE,
    "succeeded": COMPLETE,
    "success": COMPLETE,
    "failed": FAILED,
    "error": FAILED,
    "cancelled": FAILED,
}


class VideoGenerationError(Exception):
    """Raised when the video provider returns an error or is unreachable."""


@dataclass(frozen=True)
class VideoJobUpdate:
    """One poll of a provider job: normalised state, progress %, ETA, error."""

    state: str
    progress: int | None = None
    eta_seconds: float | None = None
    error: str | None = None


class VideoGenerationService(Protocol):
    """The three-call rendering workflow the job handler programs against."""

    def submit(self, audio_bytes: bytes, filename: str, params: dict[str, Any]) -> str:
        """Upload the song and create a rendering job; returns the provider job id."""
        ...

    def get_status(self, provider_job_id: str) -> VideoJobUpdate:
        """One status poll for a submitted job."""
        ...

    def download(self, provider_job_id: str) -> bytes:
        """Download the completed job's rendered MP4."""
        ...


def normalize_state(raw: object) -> str:
    """Map a provider status string onto the platform vocabulary."""
    return _STATE_ALIASES.get(str(raw).strip().lower(), "rendering")


def _as_int(value: Any) -> int | None:
    """Best-effort int coercion for a progress value, or None when absent/garbage."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    """Best-effort float coercion for an ETA value, or None when absent/garbage."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class HttpVideoClient:
    """Synchronous client for the hosted video-generation REST workflow."""

    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def submit(self, audio_bytes: bytes, filename: str, params: dict[str, Any]) -> str:
        """POST the song + rendering options; returns the provider's job id."""
        files = {"audio_file": (filename, audio_bytes)}
        # Multipart form fields are strings; lists (reference image URLs) repeat the key.
        data: dict[str, Any] = {}
        for key, value in params.items():
            if value is None:
                continue
            data[key] = [str(v) for v in value] if isinstance(value, list) else str(value)
        # retries=0: submission creates a billed render on the provider. A 5xx
        # after the provider accepted the job would mean an auto-retry creates
        # (and pays for) duplicate renders — mirrors image_client's policy.
        response = self._request(
            httpx.post, f"{self.base_url}/jobs", files=files, data=data, timeout=_API_TIMEOUT, retries=0
        )
        job_id = self._json(response).get("id")
        if not job_id:
            raise VideoGenerationError("Video provider returned no job id")
        return str(job_id)

    def get_status(self, provider_job_id: str) -> VideoJobUpdate:
        """GET the job's state, progress percentage, and estimated time remaining."""
        response = self._request(httpx.get, f"{self.base_url}/jobs/{provider_job_id}", timeout=_API_TIMEOUT)
        payload = self._json(response)
        return VideoJobUpdate(
            state=normalize_state(payload.get("status")),
            progress=_as_int(payload.get("progress")),
            eta_seconds=_as_float(payload.get("eta_seconds")),
            error=payload.get("error"),
        )

    def download(self, provider_job_id: str) -> bytes:
        """GET the completed job's rendered MP4 bytes."""
        response = self._request(httpx.get, f"{self.base_url}/jobs/{provider_job_id}/result", timeout=_DOWNLOAD_TIMEOUT)
        if not response.content:
            raise VideoGenerationError("Video provider returned an empty result")
        return response.content

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        """Parse a JSON body, wrapping a non-JSON 200 (e.g. an HTML error page)."""
        try:
            payload = response.json()
        except ValueError as exc:
            raise VideoGenerationError("Video provider returned a non-JSON response") from exc
        if not isinstance(payload, dict):
            raise VideoGenerationError("Video provider returned an unexpected JSON shape")
        return payload

    def _request(self, method: Any, url: str, **kwargs: Any) -> httpx.Response:
        """Issue one call through the shared 5xx-retry policy, wrapping failures."""
        try:
            response = _http.request(method, url, headers=self._headers, **kwargs)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise VideoGenerationError(f"Video provider returned {exc.response.status_code} for {url}") from exc
        except httpx.HTTPError as exc:
            raise VideoGenerationError(f"Video provider request failed for {url}: {exc}") from exc
        return response
