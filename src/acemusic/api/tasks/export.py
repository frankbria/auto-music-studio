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

``export_audio`` requires ffmpeg to decode the source and encode the target
(flac/mp3/24-bit wav); on a server without ffmpeg the job fails with a clear
error. The source may be any format the API can generate (wav/flac/mp3/aac/opus)
— ffmpeg reads them all — so the temp input keeps the source's real extension to
give pydub the right decode hint.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

from acemusic.audio import EXPORT_FORMATS, export_audio
from acemusic.storage import StorageBackend

from ..models import Job
from ..services.clips import native_format
from .common import JobProcessingError, download_clip, load_source_clip

# Container/extension each export format is written to (wav32 is a wav variant).
_FORMAT_EXTENSIONS = {"wav": "wav", "wav32": "wav", "flac": "flac", "mp3": "mp3"}


async def process_export_job(job: Job, storage: StorageBackend) -> dict[str, Any]:
    """Transcode the source clip to the requested format and store the file."""
    fmt = (job.input_params or {}).get("format")
    if fmt not in EXPORT_FORMATS:
        raise JobProcessingError(f"Unsupported export format: {fmt!r}. Expected one of {EXPORT_FORMATS}.")

    source = await load_source_clip(job)
    src_ext = native_format(source)

    ext = _FORMAT_EXTENSIONS[fmt]
    with tempfile.TemporaryDirectory(prefix="acemusic-export-") as tmp_dir:
        # Keep the source's real extension so export_audio's pydub decode hint
        # (derived from the suffix) matches the actual format.
        input_path = Path(tmp_dir) / f"source.{src_ext}"
        await asyncio.to_thread(input_path.write_bytes, await download_clip(storage, source))
        dest_path = Path(tmp_dir) / f"export.{ext}"
        await asyncio.to_thread(export_audio, input_path, dest_path, fmt)
        data = await asyncio.to_thread(dest_path.read_bytes)

    export_path = f"{job.user_id}/{job.workspace_id}/exports/{job.id}.{ext}"
    await asyncio.to_thread(storage.upload, export_path, data)
    return {"export_path": export_path, "format": fmt}


EXPORT_JOB_HANDLERS = {
    "export": process_export_job,
}
