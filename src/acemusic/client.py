"""HTTP client for ACE-Step server (US-2.2, US-2.3)."""

from __future__ import annotations

import httpx


class AceStepError(Exception):
    """Raised when the ACE-Step API returns an error or is unreachable."""


class AceStepClient:
    """Reusable HTTP client for the ACE-Step API."""

    def __init__(self, base_url: str, api_key: str | None = None) -> None:
        """Initialise the client with a base URL and optional API key."""
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

    def submit_task(
        self,
        prompt: str,
        num_clips: int = 2,
        audio_duration: float | None = None,
        format: str = "wav",
    ) -> str:
        """Submit a generation task via POST /release_task and return the task_id.

        Raises:
            AceStepError: on HTTP error or unexpected response shape.
        """
        payload: dict = {"prompt": prompt, "num_clips": num_clips, "format": format}
        if audio_duration is not None:
            payload["audio_duration"] = audio_duration
        try:
            response = httpx.post(
                f"{self.base_url}/release_task",
                json=payload,
                headers=self._headers,
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()
            task_id = data.get("task_id") or data.get("id")
            if not task_id:
                raise AceStepError(f"No task_id in response: {data}")
            return task_id
        except httpx.HTTPStatusError as exc:
            raise AceStepError(f"Submit failed: {exc.response.status_code} {exc.response.text}") from exc
        except httpx.RequestError as exc:
            raise AceStepError(f"Submit failed: {exc}") from exc

    def query_result(self, task_id: str, timeout: float = 10.0) -> dict:
        """Poll GET /query_result?task_id=<id> and return the status dict.

        Raises:
            AceStepError: on HTTP error or connection failure.
        """
        try:
            response = httpx.get(
                f"{self.base_url}/query_result",
                params={"task_id": task_id},
                headers=self._headers,
                timeout=timeout,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            raise AceStepError(f"Query failed: {exc.response.status_code} {exc.response.text}") from exc
        except httpx.RequestError as exc:
            raise AceStepError(f"Query failed: {exc}") from exc

    def download_audio(self, url: str, timeout: float = 120.0) -> bytes:
        """Download raw audio bytes from a URL.

        Raises:
            AceStepError: on HTTP error or connection failure.
        """
        try:
            response = httpx.get(url, headers=self._headers, timeout=timeout, follow_redirects=True)
            response.raise_for_status()
            return response.content
        except httpx.HTTPStatusError as exc:
            raise AceStepError(f"Download failed: {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise AceStepError(f"Download failed: {exc}") from exc
