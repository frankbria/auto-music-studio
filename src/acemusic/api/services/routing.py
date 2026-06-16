"""Compute routing engine (US-11.1).

Decides whether a generation runs on the local GPU or a remote RunPod worker,
based on the configured ``compute_preference`` and each target's live
availability. A per-request ``compute_target`` can override the preference.

Kept transport-agnostic (raises plain exceptions, never ``HTTPException``) like
the other service modules, so the router stays free of routing concerns.
"""

import asyncio
from enum import Enum

import httpx

from ...runpod_client import RunPodClient, RunPodError
from ..settings import ApiSettings

# The local availability probe must be quick: the issue caps it at a 2-second
# timeout so a down local server degrades to fallback/503 without stalling the
# request.
LOCAL_AVAILABILITY_TIMEOUT = 2.0

# The remote (RunPod) readiness probe gets a slightly longer budget than the local
# one — a serverless endpoint may be a touch slower to answer /health — but still
# short enough that an unreachable remote degrades to fallback/503 promptly.
REMOTE_AVAILABILITY_TIMEOUT = 5.0

# ACE-Step exposes a lightweight stats endpoint used here purely as a health ping.
LOCAL_STATS_PATH = "/v1/stats"


class ComputeTarget(str, Enum):
    """Where a generation actually runs."""

    LOCAL = "local"
    REMOTE = "remote"


class ComputePreference(str, Enum):
    """Configured routing strategy (``ACEMUSIC_API_COMPUTE_PREFERENCE``).

    Values mirror the ``ApiSettings.compute_preference`` literal so a settings
    string maps directly onto a member (``ComputePreference(settings.value)``).
    """

    LOCAL_FIRST = "local_first"
    REMOTE_FIRST = "remote_first"
    LOCAL_ONLY = "local_only"
    REMOTE_ONLY = "remote_only"


class ComputeUnavailableError(RuntimeError):
    """No compute target could satisfy the request.

    Carries the ``target`` that was being attempted and the ``preference`` in
    play so the router can render an informative 503 detail.
    """

    def __init__(self, target: ComputeTarget, preference: ComputePreference) -> None:
        self.target = target
        self.preference = preference
        super().__init__(f"compute target {target.value!r} is unavailable (preference {preference.value!r})")


async def check_local_availability(url: str, timeout: float = LOCAL_AVAILABILITY_TIMEOUT) -> bool:
    """Return ``True`` if the local ACE-Step server answers ``GET {url}/v1/stats``.

    Any non-2xx response, connection error, or timeout counts as unavailable —
    the caller falls back or fails closed rather than dispatching to a dead host.
    """
    endpoint = f"{url.rstrip('/')}{LOCAL_STATS_PATH}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(endpoint)
    except httpx.HTTPError:
        return False
    return response.is_success


async def check_remote_availability(settings: ApiSettings | None = None) -> bool:
    """Return ``True`` if the remote RunPod endpoint is ready to accept work (US-11.2).

    Remote routing is only available when RunPod is configured (both credentials set)
    AND its ``/health`` endpoint answers — so a deployment without RunPod, or one
    whose endpoint is down, degrades safely: ``remote_only`` yields 503 and ``*_first``
    falls back to local. Any probe error counts as unavailable rather than surfacing a
    500. ``settings`` is supplied by the router (which holds it on app state); a call
    without it (``None``) is treated as "remote disabled" — we never read the
    environment here, to avoid surprising request-time env/.env reads.
    """
    if settings is None or not settings.runpod_enabled:
        return False
    client = RunPodClient(
        endpoint_id=settings.runpod_endpoint_id,
        api_key=settings.runpod_api_key,
        base_url=settings.runpod_base_url,
    )
    try:
        return await asyncio.to_thread(client.health, REMOTE_AVAILABILITY_TIMEOUT)
    except RunPodError:
        return False


def _effective_preference(request_target: str | None, preference: ComputePreference) -> ComputePreference:
    """Collapse a per-request override into the preference that governs routing.

    ``"auto"``/``None`` defer to the configured ``preference``. An explicit
    ``"local"``/``"remote"`` forces that target with no fallback — the same
    semantics as ``local_only``/``remote_only``.
    """
    if request_target in (None, "auto"):
        return preference
    if request_target == ComputeTarget.LOCAL.value:
        return ComputePreference.LOCAL_ONLY
    if request_target == ComputeTarget.REMOTE.value:
        return ComputePreference.REMOTE_ONLY
    raise ValueError(f"unknown compute_target {request_target!r}")


async def resolve_compute_target(
    *,
    request_target: str | None,
    preference: ComputePreference,
    local_url: str,
    timeout: float = LOCAL_AVAILABILITY_TIMEOUT,
    settings: ApiSettings | None = None,
) -> ComputeTarget:
    """Resolve which :class:`ComputeTarget` a generation should run on.

    Applies the effective preference (after any per-request override) against the
    live availability of each target. Raises :class:`ComputeUnavailableError`
    when the required target is down and no fallback is permitted (``*_only`` and
    explicit overrides) or when neither target is reachable (``*_first``).

    ``settings`` is forwarded to the remote (RunPod) readiness probe so it can read
    the configured credentials (US-11.2); the router supplies it from app state.
    """
    effective = _effective_preference(request_target, preference)

    if effective is ComputePreference.LOCAL_ONLY:
        if await check_local_availability(local_url, timeout):
            return ComputeTarget.LOCAL
        raise ComputeUnavailableError(ComputeTarget.LOCAL, effective)

    if effective is ComputePreference.REMOTE_ONLY:
        if await check_remote_availability(settings):
            return ComputeTarget.REMOTE
        raise ComputeUnavailableError(ComputeTarget.REMOTE, effective)

    if effective is ComputePreference.LOCAL_FIRST:
        if await check_local_availability(local_url, timeout):
            return ComputeTarget.LOCAL
        if await check_remote_availability(settings):
            return ComputeTarget.REMOTE
        raise ComputeUnavailableError(ComputeTarget.LOCAL, effective)

    if effective is ComputePreference.REMOTE_FIRST:
        # Prefer remote, fall back to local.
        if await check_remote_availability(settings):
            return ComputeTarget.REMOTE
        if await check_local_availability(local_url, timeout):
            return ComputeTarget.LOCAL
        raise ComputeUnavailableError(ComputeTarget.REMOTE, effective)

    # Unreachable: every ComputePreference member is handled above. Explicit so a
    # future enum addition fails loudly instead of silently returning None.
    raise ValueError(f"unhandled compute preference {effective!r}")  # pragma: no cover
