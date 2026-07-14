"""Studio export job handlers (US-19.6): render a mixdown, or bundle DAW stems.

Both handlers take the ``(job, storage)`` contract the processor's storage-handler
wrapper expects. They read the whole arrangement from ``job.input_params`` (the
Studio has no backend arrangement persistence), download every referenced source
clip once, then:

* :func:`process_studio_mixdown_job` mixes the arrangement to one file, converts
  it to the requested delivery format via :func:`acemusic.audio.export_audio`, and
  stores it as a ``generation_mode="studio"`` child clip (lineage
  ``parent_clip_ids`` = the distinct source clips) — auditionable through the
  generic job-status endpoint via ``result["clip_ids"]``.
* :func:`process_studio_daw_export_job` bounces one silence-padded WAV stem per
  track (gain/pan recorded in ``project.json``, not baked in), assembles the
  ``<Slug>_Export/`` ZIP, and uploads it to the per-job export key served by
  ``GET /studio/export/daw/{id}``.

Blocking audio work (pydub mix, ffmpeg conversion, ZIP assembly) runs in a worker
thread; progress is surfaced on ``job.progress`` for the polling UI.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

from beanie import PydanticObjectId

from acemusic.storage import StorageBackend
from acemusic.studio_mixdown import (
    PlacementMix,
    StudioTrackFile,
    TrackMix,
    arrangement_duration,
    assemble_studio_bundle,
    export_mix,
    mixdown_arrangement,
    render_track_timeline,
)

from ..models import Clip, Job
from ..services.clips import native_format
from ..services.studio import (
    STUDIO_DAW_EXPORT_JOB_TYPE,
    STUDIO_MIXDOWN_JOB_TYPE,
    studio_export_storage_path,
)
from .common import download_clip, load_clip, store_clip


async def _download_sources(job: Job, storage: StorageBackend, tmp: Path) -> tuple[dict[str, Path], list[Clip]]:
    """Download each distinct referenced clip to a temp WAV; return path map + loaded clips.

    Order-preserving over first placement occurrence, so lineage
    (``parent_clip_ids``) is deterministic. A clip deleted between enqueue and
    processing fails the job via :func:`load_clip`.
    """
    tracks = (job.input_params or {}).get("tracks", [])
    ordered_ids: list[str] = []
    seen: set[str] = set()
    for track in tracks:
        for placement in track.get("placements", []):
            cid = placement.get("clip_id")
            if cid and cid not in seen:
                seen.add(cid)
                ordered_ids.append(cid)

    clip_local: dict[str, Path] = {}
    clips: list[Clip] = []
    for cid in ordered_ids:
        clip = await load_clip(cid)
        dest = tmp / f"src-{cid}.{native_format(clip)}"
        data = await download_clip(storage, clip)
        await asyncio.to_thread(dest.write_bytes, data)
        clip_local[cid] = dest
        clips.append(clip)
    return clip_local, clips


def _build_track_mixes(tracks: list[dict], clip_local: dict[str, Path]) -> list[TrackMix]:
    """Map arrangement track dicts to :class:`TrackMix` with resolved local paths."""
    mixes: list[TrackMix] = []
    for track in tracks:
        placements = [
            PlacementMix(
                audio_path=clip_local[p["clip_id"]],
                start_sec=float(p.get("start_sec", 0.0)),
                duration_sec=p.get("duration_sec"),
            )
            for p in track.get("placements", [])
            if p.get("clip_id") in clip_local
        ]
        mixes.append(
            TrackMix(
                placements=placements,
                volume_db=float(track.get("volume_db", 0.0)),
                pan=float(track.get("pan", 0.0)),
                muted=bool(track.get("muted", False)),
                solo=bool(track.get("solo", False)),
            )
        )
    return mixes


def _render_mixdown(track_mixes: list[TrackMix], fmt: str, tmp: Path) -> tuple[bytes, float]:
    """Mix to WAV, convert to ``fmt``, return the bytes and the arrangement duration (sync)."""
    duration = arrangement_duration(track_mixes)
    raw = tmp / "mix.wav"
    mixdown_arrangement(track_mixes, output_path=raw, total_duration_sec=duration)
    final = tmp / f"mix.{fmt}"
    export_mix(raw, final, fmt)
    return final.read_bytes(), duration


async def process_studio_mixdown_job(job: Job, storage: StorageBackend) -> dict[str, Any]:
    """Render the arrangement to one clip (``generation_mode="studio"``) and store it."""
    params = dict(job.input_params or {})
    fmt = params.get("format", "wav")
    project_name = params.get("project_name") or "Studio Export"
    bpm = params.get("bpm")

    with tempfile.TemporaryDirectory(prefix="acemusic-studio-mix-") as tmp_dir:
        tmp = Path(tmp_dir)
        await job.set({Job.progress: "Downloading tracks"})
        clip_local, clips = await _download_sources(job, storage, tmp)

        await job.set({Job.progress: "Mixing"})
        track_mixes = _build_track_mixes(params.get("tracks", []), clip_local)
        data, duration = await asyncio.to_thread(_render_mixdown, track_mixes, fmt, tmp)

        await job.set({Job.progress: "Uploading"})
        clip_id = PydanticObjectId()
        clip = Clip(
            id=clip_id,
            user_id=job.user_id,
            workspace_id=job.workspace_id,
            file_path=f"{job.user_id}/{job.workspace_id}/clips/{clip_id}.{fmt}",
            title=project_name,
            format=fmt,
            duration=duration,
            bpm=int(round(bpm)) if bpm else None,
            parent_clip_ids=[c.id for c in clips],
            generation_mode="studio",
            generation_params=params,
        )
        await store_clip(storage, clip, data)

    return {"clip_ids": [str(clip_id)]}


def _assemble_bundle(tracks: list[dict], track_mixes: list[TrackMix], project_name, bpm, markers, tmp: Path) -> bytes:
    """Bounce per-track stems, assemble the DAW ZIP, return its bytes (sync)."""
    duration = arrangement_duration(track_mixes)
    track_files: list[StudioTrackFile] = []
    for index, (track, mix) in enumerate(zip(tracks, track_mixes)):
        stem_path = tmp / f"stem-{index}.wav"
        render_track_timeline(mix.placements, output_path=stem_path, total_duration_sec=duration)
        track_files.append(
            StudioTrackFile(
                name=track.get("name") or f"Track {index + 1}",
                audio_path=stem_path,
                volume_db=float(track.get("volume_db", 0.0)),
                pan=float(track.get("pan", 0.0)),
            )
        )
    zip_local = tmp / "bundle.zip"
    assemble_studio_bundle(
        project_name=project_name,
        bpm=bpm,
        duration_seconds=duration,
        tracks=track_files,
        markers=markers,
        output_path=zip_local,
    )
    return zip_local.read_bytes()


async def process_studio_daw_export_job(job: Job, storage: StorageBackend) -> dict[str, Any]:
    """Bounce per-track stems into a DAW ZIP and upload it to the per-job export key."""
    params = dict(job.input_params or {})
    project_name = params.get("project_name") or "Studio Export"
    bpm = params.get("bpm")
    markers = params.get("markers", [])
    tracks = params.get("tracks", [])

    with tempfile.TemporaryDirectory(prefix="acemusic-studio-daw-") as tmp_dir:
        tmp = Path(tmp_dir)
        await job.set({Job.progress: "Downloading tracks"})
        clip_local, _ = await _download_sources(job, storage, tmp)

        await job.set({Job.progress: "Bundling"})
        track_mixes = _build_track_mixes(tracks, clip_local)
        data = await asyncio.to_thread(_assemble_bundle, tracks, track_mixes, project_name, bpm, markers, tmp)

        await job.set({Job.progress: "Uploading"})
        export_path = studio_export_storage_path(job.user_id, job.workspace_id, job.id)
        await asyncio.to_thread(storage.upload, export_path, data)

    return {"export_path": export_path}


STUDIO_JOB_HANDLERS = {
    STUDIO_MIXDOWN_JOB_TYPE: process_studio_mixdown_job,
    STUDIO_DAW_EXPORT_JOB_TYPE: process_studio_daw_export_job,
}
