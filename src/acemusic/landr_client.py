"""HTTP client for the LANDR B2B Music Mastering API (US-12.3).

LANDR is the first fallback mastering backend alongside Dolby.io (US-12.2). It
mirrors the conventions of the other external clients in this package:
synchronous :mod:`httpx` (the job processor calls it from a worker thread via
``asyncio.to_thread``), module-level timeouts, a single :class:`LandrError` for
every failure mode, and RunPod-style exponential-backoff retries on transient
(5xx / network) errors while 4xx auth/validation errors fail fast.

It implements the shared :class:`~acemusic.mastering_protocol.MasteringService`
contract: a single :meth:`LandrClient.master` entrypoint drives the full
upload -> submit -> poll -> download workflow and returns a normalized
:class:`~acemusic.mastering_protocol.MasteringOutput`, so the mastering
orchestrator can treat it interchangeably with Dolby.io and Bakuage.

.. note::

   LANDR's B2B REST API is partnership-gated, so the endpoint shapes below
   encode the contract this client assumes (auth token, two-step upload to a
   presigned URL, job submission with loudness/style, status polling, download
   with redirect handling). They follow LANDR's published B2B model (REST,
   genre-aware processing, three loudness tiers, multiple mastering styles) per
   ``ai-music-spec.md`` §41.2.2. A live integration swaps these constants for
   the partnership's documented URLs without changing the workflow.
"""

from __future__ import annotations

import random
import time
from typing import Any, Callable

import httpx

from acemusic.mastering_protocol import MasteringError, MasteringOutput

# LANDR B2B API (assumed partnership-gated surface, per spec §41.2.2).
_BASE_URL = "https://api.landr.com/v1"
_AUTH_URL = f"{_BASE_URL}/auth/token"
_UPLOAD_URL = f"{_BASE_URL}/uploads"
_MASTERS_URL = f"{_BASE_URL}/masters"

# Token lifetime requested from LANDR (30 min) and the buffer before expiry at
# which we proactively refresh, mirroring the Dolby client.
_TOKEN_LIFETIME_S = 1800
_TOKEN_EXPIRY_BUFFER_S = 60.0

# Retry policy for transient (5xx) responses, matching Dolby/RunPod.
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0
_BACKOFF_JITTER = 0.5

# Auth/JSON calls are quick; upload and download stream whole audio files.
_AUTH_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
_API_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)
_UPLOAD_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=300.0, pool=10.0)
_DOWNLOAD_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0)

# Internal mastering profile -> LANDR loudness tier + style preset. LANDR exposes
# three loudness settings and multiple mastering styles (spec §41.2.2); this maps
# the platform profile vocabulary onto LANDR's parameters. ``custom`` defers to
# the resolved target_lufs and carries it through explicitly.
_PROFILE_LOUDNESS = {
    "streaming": "low",
    "soundcloud": "medium",
    "club": "high",
    "vinyl": "low",
}
_PROFILE_STYLE = {
    "streaming": "universal",
    "soundcloud": "warm",
    "club": "club",
    "vinyl": "vinyl",
}
_DEFAULT_LOUDNESS = "low"
_DEFAULT_STYLE = "universal"

# LANDR reports job state under these lower-cased strings; anything else is
# treated as still-running so the poll loop keeps waiting until its timeout.
_SUCCESS_STATES = {"completed", "success"}
_FAILURE_STATES = {"failed", "cancelled", "error"}


class LandrError(MasteringError):
    """Raised when the LANDR API returns an error or is unreachable.

    Subclasses :class:`~acemusic.mastering_protocol.MasteringError` so the
    orchestrator can fall back to the next service on any LANDR failure.
    """


def landr_master_params(profile: str, target_lufs: float, output_format: str) -> dict[str, Any]:
    """Map the platform profile onto LANDR's loudness/style/output parameters.

    ``custom`` carries the resolved ``target_lufs`` explicitly (LANDR applies the
    exact loudness target). Kept a free function so the handler/tests can compose
    and assert the mapping without the client.
    """
    params: dict[str, Any] = {
        "loudness": _PROFILE_LOUDNESS.get(profile, _DEFAULT_LOUDNESS),
        "style": _PROFILE_STYLE.get(profile, _DEFAULT_STYLE),
        "output_format": output_format,
    }
    if profile == "custom":
        params["target_lufs"] = float(target_lufs)
    return params


def _backoff_delay(attempt: int) -> float:
    """Exponential backoff (1s, 2s, 4s …) plus jitter for the given retry attempt."""
    return _BACKOFF_BASE * (2**attempt) + random.uniform(0, _BACKOFF_JITTER)


def _as_float(value: Any) -> float | None:
    """Best-effort float coercion for a metric value, or None when absent/garbage."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class LandrClient:
    """Synchronous client for the LANDR B2B Music Mastering workflow."""

    # Canonical service name used for dispatch and result attribution (US-12.3).
    service = "landr"

    def __init__(self, api_key: str, api_secret: str) -> None:
        """Initialise with the LANDR B2B key/secret used to mint session tokens."""
        self.api_key = api_key
        self.api_secret = api_secret
        self._token: str | None = None
        self._token_expiry: float = 0.0

    # -- auth --------------------------------------------------------------

    def _get_token(self) -> str:
        """Return a valid bearer token, refreshing it when missing or near expiry."""
        now = time.monotonic()
        if self._token is not None and now < self._token_expiry - _TOKEN_EXPIRY_BUFFER_S:
            return self._token
        try:
            response = httpx.post(
                _AUTH_URL,
                auth=(self.api_key, self.api_secret),
                data={"grant_type": "client_credentials", "expires_in": _TOKEN_LIFETIME_S},
                timeout=_AUTH_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise LandrError(f"LANDR authentication failed: {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise LandrError(f"LANDR authentication failed: {exc}") from exc
        except ValueError as exc:
            raise LandrError("LANDR authentication failed: invalid JSON response") from exc

        token = payload.get("access_token") if isinstance(payload, dict) else None
        if not token:
            raise LandrError("LANDR authentication failed: response contains no access_token")
        raw_expires = _as_float(payload.get("expires_in"))
        expires_in = raw_expires if raw_expires is not None and raw_expires > 0 else float(_TOKEN_LIFETIME_S)
        self._token = str(token)
        self._token_expiry = now + expires_in
        return self._token

    def _auth_headers(self) -> dict[str, str]:
        """Bearer auth header carrying a fresh-enough token."""
        return {"Authorization": f"Bearer {self._get_token()}"}

    # -- transport ---------------------------------------------------------

    def _send_with_retry(
        self,
        method: Callable[..., httpx.Response],
        url: str,
        *,
        timeout: httpx.Timeout | float,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Issue an HTTP request, retrying on 5xx with exponential backoff."""
        request_headers = self._auth_headers() if headers is None else headers
        response = None
        for attempt in range(_MAX_RETRIES + 1):
            response = method(url, headers=request_headers, timeout=timeout, **kwargs)
            if response.status_code >= 500 and attempt < _MAX_RETRIES:
                time.sleep(_backoff_delay(attempt))
                continue
            return response
        return response  # pragma: no cover - loop always returns on the last attempt

    # -- upload ------------------------------------------------------------

    def upload(self, audio_bytes: bytes, filename: str) -> str:
        """Upload ``audio_bytes`` to LANDR, returning the LANDR audio id.

        Two-step presigned workflow: ask ``POST /uploads`` for a presigned PUT URL
        and an audio id, then PUT the bytes to the presigned URL (no bearer token).
        """
        try:
            response = self._send_with_retry(httpx.post, _UPLOAD_URL, json={"filename": filename}, timeout=_API_TIMEOUT)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise LandrError(f"LANDR upload request failed: {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise LandrError(f"LANDR upload request failed: {exc}") from exc
        except ValueError as exc:
            raise LandrError("LANDR upload request failed: invalid JSON response") from exc

        presigned_url = payload.get("upload_url") if isinstance(payload, dict) else None
        audio_id = payload.get("audio_id") if isinstance(payload, dict) else None
        if not audio_id:
            raise LandrError("LANDR upload request failed: response contains no audio_id")
        if not presigned_url:
            raise LandrError("LANDR upload request failed: response contains no upload_url")

        try:
            put = self._send_with_retry(
                httpx.put, presigned_url, content=audio_bytes, timeout=_UPLOAD_TIMEOUT, headers={}
            )
            put.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise LandrError(f"LANDR upload failed: {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise LandrError(f"LANDR upload failed: {exc}") from exc
        return str(audio_id)

    # -- submission --------------------------------------------------------

    def submit(self, audio_id: str, profile: str, target_lufs: float, output_format: str) -> str:
        """Submit a LANDR mastering job and return its ``job_id``."""
        body = {"audio_id": audio_id, **landr_master_params(profile, target_lufs, output_format)}
        try:
            response = self._send_with_retry(httpx.post, _MASTERS_URL, json=body, timeout=_API_TIMEOUT)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise LandrError(f"LANDR submission failed: {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise LandrError(f"LANDR submission failed: {exc}") from exc
        except ValueError as exc:
            raise LandrError("LANDR submission failed: invalid JSON response") from exc

        job_id = payload.get("job_id") if isinstance(payload, dict) else None
        if not job_id:
            raise LandrError("LANDR submission failed: response contains no job_id")
        return str(job_id)

    # -- polling -----------------------------------------------------------

    def get_status(self, job_id: str) -> dict[str, Any]:
        """Fetch the current state of LANDR job ``job_id`` with a normalised status."""
        try:
            response = self._send_with_retry(httpx.get, f"{_MASTERS_URL}/{job_id}", timeout=_API_TIMEOUT)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise LandrError(f"LANDR status check failed: {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise LandrError(f"LANDR status check failed: {exc}") from exc
        except ValueError as exc:
            raise LandrError("LANDR status check failed: invalid JSON response") from exc
        if not isinstance(payload, dict):
            raise LandrError("LANDR status check failed: unexpected response payload")
        payload["status"] = str(payload.get("status", "")).lower()
        payload["progress"] = _as_float(payload.get("progress")) or 0.0
        return payload

    def wait_for_completion(self, job_id: str, timeout: float = 600.0, poll_interval: float = 2.0) -> dict[str, Any]:
        """Poll ``job_id`` until it succeeds, returning the final status payload."""
        deadline = time.monotonic() + timeout
        interval = poll_interval
        while True:
            status_payload = self.get_status(job_id)
            state = status_payload["status"]
            if state in _SUCCESS_STATES:
                return status_payload
            if state in _FAILURE_STATES:
                detail = status_payload.get("error") or state
                raise LandrError(f"LANDR mastering job {job_id} failed: {detail}")
            if time.monotonic() >= deadline:
                raise LandrError(f"LANDR mastering job {job_id} timed out after {timeout:.0f}s")
            time.sleep(interval)
            interval = min(interval * 2, 30.0)

    # -- download ----------------------------------------------------------

    def download(self, job_id: str) -> bytes:
        """Download the mastered audio for ``job_id`` from LANDR.

        ``GET /masters/{id}/download`` either streams the bytes directly or
        redirects to a pre-authorized CDN URL; a redirect is followed manually
        with *no* bearer header so the token never reaches the CDN host.
        """
        try:
            response = self._send_with_retry(
                httpx.get,
                f"{_MASTERS_URL}/{job_id}/download",
                timeout=_DOWNLOAD_TIMEOUT,
                follow_redirects=False,
            )
            if response.is_redirect and response.headers.get("location"):
                response = self._send_with_retry(
                    httpx.get,
                    response.headers["location"],
                    timeout=_DOWNLOAD_TIMEOUT,
                    headers={},
                    follow_redirects=True,
                )
            response.raise_for_status()
            return response.content
        except httpx.HTTPStatusError as exc:
            raise LandrError(f"LANDR download failed: {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise LandrError(f"LANDR download failed: {exc}") from exc

    # -- high-level entrypoint (US-12.3 shared interface) -----------------

    def master(
        self,
        audio_bytes: bytes,
        filename: str,
        profile: str,
        target_lufs: float,
        output_format: str,
        timeout: float | None = None,
    ) -> MasteringOutput:
        """Run the full LANDR mastering workflow and return a normalized output.

        Wraps upload -> submit -> poll -> download behind the single
        :meth:`~acemusic.mastering_protocol.MasteringService.master` entrypoint.
        LANDR reports fewer metrics than Dolby (loudness, optional EQ); the
        metrics dict is built defensively so missing fields degrade to ``None``
        rather than raising. ``timeout`` caps the poll phase (defaults to 600s).
        """
        audio_id = self.upload(audio_bytes, filename)
        job_id = self.submit(audio_id, profile, target_lufs, output_format)
        status_payload = self.wait_for_completion(job_id, timeout=timeout if timeout is not None else 600.0)
        audio = self.download(job_id)
        return MasteringOutput(audio_bytes=audio, metrics=_parse_metrics(status_payload), service=self.service)


def _parse_metrics(status_payload: dict[str, Any]) -> dict[str, Any]:
    """Extract the loudness / EQ metrics LANDR reports, defensively.

    LANDR nests analysis under ``result``; fields are optional, so missing values
    degrade to ``None`` / empty to match the shared metrics shape.
    """
    result = status_payload.get("result")
    result = result if isinstance(result, dict) else {}
    raw_bands = result.get("eq_bands") if isinstance(result.get("eq_bands"), list) else []
    eq_bands = [band for band in (_as_float(v) for v in raw_bands) if band is not None]
    return {
        "loudness": _as_float(result.get("loudness_lufs")),
        "eq_bands": eq_bands,
        # LANDR does not report stereo-image analysis; keep the shared shape.
        "stereo": {"width": None, "balance": None},
    }
