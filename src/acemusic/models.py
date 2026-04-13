"""Data models for acemusic (US-4.2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Clip:
    """Represents a generated audio clip with its full metadata."""

    workspace_id: str
    file_path: str
    created_at: str
    id: Optional[int] = field(default=None)
    title: Optional[str] = field(default=None)
    format: Optional[str] = field(default=None)
    duration: Optional[float] = field(default=None)
    bpm: Optional[int] = field(default=None)
    key: Optional[str] = field(default=None)
    style_tags: Optional[str] = field(default=None)
    lyrics: Optional[str] = field(default=None)
    vocal_language: Optional[str] = field(default=None)
    model: Optional[str] = field(default=None)
    seed: Optional[int] = field(default=None)
    inference_steps: Optional[int] = field(default=None)
    parent_clip_id: Optional[int] = field(default=None)
    generation_mode: Optional[str] = field(default=None)
