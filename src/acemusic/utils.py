"""Filename and audio duration utilities for acemusic (US-2.3, US-5.1)."""

from __future__ import annotations

import re
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


def snap_to_beat(time_ms: int | float, bpm: int | float) -> int:
    """Round time_ms to the nearest beat boundary for the given BPM.

    Returns the snapped time in milliseconds.
    """
    beat_ms = 60_000 / bpm
    return round(round(time_ms / beat_ms) * beat_ms)
