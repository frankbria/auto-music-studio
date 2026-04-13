"""Filename and audio duration utilities for acemusic (US-2.3)."""

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
