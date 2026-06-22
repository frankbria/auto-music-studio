"""SoundCloud distribution-status poller (US-13.6).

A lightweight background service that keeps the SoundCloud channel's status in
sync with the real track state. It mirrors :class:`JobProcessor`'s lifecycle
(``start``/``stop``, ``running`` flag, a single background task) but is
purpose-built: each cycle finds releases whose SoundCloud upload is still in a
non-terminal state, asks SoundCloud for the current track state, and advances the
channel status (recording a notification when it reaches ``live``/``rejected``).

The SoundCloud HTTP calls are injected (``connection_getter`` / ``status_fetcher``)
so tests can drive the loop against a real MongoDB without hitting the gated
SoundCloud API.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from ..models.common import utcnow
from ..models.distribution import SOUNDCLOUD_CHANNEL, DistributionStatus
from ..models.release import Release
from ..services import distribution_status as status_service, soundcloud as sc
from ..settings import ApiSettings

logger = logging.getLogger(__name__)

#: SoundCloud states the poller still acts on (terminal states are left alone).
_NON_TERMINAL = (DistributionStatus.SUBMITTED.value, DistributionStatus.IN_REVIEW.value)

ConnectionGetter = Callable[[str, ApiSettings], Awaitable[object]]
StatusFetcher = Callable[[str, str], Awaitable[dict]]


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
    ) -> None:
        self._settings = settings
        self._poll_interval = poll_interval
        self._batch_size = batch_size
        self._connection_getter = connection_getter or sc.get_valid_connection
        self._status_fetcher = status_fetcher or sc.get_track_status
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
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # a poll cycle must never kill the loop
                logger.exception("SoundCloud status poll cycle failed")
            await asyncio.sleep(self._poll_interval)

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
