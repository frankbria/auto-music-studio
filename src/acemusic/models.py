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


@dataclass
class Preset:
    """Represents a saved generation preset with style, lyrics, and parameters."""

    workspace_id: str
    name: str
    created_at: str
    id: Optional[int] = None
    style: Optional[str] = None
    lyrics: Optional[str] = None
    bpm: Optional[int] = None
    key: Optional[str] = None
    duration: Optional[int] = None
    model: Optional[str] = None
    seed: Optional[int] = None
    inference_steps: Optional[int] = None
    vocal_language: Optional[str] = None
    instrumental: Optional[int] = None  # 0=False, 1=True, None=not set
    quality: Optional[str] = None
    weirdness: Optional[float] = None
    style_influence: Optional[float] = None
    exclude_style: Optional[str] = None
    time_signature: Optional[str] = None
