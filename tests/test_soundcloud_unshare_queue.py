"""The SoundCloud un-share queue (#569).

Takedowns (remove, ban, a removal racing a share, a dropped cover) only queue a track; the
SoundCloud poller drains the queue, retrying with backoff until the track is private or the
owner's grant is gone. The SoundCloud calls are injected, so the loop runs against real MongoDB
without the gated SoundCloud API.
"""

import itertools
from datetime import timedelta, timezone

import pytest
from bson import ObjectId

from acemusic.api.models import Clip, ModerationLogEntry, Release, SoundCloudUnshare, Workspace
from acemusic.api.models.common import utcnow
from acemusic.api.services import releases as release_service, soundcloud as sc
from acemusic.api.tasks.soundcloud_poller import MAX_UNSHARE_BACKOFF, SoundCloudStatusPoller
from tests.test_releases_api import FULL_METADATA as RELEASE_METADATA
from tests.users import make_user

pytestmark = pytest.mark.integration


class _Conn:
    access_token = "tok"


_SEQ = itertools.count()


def _aware(dt):
    """Mongo hands datetimes back naive (UTC)."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _clip(user, *, track_ids=()) -> Clip:
    workspace = await Workspace(name=f"W{next(_SEQ)}", user_id=user.id).insert()
    return await Clip(
        user_id=user.id,
        workspace_id=workspace.id,
        file_path="x.wav",
        format="wav",
        soundcloud_track_ids=list(track_ids),
    ).insert()


async def _release(clip, *, track_id=None) -> Release:
    return await Release(
        clip_id=clip.id,
        user_id=clip.user_id,
        release_date=utcnow(),
        **{k: v for k, v in RELEASE_METADATA.items() if k != "release_date"},
        soundcloud_track_id=track_id,
    ).insert()


def _poller(mongo_settings, *, sharing=None, getter=None, interval=60.0) -> tuple[SoundCloudStatusPoller, list]:
    calls: list[tuple[str, str]] = []

    async def _share(token, track_id, value):
        calls.append((track_id, value))
        if sharing is not None:
            await sharing(track_id)
        return {}

    async def _get(user_id, _settings):
        return _Conn()

    poller = SoundCloudStatusPoller(
        mongo_settings, poll_interval=interval, connection_getter=getter or _get, sharing_updater=_share
    )
    return poller, calls


async def _queued() -> dict[str, SoundCloudUnshare]:
    return {row.track_id: row for row in await SoundCloudUnshare.find_all().to_list()}


async def _log(action: str) -> list[ModerationLogEntry]:
    return await ModerationLogEntry.find(ModerationLogEntry.action == action).to_list()


class TestQueueing:
    async def test_unshare_releases_queues_tracks_from_releases_and_clips(self, mongo_db):
        user = await make_user("q-both@example.com")
        clip = await _clip(user, track_ids=["bare-1"])
        await _release(clip, track_id="rel-1")
        other = await _clip(user, track_ids=["other-1"])

        result = await release_service.unshare_releases({"clip_id": clip.id}, {"_id": clip.id})

        assert result["soundcloud_unshare_queued"] == ["bare-1", "rel-1"]
        queued = await _queued()
        assert sorted(queued) == ["bare-1", "rel-1"]
        assert queued["bare-1"].clip_id == clip.id and queued["bare-1"].user_id == user.id
        assert "other-1" not in queued and other.id != clip.id

    async def test_queueing_twice_keeps_one_row_and_makes_it_due_now(self, mongo_db):
        user = await make_user("q-twice@example.com")
        clip = await _clip(user, track_ids=["t1"])
        await release_service.unshare_releases({"clip_id": clip.id}, {"_id": clip.id})
        later = utcnow() + timedelta(hours=1)
        await SoundCloudUnshare.find_one(SoundCloudUnshare.track_id == "t1").update(
            {"$set": {"next_attempt_at": later, "attempts": 3}}
        )

        await release_service.unshare_releases({"clip_id": clip.id}, {"_id": clip.id})

        [row] = (await _queued()).values()
        assert row.attempts == 3
        assert _aware(row.next_attempt_at) <= utcnow()

    async def test_a_takedown_never_calls_soundcloud(self, mongo_db, monkeypatch):
        async def _boom(*_args, **_kwargs):
            raise AssertionError("SoundCloud was called inside the request")

        monkeypatch.setattr(sc, "update_track_sharing", _boom)
        monkeypatch.setattr(sc, "get_valid_connection", _boom)
        user = await make_user("q-nocall@example.com")
        await _clip(user, track_ids=["t1"])

        await release_service.unshare_releases({"user_id": user.id}, {"user_id": user.id})

        assert list(await _queued()) == ["t1"]


class TestDraining:
    async def test_a_successful_unshare_clears_the_row_and_is_logged(self, mongo_db, mongo_settings):
        user = await make_user("d-ok@example.com")
        clip = await _clip(user, track_ids=["t1"])
        await release_service.unshare_releases({"clip_id": clip.id}, {"_id": clip.id})
        poller, calls = _poller(mongo_settings)

        assert await poller.drain_unshares() == 1

        assert calls == [("t1", "private")]
        assert await _queued() == {}
        [entry] = await _log("soundcloud_unshared")
        assert entry.actor_id is None
        assert entry.target_type == "clip" and entry.target_id == str(clip.id)
        assert entry.details["track_id"] == "t1"

    async def test_a_deleted_track_counts_as_unshared(self, mongo_db, mongo_settings):
        async def _gone(_track_id):
            raise sc.SoundCloudTrackGone("The SoundCloud track no longer exists.")

        user = await make_user("d-gone@example.com")
        clip = await _clip(user, track_ids=["t1"])
        await release_service.unshare_releases({"clip_id": clip.id}, {"_id": clip.id})
        poller, _ = _poller(mongo_settings, sharing=_gone)

        assert await poller.drain_unshares() == 1
        assert await _queued() == {}
        assert len(await _log("soundcloud_unshared")) == 1

    @pytest.mark.parametrize("error", [sc.SoundCloudNotConnectedError, sc.SoundCloudAuthError])
    async def test_a_lost_grant_abandons_the_row(self, mongo_db, mongo_settings, error):
        async def _get(_user_id, _settings):
            raise error("No linked SoundCloud account.")

        user = await make_user(f"d-lost-{error.__name__}@example.com")
        clip = await _clip(user, track_ids=["t1"])
        await release_service.unshare_releases({"clip_id": clip.id}, {"_id": clip.id})
        poller, calls = _poller(mongo_settings, getter=_get)

        assert await poller.drain_unshares() == 0

        assert calls == []
        assert await _queued() == {}
        [entry] = await _log("soundcloud_unshare_abandoned")
        assert entry.actor_id is None and entry.target_id == str(clip.id)
        assert entry.details["track_id"] == "t1" and entry.details["error"]

    async def test_a_transient_failure_backs_off_and_is_logged_once(self, mongo_db, mongo_settings):
        async def _down(_track_id):
            raise sc.SoundCloudError("Updating the SoundCloud track sharing failed.")

        user = await make_user("d-down@example.com")
        clip = await _clip(user, track_ids=["t1"])
        await release_service.unshare_releases({"clip_id": clip.id}, {"_id": clip.id})
        poller, calls = _poller(mongo_settings, sharing=_down, interval=60.0)

        before = utcnow()
        assert await poller.drain_unshares() == 0
        row = (await _queued())["t1"]
        assert row.attempts == 1
        assert row.last_error == "Updating the SoundCloud track sharing failed."
        assert _aware(row.next_attempt_at) >= before + timedelta(seconds=60)
        # Not due yet: the next cycle leaves it alone.
        assert await poller.drain_unshares() == 0
        assert len(calls) == 1

        await SoundCloudUnshare.find_one(SoundCloudUnshare.id == row.id).update({"$set": {"next_attempt_at": before}})
        await poller.drain_unshares()
        row = (await _queued())["t1"]
        assert row.attempts == 2
        assert _aware(row.next_attempt_at) >= utcnow() + timedelta(seconds=110)
        [entry] = await _log("soundcloud_unshare_failed")
        assert entry.actor_id is None
        assert entry.details["soundcloud_unshare_failed"] == [
            {"track_id": "t1", "error": "Updating the SoundCloud track sharing failed."}
        ]

    async def test_backoff_is_capped(self, mongo_db, mongo_settings):
        async def _down(_track_id):
            raise sc.SoundCloudError("down")

        user = await make_user("d-cap@example.com")
        clip = await _clip(user, track_ids=["t1"])
        await release_service.unshare_releases({"clip_id": clip.id}, {"_id": clip.id})
        await SoundCloudUnshare.find_one(SoundCloudUnshare.track_id == "t1").update({"$set": {"attempts": 30}})
        poller, _ = _poller(mongo_settings, sharing=_down, interval=60.0)

        await poller.drain_unshares()

        row = (await _queued())["t1"]
        assert _aware(row.next_attempt_at) <= utcnow() + MAX_UNSHARE_BACKOFF

    async def test_one_bad_row_does_not_stop_the_batch(self, mongo_db, mongo_settings):
        async def _crash(track_id):
            if track_id == "bad":
                raise RuntimeError("unexpected")

        user = await make_user("d-batch@example.com")
        clip = await _clip(user, track_ids=["bad", "good"])
        await release_service.unshare_releases({"clip_id": clip.id}, {"_id": clip.id})
        poller, _ = _poller(mongo_settings, sharing=_crash)

        assert await poller.drain_unshares() == 1
        assert list(await _queued()) == ["bad"]

    async def test_a_cycle_polls_statuses_and_drains_the_queue(self, mongo_db, mongo_settings):
        user = await make_user("d-cycle@example.com")
        clip = await _clip(user, track_ids=["t1"])
        await release_service.unshare_releases({"clip_id": clip.id}, {"_id": clip.id})
        poller, calls = _poller(mongo_settings)

        await poller.run_cycle()

        assert calls == [("t1", "private")]


async def test_queued_ids_are_stored_as_object_ids(mongo_db):
    # Rows are upserted with raw pymongo; Beanie queries on user_id/clip_id only match ObjectIds.
    user = await make_user("q-oid@example.com")
    clip = await _clip(user, track_ids=["t1"])
    await release_service.unshare_releases({"clip_id": clip.id}, {"_id": clip.id})
    raw = await SoundCloudUnshare.get_pymongo_collection().find_one({"track_id": "t1"})
    assert isinstance(raw["user_id"], ObjectId) and raw["user_id"] == user.id
    assert isinstance(raw["clip_id"], ObjectId) and raw["clip_id"] == clip.id
