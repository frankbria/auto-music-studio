"""Compute routing engine (US-11.1).

Decides whether a generation runs on the local GPU or a remote RunPod worker,
based on the configured ``compute_preference`` and each target's live
availability. A per-request ``compute_target`` can override the preference.

Kept transport-agnostic (raises plain exceptions, never ``HTTPException``) like
the other service modules, so the router stays free of routing concerns.
"""

from enum import Enum

import httpx

# The local availability probe must be quick: the issue caps it at a 2-second
# timeout so a down local server degrades to fallback/503 without stalling the
# request.
LOCAL_AVAILABILITY_TIMEOUT = 2.0

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


async def check_remote_availability() -> bool:
    """Return ``True`` if the remote RunPod endpoint is ready to accept work.

    Stub that reports unavailable until US-11.2 wires up the RunPod serverless
    client. It is a real (overridable) async function rather than an inline
    constant so remote selection degrades safely in production — ``remote_only``
    yields 503 and ``*_first`` falls back — while tests can exercise the
    remote/fallback routing branches by patching it.
    """
    # TODO(US-11.2): query the RunPod serverless endpoint status via the RunPod API.
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
) -> ComputeTarget:
    """Resolve which :class:`ComputeTarget` a generation should run on.

    Applies the effective preference (after any per-request override) against the
    live availability of each target. Raises :class:`ComputeUnavailableError`
    when the required target is down and no fallback is permitted (``*_only`` and
    explicit overrides) or when neither target is reachable (``*_first``).
    """
    effective = _effective_preference(request_target, preference)

    if effective is ComputePreference.LOCAL_ONLY:
        if await check_local_availability(local_url, timeout):
            return ComputeTarget.LOCAL
        raise ComputeUnavailableError(ComputeTarget.LOCAL, effective)

    if effective is ComputePreference.REMOTE_ONLY:
        if await check_remote_availability():
            return ComputeTarget.REMOTE
        raise ComputeUnavailableError(ComputeTarget.REMOTE, effective)

    if effective is ComputePreference.LOCAL_FIRST:
        if await check_local_availability(local_url, timeout):
            return ComputeTarget.LOCAL
        if await check_remote_availability():
            return ComputeTarget.REMOTE
        raise ComputeUnavailableError(ComputeTarget.LOCAL, effective)

    # REMOTE_FIRST: prefer remote, fall back to local.
    if await check_remote_availability():
        return ComputeTarget.REMOTE
    if await check_local_availability(local_url, timeout):
        return ComputeTarget.LOCAL
    raise ComputeUnavailableError(ComputeTarget.REMOTE, effective)
