"""Per-channel distribution status logic (US-13.6).

The state machine and notification side of distribution tracking: validating a
channel's status transition, applying it to a release, and recording a
notification event when a channel reaches a terminal state (``live``/``rejected``).

Two callers, two contracts:

* **Manual guided updates** (router) go through :func:`apply_channel_status` with
  validation on, so a user cannot skip the sequence (e.g. draft → live).
* **SoundCloud polling** (the poller) reflects *authoritative external* state, so
  it applies with ``validate=False`` — the platform's real track state is the
  truth and isn't forced through intermediate steps.
"""

from pymongo import ReturnDocument

from ..models import NotificationEvent
from ..models.common import utcnow
from ..models.distribution import (
    VALID_STATUS_TRANSITIONS,
    DistributionStatus,
)
from ..models.release import Release

#: Statuses no further transition leaves; reaching one is notification-worthy.
TERMINAL_STATUSES: frozenset[DistributionStatus] = frozenset({DistributionStatus.LIVE, DistributionStatus.REJECTED})


class InvalidStatusTransition(Exception):
    """A requested status transition violates the valid sequence."""

    def __init__(self, current: DistributionStatus, target: DistributionStatus) -> None:
        self.current = current
        self.target = target
        super().__init__(f"Cannot move a channel from {current.value!r} to {target.value!r}.")


def validate_status_transition(current: DistributionStatus, target: DistributionStatus) -> bool:
    """True if ``current → target`` is an allowed step in the distribution sequence."""
    return target in VALID_STATUS_TRANSITIONS.get(current, frozenset())


async def apply_channel_status(
    release: Release,
    channel: str,
    new_status: DistributionStatus,
    *,
    validate: bool = True,
) -> DistributionStatus:
    """Set ``channel``'s status on ``release`` and persist; return the *previous* status.

    A channel with no recorded status is treated as ``draft`` (the implicit start),
    so the first manual update must begin the sequence. With ``validate=True`` an
    out-of-sequence step raises :class:`InvalidStatusTransition`; the SoundCloud
    poller passes ``validate=False`` to mirror real platform state verbatim.
    """
    current = DistributionStatus(release.channel_statuses.get(channel, DistributionStatus.DRAFT))
    if validate and not validate_status_transition(current, new_status):
        raise InvalidStatusTransition(current, new_status)

    # Atomic per-channel $set guarded by the observed current state (mirrors the
    # atomic claims in ``services.releases``): a concurrent update to a *different*
    # channel isn't clobbered by a full-document save, and only one writer wins a
    # given transition — so terminal notifications can't be duplicated.
    field = f"channel_statuses.{channel}"
    guard = {field: current.value} if channel in release.channel_statuses else {field: {"$exists": False}}
    doc = await Release.get_pymongo_collection().find_one_and_update(
        {"_id": release.id, **guard},
        {"$set": {field: new_status.value, "updated_at": utcnow()}},
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        # Lost the race: another writer already moved this channel. Reflect the
        # winning state and report it as the "previous" status, so the caller's
        # ``should_notify(old, new)`` sees old == new and does not double-notify.
        refreshed = await Release.get(release.id)
        if refreshed is not None:
            release.channel_statuses = refreshed.channel_statuses
            release.updated_at = refreshed.updated_at
        return DistributionStatus(release.channel_statuses.get(channel, new_status))

    # Reflect the win in the in-memory document for the caller's response.
    release.channel_statuses = {**release.channel_statuses, channel: new_status}
    release.updated_at = doc.get("updated_at")
    return current


def should_notify(old_status: DistributionStatus, new_status: DistributionStatus) -> bool:
    """True when a channel newly reaches a terminal state (``live``/``rejected``)."""
    return new_status in TERMINAL_STATUSES and new_status != old_status


async def create_status_notification(
    release: Release, channel: str, new_status: DistributionStatus
) -> NotificationEvent:
    """Record a notification event for a channel reaching a terminal status."""
    event = NotificationEvent(
        user_id=release.user_id,
        release_id=release.id,
        event_type=f"status_{new_status.value}",
        channel=channel,
        payload={"title": release.title, "status": new_status.value},
    )
    await event.insert()
    return event


def map_soundcloud_state(track: dict) -> DistributionStatus | None:
    """Map a SoundCloud track's API state to a :class:`DistributionStatus`.

    SoundCloud reports a ``state`` (``processing``/``finished``/``failed``) and a
    ``sharing`` (``public``/``private``). ``None`` means "no opinion" — leave the
    current status untouched (e.g. an unknown/empty state).
    """
    state = (track.get("state") or "").lower()
    if state == "failed":
        return DistributionStatus.REJECTED
    if state == "processing":
        return DistributionStatus.IN_REVIEW
    if state == "finished":
        # A finished-but-private track is processed yet not publicly live.
        return DistributionStatus.LIVE if (track.get("sharing") == "public") else DistributionStatus.IN_REVIEW
    return None
