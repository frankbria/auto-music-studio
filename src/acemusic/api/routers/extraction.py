"""Stem / MIDI extraction endpoints (US-10.2), mounted under ``/api/v1/clips``.

* ``POST /clips/{id}/stems`` → separate into vocals/drums/bass/other (4 child clips)
* ``GET  /clips/{id}/stems`` → the stem clip ids if separation has been done
* ``POST /clips/{id}/midi``  → extract melody/chords/drums/bass MIDI files
* ``GET  /clips/{id}/midi``  → download URLs for extracted MIDI files

The POST endpoints are *cache-first*: if a clip already has stems (child clips)
or MIDI (``Clip.midi_paths``), they return the existing results with 200 instead
of enqueuing a duplicate job. Otherwise they persist a queued
:class:`~acemusic.api.models.job.Job` and return 202 with a job id trackable via
``GET /api/v1/jobs/{id}/status`` (mirrors the editing endpoints). Extraction is
non-generative local CPU work, so no credits are deducted.
"""

import asyncio
import logging

from beanie.operators import In
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from acemusic.storage import get_storage_backend

from ..auth.dependencies import CurrentUser, get_current_user, require_existing_user
from ..models import Clip
from ..services import clips as clip_service, extraction as extraction_service

logger = logging.getLogger(__name__)

# Router-level dependency gates every route behind a valid Bearer token (mirrors
# the clips/editing routers), so unauthenticated requests get 401.
router = APIRouter(prefix="/clips", tags=["extraction"], dependencies=[Depends(get_current_user)])


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


def _require_wav(clip: Clip) -> None:
    """422 unless the clip's audio is wav.

    Stem separation and MIDI extraction read the source through torchaudio /
    basic-pitch, which need ffmpeg for compressed formats (absent on the
    server). Gate at request time so a bad job fails fast with a clear message
    instead of an opaque worker error (mirrors the editing endpoints).
    """
    fmt = clip_service.native_format(clip)
    if fmt != "wav":
        raise _unprocessable(f"unsupported format {fmt!r} for extraction; currently only wav is supported.")


class ExtractionJobResponse(BaseModel):
    """The accepted-job acknowledgement returned with HTTP 202."""

    job_id: str
    status: str = "queued"


class StemsResult(BaseModel):
    """Existing stems for a clip (returned by GET, and by POST on a cache hit)."""

    stem_clip_ids: list[str]
    labels: list[str]
    parent_clip_id: str


class MidiResult(BaseModel):
    """Extracted MIDI for a clip (returned by GET, and by POST on a cache hit)."""

    download_urls: dict[str, str]
    parent_clip_id: str


async def _existing_stems(clip: Clip) -> list[Clip]:
    """Child clips produced by a prior stem-separation of ``clip`` (label-ordered)."""
    stems = await Clip.find(
        In(Clip.parent_clip_ids, [clip.id]),
        Clip.generation_mode == extraction_service.STEMS_JOB_TYPE,
    ).to_list()
    # Stable, predictable order regardless of insertion/scan order.
    return sorted(stems, key=lambda c: c.title or "")


def _stems_result(parent: Clip, stems: list[Clip]) -> StemsResult:
    return StemsResult(
        stem_clip_ids=[str(c.id) for c in stems],
        labels=[c.title or "" for c in stems],
        parent_clip_id=str(parent.id),
    )


async def _midi_result(clip: Clip) -> MidiResult:
    """Resolve the clip's stored MIDI keys to retrievable URLs at read time.

    URLs are generated per request (S3 presigned URLs expire), so only the
    storage keys are persisted on the clip.
    """
    storage = get_storage_backend()
    urls: dict[str, str] = {}
    for label, key in (clip.midi_paths or {}).items():
        urls[label] = await asyncio.to_thread(storage.get_url, key)
    return MidiResult(download_urls=urls, parent_clip_id=str(clip.id))


@router.post("/{clip_id}/stems", status_code=status.HTTP_202_ACCEPTED, response_model=None)
async def separate_stems(
    clip_id: str,
    response: Response,
    current: CurrentUser = Depends(require_existing_user),
) -> ExtractionJobResponse | StemsResult:
    """Enqueue stem separation of ``clip_id`` (or return cached stems with 200)."""
    clip = await clip_service.get_owned_clip(clip_id, current.user_id)

    existing = await _existing_stems(clip)
    if existing:
        response.status_code = status.HTTP_200_OK
        return _stems_result(clip, existing)

    _require_wav(clip)
    job = await extraction_service.create_extraction_job(
        user_id=clip.user_id,
        workspace_id=clip.workspace_id,
        job_type=extraction_service.STEMS_JOB_TYPE,
        clip_id=clip.id,
    )
    return ExtractionJobResponse(job_id=str(job.id))


@router.get("/{clip_id}/stems", response_model=StemsResult)
async def get_stems(
    clip_id: str,
    current: CurrentUser = Depends(require_existing_user),
) -> StemsResult:
    """Return the stem clip ids for ``clip_id`` (404 if not yet separated)."""
    clip = await clip_service.get_owned_clip(clip_id, current.user_id)
    existing = await _existing_stems(clip)
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No stems for this clip.")
    return _stems_result(clip, existing)


@router.post("/{clip_id}/midi", status_code=status.HTTP_202_ACCEPTED, response_model=None)
async def extract_midi(
    clip_id: str,
    response: Response,
    current: CurrentUser = Depends(require_existing_user),
) -> ExtractionJobResponse | MidiResult:
    """Enqueue MIDI extraction of ``clip_id`` (or return cached MIDI with 200)."""
    clip = await clip_service.get_owned_clip(clip_id, current.user_id)

    if clip.midi_paths:
        response.status_code = status.HTTP_200_OK
        return await _midi_result(clip)

    _require_wav(clip)
    job = await extraction_service.create_extraction_job(
        user_id=clip.user_id,
        workspace_id=clip.workspace_id,
        job_type=extraction_service.MIDI_JOB_TYPE,
        clip_id=clip.id,
    )
    return ExtractionJobResponse(job_id=str(job.id))


@router.get("/{clip_id}/midi", response_model=MidiResult)
async def get_midi(
    clip_id: str,
    current: CurrentUser = Depends(require_existing_user),
) -> MidiResult:
    """Return download URLs for ``clip_id``'s MIDI files (404 if not yet extracted)."""
    clip = await clip_service.get_owned_clip(clip_id, current.user_id)
    if not clip.midi_paths:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No MIDI for this clip.")
    return await _midi_result(clip)
