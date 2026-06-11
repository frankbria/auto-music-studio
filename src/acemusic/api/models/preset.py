"""Preset document model (US-9.5).

A preset is a user-owned, named snapshot of generation parameters. The
parameter fields mirror :class:`~acemusic.api.routers.generation.GenerationRequest`
(every creative knob the generate endpoint accepts) and are all optional — a
preset stores only what the user chose to pin down. Applying a preset to a
generation request happens in the generation router (preset values as
defaults, explicitly-sent request values win).
"""

from datetime import datetime
from typing import Literal

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, IndexModel

from .common import utcnow


class Preset(Document):
    """A user-owned generation parameter snapshot."""

    name: str
    user_id: PydanticObjectId
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime | None = None

    # Generation parameters — same names and shapes as GenerationRequest.
    style: str | None = None
    lyrics: str | None = None
    vocal_language: str | None = None
    instrumental: bool | None = None
    bpm: int | Literal["auto"] | None = None
    key: str | None = None
    time_signature: str | None = None
    duration: float | None = None
    seed: int | None = None
    inference_steps: int | None = None
    model: str | None = None
    weirdness: int | None = None
    style_influence: int | None = None
    format: str | None = None
    thinking: bool | None = None
    mode: Literal["song", "sound"] | None = None
    sound_type: Literal["one-shot", "loop"] | None = None

    class Settings:
        name = "presets"
        indexes = [
            IndexModel([("user_id", ASCENDING)]),
            # Preset names are unique per user: create and rename rely on this
            # index for race-safe 409s (same pattern as Workspace).
            IndexModel([("user_id", ASCENDING), ("name", ASCENDING)], unique=True),
        ]


# The parameter fields a preset can contribute to a generation request, i.e.
# every field above except identity/bookkeeping. The generation router uses
# this to build the merge base.
PRESET_PARAM_FIELDS: tuple[str, ...] = (
    "style",
    "lyrics",
    "vocal_language",
    "instrumental",
    "bpm",
    "key",
    "time_signature",
    "duration",
    "seed",
    "inference_steps",
    "model",
    "weirdness",
    "style_influence",
    "format",
    "thinking",
    "mode",
    "sound_type",
)
