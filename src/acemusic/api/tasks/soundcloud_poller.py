"""SoundCloud distribution-status poller (US-13.6).

A lightweight background service that keeps the SoundCloud channel's status in
sync with the real track state. It mirrors :class:`JobProcessor`'s lifecycle
(``start``/``stop``, ``running`` flag, a single background task) but is
purpose-built: each cycle finds releases whose SoundCloud upload is still in a
non-terminal state, asks SoundCloud for the current track state, and advances the
channel status (recording a notification when it reaches ``live``/``rejected``).

Each cycle also drains the un-share queue (#569): takedowns only queue a track
(:class:`SoundCloudUnshare`), and the poller makes it private, retrying with
exponential backoff until it succeeds or the owner's grant is gone. Each outcome
is a platform-written moderation log entry (``actor_id=None``).

The SoundCloud HTTP calls are injected (``connection_getter`` / ``status_fetcher``)
(and ``sharing_updater``) so tests can drive the loop against a real MongoDB
without hitting the gated SoundCloud API.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta

from ..models.common import utcnow
from ..models.distribution import SOUNDCLOUD_CHANNEL, DistributionStatus
from ..models.moderation_log import ModerationLogEntry
from ..models.release import Release
from ..models.soundcloud_unshare import SoundCloudUnshare
from ..services import distribution_status as status_service, soundcloud as sc
from ..settings import ApiSettings

logger = logging.getLogger(__name__)

#: SoundCloud states the poller still acts on (terminal states are left alone).
_NON_TERMINAL = (DistributionStatus.SUBMITTED.value, DistributionStatus.IN_REVIEW.value)

#: The longest a failing un-share waits between attempts.
MAX_UNSHARE_BACKOFF = timedelta(hours=1)

ConnectionGetter = Callable[[str, ApiSettings], Awaitable[object]]
StatusFetcher = Callable[[str, str], Awaitable[dict]]
SharingUpdater = Callable[[str, str, str], Awaitable[dict]]


class SoundCloudStatusPoller:
    """Background service that advances SoundCloud channel statuses from the API."""

    def __init__(
        self,
        settings: ApiSettings,
        *,
        poll_interval: float = 60.0,
        batch_size: int = 20,
        connection_getter: ConnectionGetter | None = None,
        status_fetcher: StatusFetcher | None = None,
        sharing_updater: SharingUpdater | None = None,
    ) -> None:
        self._settings = settings
        self._poll_interval = poll_interval
        self._batch_size = batch_size
        self._connection_getter = connection_getter or sc.get_valid_connection
        self._status_fetcher = status_fetcher or sc.get_track_status
        self._sharing_updater = sharing_updater
        self._running = False
        self._task: asyncio.Task[None] | None = None

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        """Launch the polling loop. Idempotent."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("SoundCloud status poller started (interval=%.0fs)", self._poll_interval)

    async def stop(self) -> None:
        """Stop the polling loop and await its unwind."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("SoundCloud status poller stopped")

    async def _run_loop(self) -> None:
        while self._running:
            await self.run_cycle()
            await asyncio.sleep(self._poll_interval)

    async def run_cycle(self) -> None:
        """Poll statuses, then drain the un-share queue. Neither step's failure stops the other or the loop."""
        for step in (self.poll_once, self.drain_unshares):
            try:
                await step()
            except asyncio.CancelledError:
                raise
            except Exception:  # a poll cycle must never kill the loop
                logger.exception("SoundCloud poller step %s failed", step.__name__)

    # -- work --------------------------------------------------------------

    async def poll_once(self) -> int:
        """Poll one batch of pending releases; return how many changed status.

        A failure on one release (missing token, SoundCloud error) is logged and
        skipped so the rest of the batch still makes progress.
        """
        releases = await self._pending_batch()
        changed = 0
        for release in releases:
            try:
                if await self._poll_release(release):
                    changed += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Polling SoundCloud status for release %s failed", release.id)
        return changed

    async def _pending_batch(self) -> list[Release]:
        # Oldest-polled first (nulls sort first in ascending order, so a
        # never-polled release leads). Each poll stamps ``soundcloud_last_polled``,
        # moving the release to the back — so a stuck track can't starve the rest.
        return (
            await Release.find(
                {
                    "soundcloud_track_id": {"$ne": None},
                    f"channel_statuses.{SOUNDCLOUD_CHANNEL}": {"$in": list(_NON_TERMINAL)},
                }
            )
            .sort(("soundcloud_last_polled", 1))
            .limit(self._batch_size)
            .to_list()
        )

    async def _poll_release(self, release: Release) -> bool:
        connection = await self._connection_getter(str(release.user_id), self._settings)
        track = await self._status_fetcher(connection.access_token, release.soundcloud_track_id)
        new_status = status_service.map_soundcloud_state(track)
        current = DistributionStatus(release.channel_statuses.get(SOUNDCLOUD_CHANNEL, DistributionStatus.SUBMITTED))

        changed = False
        if new_status is not None and new_status != current:
            # validate off: SoundCloud's real state is authoritative. apply is
            # atomic and returns the pre-state; we only "won" if it actually moved.
            old = await status_service.apply_channel_status(release, SOUNDCLOUD_CHANNEL, new_status, validate=False)
            changed = old != new_status
            if changed and status_service.should_notify(old, new_status):
                await status_service.create_status_notification(release, SOUNDCLOUD_CHANNEL, new_status)

        # Stamp the poll time regardless — atomic so it can't clobber a concurrent
        # channel update the way a full-document save would.
        await Release.get_pymongo_collection().update_one(
            {"_id": release.id}, {"$set": {"soundcloud_last_polled": utcnow()}}
        )
        return changed

    # -- un-share queue (#569) ---------------------------------------------

    async def drain_unshares(self) -> int:
        """Retry the un-shares that are due; return how many tracks were made private.

        A failure on one track is logged and skipped so the rest of the batch still makes progress.
        """
        due = (
            await SoundCloudUnshare.find(SoundCloudUnshare.next_attempt_at <= utcnow())
            .sort(("next_attempt_at", 1))
            .limit(self._batch_size)
            .to_list()
        )
        done = 0
        for row in due:
            try:
                done += await self._unshare(row)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Un-sharing SoundCloud track %s failed", row.track_id)
        return done

    async def _unshare(self, row: SoundCloudUnshare) -> bool:
        try:
            connection = await self._connection_getter(str(row.user_id), self._settings)
        except (sc.SoundCloudNotConnectedError, sc.SoundCloudAuthError) as exc:
            # The grant is gone: nobody can reach the track any more, so stop trying.
            await self._settle(row, "soundcloud_unshare_abandoned", {"track_id": row.track_id, "error": str(exc)})
            return False
        except sc.SoundCloudError as exc:  # a refresh that failed in transit: the grant may be fine
            await self._retry_later(row, str(exc))
            return False
        update = self._sharing_updater or sc.update_track_sharing
        details = {"track_id": row.track_id, "attempts": row.attempts + 1}
        try:
            await update(connection.access_token, row.track_id, "private")
        except sc.SoundCloudTrackGone:
            # Deleted, so it can't be public either. Flagged: a relinked account also answers 404 for the old track.
            details["track_gone"] = True
        except sc.SoundCloudError as exc:
            await self._retry_later(row, str(exc))
            return False
        return await self._settle(row, "soundcloud_unshared", details)

    # Both writes apply only to the generation this attempt read. A takedown queueing the track again mid-attempt
    # (e.g. the owner re-shared meanwhile) bumps it, so that newer request survives and runs next cycle.

    async def _settle(self, row: SoundCloudUnshare, action: str, details: dict) -> bool:
        result = await SoundCloudUnshare.get_pymongo_collection().delete_one(
            {"_id": row.id, "generation": row.generation}
        )
        if result.deleted_count:
            await _log(row, action, details)
        return bool(result.deleted_count)

    async def _retry_later(self, row: SoundCloudUnshare, error: str) -> None:
        # The exponent is capped before timedelta sees it: 2**45 seconds is past timedelta's range.
        delay = min(self._poll_interval * 2 ** min(row.attempts, 20), MAX_UNSHARE_BACKOFF.total_seconds())
        await SoundCloudUnshare.get_pymongo_collection().update_one(
            {"_id": row.id, "generation": row.generation},
            {
                "$set": {"next_attempt_at": utcnow() + timedelta(seconds=delay), "last_error": error},
                "$inc": {"attempts": 1},
            },
        )
        if row.attempts == 0:
            # Logged once, so an admin learns a track is stuck without a log entry per retry.
            await _log(
                row,
                "soundcloud_unshare_failed",
                {"soundcloud_unshare_failed": [{"track_id": row.track_id, "error": error}]},
            )


async def _log(row: SoundCloudUnshare, action: str, details: dict) -> None:
    await ModerationLogEntry(
        action=action,
        target_type="clip",
        target_id=str(row.clip_id) if row.clip_id else None,
        details=details,
    ).insert()
