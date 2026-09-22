"""Admin moderation dashboard (US-27.3).

The queue groups open listener reports and unreviewed automated flags per clip; admins
approve, remove or flag clips and warn or ban users in bulk, and every action lands in
the moderation log with who did it and when.
"""

import itertools
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from beanie import PydanticObjectId

from acemusic.api.auth import services as auth_services
from acemusic.api.auth.tokens import create_access_token, create_refresh_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import (
    Clip,
    ClipReport,
    Job,
    ModerationLogEntry,
    NotificationEvent,
    RefreshToken,
    Release,
    ReleaseStatus,
    User,
    Video,
    VisibilityState,
    Workspace,
)
from acemusic.api.services import routing
from acemusic.api.services.tiers import PRO
from acemusic.api.settings import ApiSettings
from tests.users import make_user

ADMIN_URL = f"{API_V1_PREFIX}/admin"
QUEUE_URL = f"{ADMIN_URL}/moderation/queue"
CLIP_ACTIONS_URL = f"{ADMIN_URL}/moderation/clips"
USER_ACTIONS_URL = f"{ADMIN_URL}/moderation/users"
LOG_URL = f"{ADMIN_URL}/moderation/log"
CLIPS_URL = f"{API_V1_PREFIX}/clips"
RELEASES_URL = f"{API_V1_PREFIX}/releases"
VIDEOS_URL = f"{API_V1_PREFIX}/videos"
REMOVED = "This clip was removed by moderation."
RELEASE_METADATA = {"title": "Tune", "artist": "DJ", "genre": "house", "release_date": "2026-07-01T00:00:00Z"}
SUSPENDED = "This account has been suspended."

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


def _auth(user, settings: ApiSettings) -> dict[str, str]:
    token = create_access_token(
        user_id=str(user.id), email=user.email, subscription_tier=user.subscription_tier, settings=settings
    )
    return {"Authorization": f"Bearer {token}"}


async def _user(**fields) -> User:
    return await make_user(f"mod-{next(_SEQ)}@example.com", **fields)


async def _admin() -> User:
    return await _user(is_admin=True)


async def _clip(owner, visibility: VisibilityState = VisibilityState.PUBLIC, **fields) -> Clip:
    workspace = Workspace(name=f"WS-{next(_SEQ)}", user_id=owner.id)
    await workspace.insert()
    clip_id = PydanticObjectId()
    clip = Clip(
        id=clip_id,
        user_id=owner.id,
        workspace_id=workspace.id,
        file_path=f"{owner.id}/{workspace.id}/clips/{clip_id}.wav",
        format="wav",
        title=fields.pop("title", "Queued"),
        visibility=visibility,
        **fields,
    )
    await clip.insert()
    return clip


async def _report(clip_id, category="spam", *, reporter=None, at: datetime | None = None) -> ClipReport:
    reporter = reporter or await _user()
    report = ClipReport(clip_id=clip_id, reporter_id=reporter.id, category=category)
    if at is not None:
        report.created_at = at
    await report.insert()
    return report


async def _queue(client, admin, settings) -> list[dict]:
    resp = await client.get(QUEUE_URL, headers=_auth(admin, settings))
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


async def _act_on_clips(client, admin, settings, action, clip_ids, reason=None) -> list[dict]:
    body = {"action": action, "clip_ids": [str(c) for c in clip_ids]}
    if reason is not None:
        body["reason"] = reason
    resp = await client.post(CLIP_ACTIONS_URL, json=body, headers=_auth(admin, settings))
    assert resp.status_code == 200, resp.text
    return resp.json()["results"]


async def _act_on_users(client, admin, settings, action, user_ids, reason=None) -> list[dict]:
    body = {"action": action, "user_ids": [str(u) for u in user_ids]}
    if reason is not None:
        body["reason"] = reason
    resp = await client.post(USER_ACTIONS_URL, json=body, headers=_auth(admin, settings))
    assert resp.status_code == 200, resp.text
    return resp.json()["results"]


@pytest.mark.integration
class TestAdminGate:
    @pytest.mark.parametrize(
        "method,url,body",
        [
            ("get", QUEUE_URL, None),
            ("get", LOG_URL, None),
            ("post", CLIP_ACTIONS_URL, {"action": "approve", "clip_ids": [str(PydanticObjectId())]}),
            ("post", USER_ACTIONS_URL, {"action": "warn", "user_ids": [str(PydanticObjectId())]}),
        ],
    )
    async def test_non_admin_is_403(self, client, settings, method, url, body):
        kwargs = {"headers": _auth(await _user(), settings)}
        if body is not None:
            kwargs["json"] = body
        resp = await getattr(client, method)(url, **kwargs)
        assert resp.status_code == 403

    async def test_banned_admin_is_403(self, client, settings):
        admin = await _user(is_admin=True, banned_at=datetime.now(timezone.utc))
        resp = await client.get(QUEUE_URL, headers=_auth(admin, settings))
        assert resp.status_code == 403


@pytest.mark.integration
class TestQueue:
    async def test_groups_open_reports_per_clip_and_sorts_by_count_then_severity(self, client, settings):
        admin, owner = await _admin(), await _user(display_name="Owner Name")
        # Created least-urgent first, so the expected order only holds if the queue really sorts.
        spam_clip, copyright_clip, busy = [await _clip(owner, title=t) for t in ("Spam", "Copy", "Busy")]
        await _clip(owner, title="Unreported")
        await _report(busy.id, "inappropriate")
        await _report(busy.id, "spam")
        await _report(copyright_clip.id, "copyright")
        await _report(spam_clip.id, "spam")

        items = await _queue(client, admin, settings)

        assert [i["clip_id"] for i in items] == [str(busy.id), str(copyright_clip.id), str(spam_clip.id)]
        top = items[0]
        assert top["report_count"] == 2
        assert top["categories"] == {"inappropriate": 1, "spam": 1}
        assert top["severity"] == 3
        assert top["sources"] == ["report"]
        assert top["title"] == "Busy"
        assert top["creator_id"] == str(owner.id)
        assert top["creator_name"] == "Owner Name"
        assert top["creator_banned"] is False
        assert top["visibility"] == "public"
        assert top["clip_deleted"] is False
        assert top["content_warning"] is False
        assert items[1]["severity"] == 2
        assert items[2]["severity"] == 1

    async def test_order_comes_from_the_sort_not_from_insertion(self, client, settings):
        admin, owner = await _admin(), await _user()
        reporters = [await _user() for _ in range(5)]
        by_count = {}
        for count in (2, 5, 1, 4, 3):
            clip = await _clip(owner, title=f"x{count}")
            by_count[count] = str(clip.id)
            for reporter in reporters[:count]:
                await _report(clip.id, "spam", reporter=reporter)

        items = await _queue(client, admin, settings)

        assert [i["clip_id"] for i in items] == [by_count[c] for c in (5, 4, 3, 2, 1)]

    async def test_unreviewed_automated_flags_are_queued(self, client, settings):
        admin = await _admin()
        clip = await _clip(await _user(), VisibilityState.PRIVATE, moderation_flags=["violence"])

        [item] = await _queue(client, admin, settings)

        assert item["clip_id"] == str(clip.id)
        assert item["sources"] == ["automated"]
        assert item["moderation_flags"] == ["violence"]
        assert item["report_count"] == 0
        assert item["severity"] == 3

    async def test_reports_and_flags_on_one_clip_merge(self, client, settings):
        admin = await _admin()
        clip = await _clip(await _user(), moderation_flags=["violence"])
        await _report(clip.id, "spam")

        [item] = await _queue(client, admin, settings)

        assert item["sources"] == ["report", "automated"]
        assert item["severity"] == 3

    async def test_reports_on_a_deleted_clip_show_as_deleted(self, client, settings):
        admin, gone = await _admin(), PydanticObjectId()
        await _report(gone, "copyright")

        [item] = await _queue(client, admin, settings)

        assert item["clip_id"] == str(gone)
        assert item["clip_deleted"] is True
        assert item["title"] is None
        assert item["creator_id"] is None
        assert item["visibility"] is None

    async def test_ties_break_on_newest_report(self, client, settings):
        admin, owner = await _admin(), await _user()
        older, newer = await _clip(owner), await _clip(owner)
        now = datetime.now(timezone.utc)
        await _report(older.id, "spam", at=now - timedelta(hours=2))
        await _report(newer.id, "spam", at=now - timedelta(hours=1))

        items = await _queue(client, admin, settings)

        assert [i["clip_id"] for i in items] == [str(newer.id), str(older.id)]

    async def test_banned_creator_is_marked(self, client, settings):
        admin = await _admin()
        owner = await _user(banned_at=datetime.now(timezone.utc))
        await _report((await _clip(owner, VisibilityState.PRIVATE)).id)

        [item] = await _queue(client, admin, settings)

        assert item["creator_banned"] is True

    async def test_empty_queue(self, client, settings):
        await _clip(await _user())
        assert await _queue(client, await _admin(), settings) == []


@pytest.mark.integration
class TestApprove:
    async def test_approve_clears_the_clip_but_keeps_the_reports(self, client, settings):
        admin = await _admin()
        clip = await _clip(await _user(), moderation_flags=["violence"])
        report = await _report(clip.id)

        results = await _act_on_clips(client, admin, settings, "approve", [clip.id])

        assert results == [{"clip_id": str(clip.id), "ok": True, "detail": None}]
        assert await _queue(client, admin, settings) == []
        assert (await ClipReport.get(report.id)).resolved_at is not None
        stored = await Clip.get(clip.id)
        assert stored.moderation_reviewed_at is not None
        assert stored.visibility == VisibilityState.PUBLIC

    async def test_a_new_report_after_approval_reopens_the_clip(self, client, settings):
        admin = await _admin()
        clip = await _clip(await _user())
        await _report(clip.id)
        await _act_on_clips(client, admin, settings, "approve", [clip.id])

        await _report(clip.id, "copyright")

        [item] = await _queue(client, admin, settings)
        assert item["report_count"] == 1
        assert item["categories"] == {"copyright": 1}

    async def test_approve_dismisses_reports_on_a_deleted_clip(self, client, settings):
        admin, gone = await _admin(), PydanticObjectId()
        await _report(gone)

        [result] = await _act_on_clips(client, admin, settings, "approve", [gone])

        assert result["ok"] is True
        assert await _queue(client, admin, settings) == []


@pytest.mark.integration
class TestRemove:
    async def test_removed_clip_is_inaccessible_to_everyone_but_its_owner(self, client, settings):
        admin, owner, stranger = await _admin(), await _user(), await _user()
        clip = await _clip(owner)
        await _report(clip.id, "inappropriate")

        [result] = await _act_on_clips(client, admin, settings, "remove", [clip.id], reason="Hate speech")

        assert result["ok"] is True
        assert (await client.get(f"{CLIPS_URL}/{clip.id}/public")).status_code == 404
        assert (await client.get(f"{CLIPS_URL}/{clip.id}/stream")).status_code == 404
        signed_in = await client.get(f"{CLIPS_URL}/{clip.id}/public", headers=_auth(stranger, settings))
        assert signed_in.status_code == 403
        assert (await client.get(f"{CLIPS_URL}/{clip.id}", headers=_auth(owner, settings))).status_code == 200
        stored = await Clip.get(clip.id)
        assert stored.visibility == VisibilityState.PRIVATE
        assert stored.is_public is False
        assert stored.removed_at is not None
        assert await _queue(client, admin, settings) == []

    async def test_creator_is_notified(self, client, settings):
        admin, owner = await _admin(), await _user()
        clip = await _clip(owner, title="Bad Song")

        await _act_on_clips(client, admin, settings, "remove", [clip.id], reason="Hate speech")

        event = await NotificationEvent.find_one(NotificationEvent.user_id == owner.id)
        assert event.event_type == "moderation_clip_removed"
        assert event.channel == "in_app"
        assert event.clip_id == clip.id
        assert event.payload == {"clip_id": str(clip.id), "title": "Bad Song", "reason": "Hate speech"}

    @pytest.mark.parametrize("visibility", ["public", "unlisted"])
    async def test_owner_cannot_republish_a_removed_clip(self, client, settings, visibility):
        admin, owner = await _admin(), await _user()
        clip = await _clip(owner)
        await _act_on_clips(client, admin, settings, "remove", [clip.id])

        resp = await client.patch(
            f"{CLIPS_URL}/{clip.id}", json={"visibility": visibility}, headers=_auth(owner, settings)
        )

        assert resp.status_code == 403
        assert resp.json()["detail"] == "This clip was removed by moderation."
        assert (await Clip.get(clip.id)).visibility == VisibilityState.PRIVATE

    async def test_owner_can_still_rename_a_removed_clip(self, client, settings):
        admin, owner = await _admin(), await _user()
        clip = await _clip(owner)
        await _act_on_clips(client, admin, settings, "remove", [clip.id])

        resp = await client.patch(f"{CLIPS_URL}/{clip.id}", json={"title": "Renamed"}, headers=_auth(owner, settings))

        assert resp.status_code == 200

    async def test_remove_on_a_deleted_clip_fails_in_results(self, client, settings):
        gone = PydanticObjectId()
        [result] = await _act_on_clips(client, await _admin(), settings, "remove", [gone])
        assert result == {"clip_id": str(gone), "ok": False, "detail": "Clip not found."}


@pytest.mark.integration
class TestFlag:
    async def test_flag_keeps_the_clip_up_with_a_content_warning(self, client, settings):
        admin = await _admin()
        clip = await _clip(await _user())
        await _report(clip.id)

        [result] = await _act_on_clips(client, admin, settings, "flag", [clip.id])

        assert result["ok"] is True
        public = await client.get(f"{CLIPS_URL}/{clip.id}/public")
        assert public.status_code == 200
        assert public.json()["content_warning"] is True
        assert await _queue(client, admin, settings) == []

    async def test_unflagged_clip_reports_no_warning(self, client, settings):
        clip = await _clip(await _user())
        assert (await client.get(f"{CLIPS_URL}/{clip.id}/public")).json()["content_warning"] is False


@pytest.mark.integration
class TestBulkClipActions:
    async def test_one_bad_id_does_not_fail_the_batch(self, client, settings):
        admin, owner = await _admin(), await _user()
        first, second = await _clip(owner), await _clip(owner)
        unknown = PydanticObjectId()

        results = await _act_on_clips(
            client, admin, settings, "remove", [first.id, "not-an-id", unknown, second.id], reason="Spam wave"
        )

        assert results == [
            {"clip_id": str(first.id), "ok": True, "detail": None},
            {"clip_id": "not-an-id", "ok": False, "detail": "Invalid clip id."},
            {"clip_id": str(unknown), "ok": False, "detail": "Clip not found."},
            {"clip_id": str(second.id), "ok": True, "detail": None},
        ]
        for clip in (first, second):
            assert (await Clip.get(clip.id)).removed_at is not None

    @pytest.mark.parametrize(
        "body",
        [
            {"action": "approve", "clip_ids": []},
            {"action": "approve", "clip_ids": [str(PydanticObjectId()) for _ in range(101)]},
            {"action": "delete", "clip_ids": [str(PydanticObjectId())]},
            {"action": "remove", "clip_ids": [str(PydanticObjectId())], "reason": "x" * 1001},
        ],
    )
    async def test_invalid_request_is_422(self, client, settings, body):
        resp = await client.post(CLIP_ACTIONS_URL, json=body, headers=_auth(await _admin(), settings))
        assert resp.status_code == 422


@pytest.mark.integration
class TestAdminStreamingBypass:
    async def test_admin_can_read_another_users_private_clip(self, client, settings):
        clip = await _clip(await _user(), VisibilityState.PRIVATE)
        resp = await client.get(f"{CLIPS_URL}/{clip.id}/public", headers=_auth(await _admin(), settings))
        assert resp.status_code == 200
        assert resp.json()["is_owner"] is False

    async def test_admin_still_gets_404_for_an_unknown_clip(self, client, settings):
        resp = await client.get(f"{CLIPS_URL}/{PydanticObjectId()}/public", headers=_auth(await _admin(), settings))
        assert resp.status_code == 404


@pytest.mark.integration
class TestWarn:
    async def test_warn_notifies_the_user(self, client, settings):
        admin, user = await _admin(), await _user()

        [result] = await _act_on_users(client, admin, settings, "warn", [user.id], reason="Repeated spam")

        assert result == {"user_id": str(user.id), "ok": True, "detail": None}
        event = await NotificationEvent.find_one(NotificationEvent.user_id == user.id)
        assert event.event_type == "moderation_warning"
        assert event.channel == "in_app"
        assert event.payload == {"reason": "Repeated spam"}
        assert (await User.get(user.id)).banned_at is None


@pytest.mark.integration
class TestBan:
    async def test_ban_disables_the_account(self, client, settings):
        admin, user = await _admin(), await _user()
        raw = create_refresh_token()
        await auth_services.store_refresh_token(user.id, raw, datetime.now(timezone.utc) + timedelta(days=7))

        [result] = await _act_on_users(client, admin, settings, "ban", [user.id], reason="Abuse")

        assert result["ok"] is True
        assert (await User.get(user.id)).banned_at is not None
        live_tokens = RefreshToken.find({"user_id": user.id, "revoked": False})
        assert await live_tokens.count() == 0
        refresh = await client.post(f"{API_V1_PREFIX}/auth/refresh", json={"refresh_token": raw})
        assert refresh.status_code in (401, 403)
        existing_user_route = await client.get(CLIPS_URL, headers=_auth(user, settings))
        assert existing_user_route.status_code == 403
        assert existing_user_route.json()["detail"] == SUSPENDED
        plugin = await client.post(f"{API_V1_PREFIX}/auth/plugin-token", headers=_auth(user, settings))
        assert plugin.status_code == 403
        assert plugin.json()["detail"] == SUSPENDED

    async def test_a_live_access_token_cannot_spend_once_banned(self, client, settings, monkeypatch):
        # /generate authenticates on the JWT alone, so the ban has to stop it at the charge.
        async def _available(url, timeout=routing.LOCAL_AVAILABILITY_TIMEOUT):
            return True

        monkeypatch.setattr(routing, "check_local_availability", _available)
        user = await _user(banned_at=datetime.now(timezone.utc))
        before = user.credits_balance

        resp = await client.post(
            f"{API_V1_PREFIX}/generate", json={"prompt": "a calm piano ballad"}, headers=_auth(user, settings)
        )

        assert resp.status_code == 403
        assert resp.json()["detail"] == SUSPENDED
        assert (await User.get(user.id)).credits_balance == before
        assert await Job.find({"user_id": user.id}).count() == 0

    @pytest.mark.parametrize(
        "path,body",
        [
            ("/mastering/batch", {"profile": "streaming", "service": "dolby", "format": "wav"}),
            ("/batch/stems", {}),
            ("/distribution/soundcloud/upload", None),
        ],
    )
    async def test_a_live_access_token_cannot_use_pro_routes_once_banned(self, client, settings, path, body):
        # These gate on the tier read from the DB, not on require_existing_user; the ban rides on that read.
        user = await _user(tier=PRO, banned_at=datetime.now(timezone.utc))
        clip = await _clip(user, VisibilityState.PRIVATE)
        before = user.credits_balance
        payload = {"clip_id": str(clip.id)} if body is None else {**body, "clip_ids": [str(clip.id)]}

        resp = await client.post(f"{API_V1_PREFIX}{path}", json=payload, headers=_auth(user, settings))

        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"] == SUSPENDED
        assert (await User.get(user.id)).credits_balance == before
        assert await Job.find({"user_id": user.id}).count() == 0

    async def test_refresh_with_a_live_token_is_rejected_once_banned(self, client, settings):
        user = await _user(banned_at=datetime.now(timezone.utc))
        raw = create_refresh_token()
        await auth_services.store_refresh_token(user.id, raw, datetime.now(timezone.utc) + timedelta(days=7))

        resp = await client.post(f"{API_V1_PREFIX}/auth/refresh", json={"refresh_token": raw})

        assert resp.status_code == 403
        assert resp.json()["detail"] == SUSPENDED

    async def test_ban_takes_down_public_content(self, client, settings):
        admin, user = await _admin(), await _user()
        public, unlisted, private = (
            await _clip(user, VisibilityState.PUBLIC),
            await _clip(user, VisibilityState.UNLISTED),
            await _clip(user, VisibilityState.PRIVATE),
        )
        video = Video(
            clip_id=public.id,
            user_id=user.id,
            job_id=PydanticObjectId(),
            storage_path="v.mp4",
            resolution="720p",
            aspect_ratio="16:9",
            published=True,
        )
        await video.insert()

        await _act_on_users(client, admin, settings, "ban", [user.id])

        for clip in (public, unlisted):
            stored = await Clip.get(clip.id)
            assert stored.visibility == VisibilityState.PRIVATE
            assert stored.is_public is False
            assert stored.removed_at is not None
            assert (await client.get(f"{CLIPS_URL}/{clip.id}/public")).status_code == 404
        assert (await Clip.get(private.id)).removed_at is None
        assert (await Video.get(video.id)).published is False

    async def test_banned_users_clips_cannot_be_republished(self, client, settings):
        admin, user = await _admin(), await _user()
        clip = await _clip(user)
        await _act_on_users(client, admin, settings, "ban", [user.id])
        await User.find_one(User.id == user.id).update({"$set": {"banned_at": None}})

        resp = await client.patch(
            f"{CLIPS_URL}/{clip.id}", json={"visibility": "public"}, headers=_auth(user, settings)
        )

        assert resp.status_code == 403

    async def test_admin_cannot_ban_themself(self, client, settings):
        admin = await _admin()

        [result] = await _act_on_users(client, admin, settings, "ban", [admin.id])

        assert result == {"user_id": str(admin.id), "ok": False, "detail": "You cannot ban yourself."}
        assert (await User.get(admin.id)).banned_at is None

    async def test_one_bad_id_does_not_fail_the_batch(self, client, settings):
        admin, user = await _admin(), await _user()
        unknown = PydanticObjectId()

        results = await _act_on_users(client, admin, settings, "ban", ["nope", unknown, user.id])

        assert results == [
            {"user_id": "nope", "ok": False, "detail": "Invalid user id."},
            {"user_id": str(unknown), "ok": False, "detail": "User not found."},
            {"user_id": str(user.id), "ok": True, "detail": None},
        ]


@pytest.mark.integration
class TestModerationLog:
    async def test_every_action_is_logged_with_actor_and_timestamp(self, client, settings):
        admin, owner = await _admin(), await _user()
        clip = await _clip(owner)
        before = datetime.now(timezone.utc)

        await _act_on_clips(client, admin, settings, "flag", [clip.id], reason="Borderline")
        await _act_on_clips(client, admin, settings, "remove", [clip.id, "bad-id"], reason="Escalated")
        await _act_on_users(client, admin, settings, "warn", [owner.id], reason="First strike")

        resp = await client.get(LOG_URL, headers=_auth(admin, settings))

        assert resp.status_code == 200
        entries = resp.json()["entries"]
        assert [(e["action"], e["target_type"], e["target_id"]) for e in entries] == [
            ("warn", "user", str(owner.id)),
            ("remove", "clip", str(clip.id)),
            ("flag", "clip", str(clip.id)),
        ]
        assert {e["actor_id"] for e in entries} == {str(admin.id)}
        assert [e["reason"] for e in entries] == ["First strike", "Escalated", "Borderline"]
        for entry in entries:
            assert datetime.fromisoformat(entry["created_at"]).replace(tzinfo=timezone.utc) >= before - timedelta(
                seconds=1
            )
            assert entry["id"]

    async def test_ban_is_logged_with_what_it_took_down(self, client, settings):
        admin, user = await _admin(), await _user()
        await _clip(user)

        await _act_on_users(client, admin, settings, "ban", [user.id])

        entry = await ModerationLogEntry.find_one(ModerationLogEntry.action == "ban")
        assert entry.target_id == str(user.id)
        assert entry.details == {"clips_removed": 1, "videos_unpublished": 0}

    async def test_screening_rules_update_is_logged_with_before_and_after(self, client, settings):
        admin = await _admin()
        new_rules = {
            "rules": [{"term": "badword", "category": "profanity", "action": "flag"}],
            "allow_terms": [],
            "block_threshold": 2,
        }

        resp = await client.put(f"{ADMIN_URL}/screening-rules", json=new_rules, headers=_auth(admin, settings))
        assert resp.status_code == 200

        [entry] = (await client.get(LOG_URL, headers=_auth(admin, settings))).json()["entries"]
        assert entry["action"] == "update_screening_rules"
        assert entry["target_type"] == "screening_rules"
        assert entry["target_id"] is None
        assert entry["actor_id"] == str(admin.id)
        assert entry["details"]["after"]["rules"][0]["term"] == "badword"
        assert "before" in entry["details"]

    async def test_limit(self, client, settings):
        admin = await _admin()
        for _ in range(3):
            await _act_on_users(client, admin, settings, "warn", [(await _user()).id])

        resp = await client.get(LOG_URL, params={"limit": 2}, headers=_auth(admin, settings))

        assert len(resp.json()["entries"]) == 2
        assert (await client.get(LOG_URL, params={"limit": 501}, headers=_auth(admin, settings))).status_code == 422


async def _removed_clip(client, settings, owner, **fields) -> Clip:
    clip = await _clip(owner, **fields)
    await _act_on_clips(client, await _admin(), settings, "remove", [clip.id])
    return clip


async def _release(clip, **fields) -> Release:
    release = Release(
        clip_id=clip.id,
        user_id=clip.user_id,
        release_date=datetime.now(timezone.utc),
        **{k: v for k, v in RELEASE_METADATA.items() if k != "release_date"},
        **fields,
    )
    await release.insert()
    return release


@pytest.mark.integration
class TestRemovedClipStaysDown:
    """A removed clip cannot be republished through any owner path (US-27.3)."""

    async def test_soundcloud_upload_is_refused(self, client, settings):
        owner = await _user(tier=PRO)
        clip = await _removed_clip(client, settings, owner)

        resp = await client.post(
            f"{API_V1_PREFIX}/distribution/soundcloud/upload",
            json={"clip_id": str(clip.id)},
            headers=_auth(owner, settings),
        )

        assert resp.status_code == 403
        assert resp.json()["detail"] == REMOVED

    async def test_release_cannot_be_created(self, client, settings):
        owner = await _user()
        clip = await _removed_clip(client, settings, owner)

        resp = await client.post(
            RELEASES_URL, json={"clip_id": str(clip.id), **RELEASE_METADATA}, headers=_auth(owner, settings)
        )

        assert resp.status_code == 403
        assert resp.json()["detail"] == REMOVED
        assert await Release.find(Release.clip_id == clip.id).count() == 0

    @pytest.mark.parametrize("state", ["public", "unlisted"])
    async def test_release_cannot_be_made_visible(self, client, settings, state):
        owner = await _user()
        clip = await _clip(owner)
        # A SoundCloud track id means the route would sync sharing first; the refusal must come before it.
        release = await _release(clip, soundcloud_track_id="sc-1")
        await _act_on_clips(client, await _admin(), settings, "remove", [clip.id])

        resp = await client.patch(
            f"{RELEASES_URL}/{release.id}/visibility", json={"state": state}, headers=_auth(owner, settings)
        )

        assert resp.status_code == 403
        assert resp.json()["detail"] == REMOVED
        assert (await Release.get(release.id)).visibility == VisibilityState.PRIVATE
        assert (await Clip.get(clip.id)).visibility == VisibilityState.PRIVATE

    async def test_release_can_still_be_made_private(self, client, settings):
        owner = await _user()
        clip = await _clip(owner)
        release = await _release(clip)
        await _act_on_clips(client, await _admin(), settings, "remove", [clip.id])

        resp = await client.patch(
            f"{RELEASES_URL}/{release.id}/visibility", json={"state": "private"}, headers=_auth(owner, settings)
        )

        assert resp.status_code == 200

    @pytest.mark.parametrize("step", ["prepare", "submit"])
    async def test_release_cannot_be_distributed(self, client, settings, step):
        owner = await _user(tier=PRO)
        clip = await _clip(owner)
        release = await _release(clip, status=ReleaseStatus.READY)
        await _act_on_clips(client, await _admin(), settings, "remove", [clip.id])

        resp = await client.post(f"{RELEASES_URL}/{release.id}/{step}/distrokid", headers=_auth(owner, settings))

        assert resp.status_code == 403
        assert resp.json()["detail"] == REMOVED
        assert (await Release.get(release.id)).status == ReleaseStatus.READY

    async def test_published_video_goes_down_with_its_clip(self, client, settings):
        owner, stranger = await _user(), await _user()
        clip = await _clip(owner)
        video = Video(
            clip_id=clip.id,
            user_id=owner.id,
            job_id=PydanticObjectId(),
            storage_path="v.mp4",
            resolution="720p",
            aspect_ratio="16:9",
            published=True,
        )
        await video.insert()
        assert (await client.get(f"{VIDEOS_URL}/{video.id}")).status_code == 200

        await _act_on_clips(client, await _admin(), settings, "remove", [clip.id])

        for url in (f"{VIDEOS_URL}/{video.id}", f"{VIDEOS_URL}/for-clip/{clip.id}"):
            assert (await client.get(url)).status_code == 404
            assert (await client.get(url, headers=_auth(stranger, settings))).status_code == 403
