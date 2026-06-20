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

Remote audio delivery (US-11.x): ACE-Step writes clips to the worker-local server
(``http://localhost:8001/v1/audio?...``), which a remote platform host cannot reach.
When S3 is configured (``ACEMUSIC_S3_BUCKET`` plus the ``ACEMUSIC_S3_*`` settings the
platform already uses), the handler downloads each clip on-worker and re-uploads it to
S3, returning presigned GET URLs the platform can fetch. With no bucket configured it
returns the worker-local URLs unchanged (local / single-host use, where ``localhost``
is reachable).
"""

from __future__ import annotations

import json
import mimetypes
import os
import subprocess
import time
import urllib.parse

import httpx

try:  # boto3 ships in the worker image; optional so this module imports without it.
    import boto3
except ImportError:  # pragma: no cover - exercised only where boto3 is absent
    boto3 = None

API_BASE_URL = "http://localhost:8001"

# Parsed (scheme, host, port) of the worker-local server. The ACE-Step token is sent
# only to this exact origin — compared on parsed parts, not a string prefix, so a
# userinfo-spoofed URL whose real host differs (e.g. ``http://localhost@evil.example/``,
# which httpx connects to ``evil.example``) cannot slip through and leak the credential.
_LOCAL_ORIGIN = urllib.parse.urlsplit(API_BASE_URL)

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
            urls = _deliver_audio(_extract_audio_urls(item), task_id)
            return {"status": "completed", "audio_urls": urls}
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


def _deliver_audio(urls: list[str], task_id: str) -> list[str]:
    """Make worker-local clips reachable by the platform.

    With ``ACEMUSIC_S3_BUCKET`` set, each clip is downloaded from the worker-local
    ACE-Step server and re-uploaded to S3, and a presigned GET URL is returned in its
    place. Without a bucket the worker-local URLs are returned unchanged (local /
    single-host use, where ``localhost`` is reachable). Raises :class:`HandlerError` if
    delivery is configured but fails, so the job surfaces a clean failure rather than
    handing the platform URLs it cannot fetch.
    """
    bucket = os.getenv("ACEMUSIC_S3_BUCKET")
    if not bucket:
        # Worker-local URLs only reach the platform when it shares the host (local / pod
        # use). On a RunPod serverless worker the platform is always remote, so missing
        # storage is a misconfiguration — fail loudly rather than return dead URLs the
        # client will silently discard.
        if os.getenv("RUNPOD_ENDPOINT_ID"):
            raise HandlerError("Serverless audio delivery requires ACEMUSIC_S3_BUCKET to be set")
        return urls
    if boto3 is None:
        raise HandlerError("ACEMUSIC_S3_BUCKET is set but boto3 is not installed")

    prefix = (os.getenv("ACEMUSIC_S3_PREFIX") or "").strip("/")
    expiry = _s3_url_expiry()
    try:
        client = boto3.client(
            "s3",
            region_name=os.getenv("ACEMUSIC_S3_REGION") or None,
            endpoint_url=os.getenv("ACEMUSIC_S3_ENDPOINT_URL") or None,
        )
        delivered: list[str] = []
        for index, url in enumerate(urls):
            ext = _audio_ext(url)
            key = "/".join(part for part in (prefix, "runpod", task_id, f"{index}{ext}") if part)
            # ponytail: the staging object under runpod/<task_id> is left for a bucket
            # lifecycle policy to expire; the platform stores its own canonical copy on
            # download, so in-handler deletion would need cross-component coordination.
            client.put_object(
                Bucket=bucket,
                Key=key,
                Body=_download_clip(url),
                ContentType=_content_type(ext),
            )
            delivered.append(
                client.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expiry)
            )
        return delivered
    except Exception as exc:  # noqa: BLE001 - any download/upload failure means undeliverable audio
        raise HandlerError(f"Failed to deliver audio to S3: {exc}") from exc


def _download_clip(url: str) -> bytes:
    """Fetch raw clip bytes from the worker-local ACE-Step server.

    Mirrors :class:`acemusic.client.AceStepClient`: sends the ACE-Step bearer token when
    ``ACESTEP_API_KEY`` is set. The token is attached *only* for the worker-local server
    (``API_BASE_URL``) — ACE-Step may return absolute third-party URLs, and the
    credential must never be disclosed to an external result host.
    """
    api_key = os.getenv("ACESTEP_API_KEY")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key and _is_worker_local(url) else {}
    response = httpx.get(url, headers=headers, timeout=120.0, follow_redirects=True)
    response.raise_for_status()
    return response.content


def _is_worker_local(url: str) -> bool:
    """True only if ``url``'s parsed origin matches the worker-local ACE-Step server."""
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    return (parts.scheme, parts.hostname, parts.port) == (
        _LOCAL_ORIGIN.scheme,
        _LOCAL_ORIGIN.hostname,
        _LOCAL_ORIGIN.port,
    )


def _audio_ext(url: str) -> str:
    """Best-effort audio file extension from a clip URL (its ``path`` query, else path)."""
    parsed = urllib.parse.urlparse(url)
    candidate = urllib.parse.parse_qs(parsed.query).get("path", [""])[0] or parsed.path
    return os.path.splitext(candidate)[1] or ".wav"


def _content_type(ext: str) -> str:
    """MIME type for an audio extension, defaulting to a generic binary type."""
    return mimetypes.guess_type(f"clip{ext}")[0] or "application/octet-stream"


def _s3_url_expiry() -> int:
    """Presigned-URL lifetime in seconds (``ACEMUSIC_S3_URL_EXPIRY``, default 3600)."""
    try:
        expiry = int(os.getenv("ACEMUSIC_S3_URL_EXPIRY", "3600"))
    except ValueError:
        return 3600
    return expiry if expiry > 0 else 3600


def _failure(message: str) -> dict:
    """Build the standard failed-output envelope."""
    return {"status": "failed", "error": message, "audio_urls": []}


if __name__ == "__main__":  # pragma: no cover - exercised only inside the container
    import runpod

    runpod.serverless.start({"handler": handler})
