"""DAW-export job handler (US-14.1): assemble a DAW-ready ZIP for a clip.

Resolves the source clip's four stems and four MIDI files — reusing the cached
extraction artifacts when a complete set is present, otherwise running the same
stem/MIDI workers the extraction endpoints (US-10.2) use — downloads them
alongside the full mix, and assembles the canonical bundle ZIP via
:func:`acemusic.daw_export.assemble_daw_bundle`. The ZIP is uploaded to a
predictable per-clip ``exports/{clip_id}_daw.zip`` key (the GET endpoint serves
it directly) and the storage key is returned as ``export_path``.

Reusing :func:`~acemusic.api.tasks.extraction.process_stems_job` /
:func:`~acemusic.api.tasks.extraction.process_midi_job` means extraction is
cached and rolled back exactly as a direct extraction call would be — there is
no second copy of the stems/MIDI pipeline to keep in sync. A complete cached set
short-circuits both, so a re-export of an already-extracted clip neither
re-separates nor re-extracts.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

from beanie.operators import In

from acemusic.daw_export import assemble_daw_bundle
from acemusic.midi_client import MIDI_OUTPUT_LABELS
from acemusic.stems_client import STEM_LABELS
from acemusic.storage import StorageBackend

from ..models import Clip, Job
from ..services.clips import native_format
from ..services.daw_export import DAW_EXPORT_JOB_TYPE
from ..services.extraction import STEMS_JOB_TYPE
from .common import download_clip, load_clip, load_source_clip
from .extraction import process_midi_job, process_stems_job


async def _stem_children(clip_id: object) -> dict[str, Clip]:
    """The source's stem child clips, keyed by stem label (newest per label)."""
    children = await Clip.find(
        In(Clip.parent_clip_ids, [clip_id]),
        Clip.generation_mode == STEMS_JOB_TYPE,
    ).to_list()
    by_label: dict[str, Clip] = {}
    for child in children:
        if child.title in STEM_LABELS and child.title not in by_label:
            by_label[child.title] = child
    return by_label


def _midi_complete(clip: Clip) -> bool:
    """True when ``clip.midi_paths`` holds all four MIDI labels (a usable cache)."""
    paths = clip.midi_paths or {}
    return all(label in paths for label in MIDI_OUTPUT_LABELS)


async def process_daw_export_job(job: Job, storage: StorageBackend) -> dict[str, Any]:
    """Resolve stems + MIDI (reusing the cache), assemble the bundle, store it."""
    source = await load_source_clip(job)

    # Stems: reuse a complete cached set, else run the stems worker (which
    # deletes any partial set and stores a fresh, complete one), then re-read.
    stems = await _stem_children(source.id)
    if len(stems) < len(STEM_LABELS):
        await process_stems_job(job, storage)
        stems = await _stem_children(source.id)

    # MIDI: reuse cached ``midi_paths``, else run the MIDI worker (which sets
    # ``midi_paths`` on its own freshly-loaded copy — reload to pick it up).
    if not _midi_complete(source):
        await process_midi_job(job, storage)
        source = await load_clip(str(source.id))

    with tempfile.TemporaryDirectory(prefix="acemusic-daw-") as tmp_dir:
        tmp = Path(tmp_dir)

        full_mix = tmp / f"full_mix.{native_format(source)}"
        await asyncio.to_thread(full_mix.write_bytes, await download_clip(storage, source))

        stem_paths: dict[str, Path] = {}
        for label, child in stems.items():
            dest = tmp / f"stem-{label}.wav"
            await asyncio.to_thread(dest.write_bytes, await download_clip(storage, child))
            stem_paths[label] = dest

        midi_paths: dict[str, Path] = {}
        for label, key in (source.midi_paths or {}).items():
            dest = tmp / f"midi-{label}.mid"
            data = await asyncio.to_thread(storage.download, key)
            await asyncio.to_thread(dest.write_bytes, data)
            midi_paths[label] = dest

        zip_local = tmp / "bundle.zip"
        await asyncio.to_thread(
            assemble_daw_bundle,
            source,
            full_mix_path=full_mix,
            stem_paths=stem_paths,
            midi_paths=midi_paths,
            output_path=zip_local,
        )
        data = await asyncio.to_thread(zip_local.read_bytes)

    export_path = f"{job.user_id}/{job.workspace_id}/exports/{source.id}_daw.zip"
    await asyncio.to_thread(storage.upload, export_path, data)
    return {"export_path": export_path}


DAW_EXPORT_JOB_HANDLERS = {
    DAW_EXPORT_JOB_TYPE: process_daw_export_job,
}
