"""Compute status aggregation (US-11.4).

Backs ``GET /api/v1/compute/status``: probes the local ACE-Step server and the
remote RunPod endpoint *in parallel*, each bounded by ``compute_status_timeout``,
and reports each target's availability plus best-effort detail. A down or
unconfigured target degrades to ``available=False`` rather than an error — the
endpoint answers within the issue's 5-second ceiling even when a target hangs.

Kept transport-agnostic (returns models, never ``HTTPException``) like the sibling
``routing`` module, so the router stays thin.
"""

import asyncio
from typing import Any

import httpx
from pydantic import BaseModel

from ...runpod_client import RunPodClient
from ..settings import ApiSettings

# The local stats endpoint doubles as the availability probe (same as routing).
LOCAL_STATS_PATH = "/v1/stats"


class LocalComputeStatus(BaseModel):
    """Health + capacity of the local ACE-Step GPU server.

    Detail fields are best-effort: populated when ``/v1/stats`` exposes them and
    ``None`` otherwise, so a sparse stats payload still yields a valid response.
    """

    available: bool
    gpu_name: str | None = None
    vram_total_mb: int | None = None
    vram_used_mb: int | None = None
    active_jobs: int | None = None
    loaded_models: list[str] | None = None


class RemoteComputeStatus(BaseModel):
    """Health + capacity of the remote RunPod serverless endpoint.

    ``provider`` is ``None`` when RunPod is not configured at all, and ``"runpod"``
    once credentials are set — even if the endpoint is unreachable — so callers can
    distinguish "no remote" from "remote down".
    """

    available: bool
    provider: str | None = None
    endpoint_id: str | None = None
    active_workers: int | None = None
    max_workers: int | None = None
    scaling_status: str | None = None


class ComputeStatusResponse(BaseModel):
    """Combined local + remote compute status with the configured routing preference."""

    local: LocalComputeStatus
    remote: RemoteComputeStatus
    routing_preference: str


def _as_int(value: Any) -> int | None:
    """Coerce a stats value to ``int`` when it is a real number, else ``None``."""
    if isinstance(value, bool):  # bool is an int subclass; never a count here.
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _parse_local_stats(payload: Any) -> dict[str, Any]:
    """Extract GPU/VRAM/jobs/models from a (loosely-typed) ``/v1/stats`` body.

    ACE-Step's exact stats shape is not guaranteed, so several common key spellings
    are accepted and anything missing falls through to ``None``/empty.
    """
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        return {}

    # GPU/VRAM may be flat or nested under a "gpu" object.
    gpu = data.get("gpu")
    gpu_obj = gpu if isinstance(gpu, dict) else {}
    gpu_name = data.get("gpu_name") or gpu_obj.get("name")
    if gpu_name is None and isinstance(gpu, str):
        gpu_name = gpu
    vram_total = data.get("vram_total_mb") or gpu_obj.get("vram_total_mb") or gpu_obj.get("memory_total_mb")
    vram_used = data.get("vram_used_mb") or gpu_obj.get("vram_used_mb") or gpu_obj.get("memory_used_mb")

    # active_jobs: prefer the nested running count, fall back to a flat field.
    jobs = data.get("jobs")
    active_jobs = jobs.get("running") if isinstance(jobs, dict) else None
    if active_jobs is None:
        active_jobs = data.get("active_jobs")

    # loaded_models: list of {"name": ...} objects or a list of plain strings.
    models_raw = data.get("models")
    loaded_models: list[str] | None = None
    if isinstance(models_raw, list):
        loaded_models = [
            m["name"] if isinstance(m, dict) and "name" in m else m for m in models_raw if isinstance(m, (str, dict))
        ]
        loaded_models = [m for m in loaded_models if isinstance(m, str)]

    return {
        "gpu_name": gpu_name if isinstance(gpu_name, str) else None,
        "vram_total_mb": _as_int(vram_total),
        "vram_used_mb": _as_int(vram_used),
        "active_jobs": _as_int(active_jobs),
        "loaded_models": loaded_models,
    }


async def get_local_status(url: str, timeout: float) -> LocalComputeStatus:
    """Probe the local ACE-Step server, returning availability + best-effort detail.

    A 2xx from ``GET {url}/v1/stats`` means available; any non-2xx, connection
    error, or timeout means ``available=False`` with all detail fields ``None``.
    """
    endpoint = f"{url.rstrip('/')}{LOCAL_STATS_PATH}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(endpoint)
        if not response.is_success:
            return LocalComputeStatus(available=False)
        body = response.json()
    except (httpx.HTTPError, ValueError):
        return LocalComputeStatus(available=False)
    return LocalComputeStatus(available=True, **_parse_local_stats(body))


def _parse_remote_workers(health: dict[str, Any], endpoint_id: str) -> RemoteComputeStatus:
    """Turn a RunPod ``/health`` body into a populated :class:`RemoteComputeStatus`."""
    workers = health.get("workers")
    workers = workers if isinstance(workers, dict) else {}
    initializing = _as_int(workers.get("initializing")) or 0
    throttled = _as_int(workers.get("throttled")) or 0
    running = _as_int(workers.get("running"))
    ready = _as_int(workers.get("ready")) or 0
    idle = _as_int(workers.get("idle")) or 0

    # /health reports live worker states but not the endpoint's configured ceiling,
    # so max_workers stays None (it would need RunPod's GraphQL API).
    if initializing > 0:
        scaling_status = "initializing"
    elif throttled > 0:
        scaling_status = "throttled"
    elif (running or 0) > 0 or ready > 0 or idle > 0:
        scaling_status = "ready"
    else:
        scaling_status = "idle"

    return RemoteComputeStatus(
        available=True,
        provider="runpod",
        endpoint_id=endpoint_id,
        active_workers=running,
        max_workers=None,
        scaling_status=scaling_status,
    )


async def get_remote_status(settings: ApiSettings, timeout: float) -> RemoteComputeStatus:
    """Probe the remote RunPod endpoint when configured, returning availability + detail.

    Unconfigured RunPod (missing credentials) returns ``available=False`` with
    ``provider=None`` and makes no HTTP call. A configured-but-unreachable endpoint
    returns ``available=False`` but keeps ``provider="runpod"`` and ``endpoint_id``
    so callers can tell "no remote" from "remote down".
    """
    if not settings.runpod_enabled:
        return RemoteComputeStatus(available=False, provider=None)

    endpoint_id = settings.runpod_endpoint_id or ""
    client = RunPodClient(
        endpoint_id=endpoint_id,
        api_key=settings.runpod_api_key or "",
        base_url=settings.runpod_base_url,
    )
    try:
        health = await asyncio.wait_for(asyncio.to_thread(client.health_details, timeout), timeout)
    except Exception:
        # A status probe must never surface a 500: a timeout, thread-pool
        # exhaustion, or any client error all mean "remote unreachable".
        health = None
    if health is None:
        return RemoteComputeStatus(available=False, provider="runpod", endpoint_id=endpoint_id)
    return _parse_remote_workers(health, endpoint_id)


async def get_compute_status(settings: ApiSettings) -> ComputeStatusResponse:
    """Aggregate local + remote status, probing both targets concurrently."""
    timeout = settings.compute_status_timeout
    local, remote = await asyncio.gather(
        get_local_status(settings.local_url, timeout),
        get_remote_status(settings, timeout),
    )
    return ComputeStatusResponse(
        local=local,
        remote=remote,
        routing_preference=settings.compute_preference,
    )
