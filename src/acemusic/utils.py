"""Filename and audio duration utilities for acemusic (US-2.3, US-5.1, US-6.5)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path


def make_slug(prompt: str, max_len: int = 40) -> str:
    """Convert a prompt string to a URL/filename-safe slug.

    Lowercases, replaces spaces with hyphens, strips non-alphanumeric characters,
    collapses consecutive hyphens, and truncates to `max_len`.
    """
    slug = prompt.lower()
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"[^a-z0-9\-]", "", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[:max_len]


def make_filename(slug: str, timestamp: str, index: int, ext: str = "wav") -> str:
    """Build a descriptive output filename from slug, timestamp, and clip index."""
    return f"{slug}-{timestamp}-{index}.{ext}"


def get_duration(path: Path | str) -> float | None:
    """Return the duration in seconds of an audio file using mutagen, or None on failure."""
    import mutagen

    audio = mutagen.File(str(path))
    if audio is None:
        return None
    return audio.info.length


# ---------------------------------------------------------------------------
# Time parsing utilities (US-5.1)
# ---------------------------------------------------------------------------

_TIME_PATTERN = re.compile(r"^(?:(?P<minutes>\d+)m)?(?P<seconds>\d+(?:\.\d+)?)s$|^(?P<plain>\d+(?:\.\d+)?)$")


def parse_time_string(time_str: str) -> int:
    """Parse a human-readable time string into milliseconds.

    Supported formats: "10s", "1m30s", "1.5s", "90s", "5" (plain seconds).
    Returns milliseconds as an integer.
    Raises ValueError for invalid or negative input.
    """
    if not time_str:
        raise ValueError(f"Cannot parse time string: {time_str!r}")

    m = _TIME_PATTERN.match(time_str.strip())
    if not m:
        raise ValueError(f"Cannot parse time string: {time_str!r}")

    if m.group("plain") is not None:
        seconds = float(m.group("plain"))
    else:
        minutes = int(m.group("minutes") or 0)
        seconds = float(m.group("seconds"))
        seconds += minutes * 60

    return int(round(seconds * 1000))


def generate_remaster_filename(original_path: Path) -> Path:
    """Generate a remaster output filename in the same directory as the original.

    Produces: {stem}-remaster-{timestamp}.{ext}
    """
    from datetime import datetime

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return original_path.parent / f"{original_path.stem}-remaster-{timestamp}{original_path.suffix}"


def snap_to_beat(time_ms: int | float, bpm: int | float) -> int:
    """Round time_ms to the nearest beat boundary for the given BPM.

    Returns the snapped time in milliseconds.
    """
    beat_ms = 60_000 / bpm
    return round(round(time_ms / beat_ms) * beat_ms)


# ---------------------------------------------------------------------------
# Audio manipulation utilities (US-6.1)
# ---------------------------------------------------------------------------


def concatenate_audio(original_path: Path | str, extension_path: Path | str, output_path: Path | str) -> Path:
    """Concatenate two audio files end-to-end and write the result to output_path.

    The sample rate of the first file is preserved. If the second file has a
    different sample rate it is resampled to match.

    Returns the output path.
    Raises FileNotFoundError if either input is missing, or RuntimeError on read failure.
    """
    import numpy as np
    import soundfile as sf

    original_path = Path(original_path)
    extension_path = Path(extension_path)
    output_path = Path(output_path)

    if not original_path.exists():
        raise FileNotFoundError(f"Original audio file not found: {original_path}")
    if not extension_path.exists():
        raise FileNotFoundError(f"Extension audio file not found: {extension_path}")

    a_data, a_sr = sf.read(str(original_path))
    b_data, b_sr = sf.read(str(extension_path))

    if b_sr != a_sr:
        import librosa

        if b_data.ndim > 1:
            # librosa expects (channels, samples)
            b_data = librosa.resample(b_data.T, orig_sr=b_sr, target_sr=a_sr).T
        else:
            b_data = librosa.resample(b_data, orig_sr=b_sr, target_sr=a_sr)

    # Align channel counts (mono → stereo if needed). Only one branch can fire
    # because the outer guard requires the two ndims differ.
    if a_data.ndim != b_data.ndim:
        if a_data.ndim == 1:
            a_data = np.column_stack([a_data, a_data])
        elif b_data.ndim == 1:
            b_data = np.column_stack([b_data, b_data])

    joined = np.concatenate([a_data, b_data], axis=0)
    sf.write(str(output_path), joined, a_sr)
    return output_path


def slice_audio(input_path: Path | str, head_seconds: float, output_path: Path | str) -> Path:
    """Trim an audio file to the first head_seconds and write it to output_path.

    Used by the extend command to truncate the source when --from <timestamp>
    is supplied so the model only sees audio up to the splice point.

    Returns the output path.
    Raises ValueError when head_seconds is non-positive or exceeds the input duration.
    Raises FileNotFoundError if the input is missing.
    """
    import soundfile as sf

    if head_seconds <= 0:
        raise ValueError(f"head_seconds must be positive, got {head_seconds}")

    input_path = Path(input_path)
    output_path = Path(output_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Input audio file not found: {input_path}")

    data, sr = sf.read(str(input_path))
    total_samples = data.shape[0]
    requested_samples = int(round(head_seconds * sr))

    if requested_samples > total_samples:
        actual_duration = total_samples / sr
        raise ValueError(f"head_seconds ({head_seconds}) exceeds input duration ({actual_duration:.3f}s)")

    sliced = data[:requested_samples]
    sf.write(str(output_path), sliced, sr)
    return output_path


# ---------------------------------------------------------------------------
# Sample attribution metadata (US-6.5)
# ---------------------------------------------------------------------------


def write_sample_metadata(
    output_audio_path: Path | str,
    *,
    source_clip_id: int | None,
    source_file: str,
    start_ms: int,
    end_ms: int,
    role: str,
    prompt: str,
    backend: str,
) -> Path:
    """Write a ``{filename}.meta.json`` sidecar describing a sample's provenance.

    The sidecar lives next to the audio file. Tooling can read it later to trace
    the new clip back to its source range and the user's intent (role, prompt).
    Returns the path to the written sidecar.
    """
    output_audio_path = Path(output_audio_path)
    metadata = {
        "source_clip_id": source_clip_id,
        "source_file": source_file,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "role": role,
        "prompt": prompt,
        "backend": backend,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    sidecar = output_audio_path.with_name(output_audio_path.name + ".meta.json")
    sidecar.write_text(json.dumps(metadata, indent=2))
    return sidecar
