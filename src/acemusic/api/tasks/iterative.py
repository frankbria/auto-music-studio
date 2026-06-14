"""Iterative generation job handlers (US-10.3).

One worker per iterative mode (extend, cover, remix, repaint, mashup, sample,
add-vocal). Each handler runs a claimed
:class:`~acemusic.api.models.job.Job`: download the source clip(s) from storage
into a temp file, submit the corresponding ACE-Step task (the same ``task_type``
and parameters the CLI commands use), poll for completion, download the result,
apply any local post-processing (repaint stitches the regenerated window back
into the original; sample combines the extracted loop with the generated track),
and store the output as a new child :class:`~acemusic.api.models.clip.Clip` with
lineage back to its source(s).

Unlike the editing/extraction handlers (which need only ``(job, storage)``),
these are generative and need the ACE-Step client and the processor's poll loop,
so they are adapted onto the registry through ``JobProcessor._run_iterative_handler``
which injects ``storage``, ``client`` and ``poll``.

Every child clip records ``parent_clip_ids`` (the source(s)), ``generation_mode``
(the job type) and ``generation_params`` (the verbatim request) so an operation
can be reproduced from its output; ``bpm``/``key``/``vocal_language`` are inherited
from the primary source. A failure after the audio object is uploaded but before
(or during) the clip insert rolls the object back, so a failed job leaves no
orphaned storage objects or clip rows.

The source audio is handed to ACE-Step as a worker-local ``src_audio_path``, so
ACE-Step must run on the same host (or with shared-filesystem access) as the API
worker — the same constraint the CLI iterative commands document. Remote /
cross-container ACE-Step deployments are not yet supported (a deferred story);
under such a deployment these jobs fail after the credit has been deducted.
"""

from __future__ import annotations

import asyncio
import io
import logging
import tempfile
from collections.abc import Awaitable, Callable
from functools import partial
from pathlib import Path
from typing import Any

from beanie import PydanticObjectId
from pydub import AudioSegment

from acemusic.audio import calculate_speed_multiplier, combine_sample, crop_audio, crossfade_stitch, time_stretch_audio
from acemusic.client import AceStepClient
from acemusic.storage import StorageBackend
from acemusic.utils import parse_time_string, slice_audio

from ..models import Clip, Job
from ..services.clips import native_format
from ..services.iterative import (
    ADD_VOCAL_JOB_TYPE,
    COVER_JOB_TYPE,
    EXTEND_JOB_TYPE,
    MASHUP_JOB_TYPE,
    REMIX_JOB_TYPE,
    REPAINT_JOB_TYPE,
    SAMPLE_JOB_TYPE,
)

logger = logging.getLogger(__name__)

# Seam between the repaint window and the surrounding original audio.
_REPAINT_CROSSFADE_MS = 50

# Sentinel for "inherit the primary's key" so callers can distinguish that from an
# explicit ``key=None`` override (a key-mismatched mashup is unconstrained).
_INHERIT = "__inherit__"

# Role-specific prompt prefixes for the sample endpoint (mirrors the CLI's
# ``_ROLE_PROMPT_PREFIX``); kept here so the worker has no CLI/typer dependency.
_ROLE_PROMPT_PREFIX = {
    "loop-bed": "Create a track that works as an overlay on top of a repeating loop.",
    "intro-outro": "Create a track that transitions smoothly from and back to a musical phrase.",
    "rhythmic-element": "Create a track with space for a recurring rhythmic sample.",
    "melodic-hook": "Create a track that follows and develops from a melodic hook.",
}

# A poll callable matching ``JobProcessor._poll_until_complete``.
PollFn = Callable[[AceStepClient, str], Awaitable[dict[str, Any]]]


class IterativeProcessingError(Exception):
    """An iterative-generation job could not be processed."""


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


async def _load_clip(clip_id: str) -> Clip:
    """Resolve a source clip by id, or fail the job with a clear error.

    A source clip may legitimately vanish between enqueue and processing (the
    owner can DELETE it while the job is queued), so a miss is a job failure,
    not a crash (mirrors the extraction handlers).
    """
    try:
        oid = PydanticObjectId(clip_id)
    except Exception as exc:
        raise IterativeProcessingError(f"Job has an invalid source clip id: {clip_id!r}") from exc
    clip = await Clip.get(oid)
    if clip is None:
        raise IterativeProcessingError(f"Source clip {clip_id} no longer exists")
    return clip


async def _download(storage: StorageBackend, clip: Clip, dest: Path) -> None:
    try:
        data = await asyncio.to_thread(storage.download, clip.file_path)
    except FileNotFoundError as exc:
        raise IterativeProcessingError(f"Source clip {clip.id} audio object {clip.file_path!r} is missing") from exc
    dest.write_bytes(data)


def _source_prompt(clip: Clip, fallback: str) -> str:
    """Build a text prompt describing ``clip`` from its style tags / title."""
    if clip.style_tags:
        return ", ".join(clip.style_tags)
    return clip.title or fallback


def _style_tags(style: str | None) -> list[str] | None:
    """Effective ``style_tags`` for a child: ``[style]`` when set, else inherit (None)."""
    return [style] if style else None


async def _submit_and_download(
    client: AceStepClient,
    poll: PollFn,
    submit_kwargs: dict[str, Any],
    *,
    expected: int = 1,
) -> list[bytes]:
    """Submit one ACE-Step task, poll to completion, return the downloaded audio."""
    task_id = await asyncio.to_thread(partial(client.submit_task, **submit_kwargs))
    result = await poll(client, task_id)
    if result.get("status") == "failed":
        raise IterativeProcessingError(result.get("error") or "ACE-Step task failed")
    audio_urls = result.get("audio_urls") or []
    if len(audio_urls) < expected:
        raise IterativeProcessingError(f"ACE-Step returned {len(audio_urls)} clip(s) but {expected} were expected")
    return [await asyncio.to_thread(client.download_audio, url) for url in audio_urls[:expected]]


async def _store_child_clip(
    job: Job,
    *,
    data: bytes,
    fmt: str,
    duration: float | None,
    parent_ids: list[PydanticObjectId],
    primary: Clip,
    storage: StorageBackend,
    title: str | None = None,
    key: str | None = _INHERIT,
    style_tags: list[str] | None = None,
    lyrics: str | None = _INHERIT,
) -> str:
    """Upload one output and insert its lineage-tagged child Clip.

    ``key``/``lyrics`` default to inheriting the primary's; pass an explicit value
    (including ``None``) to override — e.g. a key-mismatched mashup is generated
    without a key constraint, so its child must not claim the primary's key.
    ``style_tags``/``lyrics`` should carry the *effective* style/lyrics the clip
    was generated with (not the source's), so a later chained operation reads the
    right metadata via ``_source_prompt`` instead of falling back to a generic
    prompt. ``style_tags=None`` inherits the primary's tags.

    Rolls the uploaded object back if the insert fails, so a job that ends up
    ``failed`` never leaves an orphaned storage object behind (mirrors the
    generate / editing paths' rollback).
    """
    clip_id = PydanticObjectId()
    path = f"{job.user_id}/{job.workspace_id}/clips/{clip_id}.{fmt}"
    await asyncio.to_thread(storage.upload, path, data)
    clip = Clip(
        id=clip_id,
        user_id=job.user_id,
        workspace_id=job.workspace_id,
        file_path=path,
        title=title,
        format=fmt,
        duration=duration,
        bpm=primary.bpm,
        key=primary.key if key is _INHERIT else key,
        style_tags=list(primary.style_tags) if style_tags is None else style_tags,
        lyrics=primary.lyrics if lyrics is _INHERIT else lyrics,
        vocal_language=primary.vocal_language,
        parent_clip_ids=parent_ids,
        generation_mode=job.job_type,
        generation_params=dict(job.input_params or {}),
    )
    try:
        await clip.insert()
    except BaseException:
        try:
            await asyncio.to_thread(storage.delete, path)
        except Exception:  # pragma: no cover - cleanup is best-effort
            logger.exception("Failed to delete orphaned storage object %s during rollback", path)
        raise
    return str(clip_id)


async def _rollback_children(storage: StorageBackend, clip_ids: list[str]) -> None:
    """Best-effort removal of child clips (docs + audio objects) already stored.

    Used by multi-output modes (sample) so a failure partway through the batch
    does not leave earlier children behind for a job that ends up ``failed``.
    """
    for clip_id in clip_ids:
        clip = await Clip.get(PydanticObjectId(clip_id))
        if clip is None:  # pragma: no cover - already gone
            continue
        try:
            await asyncio.to_thread(storage.delete, clip.file_path)
        except Exception:  # pragma: no cover - cleanup is best-effort
            logger.exception("Failed to delete orphaned storage object %s during rollback", clip.file_path)
        await clip.delete()


def _decode(data: bytes, fmt: str) -> AudioSegment:
    """Decode audio bytes, passing ``format`` so pydub never shells out to ffprobe."""
    return AudioSegment.from_file(io.BytesIO(data), format=fmt)


# ---------------------------------------------------------------------------
# Single-source generative handlers (extend / cover / remix / add-vocal)
# ---------------------------------------------------------------------------


async def process_extend_job(job: Job, *, storage: StorageBackend, client: AceStepClient, poll: PollFn) -> dict:
    """Grow the source by ``duration`` from ``from_point`` (ACE-Step ``repaint``)."""
    params = dict(job.input_params or {})
    source = await _load_clip(params["clip_id"])
    if source.duration is None:
        raise IterativeProcessingError(f"Source clip {source.id} has no duration metadata")
    fmt = native_format(source)
    duration_s = parse_time_string(params["duration"]) / 1000.0
    from_point = params.get("from_point", "end")
    from_s = source.duration if from_point == "end" else parse_time_string(from_point) / 1000.0
    target_duration = from_s + duration_s

    with tempfile.TemporaryDirectory(prefix="acemusic-extend-") as tmp:
        src_path = Path(tmp) / f"source.{fmt}"
        await _download(storage, source, src_path)
        # When extending from a mid-clip point, trim the source to that prefix so
        # ACE-Step continues from the splice and never sees the discarded tail
        # (mirrors the CLI extend path's slice_audio step).
        api_src = src_path
        if from_point != "end" and from_s < source.duration:
            trimmed = Path(tmp) / f"trimmed.{fmt}"
            await asyncio.to_thread(slice_audio, src_path, from_s, trimmed)
            api_src = trimmed
        data = await _submit_and_download(
            client,
            poll,
            {
                "prompt": _source_prompt(source, "continue the song"),
                "num_clips": 1,
                "audio_duration": target_duration,
                "format": fmt,
                "style": params.get("style_override"),
                "lyrics": params.get("lyrics"),
                "bpm": source.bpm,
                "key": source.key,
                "seed": source.seed,
                "task_type": "repaint",
                "src_audio_path": str(api_src.resolve()),
                "repainting_start": from_s,
                "repainting_end": target_duration,
            },
        )
    extend_lyrics = params.get("lyrics")
    clip_id = await _store_child_clip(
        job,
        data=data[0],
        fmt=fmt,
        duration=target_duration,
        parent_ids=[source.id],
        primary=source,
        storage=storage,
        style_tags=_style_tags(params.get("style_override")),
        lyrics=extend_lyrics if extend_lyrics is not None else _INHERIT,
    )
    return {"clip_ids": [clip_id]}


async def _process_restyle_job(
    job: Job,
    *,
    storage: StorageBackend,
    client: AceStepClient,
    poll: PollFn,
    style: str,
    lyrics: str | None,
) -> dict:
    """Shared cover/remix path: ACE-Step ``cover`` at the source's length."""
    params = dict(job.input_params or {})
    source = await _load_clip(params["clip_id"])
    fmt = native_format(source)
    effective_lyrics = lyrics if lyrics is not None else source.lyrics
    with tempfile.TemporaryDirectory(prefix="acemusic-restyle-") as tmp:
        src_path = Path(tmp) / f"source.{fmt}"
        await _download(storage, source, src_path)
        data = await _submit_and_download(
            client,
            poll,
            {
                "prompt": style,
                "num_clips": 1,
                "audio_duration": source.duration,
                "format": fmt,
                "style": style,
                "lyrics": effective_lyrics,
                "bpm": source.bpm,
                "key": source.key,
                "seed": source.seed,
                "task_type": "cover",
                "src_audio_path": str(src_path.resolve()),
            },
        )
    clip_id = await _store_child_clip(
        job,
        data=data[0],
        fmt=fmt,
        duration=source.duration,
        parent_ids=[source.id],
        primary=source,
        storage=storage,
        # The restyle changed the style (and possibly lyrics); record the
        # effective values so a chained op reads the new style, not the source's.
        style_tags=[style],
        lyrics=effective_lyrics,
    )
    return {"clip_ids": [clip_id]}


async def process_cover_job(job: Job, *, storage: StorageBackend, client: AceStepClient, poll: PollFn) -> dict:
    """Restyle the source in a new genre (ACE-Step ``cover``)."""
    params = dict(job.input_params or {})
    return await _process_restyle_job(
        job,
        storage=storage,
        client=client,
        poll=poll,
        style=params["style"],
        lyrics=params.get("lyrics_override"),
    )


async def process_remix_job(job: Job, *, storage: StorageBackend, client: AceStepClient, poll: PollFn) -> dict:
    """Style transfer (ACE-Step ``cover``; see Design Choice 2). Preserves source lyrics."""
    params = dict(job.input_params or {})
    return await _process_restyle_job(
        job,
        storage=storage,
        client=client,
        poll=poll,
        style=params["style"],
        lyrics=None,
    )


async def process_add_vocal_job(job: Job, *, storage: StorageBackend, client: AceStepClient, poll: PollFn) -> dict:
    """Layer vocals onto the source (ACE-Step ``complete``)."""
    params = dict(job.input_params or {})
    source = await _load_clip(params["clip_id"])
    fmt = native_format(source)
    with tempfile.TemporaryDirectory(prefix="acemusic-vocal-") as tmp:
        src_path = Path(tmp) / f"source.{fmt}"
        await _download(storage, source, src_path)
        data = await _submit_and_download(
            client,
            poll,
            {
                "prompt": _source_prompt(source, "layer vocals over the instrumental"),
                "num_clips": 1,
                "audio_duration": source.duration,
                "format": fmt,
                "style": params.get("vocal_style"),
                "lyrics": params["lyrics"],
                "vocal_language": source.vocal_language,
                "bpm": source.bpm,
                "key": source.key,
                "seed": source.seed,
                "task_type": "complete",
                "src_audio_path": str(src_path.resolve()),
            },
        )
    clip_id = await _store_child_clip(
        job,
        data=data[0],
        fmt=fmt,
        duration=source.duration,
        parent_ids=[source.id],
        primary=source,
        storage=storage,
        # Record the vocal style and the added lyrics so they survive chaining.
        style_tags=_style_tags(params.get("vocal_style")),
        lyrics=params["lyrics"],
    )
    return {"clip_ids": [clip_id]}


# ---------------------------------------------------------------------------
# Repaint — regenerate a window and stitch it back into the original
# ---------------------------------------------------------------------------


async def process_repaint_job(job: Job, *, storage: StorageBackend, client: AceStepClient, poll: PollFn) -> dict:
    """Regenerate ``[start, end]`` and crossfade it back into the original audio."""
    params = dict(job.input_params or {})
    source = await _load_clip(params["clip_id"])
    fmt = native_format(source)
    start_ms = int(params["start_ms"])
    end_ms = int(params["end_ms"])

    with tempfile.TemporaryDirectory(prefix="acemusic-repaint-") as tmp:
        src_path = Path(tmp) / f"source.{fmt}"
        await _download(storage, source, src_path)
        original_bytes = src_path.read_bytes()
        data = await _submit_and_download(
            client,
            poll,
            {
                "prompt": params["prompt"],
                "num_clips": 1,
                "audio_duration": source.duration,
                "format": fmt,
                "style": params.get("style"),
                "bpm": source.bpm,
                "key": source.key,
                "seed": source.seed,
                "task_type": "repaint",
                "src_audio_path": str(src_path.resolve()),
                "repainting_start": start_ms / 1000.0,
                "repainting_end": end_ms / 1000.0,
            },
        )

    original = _decode(original_bytes, fmt)
    repaint_full = _decode(data[0], fmt)
    if len(repaint_full) < end_ms - 10:
        raise IterativeProcessingError(
            f"ACE-Step output is {len(repaint_full)}ms but the repaint window ends at {end_ms}ms"
        )
    before = original[:start_ms]
    middle = repaint_full[start_ms:end_ms]
    after = original[end_ms:]
    stitched = crossfade_stitch(before, middle, after, fade_ms=_REPAINT_CROSSFADE_MS)
    out = io.BytesIO()
    stitched.export(out, format=fmt)

    clip_id = await _store_child_clip(
        job,
        data=out.getvalue(),
        fmt=fmt,
        duration=len(stitched) / 1000.0,
        parent_ids=[source.id],
        primary=source,
        storage=storage,
        # A repaint may restyle the window; record the style when given, else
        # inherit. Lyrics are unchanged, so inherit the source's.
        style_tags=_style_tags(params.get("style")),
    )
    return {"clip_ids": [clip_id]}


# ---------------------------------------------------------------------------
# Mashup — blend two or more sources into one
# ---------------------------------------------------------------------------


async def process_mashup_job(job: Job, *, storage: StorageBackend, client: AceStepClient, poll: PollFn) -> dict:
    """Blend all sources via ACE-Step ``mashup``; lineage tracks every source.

    ACE-Step's ``mashup`` takes one source plus one reference. The primary
    (``clip_ids[0]``) is the source; the remaining clips are mixed down (overlaid)
    into a single reference so every requested clip contributes to the blend
    rather than being silently dropped. All sources are recorded in
    ``parent_clip_ids``/``generation_params``.
    """
    params = dict(job.input_params or {})
    clip_ids: list[str] = params["clip_ids"]
    sources = [await _load_clip(cid) for cid in clip_ids]
    primary, secondaries = sources[0], sources[1:]
    fmt = native_format(primary)
    style = params.get("style")
    # Submit without a key constraint when any secondary's key disagrees with the
    # primary, rather than falsely asserting the primary's key (mirrors the CLI).
    submitted_key = primary.key
    if primary.key and any(s.key and s.key != primary.key for s in secondaries):
        submitted_key = None
    titles = [t for t in (primary.title, *(s.title for s in secondaries)) if t]
    prompt = style or (f"mashup of {' and '.join(titles)}" if titles else "mashup")

    with tempfile.TemporaryDirectory(prefix="acemusic-mashup-") as tmp:
        tmp_path = Path(tmp)
        primary_path = tmp_path / f"primary.{fmt}"
        await _download(storage, primary, primary_path)
        ref_path = await _build_mashup_reference(storage, secondaries, tmp_path, fmt, primary.bpm)
        data = await _submit_and_download(
            client,
            poll,
            {
                "prompt": prompt,
                "num_clips": 1,
                "audio_duration": primary.duration,
                "format": fmt,
                "style": style,
                "bpm": primary.bpm,
                "key": submitted_key,
                "task_type": "mashup",
                "src_audio_path": str(primary_path.resolve()),
                "ref_audio_path": str(ref_path.resolve()),
                "blend_mode": params.get("blend_mode", "layered"),
            },
        )

    clip_id = await _store_child_clip(
        job,
        data=data[0],
        fmt=fmt,
        duration=primary.duration,
        parent_ids=[s.id for s in sources],
        primary=primary,
        storage=storage,
        # Match what was generated: a key-mismatched mashup was submitted
        # unconstrained, so its child must not claim the primary's key.
        key=submitted_key,
        # Record the mashup style when given, else inherit the primary's tags.
        style_tags=_style_tags(style),
    )
    return {"clip_ids": [clip_id]}


async def _build_mashup_reference(
    storage: StorageBackend, secondaries: list[Clip], tmp_path: Path, fmt: str, primary_bpm: int | None
) -> Path:
    """Mix every secondary source into a single reference track (overlaid).

    Each secondary is BPM-aligned to ``primary_bpm`` before mixing (matching the
    CLI mashup path), so mismatched tempos do not produce an off-beat reference.
    With one secondary this is just that (aligned) clip; with several, they are
    layered so the blend incorporates all of them. Written as ``fmt`` to ``tmp_path``.
    """
    mixed: AudioSegment | None = None
    for index, clip in enumerate(secondaries):
        clip_fmt = native_format(clip)
        clip_path = tmp_path / f"secondary-{index}.{clip_fmt}"
        await _download(storage, clip, clip_path)
        aligned_path = await _align_to_bpm(clip_path, clip.bpm, primary_bpm, tmp_path, index)
        segment = _decode(aligned_path.read_bytes(), clip_fmt)
        if mixed is None:
            mixed = segment
        elif len(segment) > len(mixed):
            # overlay() keeps the *base* length, so always overlay the shorter
            # onto the longer — otherwise a later, longer secondary's tail is
            # silently truncated and that source wouldn't fully contribute.
            mixed = segment.overlay(mixed)
        else:
            mixed = mixed.overlay(segment)
    ref_path = tmp_path / f"reference.{fmt}"
    # ``secondaries`` is guaranteed non-empty (the API requires >= 2 sources), but
    # raise explicitly rather than assert: asserts are stripped under ``python -O``,
    # which would turn an unexpected empty list into an opaque AttributeError.
    if mixed is None:
        raise IterativeProcessingError("mashup has no secondary sources to build a reference from")
    mixed.export(ref_path, format=fmt)
    return ref_path


async def _align_to_bpm(
    src_path: Path, src_bpm: int | None, target_bpm: int | None, tmp_path: Path, index: int
) -> Path:
    """Time-stretch ``src_path`` to ``target_bpm``, or return it unchanged.

    Skips alignment when either BPM is unknown/invalid or already equal, and
    falls back to the original on a stretch failure (mirrors the CLI's
    ``_align_clips_bpm``).
    """
    if not src_bpm or not target_bpm or src_bpm <= 0 or target_bpm <= 0 or src_bpm == target_bpm:
        return src_path
    rate = calculate_speed_multiplier(float(src_bpm), float(target_bpm))
    aligned_path = tmp_path / f"aligned-{index}{src_path.suffix}"
    try:
        await asyncio.to_thread(time_stretch_audio, str(src_path), str(aligned_path), rate)
    except Exception:
        logger.warning("BPM alignment failed for %s; using the original clip", src_path, exc_info=True)
        return src_path
    return aligned_path


# ---------------------------------------------------------------------------
# Sample — extract a loop and build num_clips tracks around it
# ---------------------------------------------------------------------------


def _build_sample_prompt(base_prompt: str, role: str, sample_duration_sec: float) -> str:
    """Role-aware prompt for the generated track (mirrors the CLI helper)."""
    prefix = _ROLE_PROMPT_PREFIX.get(role, "")
    duration_hint = f"The reference sample is about {sample_duration_sec:.1f}s long."
    return f"{prefix} {duration_hint} {base_prompt}".strip()


async def process_sample_job(job: Job, *, storage: StorageBackend, client: AceStepClient, poll: PollFn) -> dict:
    """Extract ``[start, end]``, generate ``num_clips`` tracks, combine each per role.

    Only the ACE-Step backend reaches the worker — the router rejects the
    ``elevenlabs`` backend at enqueue time. Children are stored as the batch
    progresses; a failure partway through rolls back the ones already created so
    a ``failed`` job leaves no orphaned clips or storage objects behind.
    """
    params = dict(job.input_params or {})
    source = await _load_clip(params["clip_id"])
    fmt = native_format(source)
    start_ms = int(params["start_ms"])
    end_ms = int(params["end_ms"])
    role = params["role"]
    num_clips = int(params.get("num_clips", 1))
    sample_duration_sec = (end_ms - start_ms) / 1000.0
    prompt = _build_sample_prompt(params["prompt"], role, sample_duration_sec)

    clip_ids: list[str] = []
    with tempfile.TemporaryDirectory(prefix="acemusic-sample-") as tmp:
        tmp_path = Path(tmp)
        src_path = tmp_path / f"source.{fmt}"
        await _download(storage, source, src_path)
        sample_path = tmp_path / f"sample.{fmt}"
        await asyncio.to_thread(
            crop_audio, input_path=str(src_path), output_path=str(sample_path), start_ms=start_ms, end_ms=end_ms
        )
        generated = await _submit_and_download(
            client,
            poll,
            {"prompt": prompt, "num_clips": num_clips, "format": fmt},
            expected=num_clips,
        )
        try:
            for index, gen_bytes in enumerate(generated, start=1):
                gen_path = tmp_path / f"generated-{index}.{fmt}"
                gen_path.write_bytes(gen_bytes)
                out_path = tmp_path / f"combined-{index}.{fmt}"
                await asyncio.to_thread(
                    combine_sample,
                    sample_path=str(sample_path),
                    generated_path=str(gen_path),
                    output_path=str(out_path),
                    role=role,
                )
                combined = out_path.read_bytes()
                duration = len(_decode(combined, fmt)) / 1000.0
                clip_id = await _store_child_clip(
                    job,
                    data=combined,
                    fmt=fmt,
                    duration=duration,
                    parent_ids=[source.id],
                    primary=source,
                    storage=storage,
                )
                clip_ids.append(clip_id)
        except BaseException:
            # BaseException (not Exception): a shutdown CancelledError must also
            # roll back, else a requeued retry duplicates the stored children.
            await _rollback_children(storage, clip_ids)
            raise
    return {"clip_ids": clip_ids}


ITERATIVE_JOB_HANDLERS: dict[str, Callable[..., Awaitable[dict]]] = {
    EXTEND_JOB_TYPE: process_extend_job,
    COVER_JOB_TYPE: process_cover_job,
    REMIX_JOB_TYPE: process_remix_job,
    REPAINT_JOB_TYPE: process_repaint_job,
    MASHUP_JOB_TYPE: process_mashup_job,
    SAMPLE_JOB_TYPE: process_sample_job,
    ADD_VOCAL_JOB_TYPE: process_add_vocal_job,
}
