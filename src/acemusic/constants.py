"""Shared generation-parameter constants (validation bounds and enumerations).

Single source of truth for the parameter ranges and allowed values used by both
the CLI (:mod:`acemusic.cli`) and the platform API (:mod:`acemusic.api`).
Centralising them keeps CLI flag validation and API request-schema validation
from drifting apart as new surfaces are added.
"""

from __future__ import annotations

# ACE-Step model registry (US-3.4).
# Keys map directly to the --model flag value and the API's ``model`` field.
# All fields are rendered in ``acemusic models`` output.
MODELS: dict[str, dict[str, str]] = {
    "turbo": {
        "description": "Fastest generation; best for quick drafts and iteration",
        "vram": "~2.4GB",
        "steps": "8",
        "dit_size": "2B",
    },
    "base": {
        "description": "Balanced quality/speed; general-purpose generation",
        "vram": "~2.4GB",
        "steps": "32-64",
        "dit_size": "2B",
    },
    "sft": {
        "description": "Fine-tuned on supervised data; improved coherence",
        "vram": "~2.4GB",
        "steps": "32-64",
        "dit_size": "2B",
    },
    "xl-base": {
        "description": "Highest quality; best for professional-grade output",
        "vram": "~8GB",
        "steps": "32-64",
        "dit_size": "4B",
    },
    "xl-sft": {
        "description": "XL fine-tuned; premium quality with improved coherence",
        "vram": "~8GB",
        "steps": "32-64",
        "dit_size": "4B",
    },
    "xl-turbo": {
        "description": "Fast XL generation; high quality with reduced steps",
        "vram": "~8GB",
        "steps": "8",
        "dit_size": "4B",
    },
}
VALID_MODELS: frozenset[str] = frozenset(MODELS.keys())

# Tempo bounds (BPM) — ACE-Step native range.
BPM_MIN = 60
BPM_MAX = 180

# Track duration bounds (seconds) for the ACE-Step backend.
DURATION_MIN = 30.0
DURATION_MAX = 240.0

# Output audio container formats.
VALID_FORMATS: frozenset[str] = frozenset({"wav", "flac", "mp3", "aac", "opus"})

# Supported meters.
VALID_TIME_SIGNATURES: frozenset[str] = frozenset({"4/4", "3/4", "6/8", "5/4", "7/8"})

# Creative-control ranges (0-100), ACE-Step only.
WEIRDNESS_MIN = 0
WEIRDNESS_MAX = 100
STYLE_INFLUENCE_MIN = 0
STYLE_INFLUENCE_MAX = 100

# Creation modes and the sound sub-types valid when ``mode == "sound"``.
VALID_MODES: frozenset[str] = frozenset({"song", "sound"})
VALID_SOUND_TYPES: frozenset[str] = frozenset({"one-shot", "loop"})
