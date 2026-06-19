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

import asyncio
import io
import logging
import math

from beanie import PydanticObjectId

from acemusic.storage import StorageBackend

from ..models import Clip, Job, JobStatus
from .common import coerce_object_id
from .jobs import create_job

logger = logging.getLogger(__name__)

MASTERING_JOB_TYPE = "mastering"

# An approved master is promoted from ``generation_mode="mastering"`` (the worker's
# tag for any mastered child) to this terminal mode (US-12.4), distinguishing the
# musician's chosen release master from the other auditioned candidates.
APPROVED_GENERATION_MODE = "mastered"

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


# ---------------------------------------------------------------------------
# Preview / A/B comparison and approval (US-12.4)
#
# The mastering pipeline (US-12.2) produces ONE mastered clip per job, so a
# source clip's "previews" are the mastered children from its completed mastering
# jobs (one per job). Approval promotes a chosen candidate to the final master.
# ---------------------------------------------------------------------------


class PreviewNotFoundError(Exception):
    """The requested preview is not a completed mastered candidate of the source."""


async def get_mastering_job(job_id: str, user_id: str) -> Job | None:
    """Return the owner's mastering job, or ``None`` for unknown/unowned/wrong-type.

    Owner-scoped and type-scoped: a missing id, another user's job, or a
    non-mastering job are all indistinguishable from "no such job" so the
    endpoint never reveals another user's (or another feature's) jobs.
    """
    oid = coerce_object_id(job_id)
    if oid is None:
        return None
    job = await Job.get(oid)
    if job is None or str(job.user_id) != user_id or job.job_type != MASTERING_JOB_TYPE:
        return None
    return job


async def list_source_previews(source_clip_id: str | None, user_id: str) -> list[Job]:
    """The owner's completed mastering jobs for ``source_clip_id``, oldest-first.

    Each completed mastering job carries one mastered candidate in
    ``result["clip_ids"]`` plus its metrics — the set the musician auditions.
    """
    if not source_clip_id:
        return []
    uid = coerce_object_id(user_id)
    if uid is None:
        return []
    jobs = await Job.find(
        Job.user_id == uid,
        Job.job_type == MASTERING_JOB_TYPE,
        Job.status == JobStatus.COMPLETED,
    ).to_list()
    # clip_id lives inside the free-form input_params dict; filter in Python rather
    # than with a nested query — a user's completed mastering jobs are few.
    # ponytail: linear scan; add an input_params.clip_id index if this gets hot.
    matching = [j for j in jobs if (j.input_params or {}).get("clip_id") == source_clip_id]
    matching.sort(key=lambda j: j.created_at)
    return matching


def _measure_loudness_sync(data: bytes) -> float | None:
    """Integrated LUFS of ``data``, or ``None`` if it can't be measured."""
    import numpy as np
    import soundfile as sf

    from acemusic.audio import measure_lufs

    try:
        audio, sample_rate = sf.read(io.BytesIO(data))
    except Exception:
        # soundfile decodes wav/flac/ogg; a format it can't read (e.g. mp3) or a
        # corrupt object yields no measurement rather than a 500.
        return None
    if audio.ndim == 1:
        audio = np.column_stack([audio, audio])
    try:
        lufs = float(measure_lufs(audio, sample_rate))
    except Exception:
        return None
    # pyloudnorm returns -inf for silence; only finite loudness is meaningful.
    return lufs if math.isfinite(lufs) else None


async def measure_clip_loudness(storage: StorageBackend, clip: Clip) -> float | None:
    """Measure a clip's integrated LUFS on demand (None if the audio is unavailable).

    The unmastered source has no stored metrics, so its loudness is computed here
    for the A/B comparison. Off-loaded to a thread — both the download and the
    pyloudnorm pass are blocking.
    """
    try:
        data = await asyncio.to_thread(storage.download, clip.file_path)
    except Exception:
        # Original loudness is a best-effort A/B extra: a missing object or a
        # transient storage error degrades to "no measurement", never a 500 on
        # the comparison view.
        logger.debug("Could not download clip %s for loudness measurement", clip.id, exc_info=True)
        return None
    return await asyncio.to_thread(_measure_loudness_sync, data)


async def approve_preview(source_job: Job, preview_clip_id: str, user_id: str) -> Clip:
    """Promote a mastered candidate to the final master and return it.

    ``preview_clip_id`` must be a completed mastered candidate of ``source_job``'s
    source clip and owned by the user; otherwise :class:`PreviewNotFoundError`.
    Sets ``generation_mode`` to :data:`APPROVED_GENERATION_MODE`. Idempotent — the
    clip already exists (the worker created it); approving twice is a no-op re-save.
    """
    source_clip_id = (source_job.input_params or {}).get("clip_id")
    previews = await list_source_previews(source_clip_id, user_id)
    candidate_ids = {cid for job in previews for cid in (job.result or {}).get("clip_ids", [])}
    if preview_clip_id not in candidate_ids:
        raise PreviewNotFoundError(f"Preview {preview_clip_id!r} is not a candidate for this source clip")

    oid = coerce_object_id(preview_clip_id)
    clip = await Clip.get(oid) if oid is not None else None
    if clip is None or str(clip.user_id) != user_id:
        # A candidate id with no owned clip behind it is a data inconsistency, not
        # a client error the caller can fix — surface it as "not found" all the same.
        raise PreviewNotFoundError(f"Preview clip {preview_clip_id!r} not found")
    clip.generation_mode = APPROVED_GENERATION_MODE
    await clip.save()
    return clip
