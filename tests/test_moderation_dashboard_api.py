"""Admin moderation dashboard (US-27.3).

The queue groups open listener reports and unreviewed automated flags per clip; admins
approve, remove or flag clips and warn or ban users in bulk, and every action lands in
the moderation log with who did it and when.
"""

import base64
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
    SoundCloudConnection,
    SoundCloudUnshare,
    User,
    Video,
    VisibilityState,
    Workspace,
)
from acemusic.api.services import moderation, routing, screening, soundcloud
from acemusic.api.services.tiers import PRO
from acemusic.api.settings import ApiSettings
from acemusic.api.tasks.soundcloud_poller import SoundCloudStatusPoller
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


async def _queue_page(client, admin, settings, **params) -> dict:
    resp = await client.get(QUEUE_URL, params=params, headers=_auth(admin, settings))
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _mixed_queue(owner) -> dict[str, str]:
    """Clips whose order differs by sort: most reports, highest severity and newest are all different."""
    now = datetime.now(timezone.utc)
    reporters = [await _user() for _ in range(3)]
    ids = {}
    for name, category, count, hours_ago in (
        ("three-spam", "spam", 3, 5),
        ("one-inappropriate", "inappropriate", 1, 4),
        ("one-copyright", "copyright", 1, 3),
        ("one-spam-new", "spam", 1, 1),
    ):
        clip = await _clip(owner, title=name)
        ids[name] = str(clip.id)
        for reporter in reporters[:count]:
            await _report(clip.id, category, reporter=reporter, at=now - timedelta(hours=hours_ago))
    flagged = await _clip(owner, title="flagged", moderation_flags=["violence"])
    await flagged.set({"created_at": now - timedelta(hours=2)})
    ids["flagged"] = str(flagged.id)
    return ids


@pytest.mark.integration
class TestQueuePaging:
    @pytest.mark.parametrize(
        "sort,expected",
        [
            ("reports", ["three-spam", "one-inappropriate", "one-copyright", "one-spam-new", "flagged"]),
            ("severity", ["one-inappropriate", "flagged", "one-copyright", "three-spam", "one-spam-new"]),
            ("newest", ["one-spam-new", "flagged", "one-copyright", "one-inappropriate", "three-spam"]),
        ],
    )
    async def test_the_server_sorts(self, client, settings, sort, expected):
        admin = await _admin()
        ids = await _mixed_queue(await _user())

        page = await _queue_page(client, admin, settings, sort=sort)

        assert [i["clip_id"] for i in page["items"]] == [ids[name] for name in expected]
        assert page["next_cursor"] is None

    @pytest.mark.parametrize("sort", ["reports", "severity", "newest"])
    async def test_cursor_pages_walk_every_item_once(self, client, settings, sort):
        admin = await _admin()
        await _mixed_queue(await _user())
        whole = [i["target_id"] for i in (await _queue_page(client, admin, settings, sort=sort))["items"]]

        seen, cursor, pages = [], None, 0
        while True:
            params = {"sort": sort, "limit": 2} | ({"cursor": cursor} if cursor else {})
            page = await _queue_page(client, admin, settings, **params)
            seen += [i["target_id"] for i in page["items"]]
            pages += 1
            assert pages <= 5, "the cursor never advanced"
            cursor = page["next_cursor"]
            if cursor is None:
                break

        assert seen == whole
        assert pages == 3

    async def test_acting_on_a_page_does_not_skip_the_next(self, client, settings):
        admin = await _admin()
        ids = await _mixed_queue(await _user())
        first = await _queue_page(client, admin, settings, limit=2)

        await _act_on_clips(client, admin, settings, "approve", [i["clip_id"] for i in first["items"]])
        second = await _queue_page(client, admin, settings, limit=2, cursor=first["next_cursor"])

        assert [i["clip_id"] for i in second["items"]] == [ids["one-copyright"], ids["one-spam-new"]]

    @pytest.mark.parametrize(
        "params,expected",
        [
            ({"source": "automated"}, ["flagged"]),
            ({"source": "report"}, ["three-spam", "one-inappropriate", "one-copyright", "one-spam-new"]),
            ({"category": "copyright"}, ["one-copyright"]),
            ({"category": "spam", "sort": "newest"}, ["one-spam-new", "three-spam"]),
            ({"source": "automated", "category": "spam"}, []),
        ],
    )
    async def test_the_server_filters(self, client, settings, params, expected):
        admin = await _admin()
        ids = await _mixed_queue(await _user())

        page = await _queue_page(client, admin, settings, **params)

        assert [i["clip_id"] for i in page["items"]] == [ids[name] for name in expected]

    @pytest.mark.parametrize(
        "params",
        [
            {"cursor": "not-a-cursor"},
            {"cursor": "WzEsMl0"},  # valid base64 JSON, wrong shape
            {"sort": "loudest"},
            {"source": "rumour"},
            {"category": "boring"},
            {"limit": 0},
            {"limit": 501},
        ],
    )
    async def test_bad_params_are_422(self, client, settings, params):
        resp = await client.get(QUEUE_URL, params=params, headers=_auth(await _admin(), settings))
        assert resp.status_code == 422

    # reports and severity keys have the same shape, so only a sort tag in the cursor tells them apart.
    @pytest.mark.parametrize(
        "minted,replayed", [("newest", "reports"), ("reports", "severity"), ("severity", "reports")]
    )
    async def test_a_cursor_from_another_sort_is_422(self, client, settings, minted, replayed):
        admin = await _admin()
        await _mixed_queue(await _user())
        cursor = (await _queue_page(client, admin, settings, sort=minted, limit=1))["next_cursor"]

        resp = await client.get(QUEUE_URL, params={"sort": replayed, "cursor": cursor}, headers=_auth(admin, settings))

        assert resp.status_code == 422


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
        assert entry.details == {
            "clips_removed": 1,
            "videos_unpublished": 0,
            "releases_privatized": 0,
            "soundcloud_unshare_queued": [],
        }

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

    async def test_a_platform_entry_has_no_actor(self, client, settings):
        admin = await _admin()
        await ModerationLogEntry(action="soundcloud_unshare_failed", target_type="clip", target_id="c1").insert()

        resp = await client.get(LOG_URL, headers=_auth(admin, settings))

        assert resp.status_code == 200
        [entry] = resp.json()["entries"]
        assert (entry["action"], entry["actor_id"]) == ("soundcloud_unshare_failed", None)

    async def test_limit(self, client, settings):
        admin = await _admin()
        for _ in range(3):
            await _act_on_users(client, admin, settings, "warn", [(await _user()).id])

        resp = await client.get(LOG_URL, params={"limit": 2}, headers=_auth(admin, settings))

        assert len(resp.json()["entries"]) == 2
        assert (await client.get(LOG_URL, params={"limit": 501}, headers=_auth(admin, settings))).status_code == 422

    async def test_cursor_pages_walk_the_log_newest_first(self, client, settings):
        admin = await _admin()
        now = datetime.now(timezone.utc)
        # Two entries share a timestamp, so the page boundary has to break the tie on id.
        stamps = [now - timedelta(minutes=m) for m in (5, 4, 3, 3, 1)]
        written = [
            await ModerationLogEntry(action="warn", target_type="user", target_id=str(i), created_at=at).insert()
            for i, at in enumerate(stamps)
        ]
        newest_first = sorted(written, key=lambda e: (e.created_at, e.id), reverse=True)

        seen, cursor = [], None
        while True:
            params = {"limit": 2} | ({"cursor": cursor} if cursor else {})
            body = (await client.get(LOG_URL, params=params, headers=_auth(admin, settings))).json()
            seen += [e["id"] for e in body["entries"]]
            assert len(seen) <= len(written), "the cursor never advanced"
            cursor = body["next_cursor"]
            if cursor is None:
                break

        assert seen == [str(e.id) for e in newest_first]

    async def test_a_new_entry_does_not_shift_the_next_page(self, client, settings):
        admin, owner = await _admin(), await _user()
        for _ in range(3):
            await _act_on_users(client, admin, settings, "warn", [owner.id])
        first = (await client.get(LOG_URL, params={"limit": 2}, headers=_auth(admin, settings))).json()

        await _act_on_users(client, admin, settings, "warn", [owner.id])
        second = (
            await client.get(
                LOG_URL, params={"limit": 2, "cursor": first["next_cursor"]}, headers=_auth(admin, settings)
            )
        ).json()

        assert len(second["entries"]) == 1
        assert second["next_cursor"] is None
        assert second["entries"][0]["id"] not in {e["id"] for e in first["entries"]}

    @pytest.mark.parametrize(
        "cursor",
        [
            "nope",
            # Well-formed, but its id is not an ObjectId.
            base64.urlsafe_b64encode(b'["log","2026-09-01T00:00:00","not-an-id"]').decode(),
        ],
    )
    async def test_a_bad_cursor_is_422(self, client, settings, cursor):
        resp = await client.get(LOG_URL, params={"cursor": cursor}, headers=_auth(await _admin(), settings))
        assert resp.status_code == 422

    async def test_entries_name_the_admin_and_the_target(self, client, settings):
        admin = await _user(is_admin=True, display_name="Ada Admin")
        owner = await _user(display_name="Owner Name")
        clip = await _clip(owner, title="Night Drive")

        await _act_on_clips(client, admin, settings, "flag", [clip.id])
        await _act_on_users(client, admin, settings, "warn", [owner.id])
        await ModerationLogEntry(
            action="soundcloud_unshare_failed", target_type="clip", target_id=str(clip.id)
        ).insert()

        entries = (await client.get(LOG_URL, headers=_auth(admin, settings))).json()["entries"]

        assert [(e["action"], e["actor_name"], e["target_label"]) for e in entries] == [
            ("soundcloud_unshare_failed", None, "Night Drive"),
            ("warn", "Ada Admin", "Owner Name"),
            ("flag", "Ada Admin", "Night Drive"),
        ]

    async def test_targets_that_have_no_name_label_as_none(self, client, settings):
        admin = await _admin()
        await ModerationLogEntry(
            actor_id=admin.id, action="remove", target_type="clip", target_id=str(PydanticObjectId())
        ).insert()
        await ModerationLogEntry(actor_id=admin.id, action="remove", target_type="clip", target_id="bad-id").insert()
        await ModerationLogEntry(
            actor_id=PydanticObjectId(), action="warn", target_type="user", target_id=None
        ).insert()
        await ModerationLogEntry(
            actor_id=admin.id, action="update_screening_rules", target_type="screening_rules"
        ).insert()

        entries = (await client.get(LOG_URL, headers=_auth(admin, settings))).json()["entries"]

        assert [e["target_label"] for e in entries] == [None, None, None, None]
        # A deleted admin has no name.
        assert [e["actor_name"] for e in entries] == [admin.name, None, admin.name, admin.name]


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


async def _sc_connection(owner) -> SoundCloudConnection:
    connection = SoundCloudConnection(
        user_id=owner.id,
        soundcloud_user_id=f"sc-{owner.id}",
        access_token="at",
        refresh_token="rt",
        token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    await connection.insert()
    return connection


@pytest.fixture
def sharing_calls(monkeypatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []

    async def update_track_sharing(_token, track_id, sharing):
        calls.append((track_id, sharing))
        return {}

    monkeypatch.setattr(soundcloud, "update_track_sharing", update_track_sharing)
    return calls


async def _latest_log(action: str) -> ModerationLogEntry:
    return (
        await ModerationLogEntry.find(ModerationLogEntry.action == action).sort(-ModerationLogEntry.id).first_or_none()
    )


async def _drain(settings) -> int:
    """Run the poller's queue drain once, as its next cycle would (#569)."""
    return await SoundCloudStatusPoller(settings).drain_unshares()


async def _queued_track_ids() -> list[str]:
    return sorted(row.track_id for row in await SoundCloudUnshare.find_all().to_list())


@pytest.mark.integration
class TestRemovalUnsharesSoundCloud:
    """#538: taking a clip down also takes down what was already distributed from it.

    #569: the takedown only queues each track; the SoundCloud poller makes it private off-request.
    """

    async def test_remove_makes_releases_private_and_queues_their_tracks(self, client, settings, sharing_calls):
        owner = await _user()
        clip = await _clip(owner)
        await _sc_connection(owner)
        shared = await _release(clip, visibility=VisibilityState.PUBLIC, soundcloud_track_id="sc-1")
        unshipped = await _release(clip, visibility=VisibilityState.UNLISTED)
        await _release(clip)  # already private: not counted as privatized

        [result] = await _act_on_clips(client, await _admin(), settings, "remove", [clip.id])

        assert result == {"clip_id": str(clip.id), "ok": True, "detail": None}
        # The admin request never waits on SoundCloud.
        assert sharing_calls == []
        for release in (shared, unshipped):
            assert (await Release.get(release.id)).visibility == VisibilityState.PRIVATE
        details = (await _latest_log("remove")).details
        assert details["releases_privatized"] == 2
        assert details["soundcloud_unshare_queued"] == ["sc-1"]

        assert await _drain(settings) == 1
        assert sharing_calls == [("sc-1", "private")]
        assert await _queued_track_ids() == []

    async def test_an_unreachable_track_is_abandoned_off_request_and_logged(self, client, settings, sharing_calls):
        owner = await _user()
        clip = await _clip(owner)
        # No SoundCloud connection: the owner unlinked their account, so the track can't be reached.
        release = await _release(clip, visibility=VisibilityState.PUBLIC, soundcloud_track_id="sc-9")

        [result] = await _act_on_clips(client, await _admin(), settings, "remove", [clip.id])

        assert result == {"clip_id": str(clip.id), "ok": True, "detail": None}
        assert (await Release.get(release.id)).visibility == VisibilityState.PRIVATE
        assert (await Clip.get(clip.id)).removed_at is not None
        assert await _queued_track_ids() == ["sc-9"]

        await _drain(settings)

        assert sharing_calls == []
        assert await _queued_track_ids() == []
        entry = await _latest_log("soundcloud_unshare_abandoned")
        assert entry.actor_id is None and entry.target_id == str(clip.id)
        assert entry.details["track_id"] == "sc-9"

    async def test_other_clips_tracks_are_untouched(self, client, settings, sharing_calls):
        owner = await _user()
        clip, other = await _clip(owner), await _clip(owner, soundcloud_track_ids=["sc-bare-other"])
        await _sc_connection(owner)
        kept = await _release(other, visibility=VisibilityState.PUBLIC, soundcloud_track_id="sc-other")

        await _act_on_clips(client, await _admin(), settings, "remove", [clip.id])
        await _drain(settings)

        assert sharing_calls == []
        assert (await Release.get(kept.id)).visibility == VisibilityState.PUBLIC

    async def test_remove_queues_a_bare_upload_recorded_on_the_clip(self, client, settings, sharing_calls):
        owner = await _user()
        clip = await _clip(owner, soundcloud_track_ids=["sc-bare"])
        await _sc_connection(owner)

        await _act_on_clips(client, await _admin(), settings, "remove", [clip.id])
        await _drain(settings)

        assert sharing_calls == [("sc-bare", "private")]

    async def test_ban_makes_every_release_private_and_queues_its_tracks(self, client, settings, sharing_calls):
        owner = await _user()
        await _sc_connection(owner)
        first = await _release(await _clip(owner), visibility=VisibilityState.PUBLIC, soundcloud_track_id="sc-a")
        second = await _release(await _clip(owner), visibility=VisibilityState.PUBLIC, soundcloud_track_id="sc-b")
        await _clip(owner, visibility=VisibilityState.PRIVATE, soundcloud_track_ids=["sc-bare"])

        [result] = await _act_on_users(client, await _admin(), settings, "ban", [owner.id])

        assert result == {"user_id": str(owner.id), "ok": True, "detail": None}
        assert sharing_calls == []
        for release in (first, second):
            assert (await Release.get(release.id)).visibility == VisibilityState.PRIVATE
        details = (await _latest_log("ban")).details
        assert details["soundcloud_unshare_queued"] == ["sc-a", "sc-b", "sc-bare"]

        assert await _drain(settings) == 3
        assert sorted(sharing_calls) == [("sc-a", "private"), ("sc-b", "private"), ("sc-bare", "private")]

    async def test_a_removal_landing_mid_share_leaves_the_track_private(self, client, settings, monkeypatch):
        owner, admin = await _user(), await _admin()
        clip = await _clip(owner, visibility=VisibilityState.PRIVATE)
        await _sc_connection(owner)
        release = await _release(clip, soundcloud_track_id="sc-race")
        calls: list[str] = []

        async def update_track_sharing(_token, track_id, sharing):
            if sharing == "public" and not calls:
                # The admin removes the clip after the route's local write; the moderation un-share
                # reaches SoundCloud first and the route's "public" PUT lands after it.
                await moderation.act_on_clip(str(admin.id), "remove", str(clip.id), None)
            calls.append(sharing)
            return {}

        monkeypatch.setattr(soundcloud, "update_track_sharing", update_track_sharing)

        resp = await client.patch(
            f"{RELEASES_URL}/{release.id}/visibility", json={"state": "public"}, headers=_auth(owner, settings)
        )

        assert resp.status_code == 403
        assert resp.json()["detail"] == REMOVED
        await _drain(settings)
        assert calls[-1] == "private"
        assert (await Release.get(release.id)).visibility == VisibilityState.PRIVATE
        assert (await Clip.get(clip.id)).visibility == VisibilityState.PRIVATE

    async def test_a_ban_landing_mid_publish_of_a_private_clip_leaves_the_track_private(
        self, client, settings, monkeypatch
    ):
        owner, admin = await _user(), await _admin()
        clip = await _clip(owner, visibility=VisibilityState.PRIVATE)
        await _sc_connection(owner)
        release = await _release(clip, soundcloud_track_id="sc-ban")
        real_enforce = screening.enforce
        calls: list[str] = []

        async def banned_while_screening(*texts, **kwargs):
            # After the route read the clip, before it writes it public: the ban's sweep skips a private clip.
            if not calls:
                calls.append("ban")
                await moderation.act_on_user(str(admin.id), "ban", str(owner.id), None)
            return await real_enforce(*texts, **kwargs)

        async def update_track_sharing(_token, track_id, sharing):
            calls.append(sharing)
            return {}

        monkeypatch.setattr(screening, "enforce", banned_while_screening)
        monkeypatch.setattr(soundcloud, "update_track_sharing", update_track_sharing)

        resp = await client.patch(
            f"{RELEASES_URL}/{release.id}/visibility", json={"state": "public"}, headers=_auth(owner, settings)
        )

        assert resp.status_code == 403
        assert resp.json()["detail"] == SUSPENDED
        await _drain(settings)
        assert calls[-1] == "private"
        assert (await Release.get(release.id)).visibility == VisibilityState.PRIVATE
        stored = await Clip.get(clip.id)
        # Taken down the way the ban would have, had its sweep seen the clip public.
        assert (stored.visibility, stored.removed_at is not None) == (VisibilityState.PRIVATE, True)


@pytest.mark.integration
class TestBulkActionsIsolateFailures:
    """#569: one target's unexpected error is that target's result; the rest of the batch still runs."""

    async def test_a_crashing_clip_does_not_abort_the_batch(self, client, settings, monkeypatch):
        owner = await _user()
        first, bad, last = await _clip(owner), await _clip(owner), await _clip(owner)
        real = moderation.act_on_clip

        async def flaky(actor_id, action, clip_id, reason):
            if clip_id == str(bad.id):
                raise RuntimeError("mongo went away")
            return await real(actor_id, action, clip_id, reason)

        monkeypatch.setattr(moderation, "act_on_clip", flaky)

        results = await _act_on_clips(client, await _admin(), settings, "remove", [first.id, bad.id, last.id])

        assert [r["ok"] for r in results] == [True, False, True]
        assert results[1]["clip_id"] == str(bad.id)
        assert "unexpected error" in results[1]["detail"]
        for clip in (first, last):
            assert (await Clip.get(clip.id)).removed_at is not None

    async def test_a_crashing_user_does_not_abort_the_batch(self, client, settings, monkeypatch):
        bad, good = await _user(), await _user()
        real = moderation.act_on_user

        async def flaky(actor_id, action, user_id, reason):
            if user_id == str(bad.id):
                raise RuntimeError("mongo went away")
            return await real(actor_id, action, user_id, reason)

        monkeypatch.setattr(moderation, "act_on_user", flaky)

        results = await _act_on_users(client, await _admin(), settings, "ban", [bad.id, good.id])

        assert [r["ok"] for r in results] == [False, True]
        assert (await User.get(good.id)).banned_at is not None
