"""HTTP client for OpenAI DALL-E cover-art generation (US-13.1).

Mirrors the other backend clients (ElevenLabs/Dolby/...): synchronous httpx calls
through the shared :mod:`acemusic._http` retry helper, with a single typed error
(:class:`ImageGenerationError`) raised on any HTTP or connection failure. No
vendor SDK — the OpenAI images REST endpoint is called directly so the dependency
surface stays consistent with the rest of the package.

DALL-E 3 only accepts ``n=1`` per request, so a batch of options is N separate
calls. ``response_format=b64_json`` returns the image inline, avoiding a second
download round-trip per option.
"""

from __future__ import annotations

import base64

import httpx

from acemusic import _http

_BASE_URL = "https://api.openai.com"
# Image generation is slow (tens of seconds) and credit-billed, so use a generous
# read timeout and do not auto-retry (retries=0) — a retry would double-charge.
_GENERATION_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)
# dall-e-3 was retired from the API on 2026-05-12 and gpt-image-1 on 2026-10-23 (#693).
_DEFAULT_MODEL = "gpt-image-2.5-flare"
_IMAGE_SIZE = "1024x1024"
# Medium is what credit pricing assumes (about $0.05 for four images); high costs about four times as much.
_IMAGE_QUALITY = "medium"


class ImageGenerationError(Exception):
    """Raised when the image API errors, is unreachable, or returns no image."""


class ImageGenerationClient:
    """Client for OpenAI's image-generation endpoint."""

    def __init__(self, api_key: str, model: str = _DEFAULT_MODEL) -> None:
        """Initialise with a bearer API key and the GPT image model to use."""
        self.api_key = api_key
        self.model = model
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def generate_images(self, prompt: str, count: int = 4) -> list[bytes]:
        """Generate ``count`` images for ``prompt`` in one request and return their raw bytes.

        Raises :class:`ImageGenerationError` on any HTTP/connection failure, or a response
        carrying fewer images than asked for.
        """
        # GPT image models always answer in b64_json and reject response_format with a 400.
        body = {"model": self.model, "prompt": prompt, "n": count, "size": _IMAGE_SIZE, "quality": _IMAGE_QUALITY}
        try:
            response = _http.request(
                httpx.post,
                f"{_BASE_URL}/v1/images/generations",
                headers=self._headers,
                json=body,
                timeout=_GENERATION_TIMEOUT,
                retries=0,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ImageGenerationError(f"Image generation failed: {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise ImageGenerationError(f"Image generation failed: {exc}") from exc

        encoded = [item.get("b64_json") for item in (response.json() or {}).get("data") or []]
        if len(encoded) < count or not all(encoded):
            raise ImageGenerationError("Image generation returned no image data.")
        try:
            return [base64.b64decode(item) for item in encoded[:count]]
        except (ValueError, TypeError) as exc:
            raise ImageGenerationError(f"Image generation returned undecodable data: {exc}") from exc
