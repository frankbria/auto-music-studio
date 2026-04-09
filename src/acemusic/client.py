"""HTTP client for ACE-Step server (US-2.2, US-2.3).

ACE-Step 1.5 API contract:
- All responses are wrapped: {"data": ..., "code": 200, "error": null, ...}
- POST /release_task  → submit a generation task
- POST /query_result  → poll task status (body: {"task_id_list": [id]})
  - status integers: 0=queued/running, 1=succeeded, 2=failed
  - result field is a JSON string containing [{file: "/v1/audio?path=..."}]
- GET  /v1/stats      → server statistics
- GET  /v1/audio?path=... → download audio file
"""

from __future__ import annotations

import json as _json

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
        """Call GET /v1/stats and return a normalised stats dict.

        Returns:
            dict with keys: models (list), active_jobs (int), avg_job_time (float|None)

        Raises:
            httpx.TimeoutException: if the server does not respond in time.
            httpx.HTTPStatusError: if the server returns a non-2xx status.
        """
        response = httpx.get(f"{self.base_url}/v1/stats", headers=self._headers, timeout=timeout)
        response.raise_for_status()
        outer = response.json()
        data = outer.get("data", outer)
        jobs = data.get("jobs", {})
        return {
            "models": [m.get("name") for m in data.get("models", [])],
            "active_jobs": jobs.get("running", data.get("active_jobs", 0)),
            "avg_job_time": data.get("avg_job_seconds", data.get("avg_job_time")),
        }

    def submit_task(
        self,
        prompt: str,
        num_clips: int = 2,
        audio_duration: float | None = None,
        format: str = "wav",
        style: str | None = None,
        lyrics: str | None = None,
        vocal_language: str | None = None,
        instrumental: bool = False,
    ) -> str:
        """Submit a generation task via POST /release_task and return the task_id.

        Args:
            prompt: Text description of the music.
            num_clips: Number of audio clips to generate (maps to batch_size).
            audio_duration: Target duration in seconds, or None for server default.
            format: Output audio format (maps to audio_format).
            style: Comma-separated style descriptors (e.g. "dark electro, punchy drums").
            lyrics: Inline lyrics text (may include structure tags like [Verse]).
            vocal_language: ISO 639-1 vocal language code (e.g. "en", "ja").
            instrumental: If True, suppresses vocals.

        Raises:
            AceStepError: on HTTP error, connection failure, or missing task_id.
        """
        payload: dict = {"prompt": prompt, "batch_size": num_clips, "audio_format": format}
        if audio_duration is not None:
            payload["audio_duration"] = audio_duration
        if style is not None:
            payload["style"] = style
        if lyrics is not None:
            payload["lyrics"] = lyrics
        if vocal_language is not None:
            payload["vocal_language"] = vocal_language
        if instrumental:
            payload["instrumental"] = True
        try:
            response = httpx.post(
                f"{self.base_url}/release_task",
                json=payload,
                headers=self._headers,
                timeout=30.0,
            )
            response.raise_for_status()
            outer = response.json()
            data = outer.get("data", outer)
            task_id = data.get("task_id") or data.get("id")
            if not task_id:
                raise AceStepError(f"No task_id in response: {data}")
            return task_id
        except httpx.HTTPStatusError as exc:
            raise AceStepError(f"Submit failed: {exc.response.status_code} {exc.response.text}") from exc
        except httpx.RequestError as exc:
            raise AceStepError(f"Submit failed: {exc}") from exc

    def query_result(self, task_id: str, timeout: float = 10.0) -> dict:
        """Poll POST /query_result for task status and return a normalised result dict.

        Returns:
            dict with keys:
              - status: "pending" | "completed" | "failed"
              - audio_urls: list of fully-qualified audio URLs (empty until completed)
              - error: error message string or None

        Raises:
            AceStepError: on HTTP error or connection failure.
        """
        try:
            response = httpx.post(
                f"{self.base_url}/query_result",
                json={"task_id_list": [task_id]},
                headers=self._headers,
                timeout=timeout,
            )
            response.raise_for_status()
            outer = response.json()
            items = outer.get("data", [])
            item = items[0] if isinstance(items, list) and items else {}

            # Map integer status (0=running, 1=succeeded, 2=failed) to string
            raw_status = item.get("status", 0)
            if isinstance(raw_status, int):
                status_map = {0: "pending", 1: "completed", 2: "failed"}
                status_str = status_map.get(raw_status, "pending")
            else:
                status_str = raw_status  # pass through if already a string

            # result is a JSON string containing a list of {file: "/v1/audio?path=..."}
            result_raw = item.get("result", "[]")
            try:
                clips = _json.loads(result_raw) if isinstance(result_raw, str) else result_raw or []
            except Exception:
                clips = []

            audio_urls = [
                f"{self.base_url}{c['file']}" if c.get("file", "").startswith("/") else c.get("file", "")
                for c in (clips if isinstance(clips, list) else [])
                if c.get("file")
            ]

            return {"status": status_str, "audio_urls": audio_urls, "error": item.get("error")}
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
