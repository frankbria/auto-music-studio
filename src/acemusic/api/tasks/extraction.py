"""Extraction job handlers (US-10.2): stem-separation and MIDI workers.

Each handler runs one claimed extraction :class:`~acemusic.api.models.job.Job`:
download the source clip's audio from storage into a temp file, run the
corresponding CPU-bound CLI client (:class:`~acemusic.stems_client.StemsClient`
or :class:`~acemusic.midi_client.MidiClient`) in a worker thread, upload the
results, and record them.

* **Stems** become four child :class:`~acemusic.api.models.clip.Clip` records
  (``generation_mode="stems"``) with lineage back to the source, mirroring how
  the editing handlers store derived clips.
* **MIDI** files are *not* clips — they are uploaded as ``.mid`` objects and
  referenced from the source clip's ``midi_paths`` map, which is both the cache
  and the retrieval source.

Handlers receive the storage backend from the :class:`JobProcessor` (which owns
the factory seam) and return the dict persisted as ``job.result``; exceptions
propagate and the processor marks the job failed. The source clip — bytes and
document — is never modified except to attach ``midi_paths``.

``StemsClient`` and ``MidiClient`` are imported at module scope so tests can
substitute lightweight doubles without running the real demucs / basic-pitch
models (the extraction algorithms themselves are covered by US-5.3 / US-5.4).
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from beanie import PydanticObjectId
from beanie.operators import In

from acemusic.midi_client import MIDI_OUTPUT_LABELS, MidiClient
from acemusic.stems_client import STEM_LABELS, StemsClient
from acemusic.storage import StorageBackend

from ..models import Clip, Job
from ..services.clips import native_format
from ..services.extraction import MIDI_JOB_TYPE, STEMS_JOB_TYPE
from .common import JobProcessingError, download_clip, load_source_clip, rollback_clips, store_clip

logger = logging.getLogger(__name__)

# Default sample rate if the stems client does not expose ``model_samplerate``
# (mirrors acemusic.daw_export); test doubles need not load a real model.
_DEFAULT_SAMPLE_RATE = 44100


def _separate_stems(source_path: Path, output_dir: Path, base_name: str) -> dict[str, Path]:
    """Run demucs separation and write the stems (sync; called via ``to_thread``)."""
    client = StemsClient()
    stems = client.separate(source_path)
    sample_rate = getattr(client, "model_samplerate", _DEFAULT_SAMPLE_RATE)
    return client.save_stems(stems, output_dir, base_name, sample_rate=sample_rate, output_format="wav")


def _extract_midi(source_path: Path, output_dir: Path, base_name: str, bpm: float) -> dict[str, Path]:
    """Run basic-pitch extraction and write the MIDI files (sync; via ``to_thread``)."""
    client = MidiClient()
    extracted = client.extract(source_path)
    return client.save_midi(extracted, output_dir, base_name, bpm=bpm)


async def process_stems_job(job: Job, storage: StorageBackend) -> dict[str, Any]:
    """Separate the source into stems and store each as a linked child clip.

    A failure partway through (upload/insert error on a later stem) rolls back
    the clips and files already written, so a job that ends up ``failed`` never
    leaves orphaned ``Clip`` rows or storage objects behind (mirrors the
    generate path's rollback).
    """
    source = await load_source_clip(job)

    with tempfile.TemporaryDirectory(prefix="acemusic-stems-") as tmp_dir:
        input_path = Path(tmp_dir) / f"source.{native_format(source)}"
        input_path.write_bytes(await download_clip(storage, source))
        stem_paths = await asyncio.to_thread(_separate_stems, input_path, Path(tmp_dir), str(source.id))
        # Read the produced stem bytes while the temp dir still exists, in the
        # canonical label order so the result is deterministic.
        produced = [(label, Path(stem_paths[label]).read_bytes()) for label in STEM_LABELS if label in stem_paths]

    if not produced:
        raise JobProcessingError(f"Stem separation produced no output for clip {source.id}")

    # Re-extraction (only reached when the cached set is incomplete — a complete
    # set short-circuits in the router) replaces any leftover stem children so
    # the result is a single, complete set rather than a duplicated mix.
    await _delete_existing_stems(source, storage)

    clip_ids = await _store_stem_clips(job, source, storage, produced)
    return {"clip_ids": clip_ids}


async def _delete_existing_stems(source: Clip, storage: StorageBackend) -> None:
    """Remove any prior stem children of ``source`` (clip docs + audio objects)."""
    existing = await Clip.find(
        In(Clip.parent_clip_ids, [source.id]),
        Clip.generation_mode == STEMS_JOB_TYPE,
    ).to_list()
    for clip in existing:
        try:
            await asyncio.to_thread(storage.delete, clip.file_path)
        except Exception:  # pragma: no cover - cleanup is best-effort
            logger.exception("Failed to delete stale stem object %s", clip.file_path)
        await clip.delete()


async def _store_stem_clips(
    job: Job,
    source: Clip,
    storage: StorageBackend,
    produced: list[tuple[str, bytes]],
) -> list[str]:
    """Upload each stem and insert its child Clip; roll back on any failure.

    ``store_clip`` rolls back a stem whose own insert fails (its object is removed
    before raising); on that failure the already-inserted earlier stems are rolled
    back here, so a ``failed`` job leaves no orphaned clips or objects behind.
    """
    clip_ids: list[str] = []
    try:
        for label, data in produced:
            clip_id = PydanticObjectId()
            clip = Clip(
                id=clip_id,
                user_id=job.user_id,
                workspace_id=job.workspace_id,
                file_path=f"{job.user_id}/{job.workspace_id}/clips/{clip_id}.wav",
                title=label,
                format="wav",
                # Stems are the same length as the source mix (time-aligned).
                duration=source.duration,
                bpm=source.bpm,
                key=source.key,
                parent_clip_ids=[source.id],
                generation_mode=STEMS_JOB_TYPE,
            )
            await store_clip(storage, clip, data)
            clip_ids.append(str(clip_id))
    except Exception:
        await rollback_clips(storage, clip_ids)
        raise
    return clip_ids


async def process_midi_job(job: Job, storage: StorageBackend) -> dict[str, Any]:
    """Extract MIDI from the source and store the files (not as clips).

    The uploaded ``.mid`` objects are referenced from the source clip's
    ``midi_paths`` map, which both caches the result and drives retrieval. A
    failure after some uploads cleans them up so a failed job leaves no orphans
    and never half-populates ``midi_paths``.
    """
    source = await load_source_clip(job)
    bpm = float(source.bpm) if source.bpm is not None else 120.0

    with tempfile.TemporaryDirectory(prefix="acemusic-midi-") as tmp_dir:
        input_path = Path(tmp_dir) / f"source.{native_format(source)}"
        input_path.write_bytes(await download_clip(storage, source))
        midi_files = await asyncio.to_thread(_extract_midi, input_path, Path(tmp_dir), str(source.id), bpm)
        produced = [
            (label, Path(midi_files[label]).read_bytes()) for label in MIDI_OUTPUT_LABELS if label in midi_files
        ]

    if not produced:
        raise JobProcessingError(f"MIDI extraction produced no output for clip {source.id}")

    midi_paths = await _store_midi_files(job, source, storage, produced)
    # Record the artifacts on the parent clip: this is the cache + retrieval
    # source. Use a targeted ``$set`` rather than a full ``save()``: the job can
    # run for minutes, during which the owner may have edited the clip (e.g.
    # renamed it); a full-document save of our stale copy would clobber that.
    # If the update fails, the uploaded files would be unreferenced — delete them
    # so a failed job leaves no orphaned objects.
    try:
        await source.set({Clip.midi_paths: midi_paths})
    except Exception:
        await _delete_midi_objects(storage, midi_paths.values())
        raise
    return {"midi_paths": midi_paths}


async def _delete_midi_objects(storage: StorageBackend, paths: Iterable[str]) -> None:
    """Best-effort removal of uploaded MIDI objects (rollback / clip deletion)."""
    for path in paths:
        try:
            await asyncio.to_thread(storage.delete, path)
        except Exception:  # pragma: no cover - cleanup is best-effort
            logger.exception("Failed to delete orphaned MIDI object %s", path)


async def _store_midi_files(
    job: Job,
    source: Clip,
    storage: StorageBackend,
    produced: list[tuple[str, bytes]],
) -> dict[str, str]:
    """Upload each MIDI file under the per-clip midi prefix; roll back on failure."""
    midi_paths: dict[str, str] = {}
    try:
        for label, data in produced:
            path = f"{job.user_id}/{job.workspace_id}/clips/{source.id}/midi/{label}.mid"
            await asyncio.to_thread(storage.upload, path, data)
            midi_paths[label] = path
    except Exception:
        await _delete_midi_objects(storage, list(midi_paths.values()))
        raise
    return midi_paths


EXTRACTION_JOB_HANDLERS = {
    STEMS_JOB_TYPE: process_stems_job,
    MIDI_JOB_TYPE: process_midi_job,
}
