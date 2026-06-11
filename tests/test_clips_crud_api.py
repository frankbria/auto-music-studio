"""Tests for the clip CRUD endpoints (US-9.4, issue #78).

Covers ``GET /clips`` (filters, sort, pagination), ``GET /clips/{id}``,
``PATCH /clips/{id}`` and ``DELETE /clips/{id}``. The audio retrieval endpoint
(US-9.3) is covered separately in ``tests/test_clips_api.py``.

The 401 auth-gate tests run in CI (no DB); the rest are ``integration`` and
drive the real app with ``httpx.AsyncClient`` over a local MongoDB.
"""

from datetime import datetime, timedelta, timezone

import httpx
import pytest
from beanie import PydanticObjectId
from fastapi.testclient import TestClient

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import Clip, Workspace
from acemusic.api.services import users as user_service
from acemusic.api.settings import ApiSettings
from acemusic.storage import get_storage_backend

CLIPS_URL = f"{API_V1_PREFIX}/clips"


# ---------------------------------------------------------------------------
# Auth gate — runs in CI (no DB)
# ---------------------------------------------------------------------------


class TestAuthGate:
    @pytest.mark.parametrize(
        ("method", "url"),
        [
            ("GET", CLIPS_URL),
            ("GET", f"{CLIPS_URL}/{PydanticObjectId()}"),
            ("PATCH", f"{CLIPS_URL}/{PydanticObjectId()}"),
            ("DELETE", f"{CLIPS_URL}/{PydanticObjectId()}"),
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


@pytest.fixture
def local_storage(monkeypatch, tmp_path):
    """Point the storage backend at a throwaway local root."""
    monkeypatch.setenv("ACEMUSIC_STORAGE_BACKEND", "local")
    monkeypatch.setenv("ACEMUSIC_STORAGE_LOCAL_ROOT", str(tmp_path))
    return tmp_path


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


async def _make_workspace(user, name: str = "WS") -> Workspace:
    workspace = Workspace(name=name, user_id=user.id)
    await workspace.insert()
    return workspace


_SEQ = {"n": 0}


async def _insert_clip(
    user,
    workspace: Workspace,
    *,
    title: str | None = None,
    style_tags: list[str] | None = None,
    bpm: int | None = None,
    key: str | None = None,
    model: str | None = None,
    is_public: bool = False,
    created_at: datetime | None = None,
    store_bytes: bytes | None = None,
) -> Clip:
    # Monotonic created_at default keeps sort order deterministic across clips
    # inserted within the same millisecond.
    _SEQ["n"] += 1
    if created_at is None:
        created_at = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=_SEQ["n"])
    clip_id = PydanticObjectId()
    file_path = f"{user.id}/{workspace.id}/clips/{clip_id}.wav"
    if store_bytes is not None:
        get_storage_backend().upload(file_path, store_bytes)
    clip = Clip(
        id=clip_id,
        user_id=user.id,
        workspace_id=workspace.id,
        file_path=file_path,
        format="wav",
        title=title,
        style_tags=style_tags or [],
        bpm=bpm,
        key=key,
        model=model,
        is_public=is_public,
        created_at=created_at,
    )
    await clip.insert()
    return clip


@pytest.mark.integration
class TestListClips:
    async def test_lists_only_own_clips_newest_first(self, client, settings) -> None:
        user = await _make_user("clips-list@example.com")
        other = await _make_user("clips-list-other@example.com")
        workspace = await _make_workspace(user)
        other_ws = await _make_workspace(other)
        first = await _insert_clip(user, workspace, title="first")
        second = await _insert_clip(user, workspace, title="second")
        await _insert_clip(other, other_ws, title="theirs")

        resp = await client.get(CLIPS_URL, headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert [c["id"] for c in body["clips"]] == [str(second.id), str(first.id)]

    async def test_sort_oldest_reverses_order(self, client, settings) -> None:
        user = await _make_user("clips-sort@example.com")
        workspace = await _make_workspace(user)
        first = await _insert_clip(user, workspace)
        second = await _insert_clip(user, workspace)

        resp = await client.get(CLIPS_URL, params={"sort": "oldest"}, headers=_auth_headers(user, settings))
        assert [c["id"] for c in resp.json()["clips"]] == [str(first.id), str(second.id)]

    async def test_invalid_sort_returns_422(self, client, settings) -> None:
        user = await _make_user("clips-sort-bad@example.com")
        resp = await client.get(CLIPS_URL, params={"sort": "loudest"}, headers=_auth_headers(user, settings))
        assert resp.status_code == 422

    async def test_pagination_metadata_and_page_slices(self, client, settings) -> None:
        user = await _make_user("clips-page@example.com")
        workspace = await _make_workspace(user)
        clips = [await _insert_clip(user, workspace) for _ in range(5)]
        newest_first = [str(c.id) for c in reversed(clips)]
        headers = _auth_headers(user, settings)

        page1 = (await client.get(CLIPS_URL, params={"per_page": 2}, headers=headers)).json()
        assert page1["total"] == 5
        assert page1["page"] == 1
        assert page1["per_page"] == 2
        assert page1["total_pages"] == 3
        assert [c["id"] for c in page1["clips"]] == newest_first[:2]

        page3 = (await client.get(CLIPS_URL, params={"per_page": 2, "page": 3}, headers=headers)).json()
        assert [c["id"] for c in page3["clips"]] == newest_first[4:]
        assert page3["total_pages"] == 3

        beyond = (await client.get(CLIPS_URL, params={"per_page": 2, "page": 4}, headers=headers)).json()
        assert beyond["clips"] == []
        assert beyond["total"] == 5

    @pytest.mark.parametrize("params", [{"page": 0}, {"per_page": 0}, {"per_page": 101}])
    async def test_pagination_bounds_return_422(self, client, settings, params: dict) -> None:
        user = await _make_user("clips-page-bad@example.com")
        resp = await client.get(CLIPS_URL, params=params, headers=_auth_headers(user, settings))
        assert resp.status_code == 422

    async def test_filter_by_workspace(self, client, settings) -> None:
        user = await _make_user("clips-ws@example.com")
        ws_a = await _make_workspace(user, "A")
        ws_b = await _make_workspace(user, "B")
        clip_a = await _insert_clip(user, ws_a)
        await _insert_clip(user, ws_b)

        resp = await client.get(
            CLIPS_URL, params={"workspace_id": str(ws_a.id)}, headers=_auth_headers(user, settings)
        )
        body = resp.json()
        assert body["total"] == 1
        assert body["clips"][0]["id"] == str(clip_a.id)

    async def test_other_users_workspace_filter_returns_404(self, client, settings) -> None:
        user = await _make_user("clips-ws-404@example.com")
        other = await _make_user("clips-ws-404-other@example.com")
        their_ws = await _make_workspace(other)

        resp = await client.get(
            CLIPS_URL, params={"workspace_id": str(their_ws.id)}, headers=_auth_headers(user, settings)
        )
        assert resp.status_code == 404

    async def test_malformed_workspace_filter_returns_404(self, client, settings) -> None:
        user = await _make_user("clips-ws-malformed@example.com")
        resp = await client.get(
            CLIPS_URL, params={"workspace_id": "not-an-object-id"}, headers=_auth_headers(user, settings)
        )
        assert resp.status_code == 404

    async def test_filter_by_style_substring(self, client, settings) -> None:
        user = await _make_user("clips-style@example.com")
        workspace = await _make_workspace(user)
        lofi = await _insert_clip(user, workspace, style_tags=["Lofi-HipHop", "chill"])
        await _insert_clip(user, workspace, style_tags=["rock"])

        resp = await client.get(CLIPS_URL, params={"style": "lofi"}, headers=_auth_headers(user, settings))
        body = resp.json()
        assert body["total"] == 1
        assert body["clips"][0]["id"] == str(lofi.id)

    async def test_filter_by_bpm_range(self, client, settings) -> None:
        user = await _make_user("clips-bpm@example.com")
        workspace = await _make_workspace(user)
        await _insert_clip(user, workspace, bpm=80)
        mid = await _insert_clip(user, workspace, bpm=120)
        await _insert_clip(user, workspace, bpm=160)

        resp = await client.get(
            CLIPS_URL, params={"bpm_min": 100, "bpm_max": 140}, headers=_auth_headers(user, settings)
        )
        body = resp.json()
        assert body["total"] == 1
        assert body["clips"][0]["id"] == str(mid.id)

    async def test_filter_by_key_and_model_exact(self, client, settings) -> None:
        user = await _make_user("clips-key@example.com")
        workspace = await _make_workspace(user)
        target = await _insert_clip(user, workspace, key="C minor", model="ace-step-v1")
        await _insert_clip(user, workspace, key="C major", model="ace-step-v1")
        await _insert_clip(user, workspace, key="C minor", model="other-model")
        headers = _auth_headers(user, settings)

        by_key = (await client.get(CLIPS_URL, params={"key": "C minor"}, headers=headers)).json()
        assert by_key["total"] == 2

        both = (
            await client.get(CLIPS_URL, params={"key": "C minor", "model": "ace-step-v1"}, headers=headers)
        ).json()
        assert both["total"] == 1
        assert both["clips"][0]["id"] == str(target.id)

    async def test_search_matches_title_and_style_case_insensitive(self, client, settings) -> None:
        user = await _make_user("clips-search@example.com")
        workspace = await _make_workspace(user)
        by_title = await _insert_clip(user, workspace, title="Midnight Drive")
        by_style = await _insert_clip(user, workspace, title="Untitled", style_tags=["midnight-jazz"])
        await _insert_clip(user, workspace, title="Sunrise")

        resp = await client.get(CLIPS_URL, params={"search": "MIDNIGHT"}, headers=_auth_headers(user, settings))
        body = resp.json()
        assert body["total"] == 2
        assert {c["id"] for c in body["clips"]} == {str(by_title.id), str(by_style.id)}

    async def test_search_with_regex_metacharacters_is_literal(self, client, settings) -> None:
        user = await _make_user("clips-search-regex@example.com")
        workspace = await _make_workspace(user)
        literal = await _insert_clip(user, workspace, title="beat (v2)")
        await _insert_clip(user, workspace, title="beat v2")

        resp = await client.get(CLIPS_URL, params={"search": "(v2)"}, headers=_auth_headers(user, settings))
        body = resp.json()
        assert body["total"] == 1
        assert body["clips"][0]["id"] == str(literal.id)


@pytest.mark.integration
class TestGetClip:
    async def test_get_own_clip_returns_full_metadata(self, client, settings) -> None:
        user = await _make_user("clips-get@example.com")
        workspace = await _make_workspace(user)
        clip = await _insert_clip(
            user, workspace, title="Mine", style_tags=["lofi"], bpm=90, key="A minor", model="ace-step-v1"
        )

        resp = await client.get(f"{CLIPS_URL}/{clip.id}", headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == str(clip.id)
        assert body["workspace_id"] == str(workspace.id)
        assert body["title"] == "Mine"
        assert body["style_tags"] == ["lofi"]
        assert body["bpm"] == 90
        assert body["key"] == "A minor"
        assert body["model"] == "ace-step-v1"
        assert body["format"] == "wav"
        assert body["created_at"]
        # Storage keys are internal; clients fetch audio via /clips/{id}/audio.
        assert "file_path" not in body

    async def test_unknown_clip_returns_404(self, client, settings) -> None:
        user = await _make_user("clips-get-unknown@example.com")
        resp = await client.get(f"{CLIPS_URL}/{PydanticObjectId()}", headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    async def test_malformed_id_returns_404(self, client, settings) -> None:
        user = await _make_user("clips-get-malformed@example.com")
        resp = await client.get(f"{CLIPS_URL}/not-an-object-id", headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    async def test_other_users_clip_returns_404_even_when_public(self, client, settings) -> None:
        owner = await _make_user("clips-get-owner@example.com")
        other = await _make_user("clips-get-other@example.com")
        workspace = await _make_workspace(owner)
        private = await _insert_clip(owner, workspace, is_public=False)
        public = await _insert_clip(owner, workspace, is_public=True)
        headers = _auth_headers(other, settings)

        # CRUD is owner-scoped (issue #78); public visibility applies only to
        # the audio endpoint (US-9.3).
        assert (await client.get(f"{CLIPS_URL}/{private.id}", headers=headers)).status_code == 404
        assert (await client.get(f"{CLIPS_URL}/{public.id}", headers=headers)).status_code == 404


@pytest.mark.integration
class TestUpdateClip:
    async def test_update_title_returns_updated_clip(self, client, settings) -> None:
        user = await _make_user("clips-patch@example.com")
        workspace = await _make_workspace(user)
        clip = await _insert_clip(user, workspace, title="Old Title")

        resp = await client.patch(
            f"{CLIPS_URL}/{clip.id}", json={"title": "New Title"}, headers=_auth_headers(user, settings)
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "New Title"

        fetched = await Clip.get(clip.id)
        assert fetched.title == "New Title"

    @pytest.mark.parametrize("payload", [{"title": ""}, {"title": "   "}, {"bpm": 90}, {"file_path": "x"}])
    async def test_blank_title_or_non_title_fields_return_422(self, client, settings, payload: dict) -> None:
        user = await _make_user("clips-patch-bad@example.com")
        workspace = await _make_workspace(user)
        clip = await _insert_clip(user, workspace, title="Keep")

        resp = await client.patch(f"{CLIPS_URL}/{clip.id}", json=payload, headers=_auth_headers(user, settings))
        assert resp.status_code == 422
        assert (await Clip.get(clip.id)).title == "Keep"

    async def test_unknown_clip_returns_404(self, client, settings) -> None:
        user = await _make_user("clips-patch-unknown@example.com")
        resp = await client.patch(
            f"{CLIPS_URL}/{PydanticObjectId()}", json={"title": "X"}, headers=_auth_headers(user, settings)
        )
        assert resp.status_code == 404

    async def test_other_users_clip_returns_404(self, client, settings) -> None:
        owner = await _make_user("clips-patch-owner@example.com")
        other = await _make_user("clips-patch-other@example.com")
        workspace = await _make_workspace(owner)
        clip = await _insert_clip(owner, workspace, title="Theirs")

        resp = await client.patch(
            f"{CLIPS_URL}/{clip.id}", json={"title": "Hijacked"}, headers=_auth_headers(other, settings)
        )
        assert resp.status_code == 404
        assert (await Clip.get(clip.id)).title == "Theirs"


@pytest.mark.integration
class TestDeleteClip:
    async def test_delete_removes_record_and_stored_audio(self, client, settings, local_storage) -> None:
        user = await _make_user("clips-del@example.com")
        workspace = await _make_workspace(user)
        clip = await _insert_clip(user, workspace, store_bytes=b"abc")
        stored_file = local_storage / clip.file_path
        assert stored_file.exists()

        resp = await client.delete(f"{CLIPS_URL}/{clip.id}", headers=_auth_headers(user, settings))
        assert resp.status_code == 204
        assert await Clip.get(clip.id) is None
        assert not stored_file.exists()

    async def test_delete_with_missing_audio_object_still_succeeds(self, client, settings, local_storage) -> None:
        user = await _make_user("clips-del-missing@example.com")
        workspace = await _make_workspace(user)
        clip = await _insert_clip(user, workspace)  # no stored bytes

        resp = await client.delete(f"{CLIPS_URL}/{clip.id}", headers=_auth_headers(user, settings))
        assert resp.status_code == 204
        assert await Clip.get(clip.id) is None

    async def test_unknown_clip_returns_404(self, client, settings) -> None:
        user = await _make_user("clips-del-unknown@example.com")
        resp = await client.delete(f"{CLIPS_URL}/{PydanticObjectId()}", headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    async def test_other_users_clip_returns_404(self, client, settings) -> None:
        owner = await _make_user("clips-del-owner@example.com")
        other = await _make_user("clips-del-other@example.com")
        workspace = await _make_workspace(owner)
        clip = await _insert_clip(owner, workspace)

        resp = await client.delete(f"{CLIPS_URL}/{clip.id}", headers=_auth_headers(other, settings))
        assert resp.status_code == 404
        assert await Clip.get(clip.id) is not None
