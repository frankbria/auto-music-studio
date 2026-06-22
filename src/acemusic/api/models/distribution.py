"""Distribution status enums and the per-channel transition rules (US-13.6).

A release goes out to several *channels* (SoundCloud directly, plus the guided
LANDR/DistroKid/TuneCore targets from US-13.5). Each channel carries its own
:class:`DistributionStatus`, tracked independently in ``Release.channel_statuses``
— distinct from the release-level :class:`acemusic.api.models.release.ReleaseStatus`
because a channel also has an ``in_review`` state (a platform is processing the
upload) that the release lifecycle has no equivalent for.

These live in the models layer because they are field *types* on the Release
document; the business logic that uses them (validation, notifications) lives in
:mod:`acemusic.api.services.distribution_status`.
"""

from enum import Enum


class DistributionStatus(str, Enum):
    """Per-channel distribution lifecycle: ``draft → ready → submitted → in_review → live | rejected``."""

    DRAFT = "draft"
    READY = "ready"
    SUBMITTED = "submitted"
    IN_REVIEW = "in_review"
    LIVE = "live"
    REJECTED = "rejected"


class VisibilityState(str, Enum):
    """How widely a release is shared. Maps onto SoundCloud's public/private sharing."""

    PRIVATE = "private"
    UNLISTED = "unlisted"
    PUBLIC = "public"


#: The one channel whose status is driven automatically (SoundCloud polling).
SOUNDCLOUD_CHANNEL = "soundcloud"

#: Channels whose status the owner updates by hand — they have no API integration,
#: so the platform can only record what the user reports. Mirrors US-13.5's
#: ``DistributionTarget`` (landr/distrokid/tunecore).
GUIDED_CHANNELS: frozenset[str] = frozenset({"landr", "distrokid", "tunecore"})

#: Allowed next statuses for each status. Terminal states (live, rejected) map to
#: an empty set, so no transition out of them is permitted. Enforces the sequence
#: in the AC: no skipping (e.g. draft → live is rejected).
VALID_STATUS_TRANSITIONS: dict[DistributionStatus, frozenset[DistributionStatus]] = {
    DistributionStatus.DRAFT: frozenset({DistributionStatus.READY}),
    DistributionStatus.READY: frozenset({DistributionStatus.SUBMITTED}),
    DistributionStatus.SUBMITTED: frozenset({DistributionStatus.IN_REVIEW}),
    DistributionStatus.IN_REVIEW: frozenset({DistributionStatus.LIVE, DistributionStatus.REJECTED}),
    DistributionStatus.LIVE: frozenset(),
    DistributionStatus.REJECTED: frozenset(),
}
