"""Integration tests for the SoundCloud status poller (US-13.6, issue #137).

These drive the real poller against a local MongoDB (``mongo_db``). The SoundCloud
HTTP seam is injected (``connection_getter`` / ``status_fetcher``) so no network or
real connection is needed — the poller's DB orchestration is what's under test.
"""

import itertools
from datetime import datetime, timezone

import pytest
from beanie import PydanticObjectId

from acemusic.api.models import NotificationEvent, Release, Workspace
from acemusic.api.models.distribution import DistributionStatus
from acemusic.api.services import users as user_service
from acemusic.api.tasks.soundcloud_poller import SoundCloudStatusPoller

pytestmark = pytest.mark.integration

_SEQ = itertools.count(1)


class _Conn:
    def __init__(self, token: str = "tok") -> None:
        self.access_token = token


async def _make_user(email: str):
    return await user_service.get_or_create_user(email=email, provider="google", oauth_id=f"g-{email}", name="T")


async def _make_release(user, sc_status: DistributionStatus | None, *, track_id: str | None = "t1") -> Release:
    workspace = Workspace(name=f"WS-{next(_SEQ)}", user_id=user.id)
    await workspace.insert()
    statuses = {"soundcloud": sc_status} if sc_status is not None else {}
    release = Release(
        clip_id=PydanticObjectId(),
        user_id=user.id,
        title="Tune",
        artist="DJ",
        genre="house",
        release_date=datetime.now(timezone.utc),
        soundcloud_track_id=track_id,
        channel_statuses=statuses,
    )
    await release.insert()
    return release


def _poller(settings, *, track: dict, getter=None):
    async def _fetch(token: str, track_id: str) -> dict:
        return track

    async def _get(user_id: str, _settings) -> _Conn:
        return _Conn()

    return SoundCloudStatusPoller(
        settings,
        connection_getter=getter or _get,
        status_fetcher=_fetch,
    )


@pytest.mark.integration
class TestPollOnce:
    async def test_advances_processing_to_in_review(self, mongo_db, mongo_settings) -> None:
        user = await _make_user("poll-proc@example.com")
        release = await _make_release(user, DistributionStatus.SUBMITTED)
        poller = _poller(mongo_settings, track={"state": "processing"})

        changed = await poller.poll_once()
        assert changed == 1
        stored = await Release.get(release.id)
        assert stored.channel_statuses["soundcloud"] is DistributionStatus.IN_REVIEW
        assert stored.soundcloud_last_polled is not None

    async def test_finished_public_goes_live_and_notifies(self, mongo_db, mongo_settings) -> None:
        user = await _make_user("poll-live@example.com")
        release = await _make_release(user, DistributionStatus.IN_REVIEW)
        poller = _poller(mongo_settings, track={"state": "finished", "sharing": "public"})

        changed = await poller.poll_once()
        assert changed == 1
        stored = await Release.get(release.id)
        assert stored.channel_statuses["soundcloud"] is DistributionStatus.LIVE

        events = await NotificationEvent.find(NotificationEvent.release_id == release.id).to_list()
        assert len(events) == 1
        assert events[0].event_type == "status_live"
        assert events[0].channel == "soundcloud"

    async def test_terminal_release_is_not_polled(self, mongo_db, mongo_settings) -> None:
        user = await _make_user("poll-terminal@example.com")
        await _make_release(user, DistributionStatus.LIVE)
        fetched: list[str] = []

        async def _fetch(token: str, track_id: str) -> dict:
            fetched.append(track_id)
            return {"state": "finished", "sharing": "public"}

        async def _get(user_id: str, _settings) -> _Conn:
            return _Conn()

        poller = SoundCloudStatusPoller(mongo_settings, connection_getter=_get, status_fetcher=_fetch)
        changed = await poller.poll_once()
        assert changed == 0
        assert fetched == []  # terminal releases are excluded from the batch

    async def test_no_change_still_stamps_last_polled(self, mongo_db, mongo_settings) -> None:
        user = await _make_user("poll-nochange@example.com")
        release = await _make_release(user, DistributionStatus.SUBMITTED)
        poller = _poller(mongo_settings, track={})  # unknown state → no mapping

        changed = await poller.poll_once()
        assert changed == 0
        stored = await Release.get(release.id)
        assert stored.channel_statuses["soundcloud"] is DistributionStatus.SUBMITTED  # unchanged
        assert stored.soundcloud_last_polled is not None

    async def test_one_failure_does_not_stop_the_batch(self, mongo_db, mongo_settings) -> None:
        good = await _make_user("poll-good@example.com")
        bad = await _make_user("poll-bad@example.com")
        good_release = await _make_release(good, DistributionStatus.SUBMITTED)
        await _make_release(bad, DistributionStatus.SUBMITTED)

        async def _fetch(token: str, track_id: str) -> dict:
            return {"state": "processing"}

        async def _get(user_id: str, _settings) -> _Conn:
            if user_id == str(bad.id):
                raise RuntimeError("no token")
            return _Conn()

        poller = SoundCloudStatusPoller(mongo_settings, connection_getter=_get, status_fetcher=_fetch)
        changed = await poller.poll_once()
        assert changed == 1  # the good one progressed; the bad one was skipped
        assert (await Release.get(good_release.id)).channel_statuses["soundcloud"] is DistributionStatus.IN_REVIEW
