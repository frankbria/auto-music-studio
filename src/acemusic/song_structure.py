"""Song-structure planning for the full-song auto-extend pipeline (US-6.7).

Given a seed clip duration and a target total length, produces an ordered list
of sections describing how to grow the clip into a complete song. Pure
functions only: no I/O, no audio processing.
"""

from __future__ import annotations

from dataclasses import dataclass

SONG_STRUCTURE: list[str] = [
    "intro",
    "verse",
    "chorus",
    "verse",
    "chorus",
    "bridge",
    "outro",
]

# Per-section (relative_weight, style_hint).
# Weights are normalized across the full SONG_STRUCTURE list; each occurrence
# (e.g. the two verses, two choruses) contributes its weight independently.
SECTION_CONFIG: dict[str, tuple[float, str]] = {
    "intro": (1.0, "intro, atmospheric build, sparse arrangement"),
    "verse": (2.0, "verse, melodic, narrative groove"),
    "chorus": (2.0, "chorus, hook, energetic, full arrangement"),
    "bridge": (1.5, "bridge, transition, contrast and tension"),
    "outro": (1.0, "outro, fade and resolve"),
}

MIN_SECTION_SECONDS: float = 4.0


@dataclass(frozen=True)
class Section:
    """A planned section: what to generate, how long, with what style emphasis."""

    name: str
    duration_s: float
    style_hint: str


def plan_sections(seed_duration: float, target_duration: int | float) -> list[Section]:
    """Distribute (target_duration - seed_duration) across the seven canonical sections.

    Returns sections in canonical order (intro → outro). Each section receives
    a slice of the remaining time proportional to its configured weight.

    When there is enough headroom, each section is rounded up to
    MIN_SECTION_SECONDS so it produces an audible chunk. When the remainder is
    too small to honor the minimum across all sections, the floor is dropped
    and durations stay proportional to weights — so the planned total never
    overshoots ``target_duration``. Every section still gets a positive
    duration.

    Raises ValueError if target_duration is non-positive or shorter than the
    seed.
    """
    if target_duration <= 0:
        raise ValueError(f"target_duration must be positive, got {target_duration}")
    if target_duration <= seed_duration:
        raise ValueError(f"target_duration ({target_duration}s) must exceed seed_duration ({seed_duration}s)")

    remaining = float(target_duration) - float(seed_duration)
    weights = [SECTION_CONFIG[name][0] for name in SONG_STRUCTURE]
    total_weight = sum(weights)
    raw_durations = [remaining * (w / total_weight) for w in weights]

    # Only enforce the audible-section floor when remaining is large enough to
    # honor it for every section. Otherwise honoring the floor would overshoot
    # the user's target_duration — fall back to raw proportional distribution.
    if remaining >= len(weights) * MIN_SECTION_SECONDS:
        durations = [max(d, MIN_SECTION_SECONDS) for d in raw_durations]
    else:
        durations = raw_durations

    return [
        Section(name=name, duration_s=duration, style_hint=SECTION_CONFIG[name][1])
        for name, duration in zip(SONG_STRUCTURE, durations)
    ]
