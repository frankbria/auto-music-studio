"""Tests for distribution status tracking endpoints (US-13.6, issue #137).

Auth-gate tests run in CI; the status/visibility flows are ``integration`` and
drive the real app over a local MongoDB, mirroring ``tests/test_releases_api.py``.
"""

import itertools
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from beanie import PydanticObjectId
from fastapi.testclient import TestClient

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import Clip, NotificationEvent, Release, SoundCloudConnection, Workspace
from acemusic.api.services import soundcloud as sc, users as user_service
from acemusic.api.services.mastering import APPROVED_GENERATION_MODE
from acemusic.api.settings import ApiSettings

RELEASES_URL = f"{API_V1_PREFIX}/releases"

FULL_METADATA = {
    "title": "Midnight Drive",
    "artist": "The Algorithm",
    "genre": "synthwave",
    "release_date": "2026-07-01T00:00:00Z",
}


# ---------------------------------------------------------------------------
# Auth gate — runs in CI (no DB)
# ---------------------------------------------------------------------------


class TestAuthGate:
    @pytest.mark.parametrize(
        ("method", "url"),
        [
            ("GET", f"{RELEASES_URL}/{PydanticObjectId()}/status"),
            ("PATCH", f"{RELEASES_URL}/{PydanticObjectId()}/channels/landr/status"),
            ("PATCH", f"{RELEASES_URL}/{PydanticObjectId()}/visibility"),
        ],
    )
    def test_missing_auth_header_returns_401(self, method: str, url: str) -> None:
        client = TestClient(create_app())
        resp = client.request(method, url)
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Integration — real MongoDB
# ---------------------------------------------------------------------------


def _async_client(app) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@pytest.fixture
def settings(mongo_db, mongo_settings) -> ApiSettings:
    return mongo_settings.model_copy(
        update={
            "jwt_secret_key": "test-secret-key-at-least-32-bytes-long-xx",
            "job_processor_enabled": False,
            "soundcloud_poller_enabled": False,
        }
    )


@pytest.fixture
async def client(settings):
    async with _async_client(create_app(settings)) as ac:
        yield ac


def _auth_headers(user, settings: ApiSettings) -> dict[str, str]:
    token = create_access_token(
        user_id=str(user.id),
        email=user.email,
        subscription_tier=user.subscription_tier,
        settings=settings,
    )
    return {"Authorization": f"Bearer {token}"}


async def _make_user(email: str):
    return await user_service.get_or_create_user(email=email, provider="google", oauth_id=f"g-{email}", name="T")


_SEQ = itertools.count(1)


async def _insert_clip(user) -> Clip:
    workspace = Workspace(name=f"WS-{next(_SEQ)}", user_id=user.id)
    await workspace.insert()
    clip_id = PydanticObjectId()
    clip = Clip(
        id=clip_id,
        user_id=user.id,
        workspace_id=workspace.id,
        file_path=f"{user.id}/{workspace.id}/clips/{clip_id}.wav",
        format="wav",
        title="Source",
        generation_mode=APPROVED_GENERATION_MODE,
        artwork_path=f"{user.id}/art/{clip_id}.png",
    )
    await clip.insert()
    return clip


async def _create_release(client, user, settings, **overrides) -> dict:
    clip = await _insert_clip(user)
    payload = {"clip_id": str(clip.id), **FULL_METADATA, **overrides}
    resp = await client.post(RELEASES_URL, json=payload, headers=_auth_headers(user, settings))
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _patch_channel(client, user, settings, release_id, channel, status) -> httpx.Response:
    return await client.patch(
        f"{RELEASES_URL}/{release_id}/channels/{channel}/status",
        json={"status": status},
        headers=_auth_headers(user, settings),
    )


@pytest.mark.integration
class TestListingAndStatus:
    async def test_listing_includes_channel_statuses_and_visibility(self, client, settings) -> None:
        user = await _make_user("ds-list@example.com")
        created = await _create_release(client, user, settings)
        # Default state: no channels engaged, private.
        assert created["channel_statuses"] == {}
        assert created["visibility"] == "private"

        listed = await client.get(RELEASES_URL, headers=_auth_headers(user, settings))
        body = listed.json()["releases"][0]
        assert body["channel_statuses"] == {}
        assert body["visibility"] == "private"

    async def test_status_endpoint_returns_channels(self, client, settings) -> None:
        user = await _make_user("ds-status@example.com")
        created = await _create_release(client, user, settings)
        await _patch_channel(client, user, settings, created["id"], "landr", "ready")

        resp = await client.get(f"{RELEASES_URL}/{created['id']}/status", headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        body = resp.json()
        assert body["release_id"] == created["id"]
        assert body["title"] == FULL_METADATA["title"]
        assert {"channel": "landr", "status": "ready"} in body["channels"]

    async def test_status_other_users_release_returns_404(self, client, settings) -> None:
        owner = await _make_user("ds-status-owner@example.com")
        intruder = await _make_user("ds-status-intruder@example.com")
        created = await _create_release(client, owner, settings)
        resp = await client.get(f"{RELEASES_URL}/{created['id']}/status", headers=_auth_headers(intruder, settings))
        assert resp.status_code == 404


@pytest.mark.integration
class TestManualChannelStatus:
    async def test_valid_transition_is_stored(self, client, settings) -> None:
        user = await _make_user("ds-manual-ok@example.com")
        created = await _create_release(client, user, settings)
        resp = await _patch_channel(client, user, settings, created["id"], "distrokid", "ready")
        assert resp.status_code == 200
        assert resp.json() == {"channel": "distrokid", "status": "ready"}

        stored = await Release.get(PydanticObjectId(created["id"]))
        assert stored.channel_statuses["distrokid"].value == "ready"

    async def test_skip_transition_returns_409(self, client, settings) -> None:
        user = await _make_user("ds-manual-skip@example.com")
        created = await _create_release(client, user, settings)
        # draft (implicit) → live is a skip.
        resp = await _patch_channel(client, user, settings, created["id"], "landr", "live")
        assert resp.status_code == 409

    async def test_soundcloud_channel_rejected_with_400(self, client, settings) -> None:
        user = await _make_user("ds-manual-sc@example.com")
        created = await _create_release(client, user, settings)
        resp = await _patch_channel(client, user, settings, created["id"], "soundcloud", "ready")
        assert resp.status_code == 400
        assert "automatically" in resp.json()["detail"].lower()

    async def test_unknown_channel_returns_400(self, client, settings) -> None:
        user = await _make_user("ds-manual-unknown@example.com")
        created = await _create_release(client, user, settings)
        resp = await _patch_channel(client, user, settings, created["id"], "bandcamp", "ready")
        assert resp.status_code == 400

    async def test_invalid_status_value_returns_422(self, client, settings) -> None:
        user = await _make_user("ds-manual-422@example.com")
        created = await _create_release(client, user, settings)
        resp = await _patch_channel(client, user, settings, created["id"], "landr", "banana")
        assert resp.status_code == 422

    async def test_reaching_live_records_notification(self, client, settings) -> None:
        user = await _make_user("ds-manual-notify@example.com")
        created = await _create_release(client, user, settings)
        # Walk the full sequence to a terminal state.
        for step in ("ready", "submitted", "in_review", "live"):
            resp = await _patch_channel(client, user, settings, created["id"], "tunecore", step)
            assert resp.status_code == 200, (step, resp.text)

        events = await NotificationEvent.find(NotificationEvent.release_id == PydanticObjectId(created["id"])).to_list()
        assert len(events) == 1
        assert events[0].event_type == "status_live"
        assert events[0].channel == "tunecore"
        assert events[0].delivered_at is None


@pytest.mark.integration
class TestVisibility:
    async def test_update_visibility_persists(self, client, settings) -> None:
        user = await _make_user("ds-vis@example.com")
        created = await _create_release(client, user, settings)
        resp = await client.patch(
            f"{RELEASES_URL}/{created['id']}/visibility",
            json={"state": "public"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 200
        assert resp.json()["visibility"] == "public"
        assert (await Release.get(PydanticObjectId(created["id"]))).visibility.value == "public"

    async def test_visibility_syncs_soundcloud_sharing(self, client, settings, monkeypatch) -> None:
        user = await _make_user("ds-vis-sc@example.com")
        created = await _create_release(client, user, settings)
        # Put the release on SoundCloud and give the user a live connection.
        release = await Release.get(PydanticObjectId(created["id"]))
        release.soundcloud_track_id = "789"
        await release.save()
        await SoundCloudConnection(
            user_id=user.id,
            soundcloud_user_id="sc-1",
            access_token="tok",
            refresh_token="ref",
            token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        ).insert()

        calls: list[tuple[str, str, str]] = []

        async def _fake_sharing(access_token: str, track_id: str, sharing: str) -> dict:
            calls.append((access_token, track_id, sharing))
            return {}

        monkeypatch.setattr(sc, "update_track_sharing", _fake_sharing)

        resp = await client.patch(
            f"{RELEASES_URL}/{created['id']}/visibility",
            json={"state": "public"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 200
        assert calls == [("tok", "789", "public")]

    async def test_visibility_unaffected_by_soundcloud_failure(self, client, settings, monkeypatch) -> None:
        user = await _make_user("ds-vis-scfail@example.com")
        created = await _create_release(client, user, settings)
        release = await Release.get(PydanticObjectId(created["id"]))
        release.soundcloud_track_id = "789"
        await release.save()
        # No connection at all → get_valid_connection raises; the local change must stand.
        resp = await client.patch(
            f"{RELEASES_URL}/{created['id']}/visibility",
            json={"state": "unlisted"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 200
        assert resp.json()["visibility"] == "unlisted"

    async def test_visibility_other_users_release_returns_404(self, client, settings) -> None:
        owner = await _make_user("ds-vis-owner@example.com")
        intruder = await _make_user("ds-vis-intruder@example.com")
        created = await _create_release(client, owner, settings)
        resp = await client.patch(
            f"{RELEASES_URL}/{created['id']}/visibility",
            json={"state": "public"},
            headers=_auth_headers(intruder, settings),
        )
        assert resp.status_code == 404
