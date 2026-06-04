"""ElevenLabs cloud music generation client (US-2.5)."""

from __future__ import annotations

import httpx

_BASE_URL = "https://api.elevenlabs.io"

# ElevenLabs music API duration limits (music_length_ms: 3000–600000).
DURATION_MIN_S = 3.0
DURATION_MAX_S = 600.0


class ElevenLabsError(Exception):
    """Raised when the ElevenLabs API returns an error or is unreachable."""


def _validate_duration(duration: float | None) -> None:
    """Raise ElevenLabsError if duration is outside the API limits (3s–600s)."""
    if duration is not None and not (DURATION_MIN_S <= duration <= DURATION_MAX_S):
        raise ElevenLabsError(
            f"Invalid duration {duration}s: ElevenLabs requires between "
            f"{int(DURATION_MIN_S)}s and {int(DURATION_MAX_S)}s (10 min)."
        )


class ElevenLabsClient:
    """HTTP client for the ElevenLabs music generation API."""

    def __init__(self, api_key: str, output_format: str = "mp3_44100_128") -> None:
        """Initialise the client with an API key and default output format."""
        self.api_key = api_key
        self.output_format = output_format
        self._headers = {"xi-api-key": api_key}

    def generate(
        self,
        prompt: str,
        duration: float | None = None,
        instrumental: bool = False,
        style: str | None = None,
        lyrics: str | None = None,
    ) -> bytes:
        """Generate music via POST /v1/music and return the raw audio bytes.

        Args:
            prompt: Text description of the music.
            duration: Target duration in seconds (converted to music_length_ms).
            instrumental: If True, sets force_instrumental in the request body.
            style: Comma-separated style descriptors forwarded to the API.
            lyrics: Inline lyrics text forwarded to the API.

        Raises:
            ElevenLabsError: On out-of-range duration, HTTP error, or connection failure.
        """
        _validate_duration(duration)
        body: dict = {"prompt": prompt}
        if duration is not None:
            body["music_length_ms"] = int(duration * 1000)
        if instrumental:
            body["force_instrumental"] = True
        if style is not None:
            body["style"] = style
        if lyrics is not None:
            body["lyrics"] = lyrics

        try:
            response = httpx.post(
                f"{_BASE_URL}/v1/music",
                json=body,
                headers=self._headers,
                params={"output_format": self.output_format},
                timeout=120.0,
            )
            response.raise_for_status()
            return response.content
        except httpx.HTTPStatusError as exc:
            raise ElevenLabsError(f"ElevenLabs generate failed: {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise ElevenLabsError(f"ElevenLabs generate failed: {exc}") from exc

    def validate_key(self, timeout: float = 5.0) -> bool:
        """Validate the API key via GET /v1/user. Returns True if valid, False otherwise."""
        try:
            response = httpx.get(
                f"{_BASE_URL}/v1/user",
                headers=self._headers,
                timeout=timeout,
            )
            response.raise_for_status()
            return True
        except Exception:
            return False
