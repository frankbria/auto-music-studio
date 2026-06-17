"""HTTP client for the Dolby.io Music Mastering API (US-12.2).

Drives the full mastering workflow against Dolby.io's Media APIs:

1. ``POST https://api.dolby.io/v1/auth/token`` — exchange the app key/secret for a
   short-lived bearer token (cached until it nears expiry).
2. ``POST {media}/input`` + ``PUT`` — upload the source audio to Dolby's input
   storage via a presigned URL, yielding a ``dlb://`` handle.
3. ``POST {media}/master/preview`` — submit a master *preview* job with up to five
   output variants.
4. ``GET {media}/master/preview?job_id=…`` — poll until the job reaches a terminal
   state, then read the mastering metrics (loudness / EQ / stereo image).
5. ``GET {media}/output?url=…`` — download each mastered output.

The client mirrors the conventions of the other external clients in this package:
synchronous :mod:`httpx` (the job processor calls it from a worker thread via
``asyncio.to_thread``), module-level timeouts, a single :class:`DolbyError` for
every failure mode, and RunPod-style exponential-backoff retries on transient
(5xx / network) errors while 4xx auth/validation errors fail fast. It carries no
knowledge of our Job/Clip models — the mastering task handler owns that.
"""

from __future__ import annotations

import random
import time
from typing import Any, Callable

import httpx

# Auth lives on api.dolby.io; the Media (mastering/input/output) endpoints live on
# api.dolby.com — two distinct hosts, mirroring Dolby.io's published API surface.
_AUTH_URL = "https://api.dolby.io/v1/auth/token"
_MEDIA_BASE_URL = "https://api.dolby.com/media"

# Token lifetime requested from Dolby (30 min) and the buffer before expiry at
# which we proactively refresh, so a long-running job never sends a token that
# expires mid-flight.
_TOKEN_LIFETIME_S = 1800
_TOKEN_EXPIRY_BUFFER_S = 60.0

# Retry policy for transient (5xx) responses, matching the RunPod client: the
# initial attempt plus ``_MAX_RETRIES`` retries, delays growing as
# ``base * 2**attempt`` (1s, 2s, 4s) with jitter to avoid synchronised retries.
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0
_BACKOFF_JITTER = 0.5

# Dolby caps a single preview submission at five output variants; surface a clear
# client-side error rather than letting the API reject an over-large request.
MAX_PREVIEW_OUTPUTS = 5

# Auth/JSON calls are quick; the upload and download stream whole audio files, so
# they get generous read/write headroom (mirrors the ElevenLabs client's split).
_AUTH_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
_API_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)
_UPLOAD_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=300.0, pool=10.0)
_DOWNLOAD_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0)

# Internal mastering profile -> Dolby ``content.type`` preset. Dolby tailors the
# master to the declared content; every profile here is music, but the mapping is
# the seam where a future profile could target a different Dolby preset.
PROFILE_CONTENT_TYPE = {
    "streaming": "music",
    "soundcloud": "music",
    "club": "music",
    "vinyl": "music",
    "custom": "music",
}
_DEFAULT_CONTENT_TYPE = "music"

# Dolby reports preview job state under these strings; everything else is treated
# as still-running so the poll loop keeps waiting until its own timeout fires.
_SUCCESS_STATES = {"success"}
_FAILURE_STATES = {"failed", "cancelled"}


class DolbyError(Exception):
    """Raised when the Dolby.io API returns an error or is unreachable."""


def master_output_config(profile: str, target_lufs: float, destination: str) -> dict[str, Any]:
    """Build one Dolby ``outputs`` entry for ``profile`` targeting ``target_lufs``.

    ``destination`` is the ``dlb://`` URL the mastered variant is written to.
    The integrated-loudness target drives Dolby's loudness stage; the content
    preset is resolved from :data:`PROFILE_CONTENT_TYPE`. Kept a free function so
    the handler can compose an outputs list (up to five) without the client
    needing to know about our profile vocabulary.
    """
    return {
        "destination": destination,
        "master": {
            "loudness": {"target_level": float(target_lufs)},
            "content": {"type": PROFILE_CONTENT_TYPE.get(profile, _DEFAULT_CONTENT_TYPE)},
        },
    }


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


class DolbyClient:
    """Synchronous client for the Dolby.io Music Mastering workflow."""

    def __init__(self, api_key: str, api_secret: str) -> None:
        """Initialise with the Dolby.io app key/secret used to mint bearer tokens."""
        self.api_key = api_key
        self.api_secret = api_secret
        self._token: str | None = None
        # monotonic() deadline after which the cached token must be refreshed.
        self._token_expiry: float = 0.0

    # -- auth --------------------------------------------------------------

    def _get_token(self) -> str:
        """Return a valid bearer token, refreshing it when missing or near expiry.

        Caches the token until ``_TOKEN_EXPIRY_BUFFER_S`` before its stated
        lifetime, so concurrent operations on one client reuse a single token.
        """
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
            raise DolbyError(f"Dolby authentication failed: {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise DolbyError(f"Dolby authentication failed: {exc}") from exc
        except ValueError as exc:
            raise DolbyError("Dolby authentication failed: invalid JSON response") from exc

        token = payload.get("access_token") if isinstance(payload, dict) else None
        if not token:
            raise DolbyError("Dolby authentication failed: response contains no access_token")
        # A missing/zero/negative expires_in must not be read as a 30-min lifetime
        # (a 0 would cache an already-dead token), so fall back only when invalid.
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
        """Issue an HTTP request, retrying on 5xx with exponential backoff.

        Returns the response untouched so the caller decides how to interpret a
        non-5xx status. Connection errors are not retried — they propagate for the
        caller to wrap in :class:`DolbyError`. ``headers`` defaults to bearer auth;
        callers hitting a presigned URL pass ``{}`` to avoid leaking the token to
        an external host.
        """
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
        """Upload ``audio_bytes`` to Dolby input storage, returning its ``dlb://`` URL.

        Two-step presigned workflow: ask ``POST {media}/input`` for a presigned PUT
        URL for ``dlb://{filename}``, then PUT the bytes to it. The returned
        ``dlb://`` handle is what a master job consumes as its input.
        """
        dlb_url = f"dlb://{filename}"
        try:
            response = self._send_with_retry(
                httpx.post, f"{_MEDIA_BASE_URL}/input", json={"url": dlb_url}, timeout=_API_TIMEOUT
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise DolbyError(f"Dolby upload request failed: {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise DolbyError(f"Dolby upload request failed: {exc}") from exc
        except ValueError as exc:
            raise DolbyError("Dolby upload request failed: invalid JSON response") from exc

        presigned_url = payload.get("url") if isinstance(payload, dict) else None
        if not presigned_url:
            raise DolbyError("Dolby upload request failed: response contains no presigned url")

        try:
            # The presigned URL is already authorized; send no bearer token to it.
            put = self._send_with_retry(
                httpx.put, presigned_url, content=audio_bytes, timeout=_UPLOAD_TIMEOUT, headers={}
            )
            put.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise DolbyError(f"Dolby upload failed: {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise DolbyError(f"Dolby upload failed: {exc}") from exc
        return dlb_url

    # -- master submission -------------------------------------------------

    def submit_preview(self, input_url: str, outputs: list[dict[str, Any]]) -> str:
        """Submit a master *preview* job and return its ``job_id``.

        ``outputs`` is the list of variant configs (see :func:`master_output_config`),
        capped at :data:`MAX_PREVIEW_OUTPUTS`. Raises :class:`DolbyError` for an
        empty or over-large outputs list before any network call.
        """
        if not outputs:
            raise DolbyError("Dolby preview requires at least one output variant")
        if len(outputs) > MAX_PREVIEW_OUTPUTS:
            raise DolbyError(
                f"Dolby preview supports at most {MAX_PREVIEW_OUTPUTS} output variants, got {len(outputs)}"
            )
        body = {"inputs": [{"source": input_url}], "outputs": outputs}
        try:
            response = self._send_with_retry(
                httpx.post, f"{_MEDIA_BASE_URL}/master/preview", json=body, timeout=_API_TIMEOUT
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise DolbyError(f"Dolby preview submission failed: {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise DolbyError(f"Dolby preview submission failed: {exc}") from exc
        except ValueError as exc:
            raise DolbyError("Dolby preview submission failed: invalid JSON response") from exc

        job_id = payload.get("job_id") if isinstance(payload, dict) else None
        if not job_id:
            raise DolbyError("Dolby preview submission failed: response contains no job_id")
        return str(job_id)

    # -- polling -----------------------------------------------------------

    def get_status(self, job_id: str) -> dict[str, Any]:
        """Fetch the current state of preview ``job_id``.

        Returns the parsed Dolby payload with a normalised lower-case ``status``
        and a numeric ``progress`` (0–100). Raises :class:`DolbyError` on transport
        or HTTP failure.
        """
        try:
            response = self._send_with_retry(
                httpx.get, f"{_MEDIA_BASE_URL}/master/preview", timeout=_API_TIMEOUT, params={"job_id": job_id}
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise DolbyError(f"Dolby status check failed: {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise DolbyError(f"Dolby status check failed: {exc}") from exc
        except ValueError as exc:
            raise DolbyError("Dolby status check failed: invalid JSON response") from exc
        if not isinstance(payload, dict):
            raise DolbyError("Dolby status check failed: unexpected response payload")
        payload["status"] = str(payload.get("status", "")).lower()
        payload["progress"] = _as_float(payload.get("progress")) or 0.0
        return payload

    def wait_for_completion(self, job_id: str, timeout: float = 600.0, poll_interval: float = 2.0) -> dict[str, Any]:
        """Poll ``job_id`` until it succeeds, returning the final status payload.

        Backoff starts at ``poll_interval`` and doubles up to a 30s cap so a
        long master is not hammered. Raises :class:`DolbyError` if the job reports
        a failure or ``timeout`` seconds elapse with no terminal success.
        """
        deadline = time.monotonic() + timeout
        interval = poll_interval
        while True:
            status_payload = self.get_status(job_id)
            state = status_payload["status"]
            if state in _SUCCESS_STATES:
                return status_payload
            if state in _FAILURE_STATES:
                detail = status_payload.get("error") or state
                raise DolbyError(f"Dolby mastering job {job_id} failed: {detail}")
            if time.monotonic() >= deadline:
                raise DolbyError(f"Dolby mastering job {job_id} timed out after {timeout:.0f}s")
            time.sleep(interval)
            interval = min(interval * 2, 30.0)

    # -- results -----------------------------------------------------------

    def get_results(self, job_id: str) -> dict[str, Any]:
        """Return the mastering metrics and output handles for completed ``job_id``.

        Reads the terminal status payload and extracts a stable, BSON-safe shape::

            {
              "metrics": {"loudness": <LUFS>, "eq_bands": [...16...], "stereo": {...}},
              "outputs": [{"destination": "dlb://…", "preview": "dlb://…"}, …],
            }

        Defensive parsing: missing fields degrade to ``None``/empty rather than
        raising, since the exact Dolby payload varies by job.
        """
        status_payload = self.get_status(job_id)
        if status_payload["status"] not in _SUCCESS_STATES:
            raise DolbyError(f"Dolby mastering job {job_id} is not complete (status={status_payload['status']!r})")
        result = status_payload.get("result")
        result = result if isinstance(result, dict) else {}
        return {"metrics": _parse_metrics(result), "outputs": _parse_outputs(result)}

    # -- download ----------------------------------------------------------

    def download(self, dlb_url: str) -> bytes:
        """Download the bytes of a mastered output at ``dlb_url`` from Dolby storage.

        Two-step, mirroring :meth:`upload`: the auth-gated ``{media}/output`` request
        either streams the bytes directly or redirects to a (pre-authorized) storage
        URL. A redirect is followed manually with *no* bearer header, so the token is
        never sent to the redirect target rather than relying on httpx's cross-origin
        stripping.
        """
        try:
            response = self._send_with_retry(
                httpx.get,
                f"{_MEDIA_BASE_URL}/output",
                timeout=_DOWNLOAD_TIMEOUT,
                params={"url": dlb_url},
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
            raise DolbyError(f"Dolby download failed: {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise DolbyError(f"Dolby download failed: {exc}") from exc


def _parse_metrics(result: dict[str, Any]) -> dict[str, Any]:
    """Extract loudness / 16-band EQ / stereo-image metrics from a master result.

    Dolby nests audio analysis under ``audio`` (with ``loudness``, ``dynamics``
    and ``music`` sub-objects); every field is read defensively so a partial or
    reshaped payload yields ``None``/empty values instead of raising.
    """
    audio = result.get("audio") if isinstance(result.get("audio"), dict) else {}
    loudness_block = audio.get("loudness") if isinstance(audio.get("loudness"), dict) else {}
    # Prefer the measured *output* loudness, falling back to the integrated value.
    # An explicit None check (not ``or``) so a legitimate 0.0 LUFS is not discarded.
    measured = _as_float(loudness_block.get("measured"))
    loudness = measured if measured is not None else _as_float(loudness_block.get("integrated"))

    eq = audio.get("eq") if isinstance(audio.get("eq"), dict) else {}
    raw_bands = eq.get("bands") if isinstance(eq.get("bands"), list) else []
    eq_bands = [band for band in (_as_float(value) for value in raw_bands) if band is not None]

    stereo_block = audio.get("stereo") if isinstance(audio.get("stereo"), dict) else {}
    stereo = {
        "width": _as_float(stereo_block.get("width")),
        "balance": _as_float(stereo_block.get("balance")),
    }
    return {"loudness": loudness, "eq_bands": eq_bands, "stereo": stereo}


def _parse_outputs(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull the per-variant output handles (destination + preview ``dlb://`` URLs)."""
    raw = result.get("outputs") if isinstance(result.get("outputs"), list) else []
    outputs: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        destination = entry.get("destination") or entry.get("url")
        preview = entry.get("preview") or destination
        if destination or preview:
            outputs.append({"destination": destination, "preview": preview})
    return outputs
