"""Tests for the playback queue endpoints (US-14.3, issue #140).

The 401 auth-gate tests run in CI (the router dependency rejects before any DB
access). The behaviour tests are ``integration``: they drive the real app with
``httpx.AsyncClient`` over a local MongoDB (``mongo_db``), mirroring
``tests/test_workspaces_api.py``.

Clip ids are opaque to the queue (it stores ids; ownership is enforced by the
per-user queue), so the tests use synthetic ObjectIds rather than real clips.
"""

import httpx
import pytest
from beanie import PydanticObjectId
from fastapi.testclient import TestClient

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.services import users as user_service
from acemusic.api.settings import ApiSettings

QUEUE_URL = f"{API_V1_PREFIX}/queue"


# ---------------------------------------------------------------------------
# Auth gate — runs in CI (no DB)
# ---------------------------------------------------------------------------


class TestAuthGate:
    @pytest.mark.parametrize(
        ("method", "url"),
        [
            ("GET", QUEUE_URL),
            ("POST", QUEUE_URL),
            ("DELETE", QUEUE_URL),
            ("PATCH", QUEUE_URL),
            ("PUT", f"{QUEUE_URL}/reorder"),
            ("POST", f"{QUEUE_URL}/next"),
            ("POST", f"{QUEUE_URL}/previous"),
            ("DELETE", f"{QUEUE_URL}/{PydanticObjectId()}"),
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


def _ids(n: int) -> list[str]:
    return [str(PydanticObjectId()) for _ in range(n)]


# --- Basic operations ------------------------------------------------------


@pytest.mark.integration
class TestBasicOperations:
    async def test_add_clips_returns_queue(self, client, settings) -> None:
        user = await _make_user("q-add@example.com")
        clips = _ids(3)
        resp = await client.post(QUEUE_URL, json={"clip_ids": clips}, headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        body = resp.json()
        assert body["clips"] == clips
        assert body["current_index"] == 0
        assert body["current_clip_id"] == clips[0]

    async def test_add_persists_across_requests(self, client, settings) -> None:
        user = await _make_user("q-persist@example.com")
        clips = _ids(2)
        await client.post(QUEUE_URL, json={"clip_ids": clips}, headers=_auth_headers(user, settings))
        resp = await client.get(QUEUE_URL, headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        assert resp.json()["clips"] == clips

    async def test_add_at_position_inserts(self, client, settings) -> None:
        user = await _make_user("q-pos@example.com")
        headers = _auth_headers(user, settings)
        a, b = _ids(2)
        c = str(PydanticObjectId())
        await client.post(QUEUE_URL, json={"clip_ids": [a, b]}, headers=headers)
        resp = await client.post(QUEUE_URL, json={"clip_ids": [c], "position": 1}, headers=headers)
        assert resp.json()["clips"] == [a, c, b]

    async def test_get_empty_queue_for_new_user(self, client, settings) -> None:
        user = await _make_user("q-empty@example.com")
        resp = await client.get(QUEUE_URL, headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        body = resp.json()
        assert body["clips"] == []
        assert body["current_index"] is None
        assert body["current_clip_id"] is None
        assert body["repeat_mode"] == "none"
        assert body["shuffle_enabled"] is False

    async def test_remove_clip_adjusts_current_index(self, client, settings) -> None:
        user = await _make_user("q-remove@example.com")
        headers = _auth_headers(user, settings)
        clips = _ids(3)
        await client.post(QUEUE_URL, json={"clip_ids": clips}, headers=headers)
        await client.post(f"{QUEUE_URL}/next", headers=headers)  # current_index -> 1
        resp = await client.request("DELETE", f"{QUEUE_URL}/{clips[0]}", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["clips"] == [clips[1], clips[2]]
        assert body["current_index"] == 0  # shifted down from 1

    async def test_remove_clip_not_in_queue_returns_404(self, client, settings) -> None:
        user = await _make_user("q-remove404@example.com")
        headers = _auth_headers(user, settings)
        await client.post(QUEUE_URL, json={"clip_ids": _ids(1)}, headers=headers)
        resp = await client.request("DELETE", f"{QUEUE_URL}/{PydanticObjectId()}", headers=headers)
        assert resp.status_code == 404

    async def test_clear_queue_returns_204(self, client, settings) -> None:
        user = await _make_user("q-clear@example.com")
        headers = _auth_headers(user, settings)
        await client.post(QUEUE_URL, json={"clip_ids": _ids(2)}, headers=headers)
        resp = await client.request("DELETE", QUEUE_URL, headers=headers)
        assert resp.status_code == 204
        after = await client.get(QUEUE_URL, headers=headers)
        assert after.json()["clips"] == []
        assert after.json()["current_index"] is None

    async def test_add_to_stopped_queue_does_not_restart(self, client, settings) -> None:
        # Play to the end under repeat=none (current_index -> None), then add a
        # clip: playback stays stopped rather than silently jumping back to 0.
        user = await _make_user("q-stopped@example.com")
        headers = _auth_headers(user, settings)
        await client.post(QUEUE_URL, json={"clip_ids": _ids(1)}, headers=headers)
        resp = await client.post(f"{QUEUE_URL}/next", headers=headers)
        assert resp.json()["current_index"] is None
        added = await client.post(QUEUE_URL, json={"clip_ids": _ids(1)}, headers=headers)
        assert added.json()["current_index"] is None

    async def test_add_empty_clip_ids_returns_422(self, client, settings) -> None:
        user = await _make_user("q-emptyadd@example.com")
        resp = await client.post(QUEUE_URL, json={"clip_ids": []}, headers=_auth_headers(user, settings))
        assert resp.status_code == 422

    async def test_invalid_clip_id_returns_400(self, client, settings) -> None:
        user = await _make_user("q-badid@example.com")
        resp = await client.post(QUEUE_URL, json={"clip_ids": ["not-an-id"]}, headers=_auth_headers(user, settings))
        assert resp.status_code == 400


# --- Navigation ------------------------------------------------------------


@pytest.mark.integration
class TestNavigation:
    async def test_next_advances(self, client, settings) -> None:
        user = await _make_user("q-next@example.com")
        headers = _auth_headers(user, settings)
        await client.post(QUEUE_URL, json={"clip_ids": _ids(3)}, headers=headers)
        resp = await client.post(f"{QUEUE_URL}/next", headers=headers)
        assert resp.json()["current_index"] == 1

    async def test_previous_decrements(self, client, settings) -> None:
        user = await _make_user("q-prev@example.com")
        headers = _auth_headers(user, settings)
        await client.post(QUEUE_URL, json={"clip_ids": _ids(3)}, headers=headers)
        await client.post(f"{QUEUE_URL}/next", headers=headers)
        resp = await client.post(f"{QUEUE_URL}/previous", headers=headers)
        assert resp.json()["current_index"] == 0

    async def test_repeat_one_keeps_position(self, client, settings) -> None:
        user = await _make_user("q-repeatone@example.com")
        headers = _auth_headers(user, settings)
        await client.post(QUEUE_URL, json={"clip_ids": _ids(3)}, headers=headers)
        await client.post(f"{QUEUE_URL}/next", headers=headers)  # -> 1
        await client.patch(QUEUE_URL, json={"repeat_mode": "one"}, headers=headers)
        resp = await client.post(f"{QUEUE_URL}/next", headers=headers)
        assert resp.json()["current_index"] == 1

    async def test_repeat_all_wraps_at_end(self, client, settings) -> None:
        user = await _make_user("q-repeatall@example.com")
        headers = _auth_headers(user, settings)
        await client.post(QUEUE_URL, json={"clip_ids": _ids(2)}, headers=headers)
        await client.patch(QUEUE_URL, json={"repeat_mode": "all"}, headers=headers)
        await client.post(f"{QUEUE_URL}/next", headers=headers)  # -> 1
        resp = await client.post(f"{QUEUE_URL}/next", headers=headers)  # wraps -> 0
        assert resp.json()["current_index"] == 0

    async def test_repeat_none_stops_at_end(self, client, settings) -> None:
        user = await _make_user("q-repeatnone@example.com")
        headers = _auth_headers(user, settings)
        await client.post(QUEUE_URL, json={"clip_ids": _ids(2)}, headers=headers)
        await client.post(f"{QUEUE_URL}/next", headers=headers)  # -> 1
        resp = await client.post(f"{QUEUE_URL}/next", headers=headers)  # end -> None
        body = resp.json()
        assert body["current_index"] is None
        assert body["current_clip_id"] is None

    async def test_shuffle_picks_from_remaining(self, client, settings) -> None:
        user = await _make_user("q-shuffle@example.com")
        headers = _auth_headers(user, settings)
        clips = _ids(5)
        await client.post(QUEUE_URL, json={"clip_ids": clips}, headers=headers)
        await client.patch(QUEUE_URL, json={"shuffle_enabled": True}, headers=headers)
        seen = {0}
        for _ in range(4):
            resp = await client.post(f"{QUEUE_URL}/next", headers=headers)
            idx = resp.json()["current_index"]
            assert idx not in seen  # never replays within the session
            seen.add(idx)
        assert seen == set(range(5))

    async def test_shuffle_previous_returns_to_last_played(self, client, settings) -> None:
        user = await _make_user("q-shuffleprev@example.com")
        headers = _auth_headers(user, settings)
        await client.post(QUEUE_URL, json={"clip_ids": _ids(4)}, headers=headers)
        await client.patch(QUEUE_URL, json={"shuffle_enabled": True}, headers=headers)
        await client.post(f"{QUEUE_URL}/next", headers=headers)  # history=[0]
        resp = await client.post(f"{QUEUE_URL}/previous", headers=headers)
        assert resp.json()["current_index"] == 0

    async def test_navigation_on_empty_queue_is_noop(self, client, settings) -> None:
        user = await _make_user("q-navempty@example.com")
        headers = _auth_headers(user, settings)
        resp = await client.post(f"{QUEUE_URL}/next", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["current_index"] is None


# --- Reorder ---------------------------------------------------------------


@pytest.mark.integration
class TestReorder:
    async def test_reorder_moves_clip(self, client, settings) -> None:
        user = await _make_user("q-reorder@example.com")
        headers = _auth_headers(user, settings)
        a, b, c = _ids(3)
        await client.post(QUEUE_URL, json={"clip_ids": [a, b, c]}, headers=headers)
        resp = await client.put(QUEUE_URL + "/reorder", json={"clip_id": c, "new_position": 0}, headers=headers)
        assert resp.json()["clips"] == [c, a, b]

    async def test_reorder_adjusts_current_index(self, client, settings) -> None:
        user = await _make_user("q-reorderidx@example.com")
        headers = _auth_headers(user, settings)
        a, b, c = _ids(3)
        await client.post(QUEUE_URL, json={"clip_ids": [a, b, c]}, headers=headers)
        # current_index is 0 (a). Move a to the end -> current should follow to 2.
        resp = await client.put(QUEUE_URL + "/reorder", json={"clip_id": a, "new_position": 2}, headers=headers)
        body = resp.json()
        assert body["clips"] == [b, c, a]
        assert body["current_index"] == 2
        assert body["current_clip_id"] == a

    async def test_reorder_missing_clip_returns_404(self, client, settings) -> None:
        user = await _make_user("q-reorder404@example.com")
        headers = _auth_headers(user, settings)
        await client.post(QUEUE_URL, json={"clip_ids": _ids(2)}, headers=headers)
        resp = await client.put(
            QUEUE_URL + "/reorder",
            json={"clip_id": str(PydanticObjectId()), "new_position": 0},
            headers=headers,
        )
        assert resp.status_code == 404


# --- User isolation --------------------------------------------------------


@pytest.mark.integration
class TestUserIsolation:
    async def test_queue_is_per_user(self, client, settings) -> None:
        alice = await _make_user("q-alice@example.com")
        bob = await _make_user("q-bob@example.com")
        alice_clips = _ids(2)
        await client.post(QUEUE_URL, json={"clip_ids": alice_clips}, headers=_auth_headers(alice, settings))
        # Bob sees his own (empty) queue, not Alice's.
        resp = await client.get(QUEUE_URL, headers=_auth_headers(bob, settings))
        assert resp.json()["clips"] == []

    async def test_user_cannot_remove_from_another_queue(self, client, settings) -> None:
        alice = await _make_user("q-alice2@example.com")
        bob = await _make_user("q-bob2@example.com")
        alice_clips = _ids(2)
        await client.post(QUEUE_URL, json={"clip_ids": alice_clips}, headers=_auth_headers(alice, settings))
        # Bob removing one of Alice's clip ids hits his own empty queue -> 404.
        resp = await client.request("DELETE", f"{QUEUE_URL}/{alice_clips[0]}", headers=_auth_headers(bob, settings))
        assert resp.status_code == 404
        # Alice's queue is untouched.
        after = await client.get(QUEUE_URL, headers=_auth_headers(alice, settings))
        assert after.json()["clips"] == alice_clips
