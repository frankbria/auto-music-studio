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
#: #695: every Pro capability plus the Enterprise-only ones, more credits, and a priority job queue.
ENTERPRISE = "enterprise"
PAID_TIERS = frozenset({PRO, ENTERPRISE})

#: Monthly credit allocation per tier (US-26.2). This is what a reset tops the balance
#: back up to on the subscription anniversary.
MONTHLY_CREDITS = {
    FREE: 50.0,
    PRO: 500.0,
    ENTERPRISE: 2500.0,
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
    VIDEO_4K = "video_4k"
    LOSSLESS_EXPORT = "lossless_export"


#: What each capability is called when explaining the lock, and why it is worth having.
#: The 403 body carries these, so a musician who hits one is told what to do about it
#: rather than just refused.
_DESCRIPTIONS = {
    Capability.STEMS: ("Stem separation", "split a track into vocals, drums, bass and other"),
    Capability.MIDI: ("MIDI extraction", "export melody, chords, drums and bass as MIDI"),
    # #403: covers the hosted services (/mastering/jobs, Dolby/LANDR/Bakuage) AND the
    # local loudness remaster on /clips/{id}/remaster. The description below is exactly
    # what remaster does, just locally — leaving it open made the other gate a formality.
    Capability.MASTERING: ("Mastering", "master your tracks to a professional loudness target"),
    # #403: covers both halves — "we publish it for you" (SoundCloud upload) and
    # "you publish it yourself, we assemble the bundle" (release prepare/submit).
    # Bundling is most of the value of distribution, so gating only the upload would
    # have left the free tier with nearly the whole feature.
    Capability.DISTRIBUTION: ("Distribution", "publish your releases to streaming platforms"),
    Capability.VOICE_MODELS: ("Custom voice models", "train a voice and sing your songs in it"),
    Capability.STUDIO_EDITING: ("Studio editing", "arrange and mix in the multi-track Studio"),
    Capability.HIGH_RES_VIDEO: ("1080p video", "render videos above 720p, without a watermark"),
    Capability.VIDEO_4K: ("4K video", "render videos in 4K"),
    Capability.LOSSLESS_EXPORT: ("Lossless export", "download WAV and FLAC as well as MP3"),
}

#: Everything in :class:`Capability` is Pro-only — the free tier is deliberately defined
#: by what it *lacks*, so adding a capability locks it by default rather than leaking it.
#: A future middle tier would turn this into a per-tier set.
_ENTERPRISE_ONLY = frozenset({Capability.VIDEO_4K})
_PRO_ONLY = frozenset(Capability) - _ENTERPRISE_ONLY


def normalise(tier: str | None) -> str:
    """The tier to actually apply.

    Anything that is not exactly ``"pro"`` or ``"enterprise"`` is free — the same rule the frontend uses. An
    unknown, missing or malformed tier must fail *closed*: a typo in a database field
    should not hand out a paid plan.
    """
    return tier if tier in PAID_TIERS else FREE


def is_paid(tier: str | None) -> bool:
    """Whether ``tier`` is a paid plan (Pro or Enterprise); unknown values are not."""
    return normalise(tier) in PAID_TIERS


def required_tier(capability: Capability) -> str:
    """The cheapest tier that may use ``capability``."""
    if capability in _ENTERPRISE_ONLY:
        return ENTERPRISE
    return PRO if capability in _PRO_ONLY else FREE


def allows(tier: str | None, capability: Capability) -> bool:
    """Whether ``tier`` may use ``capability``."""
    needed = required_tier(capability)
    effective = normalise(tier)
    return needed == FREE or effective == ENTERPRISE or (needed == PRO and effective == PRO)


def monthly_allocation(tier: str | None) -> float:
    """Credits this tier is topped up to each month."""
    return MONTHLY_CREDITS[normalise(tier)]


def describe(capability: Capability) -> tuple[str, str]:
    """``(name, benefit)`` for ``capability`` — what is locked, and what it would do."""
    return _DESCRIPTIONS[capability]
