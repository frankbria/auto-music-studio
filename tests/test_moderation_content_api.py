"""Videos, artwork and voice models in the moderation queue (#539).

Screening flags a borderline prompt on a video or artwork job, or a borderline voice name,
without blocking it. Those outputs aren't clips, so they carry their own flags and review
stamp, show up in the queue under their own type, and take the actions that fit them.
"""

import itertools
from datetime import datetime

import httpx
import pytest
from beanie import PydanticObjectId

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import (
    ArtworkOption,
    Clip,
    Job,
    ModerationLogEntry,
    NotificationEvent,
    SoundCloudUnshare,
    User,
    Video,
    VisibilityState,
    VoiceModel,
    VoiceModelStatus,
    Workspace,
)
from acemusic.api.services import (
    artwork as artwork_service,
    moderation,
    releases as release_service,
    video as video_service,
)
from acemusic.api.services.tiers import PRO
from acemusic.api.settings import ApiSettings
from acemusic.storage import get_storage_backend
from tests.users import make_user

ADMIN_URL = f"{API_V1_PREFIX}/admin/moderation"
QUEUE_URL = f"{ADMIN_URL}/queue"
CONTENT_URL = f"{ADMIN_URL}/content"
LOG_URL = f"{ADMIN_URL}/log"
VIDEOS_URL = f"{API_V1_PREFIX}/videos"
VOICE_URL = f"{API_V1_PREFIX}/voice-models"
VIDEO_REMOVED = "This video was removed by moderation."

_SEQ = itertools.count(1)


@pytest.fixture
def settings(mongo_db, mongo_settings) -> ApiSettings:
    return mongo_settings.model_copy(
        update={"jwt_secret_key": "test-secret-key-at-least-32-bytes-long-xx", "job_processor_enabled": False}
    )


@pytest.fixture
async def client(settings):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(settings)), base_url="http://t") as ac:
        yield ac


@pytest.fixture
def local_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("ACEMUSIC_STORAGE_BACKEND", "local")
    monkeypatch.setenv("ACEMUSIC_STORAGE_LOCAL_ROOT", str(tmp_path / "storage"))
    return get_storage_backend()


def _auth(user, settings: ApiSettings) -> dict[str, str]:
    token = create_access_token(
        user_id=str(user.id), email=user.email, subscription_tier=user.subscription_tier, settings=settings
    )
    return {"Authorization": f"Bearer {token}"}


async def _user(**fields):
    return await make_user(f"content-{next(_SEQ)}@example.com", **fields)


async def _admin():
    return await _user(is_admin=True)


async def _clip(owner, **fields) -> Clip:
    workspace = await Workspace(name=f"WS-{next(_SEQ)}", user_id=owner.id).insert()
    return await Clip(
        user_id=owner.id,
        workspace_id=workspace.id,
        file_path="song.wav",
        title=fields.pop("title", "Song"),
        visibility=VisibilityState.PUBLIC,
        **fields,
    ).insert()


async def _job(clip, job_type: str, prompt: str) -> Job:
    return await Job(
        user_id=clip.user_id,
        workspace_id=clip.workspace_id,
        job_type=job_type,
        input_params={"clip_id": str(clip.id), "prompt": prompt, "moderation_flags": ["violent extremism"]},
    ).insert()


async def _video(owner=None, *, flags=("violent extremism",), published=False, prompt="war footage") -> Video:
    clip = await _clip(owner or await _user())
    job = await _job(clip, video_service.VIDEO_JOB_TYPE, prompt)
    return await Video(
        clip_id=clip.id,
        user_id=clip.user_id,
        job_id=job.id,
        storage_path="v.mp4",
        resolution="720p",
        aspect_ratio="16:9",
        published=published,
        moderation_flags=list(flags),
    ).insert()


async def _artwork(storage=None, *, flags=("violent extremism",), as_cover=False) -> tuple[ArtworkOption, Clip]:
    clip = await _clip(await _user())
    job = await _job(clip, artwork_service.ARTWORK_JOB_TYPE, "burning city")
    path = f"{clip.user_id}/{clip.workspace_id}/artwork/{clip.id}/{job.id}/0.png"
    if storage is not None:
        storage.upload(path, b"png")
    option = await ArtworkOption(
        clip_id=clip.id,
        user_id=clip.user_id,
        job_id=job.id,
        storage_path=path,
        option_index=0,
        moderation_flags=list(flags),
    ).insert()
    if as_cover:
        await clip.set({"artwork_path": path})
    return option, clip


async def _voice(owner=None, *, flags=("sexual violence",), **fields) -> VoiceModel:
    owner = owner or await _user(tier=PRO)
    return await VoiceModel(
        user_id=owner.id,
        name=fields.pop("name", "Rape survivor"),
        status=VoiceModelStatus.READY,
        moderation_flags=list(flags),
        **fields,
    ).insert()


async def _queue(client, admin, settings) -> list[dict]:
    resp = await client.get(QUEUE_URL, headers=_auth(admin, settings))
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


async def _act(client, admin, settings, target_type, action, ids, reason=None) -> list[dict]:
    body = {"target_type": target_type, "action": action, "ids": [str(i) for i in ids]}
    if reason is not None:
        body["reason"] = reason
    resp = await client.post(CONTENT_URL, json=body, headers=_auth(admin, settings))
    assert resp.status_code == 200, resp.text
    return resp.json()["results"]


@pytest.mark.integration
class TestQueue:
    async def test_a_flagged_video_is_queued_with_its_prompt_and_song(self, client, settings):
        owner = await _user(name="Vid Maker")
        video = await _video(owner)
        clip = await Clip.get(video.clip_id)

        [item] = await _queue(client, await _admin(), settings)

        assert item["target_type"] == "video"
        assert item["target_id"] == str(video.id)
        assert item["clip_id"] == str(clip.id)
        assert item["title"] == "Song"
        assert item["description"] == "war footage"
        assert item["creator_id"] == str(owner.id)
        assert item["creator_name"] == "Vid Maker"
        assert item["moderation_flags"] == ["violent extremism"]
        assert (item["sources"], item["severity"], item["report_count"]) == (["automated"], 3, 0)
        assert item["published"] is False

    async def test_an_edited_video_is_queued_with_its_edit_prompt(self, client, settings):
        video = await _video()
        await Job.find_one(Job.id == video.job_id).update(
            {"$set": {"input_params": {"edit": {"operation": "replace_scene", "prompt": "a burning flag"}}}}
        )

        [item] = await _queue(client, await _admin(), settings)

        assert item["description"] == "a burning flag"

    async def test_flagged_artwork_is_queued_with_its_prompt(self, client, settings):
        option, clip = await _artwork()

        [item] = await _queue(client, await _admin(), settings)

        assert (item["target_type"], item["target_id"], item["clip_id"]) == ("artwork", str(option.id), str(clip.id))
        assert item["description"] == "burning city"
        assert item["moderation_flags"] == ["violent extremism"]

    async def test_a_flagged_voice_model_is_queued_with_its_name_and_description(self, client, settings):
        owner = await _user(tier=PRO)
        voice = await _voice(owner, description="dark themes")

        [item] = await _queue(client, await _admin(), settings)

        assert (item["target_type"], item["target_id"]) == ("voice_model", str(voice.id))
        assert item["clip_id"] is None
        assert (item["title"], item["description"]) == ("Rape survivor", "dark themes")
        assert item["creator_id"] == str(owner.id)
        assert item["moderation_flags"] == ["sexual violence"]

    async def test_clips_keep_their_type(self, client, settings):
        clip = await _clip(await _user(), moderation_flags=["violence"])

        [item] = await _queue(client, await _admin(), settings)

        assert (item["target_type"], item["target_id"], item["clip_id"]) == ("clip", str(clip.id), str(clip.id))

    async def test_unflagged_and_reviewed_content_stays_out(self, client, settings):
        await _video(flags=())
        await _artwork(flags=())
        await _voice(flags=())
        reviewed = await _video()
        await reviewed.set({"moderation_reviewed_at": datetime(2026, 9, 1)})

        assert await _queue(client, await _admin(), settings) == []

    async def test_every_type_shares_one_queue(self, client, settings):
        await _clip(await _user(), moderation_flags=["violence"])
        await _video()
        await _artwork()
        await _voice()

        items = await _queue(client, await _admin(), settings)

        assert sorted(i["target_type"] for i in items) == ["artwork", "clip", "video", "voice_model"]


@pytest.mark.integration
class TestVideoActions:
    async def test_approve_clears_it_from_the_queue_and_leaves_it_published(self, client, settings):
        admin = await _admin()
        video = await _video(published=True)

        [result] = await _act(client, admin, settings, "video", "approve", [video.id])

        assert result == {"id": str(video.id), "ok": True, "detail": None}
        stored = await Video.get(video.id)
        assert stored.moderation_reviewed_at is not None
        assert (stored.published, stored.removed_at) == (True, None)
        assert await _queue(client, admin, settings) == []

    async def test_unpublish_takes_it_off_the_song_page(self, client, settings):
        admin = await _admin()
        video = await _video(published=True)
        assert (await client.get(f"{VIDEOS_URL}/for-clip/{video.clip_id}")).status_code == 200

        await _act(client, admin, settings, "video", "unpublish", [video.id], reason="gore")

        stored = await Video.get(video.id)
        assert stored.published is False
        assert stored.removed_at is not None
        assert (await client.get(f"{VIDEOS_URL}/for-clip/{video.clip_id}")).status_code == 404
        assert await _queue(client, admin, settings) == []

    async def test_owner_cannot_publish_it_again(self, client, settings):
        owner = await _user()
        video = await _video(owner, published=True)
        await _act(client, await _admin(), settings, "video", "unpublish", [video.id])

        resp = await client.post(f"{VIDEOS_URL}/{video.id}/publish", headers=_auth(owner, settings))

        assert resp.status_code == 403
        assert resp.json()["detail"] == VIDEO_REMOVED
        assert (await Video.get(video.id)).published is False

    async def test_a_ban_stops_a_live_token_republishing_its_videos(self, client, settings):
        owner = await _user()
        video = await _video(owner, flags=(), published=True)
        resp = await client.post(
            f"{ADMIN_URL}/users",
            json={"action": "ban", "user_ids": [str(owner.id)]},
            headers=_auth(await _admin(), settings),
        )
        assert resp.status_code == 200, resp.text

        resp = await client.post(f"{VIDEOS_URL}/{video.id}/publish", headers=_auth(owner, settings))

        assert resp.status_code == 403
        assert (await Video.get(video.id)).published is False

    async def test_a_banned_owner_cannot_publish_a_video_that_was_never_published(self, client, settings):
        owner = await _user()
        video = await _video(owner, flags=())
        resp = await client.post(
            f"{ADMIN_URL}/users",
            json={"action": "ban", "user_ids": [str(owner.id)]},
            headers=_auth(await _admin(), settings),
        )
        assert resp.status_code == 200, resp.text

        resp = await client.post(f"{VIDEOS_URL}/{video.id}/publish", headers=_auth(owner, settings))

        assert resp.status_code == 403
        assert (await Video.get(video.id)).published is False

    async def test_owner_can_still_publish_an_unmoderated_video(self, client, settings):
        owner = await _user()
        video = await _video(owner, flags=())

        resp = await client.post(f"{VIDEOS_URL}/{video.id}/publish", headers=_auth(owner, settings))

        assert resp.status_code == 200, resp.text
        assert (await Video.get(video.id)).published is True

    async def test_admin_can_watch_an_unpublished_video(self, client, settings):
        video = await _video()

        resp = await client.get(f"{VIDEOS_URL}/{video.id}", headers=_auth(await _admin(), settings))

        assert resp.status_code == 200, resp.text

    async def test_a_stranger_still_cannot(self, client, settings):
        video = await _video()
        resp = await client.get(f"{VIDEOS_URL}/{video.id}", headers=_auth(await _user(), settings))
        assert resp.status_code == 404

    async def test_unpublish_notifies_the_owner(self, client, settings):
        owner = await _user()
        video = await _video(owner, published=True)

        await _act(client, await _admin(), settings, "video", "unpublish", [video.id], reason="gore")

        [notice] = await NotificationEvent.find(NotificationEvent.user_id == owner.id).to_list()
        assert notice.event_type == "moderation_video_unpublished"
        assert notice.clip_id == video.clip_id
        assert notice.payload == {"video_id": str(video.id), "title": "Song", "reason": "gore"}

    async def test_approve_notifies_no_one(self, client, settings):
        owner = await _user()
        video = await _video(owner)
        await _act(client, await _admin(), settings, "video", "approve", [video.id])
        assert await NotificationEvent.find(NotificationEvent.user_id == owner.id).count() == 0


@pytest.mark.integration
class TestVideoRestore:
    async def test_restore_lets_the_owner_publish_again_and_tells_them(self, client, settings):
        owner = await _user()
        admin = await _admin()
        video = await _video(owner, published=True)
        await _act(client, admin, settings, "video", "unpublish", [video.id])

        [result] = await _act(client, admin, settings, "video", "restore", [video.id], reason="appealed by email")

        assert result == {"id": str(video.id), "ok": True, "detail": None}
        stored = await Video.get(video.id)
        assert (stored.published, stored.removed_at) == (False, None)
        notices = await NotificationEvent.find(NotificationEvent.user_id == owner.id).sort("+_id").to_list()
        assert [n.event_type for n in notices] == ["moderation_video_unpublished", "moderation_video_restored"]
        assert notices[1].payload == {"video_id": str(video.id), "title": "Song", "reason": "appealed by email"}
        resp = await client.post(f"{VIDEOS_URL}/{video.id}/publish", headers=_auth(owner, settings))
        assert resp.status_code == 200, resp.text
        assert (await Video.get(video.id)).published is True

    async def test_a_video_unpublished_before_it_was_ever_published_can_be_restored(self, client, settings):
        owner = await _user()
        admin = await _admin()
        video = await _video(owner)
        await _act(client, admin, settings, "video", "unpublish", [video.id])

        [result] = await _act(client, admin, settings, "video", "restore", [video.id])

        assert result["ok"] is True
        resp = await client.post(f"{VIDEOS_URL}/{video.id}/publish", headers=_auth(owner, settings))
        assert resp.status_code == 200, resp.text

    async def test_restore_is_logged(self, client, settings):
        admin = await _admin()
        video = await _video(published=True)
        await _act(client, admin, settings, "video", "unpublish", [video.id])

        await _act(client, admin, settings, "video", "restore", [video.id], reason="mistake")

        resp = await client.get(LOG_URL, headers=_auth(admin, settings))
        newest = resp.json()["entries"][0]
        assert (newest["action"], newest["target_type"], newest["target_id"], newest["reason"]) == (
            "restore",
            "video",
            str(video.id),
            "mistake",
        )

    async def test_a_video_that_was_not_taken_down_is_refused(self, client, settings):
        owner = await _user()
        video = await _video(owner, published=True)

        [result] = await _act(client, await _admin(), settings, "video", "restore", [video.id])

        assert result == {"id": str(video.id), "ok": False, "detail": "This video is not taken down."}
        assert await NotificationEvent.find(NotificationEvent.user_id == owner.id).count() == 0
        assert await ModerationLogEntry.find(ModerationLogEntry.action == "restore").count() == 0

    async def test_a_restore_does_not_lift_an_unpublish_that_landed_after_its_read(self, settings):
        video = await _video(published=True)
        await Video.find({"_id": video.id}).update({"$set": {"removed_at": datetime(2026, 1, 1), "published": False}})
        stale = await Video.get(video.id)
        await Video.find({"_id": video.id}).update({"$set": {"removed_at": datetime(2026, 2, 1)}})

        assert await moderation._restore_video(stale) == "This video is not taken down."
        assert (await Video.get(video.id)).removed_at == datetime(2026, 2, 1)

    async def test_unpublishing_a_video_already_down_does_not_notify_again(self, client, settings):
        owner = await _user()
        admin = await _admin()
        video = await _video(owner, published=True)
        await _act(client, admin, settings, "video", "unpublish", [video.id])

        [result] = await _act(client, admin, settings, "video", "unpublish", [video.id])

        assert result["ok"] is True
        assert await NotificationEvent.find(NotificationEvent.user_id == owner.id).count() == 1

    async def test_a_failed_notice_does_not_fail_an_applied_restore(self, client, settings, monkeypatch):
        admin = await _admin()
        video = await _video(published=True)
        await _act(client, admin, settings, "video", "unpublish", [video.id])

        async def broken(*args, **kwargs):
            raise RuntimeError("mongo blip")

        monkeypatch.setattr(moderation, "_notify_owner", broken)
        [result] = await _act(client, admin, settings, "video", "restore", [video.id])

        assert result["ok"] is True
        assert (await Video.get(video.id)).removed_at is None
        assert await ModerationLogEntry.find(ModerationLogEntry.action == "restore").count() == 1

    async def test_restore_also_lifts_edits_that_inherited_the_takedown(self, client, settings):
        owner = await _user()
        admin = await _admin()
        video = await _video(owner, published=True)
        await _act(client, admin, settings, "video", "unpublish", [video.id])
        stamp = (await Video.get(video.id)).removed_at
        edit = await Video(
            clip_id=video.clip_id,
            user_id=owner.id,
            job_id=PydanticObjectId(),
            storage_path="edit.mp4",
            resolution="720p",
            aspect_ratio="16:9",
            parent_video_id=video.id,
            removed_at=stamp,
        ).insert()
        other = await _video(owner)
        await Video.find({"_id": other.id}).update({"$set": {"removed_at": datetime(2026, 1, 1)}})

        await _act(client, admin, settings, "video", "restore", [video.id])

        assert (await Video.get(edit.id)).removed_at is None
        assert (await Video.get(other.id)).removed_at == datetime(2026, 1, 1)
        resp = await client.post(f"{VIDEOS_URL}/{edit.id}/publish", headers=_auth(owner, settings))
        assert resp.status_code == 200, resp.text

    async def test_a_banned_owners_video_stays_down(self, client, settings):
        owner = await _user()
        admin = await _admin()
        video = await _video(owner, flags=(), published=True)
        resp = await client.post(
            f"{ADMIN_URL}/users", json={"action": "ban", "user_ids": [str(owner.id)]}, headers=_auth(admin, settings)
        )
        assert resp.status_code == 200, resp.text

        [result] = await _act(client, admin, settings, "video", "restore", [video.id])

        assert result == {"id": str(video.id), "ok": False, "detail": "The video's owner is banned."}
        assert (await Video.get(video.id)).removed_at is not None


@pytest.mark.integration
class TestArtworkActions:
    async def test_approve_keeps_the_option(self, client, settings):
        admin = await _admin()
        option, _clip_ = await _artwork()

        [result] = await _act(client, admin, settings, "artwork", "approve", [option.id])

        assert result["ok"] is True
        assert (await ArtworkOption.get(option.id)).moderation_reviewed_at is not None
        assert await _queue(client, admin, settings) == []

    async def test_drop_deletes_the_option_and_its_image(self, client, settings, local_storage):
        admin = await _admin()
        option, clip = await _artwork(local_storage)

        await _act(client, admin, settings, "artwork", "drop", [option.id], reason="gore")

        assert await ArtworkOption.get(option.id) is None
        with pytest.raises(FileNotFoundError):
            local_storage.size(option.storage_path)
        assert await _queue(client, admin, settings) == []
        # The owner can no longer pick it as the cover.
        resp = await client.post(
            f"{API_V1_PREFIX}/clips/{clip.id}/artwork",
            json={"artwork_id": str(option.id)},
            headers=_auth(await User.get(clip.user_id), settings),
        )
        assert resp.status_code == 404

    async def test_dropping_the_selected_cover_clears_it(self, client, settings, local_storage):
        option, clip = await _artwork(local_storage, as_cover=True)

        await _act(client, await _admin(), settings, "artwork", "drop", [option.id])

        assert (await Clip.get(clip.id)).artwork_path is None
        [entry] = await ModerationLogEntry.find(ModerationLogEntry.target_type == "artwork").to_list()
        assert entry.details == {"clip_id": str(clip.id), "was_cover": True}

    async def test_drop_notifies_the_owner(self, client, settings, local_storage):
        option, clip = await _artwork(local_storage, as_cover=True)

        await _act(client, await _admin(), settings, "artwork", "drop", [option.id], reason="gore")

        [notice] = await NotificationEvent.find(NotificationEvent.user_id == clip.user_id).to_list()
        assert notice.event_type == "moderation_artwork_dropped"
        assert notice.clip_id == clip.id
        assert notice.payload == {"title": "Song", "was_cover": True, "reason": "gore"}

    async def test_dropping_a_distributed_cover_queues_the_songs_soundcloud_tracks(
        self, client, settings, local_storage
    ):
        # #569: the cover went out with each SoundCloud upload, so dropping it takes those tracks down too.
        option, clip = await _artwork(local_storage, as_cover=True)
        await clip.set({"soundcloud_track_ids": ["sc-cover"]})

        await _act(client, await _admin(), settings, "artwork", "drop", [option.id])

        assert [row.track_id for row in await SoundCloudUnshare.find_all().to_list()] == ["sc-cover"]
        [entry] = await ModerationLogEntry.find(ModerationLogEntry.target_type == "artwork").to_list()
        assert entry.details["soundcloud_unshare_queued"] == ["sc-cover"]

    async def test_a_cover_drop_that_cannot_queue_can_be_retried(self, client, settings, local_storage, monkeypatch):
        # Queueing runs before the option is deleted, so a failure leaves the drop retryable.
        option, clip = await _artwork(local_storage, as_cover=True)
        await clip.set({"soundcloud_track_ids": ["sc-cover"]})
        admin = await _admin()
        real = release_service.queue_unshares

        async def broken(*_args, **_kwargs):
            raise RuntimeError("mongo went away")

        monkeypatch.setattr(release_service, "queue_unshares", broken)
        [failed] = await _act(client, admin, settings, "artwork", "drop", [option.id])
        assert failed["ok"] is False
        assert await ArtworkOption.get(option.id) is not None
        assert (await Clip.get(clip.id)).artwork_path == option.storage_path

        monkeypatch.setattr(release_service, "queue_unshares", real)
        [retried] = await _act(client, admin, settings, "artwork", "drop", [option.id])
        assert retried["ok"] is True
        assert [row.track_id for row in await SoundCloudUnshare.find_all().to_list()] == ["sc-cover"]

    async def test_a_track_recorded_between_the_drops_two_queueings_is_caught(
        self, client, settings, local_storage, monkeypatch
    ):
        # An upload records its track after the drop's first queueing but before the cover is cleared, so the
        # upload still saw its cover. The drop's second queueing, after the clear, picks it up.
        # No earlier tracks: the clip's first upload is the one landing in between, so the first scan finds nothing.
        option, clip = await _artwork(local_storage, as_cover=True)
        real = release_service.queue_unshares
        calls = 0

        async def upload_lands(release_query, clip_query):
            nonlocal calls
            calls += 1
            result = await real(release_query, clip_query)
            if calls == 1:
                await Clip.find_one(Clip.id == clip.id).update({"$addToSet": {"soundcloud_track_ids": "sc-late"}})
            return result

        monkeypatch.setattr(release_service, "queue_unshares", upload_lands)

        await _act(client, await _admin(), settings, "artwork", "drop", [option.id])

        assert [row.track_id for row in await SoundCloudUnshare.find_all().to_list()] == ["sc-late"]

    async def test_dropping_an_option_that_was_not_the_cover_queues_nothing(self, client, settings, local_storage):
        option, clip = await _artwork(local_storage)
        await clip.set({"soundcloud_track_ids": ["sc-kept"]})

        await _act(client, await _admin(), settings, "artwork", "drop", [option.id])

        assert await SoundCloudUnshare.find_all().to_list() == []

    async def test_dropping_an_unselected_option_leaves_the_cover(self, client, settings, local_storage):
        option, clip = await _artwork(local_storage)
        await clip.set({"artwork_path": "someone/else/upload.png"})

        await _act(client, await _admin(), settings, "artwork", "drop", [option.id])

        assert (await Clip.get(clip.id)).artwork_path == "someone/else/upload.png"

    async def test_selecting_a_cover_does_not_revert_a_concurrent_takedown(self, settings, local_storage):
        # select_artwork held a clip read before moderation removed it.
        option, clip = await _artwork(local_storage)
        stale = await Clip.get(clip.id)
        await Clip.find_one(Clip.id == clip.id).update({"$set": {"removed_at": datetime(2026, 9, 1)}})

        await artwork_service.select_artwork(stale, str(option.id))

        stored = await Clip.get(clip.id)
        assert stored.artwork_path == option.storage_path
        assert stored.removed_at is not None


@pytest.mark.integration
class TestVoiceModelActions:
    async def test_approve_clears_it_from_the_queue(self, client, settings):
        admin = await _admin()
        voice = await _voice()

        [result] = await _act(client, admin, settings, "voice_model", "approve", [voice.id])

        assert result["ok"] is True
        assert (await VoiceModel.get(voice.id)).moderation_reviewed_at is not None
        assert await _queue(client, admin, settings) == []

    async def test_a_rename_rescreens_the_untouched_description(self, client, settings):
        # #556 review: a description stored before a rule existed is caught by the next rename.
        owner = await _user(tier=PRO)
        voice = await _voice(owner, flags=(), name="Tenor", description="for my genocide concept album")

        resp = await client.patch(f"{VOICE_URL}/{voice.id}", json={"name": "Baritone"}, headers=_auth(owner, settings))

        assert resp.status_code == 200, resp.text
        assert (await VoiceModel.get(voice.id)).moderation_flags == ["violent extremism"]

    async def test_a_new_flag_category_reopens_an_approved_voice(self, client, settings):
        admin, owner = await _admin(), await _user(tier=PRO)
        voice = await _voice(owner)
        await _act(client, admin, settings, "voice_model", "approve", [voice.id])

        await client.patch(
            f"{VOICE_URL}/{voice.id}", json={"description": "genocide concept"}, headers=_auth(owner, settings)
        )

        [item] = await _queue(client, admin, settings)
        assert item["moderation_flags"] == ["sexual violence", "violent extremism"]

    async def test_a_rename_with_an_already_reviewed_category_stays_approved(self, client, settings):
        admin, owner = await _admin(), await _user(tier=PRO)
        voice = await _voice(owner)
        await _act(client, admin, settings, "voice_model", "approve", [voice.id])

        resp = await client.patch(
            f"{VOICE_URL}/{voice.id}", json={"name": "Rape survivor II"}, headers=_auth(owner, settings)
        )

        assert resp.status_code == 200, resp.text
        assert await _queue(client, admin, settings) == []


@pytest.mark.integration
class TestContentActionContract:
    @pytest.mark.parametrize(
        "target_type,action",
        [
            ("video", "drop"),
            ("artwork", "unpublish"),
            ("artwork", "restore"),
            ("voice_model", "unpublish"),
            ("voice_model", "restore"),
        ],
    )
    async def test_an_action_that_does_not_fit_the_type_is_422(self, client, settings, target_type, action):
        resp = await client.post(
            CONTENT_URL,
            json={"target_type": target_type, "action": action, "ids": [str(PydanticObjectId())]},
            headers=_auth(await _admin(), settings),
        )
        assert resp.status_code == 422

    @pytest.mark.parametrize("body", [{"target_type": "clip", "action": "approve", "ids": ["x"]}, {"ids": []}])
    async def test_malformed_request_is_422(self, client, settings, body):
        resp = await client.post(CONTENT_URL, json=body, headers=_auth(await _admin(), settings))
        assert resp.status_code == 422

    async def test_non_admin_is_403(self, client, settings):
        resp = await client.post(
            CONTENT_URL,
            json={"target_type": "video", "action": "approve", "ids": [str(PydanticObjectId())]},
            headers=_auth(await _user(), settings),
        )
        assert resp.status_code == 403

    async def test_one_bad_id_does_not_fail_the_batch(self, client, settings):
        video = await _video()
        missing = PydanticObjectId()

        results = await _act(client, await _admin(), settings, "video", "approve", ["nope", missing, video.id])

        assert results == [
            {"id": "nope", "ok": False, "detail": "Invalid video id."},
            {"id": str(missing), "ok": False, "detail": "Video not found."},
            {"id": str(video.id), "ok": True, "detail": None},
        ]

    @pytest.mark.parametrize(
        "target_type,action,make",
        [
            ("video", "unpublish", lambda: _video()),
            ("artwork", "approve", lambda: _artwork()),
            ("voice_model", "approve", lambda: _voice()),
        ],
    )
    async def test_every_action_is_logged(self, client, settings, target_type, action, make):
        admin = await _admin()
        made = await make()
        target = made[0] if isinstance(made, tuple) else made

        await _act(client, admin, settings, target_type, action, [target.id], reason="policy")

        resp = await client.get(LOG_URL, headers=_auth(admin, settings))
        [entry] = resp.json()["entries"]
        assert (entry["actor_id"], entry["action"], entry["target_type"], entry["target_id"], entry["reason"]) == (
            str(admin.id),
            action,
            target_type,
            str(target.id),
            "policy",
        )
        # A video or artwork is labelled by the song it was made for.
        assert entry["target_label"] == ("Rape survivor" if target_type == "voice_model" else "Song")


def test_moderated_documents_are_never_whole_document_saved():
    """A ``save()`` of a stale read reverts a moderation ``$set`` that landed in between (#539).

    Shape guard: the race needs the writer's own stale read, which a test that reads the
    document itself can't reproduce, so the rule is pinned where the writers live.
    """
    from pathlib import Path

    import acemusic.api as api

    root = Path(api.__file__).parent
    offenders = []
    for rel, name in [
        ("tasks/voice_training.py", "model"),
        ("services/voice_models.py", "model"),
        ("services/video.py", "video"),
        ("services/artwork.py", "clip"),
    ]:
        text = (root / rel).read_text()
        if f"{name}.save()" in text:
            offenders.append(f"{rel}: {name}.save()")
    assert offenders == []
