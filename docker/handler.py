"""RunPod serverless handler for ACE-Step-1.5 (US-11.3).

Bridges RunPod's serverless interface to the ACE-Step REST API. On the first
invocation it spawns the ACE-Step API server (``uv run acestep-api``) as a
subprocess from the project installed in the image at ``/app/ACE-Step-1.5`` (so
``uv run`` finds its ``pyproject.toml`` + venv), with ``HF_HOME`` pointed at the
RunPod Network Volume so model *weights* load from the mount and are never baked
into the image. It waits for the server to become healthy, then proxies each
generation request:

    RunPod event → POST /release_task → poll POST /query_result → audio URLs

This handler speaks the *real* ACE-Step 1.5 API contract (see
``acemusic.client.AceStepClient``), not the simplified sketch in
``model-deployment.md`` §3.4:

- responses are wrapped in a ``{"data": ..., "code": 200}`` envelope;
- ``/query_result`` takes ``{"task_id_list": [...]}`` (not ``task_ids``);
- status is an integer (0=queued/running, 1=succeeded, 2=failed), not a boolean;
- ``result`` is a JSON *string* listing ``{"file": "/v1/audio?path=..."}`` clips.

The returned ``output`` uses the ``{"status", "audio_urls"}`` shape the platform's
:class:`acemusic.runpod_client.RunPodClient` (``_extract_audio_urls``, US-11.2)
already understands, so remote and local backends are interchangeable.

Run modes:
- Pod / standalone: the image's default CMD runs the API server directly.
- Serverless: override CMD to ``python /app/handler.py``, which starts the RunPod
  worker loop. ``runpod`` is imported lazily there so this module stays importable
  for unit tests without the runpod SDK installed and never starts a server on import.

Known limitation: the audio URLs returned here point at the worker-local ACE-Step
server (``http://localhost:8001/v1/audio?...``). Delivering generated audio across
the internet (S3 upload / presigned URLs) is follow-up infrastructure tracked
separately; the platform's extractor already tolerates the URL shape emitted here.
"""

from __future__ import annotations

import json
import os
import subprocess
import time

import httpx

API_BASE_URL = "http://localhost:8001"

# The ACE-Step project (code + uv venv) is installed in the image at build time. The
# API server runs from here so ``uv run`` resolves the project's pyproject.toml + venv.
APP_DIR = "/app/ACE-Step-1.5"

# Model weights live on the RunPod Network Volume and are exposed to ACE-Step via
# HF_HOME, so they load from the mount rather than the image (see model-deployment.md
# §5.3). Used as the default when HF_HOME is not already set in the environment.
MODEL_CACHE = "/workspace/models/.cache"

# Health-check tuning: poll GET /v1/stats up to 30 times at 1s intervals while the
# server loads models on cold start.
_HEALTH_ATTEMPTS = 30
_HEALTH_INTERVAL = 1.0

# Result-poll tuning: generation can take minutes on larger models / cold caches.
_POLL_INTERVAL = 1.0
_POLL_TIMEOUT = 600.0

# ACE-Step integer status → platform status vocabulary.
_STATUS_MAP = {0: "pending", 1: "completed", 2: "failed"}

# Subprocess handle for the ACE-Step API server, started lazily on first request and
# reused across warm invocations of the same worker.
api_process: subprocess.Popen | None = None


class HandlerError(Exception):
    """Raised when the handler cannot fulfil a request (mapped to a failed output)."""


def start_api_server() -> bool:
    """Start the ACE-Step API server subprocess if needed and wait until it is healthy.

    Spawns ``uv run acestep-api`` from the installed project dir (``APP_DIR``) so the
    venv resolves, with ``HF_HOME`` defaulted to the Network Volume cache so weights
    load from the mount. Forwards ``ACESTEP_API_KEY``, then polls ``GET /v1/stats``
    until it answers 200. Returns ``True`` once healthy, ``False`` if the server never
    came up within the health-check budget. Reuses an already-running process across
    warm invocations.
    """
    global api_process
    if api_process is None or api_process.poll() is not None:
        env = os.environ.copy()
        env["ACESTEP_API_KEY"] = os.getenv("ACESTEP_API_KEY", "")
        # Respect an explicitly-set HF_HOME (RunPod template / image ENV); otherwise
        # point at the volume cache so weights come from the mount, not the image.
        env.setdefault("HF_HOME", MODEL_CACHE)
        api_process = subprocess.Popen(
            ["uv", "run", "acestep-api"],
            cwd=APP_DIR,
            env=env,
        )

    for _ in range(_HEALTH_ATTEMPTS):
        try:
            response = httpx.get(f"{API_BASE_URL}/v1/stats", timeout=2.0)
            if response.status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(_HEALTH_INTERVAL)
    return False


def handler(event: dict) -> dict:
    """Proxy a RunPod serverless event to the ACE-Step API and return audio URLs.

    Returns the platform-facing output shape:
        {"status": "completed", "audio_urls": [...]}                  on success
        {"status": "failed", "error": "...", "audio_urls": []}        on any failure
    """
    if not start_api_server():
        return _failure("ACE-Step API server failed to start")

    input_data = (event or {}).get("input") or {}
    try:
        task_id = _submit_task(input_data)
        return _poll_until_complete(task_id)
    except HandlerError as exc:
        return _failure(str(exc))
    except httpx.HTTPError as exc:
        return _failure(f"ACE-Step request failed: {exc}")


def _submit_task(input_data: dict) -> str:
    """POST /release_task and return the task id, unwrapping the data envelope."""
    response = httpx.post(f"{API_BASE_URL}/release_task", json=input_data, timeout=30.0)
    response.raise_for_status()
    outer = response.json()
    data = outer.get("data", outer)
    task_id = data.get("task_id") or data.get("id")
    if not task_id:
        raise HandlerError(f"No task_id in release_task response: {outer}")
    return task_id


def _poll_until_complete(task_id: str) -> dict:
    """Poll POST /query_result until the task reaches a terminal state or times out."""
    deadline = time.monotonic() + _POLL_TIMEOUT
    while True:
        response = httpx.post(
            f"{API_BASE_URL}/query_result",
            json={"task_id_list": [task_id]},
            timeout=10.0,
        )
        response.raise_for_status()
        items = response.json().get("data", [])
        item = items[0] if isinstance(items, list) and items else {}

        raw_status = item.get("status", 0)
        status = _STATUS_MAP.get(raw_status, "pending") if isinstance(raw_status, int) else raw_status

        if status == "completed":
            return {"status": "completed", "audio_urls": _extract_audio_urls(item)}
        if status == "failed":
            return _failure(item.get("error") or "ACE-Step generation failed")
        if time.monotonic() >= deadline:
            return _failure("ACE-Step generation timed out")
        time.sleep(_POLL_INTERVAL)


def _extract_audio_urls(item: dict) -> list[str]:
    """Parse ACE-Step's ``result`` (a JSON string of ``{"file": ...}`` clips) into URLs.

    Relative ``/v1/audio?path=...`` files are qualified against the worker-local
    server; absolute URLs pass through unchanged.
    """
    result_raw = item.get("result", "[]")
    try:
        clips = json.loads(result_raw) if isinstance(result_raw, str) else result_raw or []
    except (ValueError, TypeError):
        clips = []
    urls: list[str] = []
    for clip in clips if isinstance(clips, list) else []:
        file = clip.get("file") if isinstance(clip, dict) else None
        if not file:
            continue
        urls.append(f"{API_BASE_URL}{file}" if file.startswith("/") else file)
    return urls


def _failure(message: str) -> dict:
    """Build the standard failed-output envelope."""
    return {"status": "failed", "error": message, "audio_urls": []}


if __name__ == "__main__":  # pragma: no cover - exercised only inside the container
    import runpod

    runpod.serverless.start({"handler": handler})
