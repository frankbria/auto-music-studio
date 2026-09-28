"""In-app notification inbox (#537).

Moderation, appeal, voice-training and distribution code records ``NotificationEvent`` rows; this
is the creator-facing read side: list your own notices newest first, and mark them read, which
stamps ``delivered_at``. A notice is only ever visible to the user it was addressed to.
"""

import itertools
from datetime import datetime, timedelta

import httpx
import pytest
from beanie import PydanticObjectId

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import Clip, NotificationEvent, VisibilityState, Workspace
from acemusic.api.models.common import utcnow
from acemusic.api.settings import ApiSettings
from tests.users import make_user

pytestmark = pytest.mark.integration

NOTIFICATIONS_URL = f"{API_V1_PREFIX}/users/me/notifications"
READ_URL = f"{NOTIFICATIONS_URL}/read"
MODERATION_URL = f"{API_V1_PREFIX}/admin/moderation"

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


async def _user(**fields):
    return await make_user(f"notify-{next(_SEQ)}@example.com", **fields)


async def _clip(owner, title="Takedown") -> Clip:
    workspace = Workspace(name=f"WS-{next(_SEQ)}", user_id=owner.id)
    await workspace.insert()
    clip_id = PydanticObjectId()
    clip = Clip(
        id=clip_id,
        user_id=owner.id,
        workspace_id=workspace.id,
        file_path=f"{owner.id}/{workspace.id}/clips/{clip_id}.wav",
        format="wav",
        title=title,
        visibility=VisibilityState.PUBLIC,
    )
    await clip.insert()
    return clip


async def _event(user, minutes_ago: int, event_type: str = "status_live", **fields) -> NotificationEvent:
    event = NotificationEvent(
        user_id=user.id,
        event_type=event_type,
        channel="in_app",
        created_at=utcnow() - timedelta(minutes=minutes_ago),
        **fields,
    )
    await event.insert()
    return event


async def _inbox(client, settings, user, **params) -> dict:
    resp = await client.get(NOTIFICATIONS_URL, params=params, headers=_auth(user, settings))
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestModerationNotices:
    async def test_a_removal_notice_reaches_the_creator_with_its_reason(self, client, settings):
        owner = await _user()
        clip = await _clip(owner, title="Takedown")
        admin = await _user(is_admin=True)

        resp = await client.post(
            f"{MODERATION_URL}/clips",
            json={"action": "remove", "clip_ids": [str(clip.id)], "reason": "Copyrighted sample"},
            headers=_auth(admin, settings),
        )
        assert resp.status_code == 200 and resp.json()["results"][0]["ok"], resp.text

        body = await _inbox(client, settings, owner)
        [notice] = body["notifications"]
        assert notice["event_type"] == "moderation_clip_removed"
        assert notice["clip_id"] == str(clip.id)
        assert notice["payload"] == {"clip_id": str(clip.id), "title": "Takedown", "reason": "Copyrighted sample"}
        assert notice["read"] is False
        assert body["unread_count"] == 1

    async def test_a_removal_notice_is_invisible_to_anyone_else(self, client, settings):
        owner = await _user()
        clip = await _clip(owner)
        admin = await _user(is_admin=True)
        await client.post(
            f"{MODERATION_URL}/clips",
            json={"action": "remove", "clip_ids": [str(clip.id)], "reason": "Spam"},
            headers=_auth(admin, settings),
        )

        for bystander in (await _user(), admin):
            body = await _inbox(client, settings, bystander)
            assert body == {"notifications": [], "unread_count": 0, "has_more": False}

    async def test_a_warning_reaches_the_warned_user_with_its_reason(self, client, settings):
        user = await _user()
        resp = await client.post(
            f"{MODERATION_URL}/users",
            json={"action": "warn", "user_ids": [str(user.id)], "reason": "Mislabelled uploads"},
            headers=_auth(await _user(is_admin=True), settings),
        )
        assert resp.status_code == 200, resp.text

        [notice] = (await _inbox(client, settings, user))["notifications"]
        assert notice["event_type"] == "moderation_warning"
        assert notice["payload"] == {"reason": "Mislabelled uploads"}


class TestListing:
    async def test_newest_first_and_paginated(self, client, settings):
        user = await _user()
        events = [await _event(user, minutes_ago=m) for m in (30, 10, 20)]
        newest, middle, oldest = events[1], events[2], events[0]

        first = await _inbox(client, settings, user, limit=2)
        assert [n["id"] for n in first["notifications"]] == [str(newest.id), str(middle.id)]
        assert first["has_more"] is True
        assert first["unread_count"] == 3

        rest = await _inbox(client, settings, user, limit=2, offset=2)
        assert [n["id"] for n in rest["notifications"]] == [str(oldest.id)]
        assert rest["has_more"] is False

    async def test_created_at_is_explicit_utc(self, client, settings):
        user = await _user()
        await _event(user, minutes_ago=5)

        [notice] = (await _inbox(client, settings, user))["notifications"]
        stamp = datetime.fromisoformat(notice["created_at"].replace("Z", "+00:00"))
        assert stamp.utcoffset() == timedelta(0)

    async def test_limit_is_bounded(self, client, settings):
        user = await _user()
        resp = await client.get(NOTIFICATIONS_URL, params={"limit": 101}, headers=_auth(user, settings))
        assert resp.status_code == 422

    async def test_requires_authentication(self, client, settings):
        assert (await client.get(NOTIFICATIONS_URL)).status_code == 401
        assert (await client.post(READ_URL, json={})).status_code == 401


class TestMarkRead:
    async def test_marking_one_read_stamps_delivered_at(self, client, settings):
        user = await _user()
        target = await _event(user, minutes_ago=2)
        other = await _event(user, minutes_ago=1)

        resp = await client.post(READ_URL, json={"ids": [str(target.id)]}, headers=_auth(user, settings))

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"updated": 1}
        assert (await NotificationEvent.get(target.id)).delivered_at is not None
        assert (await NotificationEvent.get(other.id)).delivered_at is None
        body = await _inbox(client, settings, user)
        assert {n["id"]: n["read"] for n in body["notifications"]} == {str(target.id): True, str(other.id): False}
        assert body["unread_count"] == 1

    async def test_marking_all_read_leaves_other_users_alone(self, client, settings):
        user, stranger = await _user(), await _user()
        for m in (1, 2):
            await _event(user, minutes_ago=m)
        theirs = await _event(stranger, minutes_ago=1)

        resp = await client.post(READ_URL, json={}, headers=_auth(user, settings))

        assert resp.json() == {"updated": 2}
        assert (await _inbox(client, settings, user))["unread_count"] == 0
        assert (await NotificationEvent.get(theirs.id)).delivered_at is None

    async def test_cannot_mark_someone_elses_notice(self, client, settings):
        user, stranger = await _user(), await _user()
        theirs = await _event(stranger, minutes_ago=1)

        resp = await client.post(READ_URL, json={"ids": [str(theirs.id)]}, headers=_auth(user, settings))

        assert resp.json() == {"updated": 0}
        assert (await NotificationEvent.get(theirs.id)).delivered_at is None

    async def test_marking_read_again_keeps_the_first_timestamp(self, client, settings):
        user = await _user()
        event = await _event(user, minutes_ago=1)
        await client.post(READ_URL, json={"ids": [str(event.id)]}, headers=_auth(user, settings))
        first = (await NotificationEvent.get(event.id)).delivered_at

        resp = await client.post(READ_URL, json={"ids": [str(event.id)]}, headers=_auth(user, settings))

        assert resp.json() == {"updated": 0}
        assert (await NotificationEvent.get(event.id)).delivered_at == first

    async def test_malformed_ids_are_rejected(self, client, settings):
        user = await _user()
        resp = await client.post(READ_URL, json={"ids": ["not-an-id"]}, headers=_auth(user, settings))
        assert resp.status_code == 422
