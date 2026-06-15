"""Export job handler (US-10.5): the batch-export worker.

Runs one claimed ``export`` :class:`~acemusic.api.models.job.Job`: download the
source clip's audio from storage into a temp file, transcode it to the requested
format with :func:`acemusic.audio.export_audio` (ffmpeg, via a worker thread),
upload the result under the per-user ``exports/`` prefix, and record its storage
key. The exported file is an *object*, not a clip — it is referenced from the
job result (``export_path``) and surfaced as a download URL by the batch-status
endpoint, mirroring how MIDI extraction records ``midi_paths``.

The handler shares the editing/extraction ``(job, storage)`` contract, so the
:class:`~acemusic.api.tasks.processor.JobProcessor` adapts it the same way. The
source clip — bytes and document — is never modified.

``export_audio`` requires ffmpeg to encode flac/mp3/24-bit wav; on a server
without ffmpeg the job fails with a clear error (the source clips themselves are
wav, matching the extraction endpoints' wav-only constraint).
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

from beanie import PydanticObjectId

from acemusic.audio import EXPORT_FORMATS, export_audio
from acemusic.storage import StorageBackend

from ..models import Clip, Job
from ..services.clips import native_format

# Container/extension each export format is written to (wav32 is a wav variant).
_FORMAT_EXTENSIONS = {"wav": "wav", "wav32": "wav", "flac": "flac", "mp3": "mp3"}


class ExportProcessingError(Exception):
    """An export job could not be processed (missing source, bad format)."""


async def _load_source_clip(job: Job) -> Clip:
    """Resolve the job's source clip, or fail the job with a clear error.

    The clip may legitimately vanish between enqueue and processing (the owner
    can DELETE it while the job is queued), so a miss is a job failure, not a
    crash (mirrors the extraction handlers).
    """
    clip_id = (job.input_params or {}).get("clip_id")
    try:
        oid = PydanticObjectId(clip_id)
    except Exception as exc:
        raise ExportProcessingError(f"Job has an invalid source clip id: {clip_id!r}") from exc
    clip = await Clip.get(oid)
    if clip is None:
        raise ExportProcessingError(f"Source clip {clip_id} no longer exists")
    return clip


async def _download_source(storage: StorageBackend, source: Clip, dest: Path) -> None:
    try:
        data = await asyncio.to_thread(storage.download, source.file_path)
    except FileNotFoundError as exc:
        raise ExportProcessingError(f"Source clip {source.id} audio object {source.file_path!r} is missing") from exc
    dest.write_bytes(data)


async def process_export_job(job: Job, storage: StorageBackend) -> dict[str, Any]:
    """Transcode the source clip to the requested format and store the file."""
    fmt = (job.input_params or {}).get("format")
    if fmt not in EXPORT_FORMATS:
        raise ExportProcessingError(f"Unsupported export format: {fmt!r}. Expected one of {EXPORT_FORMATS}.")

    source = await _load_source_clip(job)
    src_fmt = native_format(source)
    if src_fmt != "wav":
        # The transcode reads the source through pydub/ffmpeg, which needs ffmpeg
        # for compressed inputs (absent on the server). Generated clips are wav;
        # gate here so a bad job fails fast (mirrors the extraction endpoints).
        raise ExportProcessingError(f"unsupported source format {src_fmt!r} for export; only wav is supported.")

    ext = _FORMAT_EXTENSIONS[fmt]
    with tempfile.TemporaryDirectory(prefix="acemusic-export-") as tmp_dir:
        input_path = Path(tmp_dir) / "source.wav"
        await _download_source(storage, source, input_path)
        dest_path = Path(tmp_dir) / f"export.{ext}"
        await asyncio.to_thread(export_audio, input_path, dest_path, fmt)
        data = dest_path.read_bytes()

    export_path = f"{job.user_id}/{job.workspace_id}/exports/{job.id}.{ext}"
    await asyncio.to_thread(storage.upload, export_path, data)
    return {"export_path": export_path, "format": fmt}


EXPORT_JOB_HANDLERS = {
    "export": process_export_job,
}
