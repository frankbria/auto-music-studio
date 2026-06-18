"""Editing job handlers (US-10.1): crop, speed and remaster workers.

Each handler runs one claimed editing :class:`~acemusic.api.models.job.Job`:
download the source clip's audio from storage into a temp file, run the
corresponding CPU-bound function from :mod:`acemusic.audio` in a worker thread,
upload the result under the standard clip key, and insert the derived
:class:`~acemusic.api.models.clip.Clip` with lineage (``parent_clip_ids``,
``generation_mode``) and derived metadata. The source clip — bytes and
document — is never modified.

Handlers receive the storage backend from the :class:`JobProcessor` (which owns
the factory seam) and return the dict persisted as ``job.result``; exceptions
propagate and the processor marks the job failed.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

from beanie import PydanticObjectId

from acemusic.audio import crop_audio, remaster_audio, time_stretch_audio
from acemusic.storage import StorageBackend

from ..models import Clip, Job
from ..services.clips import native_format
from ..services.editing import CROP_JOB_TYPE, REMASTER_JOB_TYPE, SPEED_JOB_TYPE
from .common import download_clip, load_source_clip, store_clip


async def _store_derived_clip(
    job: Job,
    source: Clip,
    storage: StorageBackend,
    data: bytes,
    *,
    duration: float | None,
    bpm: int | None,
) -> Clip:
    """Upload the edited audio and insert its Clip record (id matches the key)."""
    fmt = native_format(source)
    clip_id = PydanticObjectId()
    clip = Clip(
        id=clip_id,
        user_id=job.user_id,
        workspace_id=job.workspace_id,
        file_path=f"{job.user_id}/{job.workspace_id}/clips/{clip_id}.{fmt}",
        format=fmt,
        duration=duration,
        bpm=bpm,
        key=source.key,
        parent_clip_ids=[source.id],
        generation_mode=job.job_type,
    )
    return await store_clip(storage, clip, data)


class _EditWorkspace:
    """Temp-dir scaffold for one edit: the downloaded source and the output slot."""

    def __init__(self, tmp_dir: str, fmt: str) -> None:
        self.input_path = Path(tmp_dir) / f"source.{fmt}"
        self.output_path = Path(tmp_dir) / f"output.{fmt}"


async def _download_source(storage: StorageBackend, source: Clip, workspace: _EditWorkspace) -> None:
    workspace.input_path.write_bytes(await download_clip(storage, source))


async def process_crop_job(job: Job, storage: StorageBackend) -> dict[str, Any]:
    """Trim the source to ``[start_ms, end_ms]`` (with optional fades)."""
    source = await load_source_clip(job)
    params = job.input_params
    start_ms, end_ms = params["start_ms"], params["end_ms"]

    with tempfile.TemporaryDirectory(prefix="acemusic-crop-") as tmp_dir:
        workspace = _EditWorkspace(tmp_dir, native_format(source))
        await _download_source(storage, source, workspace)
        await asyncio.to_thread(
            crop_audio,
            input_path=str(workspace.input_path),
            output_path=str(workspace.output_path),
            start_ms=start_ms,
            end_ms=end_ms,
            fade_in_ms=params.get("fade_in_ms", 0),
            fade_out_ms=params.get("fade_out_ms", 0),
        )
        output = workspace.output_path.read_bytes()

    clip = await _store_derived_clip(
        job,
        source,
        storage,
        output,
        duration=(end_ms - start_ms) / 1000.0,
        bpm=source.bpm,
    )
    return {"clip_ids": [str(clip.id)]}


async def process_speed_job(job: Job, storage: StorageBackend) -> dict[str, Any]:
    """Time-stretch the source by the resolved ``multiplier`` (pitch preserved)."""
    source = await load_source_clip(job)
    multiplier = job.input_params["multiplier"]

    with tempfile.TemporaryDirectory(prefix="acemusic-speed-") as tmp_dir:
        workspace = _EditWorkspace(tmp_dir, native_format(source))
        await _download_source(storage, source, workspace)
        await asyncio.to_thread(
            time_stretch_audio,
            input_path=str(workspace.input_path),
            output_path=str(workspace.output_path),
            rate=multiplier,
        )
        output = workspace.output_path.read_bytes()

    clip = await _store_derived_clip(
        job,
        source,
        storage,
        output,
        duration=source.duration / multiplier if source.duration is not None else None,
        bpm=round(source.bpm * multiplier) if source.bpm is not None else None,
    )
    return {"clip_ids": [str(clip.id)]}


async def process_remaster_job(job: Job, storage: StorageBackend) -> dict[str, Any]:
    """Loudness-normalise the source to ``target_lufs`` (full remaster pipeline)."""
    source = await load_source_clip(job)
    target_lufs = job.input_params["target_lufs"]

    with tempfile.TemporaryDirectory(prefix="acemusic-remaster-") as tmp_dir:
        workspace = _EditWorkspace(tmp_dir, native_format(source))
        await _download_source(storage, source, workspace)
        measurements = await asyncio.to_thread(
            remaster_audio,
            workspace.input_path,
            workspace.output_path,
            target_lufs=target_lufs,
        )
        output = workspace.output_path.read_bytes()

    clip = await _store_derived_clip(
        job,
        source,
        storage,
        output,
        duration=source.duration,
        bpm=source.bpm,
    )
    return {
        "clip_ids": [str(clip.id)],
        # measure_lufs returns numpy float64; cast so the result is BSON-safe.
        "before_lufs": float(measurements["before_lufs"]),
        "after_lufs": float(measurements["after_lufs"]),
    }


EDIT_JOB_HANDLERS = {
    CROP_JOB_TYPE: process_crop_job,
    SPEED_JOB_TYPE: process_speed_job,
    REMASTER_JOB_TYPE: process_remaster_job,
}
