"""Mastering service layer (US-12.1).

Persists queued mastering jobs for the mastering endpoint, mirroring
:func:`acemusic.api.services.editing.create_edit_job`. Profile→LUFS resolution
lives here too so the router stays thin and the mapping is unit-testable without
the HTTP surface. Kept transport-agnostic (plain exceptions, never
``HTTPException``) like the other service modules.

Scope is job *submission* only: no processor handler is registered, so the
background processor — which claims only registered ``job_type``s — leaves
mastering jobs queued until the processing ticket wires up a handler.
"""

from beanie import PydanticObjectId

from ..models import Job
from .jobs import create_job

MASTERING_JOB_TYPE = "mastering"

# Each standard profile maps to a fixed integrated-loudness target (LUFS). "club"
# is the maximum-loudness master (-6) and "vinyl" trades loudness for dynamic
# range (-18). "custom" is absent: its target comes from the request.
PROFILE_LUFS_MAP = {
    "streaming": -14.0,
    "soundcloud": -12.0,
    "club": -6.0,
    "vinyl": -18.0,
}

CUSTOM_PROFILE = "custom"


def resolve_target_lufs(profile: str, custom_lufs: float | None) -> float:
    """The LUFS target for ``profile``.

    Standard profiles own their target (a stray ``custom_lufs`` is ignored).
    ``custom`` returns the caller-supplied value, which must be present — range
    bounds are enforced by the router's request model. Raises ``ValueError`` for
    an unknown profile or a ``custom`` profile with no value.
    """
    if profile in PROFILE_LUFS_MAP:
        return PROFILE_LUFS_MAP[profile]
    if profile == CUSTOM_PROFILE:
        if custom_lufs is None:
            raise ValueError("custom profile requires a target_lufs value")
        return custom_lufs
    raise ValueError(f"Unknown mastering profile: {profile!r}")


async def create_mastering_job(
    *,
    user_id: PydanticObjectId,
    workspace_id: PydanticObjectId,
    params: dict,
) -> Job:
    """Persist a queued mastering job and dispatch it.

    ``params`` holds the resolved mastering spec (clip_id, profile, service,
    format, target_lufs) so the future worker never re-derives anything from the
    request. ``workspace_id`` is the source clip's workspace — the master lands
    next to its parent. Returns the saved :class:`Job` (with its id).
    """
    return await create_job(
        user_id=user_id,
        workspace_id=workspace_id,
        job_type=MASTERING_JOB_TYPE,
        params=params,
    )
