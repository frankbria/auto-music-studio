"""HTTP client for the Bakuage (AI Mastering) REST API (US-12.3).

Bakuage is the cost-effective fallback mastering backend (the end of the
Dolby -> LANDR -> Bakuage chain). Unlike Dolby and LANDR it exposes a simpler
open REST API (spec §41.2.3: base ``https://api.bakuage.com:443``, bearer-token
auth) with no OAuth token dance: the API key is sent directly as a bearer header
on every call, and a single ``POST /masterings`` request uploads the audio and
creates the job.

It mirrors the conventions of the other external clients: synchronous
:mod:`httpx` (the job processor calls it from a worker thread via
``asyncio.to_thread``), module-level timeouts, a single :class:`BakuageError`
for every failure mode, and exponential-backoff retries on transient (5xx /
network) errors while 4xx auth/validation errors fail fast.

It implements the shared :class:`~acemusic.mastering_protocol.MasteringService`
contract: :meth:`BakuageClient.master` drives create -> poll -> download and
returns a normalized :class:`~acemusic.mastering_protocol.MasteringOutput`.
Bakuage reports fewer metrics than Dolby (loudness, no 16-band EQ or stereo
analysis), so optional fields degrade to ``None`` to keep the shared shape.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from acemusic import _http
from acemusic.mastering_protocol import MasteringError, MasteringOutput

# Bakuage AI Mastering open REST API (spec §41.2.3).
_BASE_URL = "https://api.bakuage.com:443/v1"
_MASTERS_URL = f"{_BASE_URL}/masterings"

# Create/poll calls are quick; download streams a whole audio file.
_API_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=120.0, pool=10.0)
_DOWNLOAD_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0)

# Internal mastering profile -> Bakuage mastering level. Bakuage exposes a
# mastering-level parameter; this maps the platform profile vocabulary onto it.
# ``custom`` defers to the resolved target_lufs and carries it through explicitly.
_PROFILE_LEVEL = {
    "streaming": "low",
    "soundcloud": "medium",
    "club": "high",
    "vinyl": "low",
}
_DEFAULT_LEVEL = "low"

# Bakuage reports job state under these lower-cased strings; anything else is
# treated as still-running so the poll loop keeps waiting until its timeout.
_SUCCESS_STATES = {"completed", "success"}
_FAILURE_STATES = {"failed", "cancelled", "error"}


class BakuageError(MasteringError):
    """Raised when the Bakuage API returns an error or is unreachable.

    Subclasses :class:`~acemusic.mastering_protocol.MasteringError` so the
    orchestrator can fall back (or report the final failure) on any Bakuage error.
    """


def bakuage_master_params(profile: str, target_lufs: float, output_format: str) -> dict[str, Any]:
    """Map the platform profile onto Bakuage's mastering parameters."""
    params: dict[str, Any] = {
        "mastering_level": _PROFILE_LEVEL.get(profile, _DEFAULT_LEVEL),
        "output_format": output_format,
    }
    if profile == "custom":
        params["target_lufs"] = float(target_lufs)
    return params


def _as_float(value: Any) -> float | None:
    """Best-effort float coercion for a metric value, or None when absent/garbage."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class BakuageClient:
    """Synchronous client for the Bakuage AI Mastering REST workflow."""

    # Canonical service name used for dispatch and result attribution (US-12.3).
    service = "bakuage"

    def __init__(self, api_key: str) -> None:
        """Initialise with the Bakuage API key (sent as a bearer header)."""
        self.api_key = api_key
        self._headers = {"Authorization": f"Bearer {api_key}"}

    # -- create mastering --------------------------------------------------

    def create_mastering(
        self,
        audio_bytes: bytes,
        filename: str,
        profile: str,
        target_lufs: float,
        output_format: str,
    ) -> str:
        """Upload ``audio_bytes`` and create a Bakuage mastering job, returning its id.

        Bakuage combines upload + job creation in one ``POST /masterings`` request
        (multipart form carrying the audio and the mastering parameters).
        """
        params = bakuage_master_params(profile, target_lufs, output_format)
        files = {"audio_file": (filename, audio_bytes)}
        data = {k: str(v) for k, v in params.items()}
        try:
            response = _http.request(
                httpx.post, _MASTERS_URL, headers=self._headers, files=files, data=data, timeout=_API_TIMEOUT
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise BakuageError(f"Bakuage create failed: {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise BakuageError(f"Bakuage create failed: {exc}") from exc
        except ValueError as exc:
            raise BakuageError("Bakuage create failed: invalid JSON response") from exc

        job_id = payload.get("id") if isinstance(payload, dict) else None
        if not job_id:
            raise BakuageError("Bakuage create failed: response contains no id")
        return str(job_id)

    # -- polling -----------------------------------------------------------

    def get_status(self, job_id: str) -> dict[str, Any]:
        """Fetch the current state of Bakuage job ``job_id`` with a normalised status."""
        try:
            response = _http.request(httpx.get, f"{_MASTERS_URL}/{job_id}", headers=self._headers, timeout=_API_TIMEOUT)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise BakuageError(f"Bakuage status check failed: {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise BakuageError(f"Bakuage status check failed: {exc}") from exc
        except ValueError as exc:
            raise BakuageError("Bakuage status check failed: invalid JSON response") from exc
        if not isinstance(payload, dict):
            raise BakuageError("Bakuage status check failed: unexpected response payload")
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
                raise BakuageError(f"Bakuage mastering job {job_id} failed: {detail}")
            if time.monotonic() >= deadline:
                raise BakuageError(f"Bakuage mastering job {job_id} timed out after {timeout:.0f}s")
            time.sleep(interval)
            interval = min(interval * 2, 30.0)

    # -- download ----------------------------------------------------------

    def download(self, job_id: str) -> bytes:
        """Download the mastered audio for ``job_id`` from Bakuage.

        ``GET /masterings/{id}/download`` either streams the bytes directly or
        redirects to a pre-authorized CDN URL; a redirect is followed manually
        with *no* bearer header so the token never reaches the CDN host.
        """
        try:
            response = _http.request(
                httpx.get,
                f"{_MASTERS_URL}/{job_id}/download",
                headers=self._headers,
                timeout=_DOWNLOAD_TIMEOUT,
                follow_redirects=False,
            )
            if response.is_redirect and response.headers.get("location"):
                response = _http.request(
                    httpx.get,
                    response.headers["location"],
                    headers={},
                    timeout=_DOWNLOAD_TIMEOUT,
                    follow_redirects=True,
                )
            response.raise_for_status()
            return response.content
        except httpx.HTTPStatusError as exc:
            raise BakuageError(f"Bakuage download failed: {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise BakuageError(f"Bakuage download failed: {exc}") from exc

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
        """Run the full Bakuage mastering workflow and return a normalized output.

        Wraps create -> poll -> download behind the single
        :meth:`~acemusic.mastering_protocol.MasteringService.master` entrypoint.
        Bakuage reports fewer metrics than Dolby (loudness only); the metrics dict
        is built defensively so missing fields degrade to ``None`` / empty.
        ``timeout`` caps the poll phase (defaults to 600s).
        """
        job_id = self.create_mastering(audio_bytes, filename, profile, target_lufs, output_format)
        status_payload = self.wait_for_completion(job_id, timeout=timeout if timeout is not None else 600.0)
        audio = self.download(job_id)
        return MasteringOutput(audio_bytes=audio, metrics=_parse_metrics(status_payload), service=self.service)


def _parse_metrics(status_payload: dict[str, Any]) -> dict[str, Any]:
    """Extract the loudness metric Bakuage reports, defensively.

    Bakuage nests analysis under ``result`` and reports loudness only (no 16-band
    EQ or stereo-image analysis); optional fields degrade to ``None`` / empty to
    match the shared metrics shape used across all three backends.
    """
    result = status_payload.get("result")
    result = result if isinstance(result, dict) else {}
    return {
        "loudness": _as_float(result.get("loudness_lufs")),
        "eq_bands": [],
        "stereo": {"width": None, "balance": None},
    }
