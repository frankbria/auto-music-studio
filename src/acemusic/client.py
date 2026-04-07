"""HTTP client for ACE-Step server (US-2.2)."""

from __future__ import annotations

import httpx


class AceStepClient:
    """Reusable HTTP client for the ACE-Step API."""

    def __init__(self, base_url: str, api_key: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    def get_stats(self, timeout: float = 5.0) -> dict:
        """Call GET /v1/stats and return the parsed JSON body.

        Raises:
            httpx.TimeoutException: if the server does not respond within `timeout` seconds.
            httpx.HTTPStatusError: if the server returns a non-2xx status.
        """
        response = httpx.get(f"{self.base_url}/v1/stats", headers=self._headers, timeout=timeout)
        response.raise_for_status()
        return response.json()
