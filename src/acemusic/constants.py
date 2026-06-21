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

VALID_TIME_SIGNATURES: frozenset[str] = frozenset({"4/4", "3/4", "6/8", "5/4", "7/8"})

# Creative-control ranges (0-100), ACE-Step only.
WEIRDNESS_MIN = 0
WEIRDNESS_MAX = 100
STYLE_INFLUENCE_MIN = 0
STYLE_INFLUENCE_MAX = 100

# Diffusion inference steps. Models run 8-64 steps (see MODELS); this is a
# generous upper guard so an API request cannot persist an absurd value.
INFERENCE_STEPS_MAX = 500

# Creation modes and the sound sub-types valid when ``mode == "sound"``.
VALID_MODES: frozenset[str] = frozenset({"song", "sound"})
VALID_SOUND_TYPES: frozenset[str] = frozenset({"one-shot", "loop"})

# Free-text field caps, shared by the API's generation and preset schemas.
# These fields are persisted verbatim (``Job.input_params``, preset documents)
# and re-read by the worker, so cap them: a single request must not be able to
# bloat a MongoDB document (16MB cap) and turn into a 500. Lyrics get the most
# headroom since a full song's words are legitimately long.
PROMPT_MAX_LENGTH = 2000
STYLE_MAX_LENGTH = 1000
LYRICS_MAX_LENGTH = 5000
VOCAL_LANGUAGE_MAX_LENGTH = 100
KEY_MAX_LENGTH = 50

# Seeds are opaque values forwarded to the backend; bound them to MongoDB's
# signed 64-bit integer range so an oversized value is a clean 422 rather than
# a BSON-encoding 500 when persisted.
SEED_MIN = -(2**63)
SEED_MAX = 2**63 - 1

# Cover art generation (US-13.1). DALL-E 3 emits 1024x1024; we upscale to a
# 3000x3000 distribution master (Spotify/Apple require >=3000). Uploads must meet
# that same floor in one of the accepted raster formats and stay under the cap so
# a single image can't exhaust worker memory or bloat storage.
ARTWORK_OPTIONS_COUNT = 4
ARTWORK_GENERATION_SIZE = 1024
ARTWORK_FINAL_SIZE = 3000
ARTWORK_MIN_RESOLUTION = 3000
ARTWORK_MAX_UPLOAD_BYTES = 25 * 1024 * 1024
# Decompression-bomb guard: a small compressed upload can decode to hundreds of MB.
# 50 megapixels (~7000x7000) is far above the 3000x3000 floor yet bounds the memory
# a single decode can allocate, so concurrent uploads can't exhaust the worker.
ARTWORK_MAX_PIXELS = 50_000_000
VALID_IMAGE_FORMATS: frozenset[str] = frozenset({"jpeg", "jpg", "png"})
ARTWORK_PROMPT_MAX_LENGTH = 2000
