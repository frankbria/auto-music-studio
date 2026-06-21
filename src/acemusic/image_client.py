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
_DEFAULT_MODEL = "dall-e-3"
_IMAGE_SIZE = "1024x1024"


class ImageGenerationError(Exception):
    """Raised when the image API errors, is unreachable, or returns no image."""


class ImageGenerationClient:
    """Client for OpenAI's image-generation endpoint."""

    def __init__(self, api_key: str, model: str = _DEFAULT_MODEL) -> None:
        """Initialise with a bearer API key and the DALL-E model to use."""
        self.api_key = api_key
        self.model = model
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def generate_images(self, prompt: str, count: int = 4) -> list[bytes]:
        """Generate ``count`` images for ``prompt`` and return their raw bytes.

        Issues one request per image (DALL-E 3 caps ``n`` at 1). Raises
        :class:`ImageGenerationError` on any HTTP/connection failure or a response
        that carries no image data.
        """
        return [self._generate_one(prompt) for _ in range(count)]

    def _generate_one(self, prompt: str) -> bytes:
        body = {"model": self.model, "prompt": prompt, "n": 1, "size": _IMAGE_SIZE, "response_format": "b64_json"}
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

        data = (response.json() or {}).get("data") or []
        if not data or not data[0].get("b64_json"):
            raise ImageGenerationError("Image generation returned no image data.")
        try:
            return base64.b64decode(data[0]["b64_json"])
        except (ValueError, TypeError) as exc:
            raise ImageGenerationError(f"Image generation returned undecodable data: {exc}") from exc
