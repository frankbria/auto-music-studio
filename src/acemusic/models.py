"""Data models for acemusic (US-4.2)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Clip:
    """Represents a generated audio clip with its full metadata."""

    workspace_id: str
    file_path: str
    created_at: str
    id: Optional[int] = None
    title: Optional[str] = None
    format: Optional[str] = None
    duration: Optional[float] = None
    bpm: Optional[int] = None
    key: Optional[str] = None
    style_tags: Optional[str] = None
    lyrics: Optional[str] = None
    vocal_language: Optional[str] = None
    model: Optional[str] = None
    seed: Optional[int] = None
    inference_steps: Optional[int] = None
    parent_clip_id: Optional[int] = None
    generation_mode: Optional[str] = None
