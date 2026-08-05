"""Subscription tiers and what each one unlocks (US-26.2).

One place that answers "may this tier do this?", so the API and the UI cannot drift into
disagreeing — the frontend badges and the backend 403 both derive from this table.

**The UI gating is decoration; this is the enforcement.** Before this module no endpoint
checked the tier at all, so a free account that called ``POST /clips/{id}/stems`` directly
got stems. A Pro badge in a dropdown stops an honest user, not a curious one.

Kept free of I/O and of ``HTTPException`` like the other service modules: it is a pure
lookup, so the rules are testable without a request, a database, or a user.
"""

from enum import Enum

FREE = "free"
PRO = "pro"

#: Monthly credit allocation per tier (US-26.2). This is what a reset tops the balance
#: back up to on the subscription anniversary.
MONTHLY_CREDITS = {
    FREE: 50.0,
    PRO: 500.0,
}


class Capability(str, Enum):
    """A thing a musician might do that the tier table has an opinion about.

    Named for the *capability* rather than the endpoint, because several endpoints can
    gate on the same one (single and batch mastering) and one endpoint can gate on
    different ones depending on its arguments (video resolution, export format).
    """

    STEMS = "stems"
    MIDI = "midi"
    MASTERING = "mastering"
    DISTRIBUTION = "distribution"
    VOICE_MODELS = "voice_models"
    STUDIO_EDITING = "studio_editing"
    HIGH_RES_VIDEO = "high_res_video"
    LOSSLESS_EXPORT = "lossless_export"


#: What each capability is called when explaining the lock, and why it is worth having.
#: The 403 body carries these, so a musician who hits one is told what to do about it
#: rather than just refused.
_DESCRIPTIONS = {
    Capability.STEMS: ("Stem separation", "split a track into vocals, drums, bass and other"),
    Capability.MIDI: ("MIDI extraction", "export melody, chords, drums and bass as MIDI"),
    Capability.MASTERING: ("Mastering", "master your tracks to a professional loudness target"),
    Capability.DISTRIBUTION: ("Distribution", "publish your releases to streaming platforms"),
    Capability.VOICE_MODELS: ("Custom voice models", "train a voice and sing your songs in it"),
    Capability.STUDIO_EDITING: ("Studio editing", "arrange and mix in the multi-track Studio"),
    Capability.HIGH_RES_VIDEO: ("1080p and 4K video", "render videos above 720p, without a watermark"),
    Capability.LOSSLESS_EXPORT: ("Lossless export", "download WAV and FLAC as well as MP3"),
}

#: Everything in :class:`Capability` is Pro-only — the free tier is deliberately defined
#: by what it *lacks*, so adding a capability locks it by default rather than leaking it.
#: A future middle tier would turn this into a per-tier set.
_PRO_ONLY = frozenset(Capability)


def normalise(tier: str | None) -> str:
    """The tier to actually apply.

    Anything that is not exactly ``"pro"`` is free — the same rule the frontend uses. An
    unknown, missing or malformed tier must fail *closed*: a typo in a database field
    should not hand out Pro.
    """
    return PRO if tier == PRO else FREE


def allows(tier: str | None, capability: Capability) -> bool:
    """Whether ``tier`` may use ``capability``."""
    return normalise(tier) == PRO or capability not in _PRO_ONLY


def monthly_allocation(tier: str | None) -> float:
    """Credits this tier is topped up to each month."""
    return MONTHLY_CREDITS[normalise(tier)]


def describe(capability: Capability) -> tuple[str, str]:
    """``(name, benefit)`` for ``capability`` — what is locked, and what it would do."""
    return _DESCRIPTIONS[capability]
