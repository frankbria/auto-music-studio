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
from pathlib import Path
from typing import Any

from beanie import PydanticObjectId

from acemusic.midi_client import MIDI_OUTPUT_LABELS, MidiClient
from acemusic.stems_client import STEM_LABELS, StemsClient
from acemusic.storage import StorageBackend

from ..models import Clip, Job
from ..services.clips import native_format
from ..services.extraction import MIDI_JOB_TYPE, STEMS_JOB_TYPE

logger = logging.getLogger(__name__)

# Default sample rate if the stems client does not expose ``model_samplerate``
# (mirrors acemusic.daw_export); test doubles need not load a real model.
_DEFAULT_SAMPLE_RATE = 44100


class ExtractionProcessingError(Exception):
    """An extraction job could not be processed (missing source, ML failure)."""


async def _load_source_clip(job: Job) -> Clip:
    """Resolve the job's source clip, or fail the job with a clear error.

    The clip may legitimately vanish between enqueue and processing (the owner
    can DELETE it while the job is queued), so a miss is a job failure, not a
    crash (mirrors the editing handlers).
    """
    clip_id = (job.input_params or {}).get("clip_id")
    try:
        oid = PydanticObjectId(clip_id)
    except Exception as exc:
        raise ExtractionProcessingError(f"Job has an invalid source clip id: {clip_id!r}") from exc
    clip = await Clip.get(oid)
    if clip is None:
        raise ExtractionProcessingError(f"Source clip {clip_id} no longer exists")
    return clip


async def _download_source(storage: StorageBackend, source: Clip, dest: Path) -> None:
    try:
        data = await asyncio.to_thread(storage.download, source.file_path)
    except FileNotFoundError as exc:
        raise ExtractionProcessingError(
            f"Source clip {source.id} audio object {source.file_path!r} is missing"
        ) from exc
    dest.write_bytes(data)


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
    source = await _load_source_clip(job)

    with tempfile.TemporaryDirectory(prefix="acemusic-stems-") as tmp_dir:
        input_path = Path(tmp_dir) / f"source.{native_format(source)}"
        await _download_source(storage, source, input_path)
        stem_paths = await asyncio.to_thread(_separate_stems, input_path, Path(tmp_dir), str(source.id))
        # Read the produced stem bytes while the temp dir still exists, in the
        # canonical label order so the result is deterministic.
        produced = [(label, Path(stem_paths[label]).read_bytes()) for label in STEM_LABELS if label in stem_paths]

    if not produced:
        raise ExtractionProcessingError(f"Stem separation produced no output for clip {source.id}")

    clip_ids = await _store_stem_clips(job, source, storage, produced)
    return {"clip_ids": clip_ids}


async def _store_stem_clips(
    job: Job,
    source: Clip,
    storage: StorageBackend,
    produced: list[tuple[str, bytes]],
) -> list[str]:
    """Upload each stem and insert its child Clip; roll back on any failure."""
    clip_ids: list[str] = []
    stored: list[tuple[Clip, str]] = []
    try:
        for label, data in produced:
            clip_id = PydanticObjectId()
            path = f"{job.user_id}/{job.workspace_id}/clips/{clip_id}.wav"
            await asyncio.to_thread(storage.upload, path, data)
            clip = Clip(
                id=clip_id,
                user_id=job.user_id,
                workspace_id=job.workspace_id,
                file_path=path,
                title=label,
                format="wav",
                # Stems are the same length as the source mix (time-aligned).
                duration=source.duration,
                bpm=source.bpm,
                key=source.key,
                parent_clip_ids=[source.id],
                generation_mode=STEMS_JOB_TYPE,
            )
            await clip.insert()
            stored.append((clip, path))
            clip_ids.append(str(clip_id))
    except Exception:
        await _rollback_clips(storage, stored)
        raise
    return clip_ids


async def _rollback_clips(storage: StorageBackend, stored: list[tuple[Clip, str]]) -> None:
    """Best-effort cleanup of stem clips/files written before a mid-batch failure."""
    for clip, path in stored:
        try:
            await clip.delete()
        except Exception:  # pragma: no cover - cleanup is best-effort
            logger.exception("Failed to delete orphaned stem clip %s during rollback", clip.id)
        try:
            await asyncio.to_thread(storage.delete, path)
        except Exception:  # pragma: no cover - cleanup is best-effort
            logger.exception("Failed to delete orphaned storage object %s during rollback", path)


async def process_midi_job(job: Job, storage: StorageBackend) -> dict[str, Any]:
    """Extract MIDI from the source and store the files (not as clips).

    The uploaded ``.mid`` objects are referenced from the source clip's
    ``midi_paths`` map, which both caches the result and drives retrieval. A
    failure after some uploads cleans them up so a failed job leaves no orphans
    and never half-populates ``midi_paths``.
    """
    source = await _load_source_clip(job)
    bpm = float(source.bpm) if source.bpm is not None else 120.0

    with tempfile.TemporaryDirectory(prefix="acemusic-midi-") as tmp_dir:
        input_path = Path(tmp_dir) / f"source.{native_format(source)}"
        await _download_source(storage, source, input_path)
        midi_files = await asyncio.to_thread(_extract_midi, input_path, Path(tmp_dir), str(source.id), bpm)
        produced = [
            (label, Path(midi_files[label]).read_bytes()) for label in MIDI_OUTPUT_LABELS if label in midi_files
        ]

    if not produced:
        raise ExtractionProcessingError(f"MIDI extraction produced no output for clip {source.id}")

    midi_paths = await _store_midi_files(job, source, storage, produced)
    # Record the artifacts on the parent clip: this is the cache + retrieval
    # source. Use a targeted ``$set`` rather than a full ``save()``: the job can
    # run for minutes, during which the owner may have edited the clip (e.g.
    # renamed it); a full-document save of our stale copy would clobber that.
    await source.set({Clip.midi_paths: midi_paths})
    return {"midi_paths": midi_paths}


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
        for path in midi_paths.values():
            try:
                await asyncio.to_thread(storage.delete, path)
            except Exception:  # pragma: no cover - cleanup is best-effort
                logger.exception("Failed to delete orphaned MIDI object %s during rollback", path)
        raise
    return midi_paths


EXTRACTION_JOB_HANDLERS = {
    STEMS_JOB_TYPE: process_stems_job,
    MIDI_JOB_TYPE: process_midi_job,
}
