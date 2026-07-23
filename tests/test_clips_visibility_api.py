"""Tests for the three-state clip visibility model (US-20.7, issue #219).

Extends the existing two-state ``is_public`` publish toggle (US-17.6) to a
three-state ``visibility`` enum (private/unlisted/public) on the *existing*
``PATCH /clips/{id}`` endpoint — no new endpoint. ``is_public`` stays a stored,
auto-synced denormalization of ``visibility == PUBLIC`` so
``{"is_public": True}`` Mongo queries (public listings, similarity scope) keep
matching unchanged and legacy public clips never regress to private.
"""

import itertools

import httpx
import pytest
from beanie import PydanticObjectId
from fastapi.testclient import TestClient

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import Clip, VisibilityState, Workspace
from acemusic.api.services import users as user_service
from acemusic.api.settings import ApiSettings
from acemusic.storage import get_storage_backend

CLIPS_URL = f"{API_V1_PREFIX}/clips"

_SEQ = itertools.count(1)


# ---------------------------------------------------------------------------
# Auth gate — runs in CI (no DB)
# ---------------------------------------------------------------------------


class TestAuthGate:
    def test_missing_auth_header_returns_401(self) -> None:
        client = TestClient(create_app())
        resp = client.patch(f"{CLIPS_URL}/{PydanticObjectId()}", json={"visibility": "public"})
        assert resp.status_code == 401


def _model_base_kwargs() -> dict:
    return dict(
        id=PydanticObjectId(),
        workspace_id=PydanticObjectId(),
        user_id=PydanticObjectId(),
        file_path="u/w/clips/c.wav",
    )


# ---------------------------------------------------------------------------
# Model unit test — no DB, no Beanie init. `set_visibility` is a plain method,
# so `model_construct` (which bypasses Beanie's collection-bound __init__) lets
# this guard the assignment invariant even when MongoDB is unavailable.
# ---------------------------------------------------------------------------


class TestVisibilityModelSync:
    def test_set_visibility_keeps_is_public_synced_on_assignment(self) -> None:
        # The after-validator that syncs is_public does NOT fire on attribute
        # assignment (validate_assignment is off), so writers must go through
        # set_visibility. If they don't, the stale is_public denormalization
        # leaks unlisted/private clips into {"is_public": True} queries.
        clip = Clip.model_construct(visibility=VisibilityState.PUBLIC, is_public=True)

        clip.set_visibility(VisibilityState.UNLISTED)
        assert clip.visibility == VisibilityState.UNLISTED
        assert clip.is_public is False

        clip.set_visibility(VisibilityState.PUBLIC)
        assert clip.is_public is True

        clip.set_visibility(VisibilityState.PRIVATE)
        assert clip.is_public is False


# ---------------------------------------------------------------------------
# Integration — real MongoDB
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestVisibilityValidators:
    """The before/after validators only run on real Pydantic construction, which
    for a Beanie Document requires init_beanie — hence the ``mongo_db`` fixture."""

    def test_legacy_doc_with_only_is_public_backfills_visibility(self, mongo_db) -> None:
        # Simulates a pre-US-20.7 Mongo document: no "visibility" key at all.
        clip = Clip(**_model_base_kwargs(), is_public=True)
        assert clip.visibility == VisibilityState.PUBLIC

        clip = Clip(**_model_base_kwargs(), is_public=False)
        assert clip.visibility == VisibilityState.PRIVATE

    def test_visibility_unlisted_forces_is_public_false(self, mongo_db) -> None:
        clip = Clip(**_model_base_kwargs(), visibility=VisibilityState.UNLISTED)
        assert clip.is_public is False

    def test_visibility_public_forces_is_public_true(self, mongo_db) -> None:
        clip = Clip(**_model_base_kwargs(), visibility=VisibilityState.PUBLIC)
        assert clip.is_public is True

    def test_visibility_wins_over_conflicting_is_public(self, mongo_db) -> None:
        # visibility is the source of truth even if a caller passes a
        # contradictory is_public alongside it.
        clip = Clip(**_model_base_kwargs(), visibility=VisibilityState.PUBLIC, is_public=False)
        assert clip.is_public is True


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


async def _insert_clip(
    user,
    workspace: Workspace,
    *,
    title: str | None = "Ready",
    style_tags: list[str] | None = None,
    visibility: VisibilityState = VisibilityState.PRIVATE,
    store_bytes: bytes | None = None,
) -> Clip:
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
        style_tags=style_tags if style_tags is not None else ["lofi"],
        visibility=visibility,
    )
    await clip.insert()
    return clip


@pytest.mark.integration
class TestVisibilityTransitions:
    async def test_private_to_unlisted_to_public_to_private(self, client, settings) -> None:
        user = await _make_user(f"vis-transitions-{next(_SEQ)}@example.com")
        workspace = await _make_workspace(user)
        clip = await _insert_clip(user, workspace)
        headers = _auth_headers(user, settings)

        resp = await client.patch(f"{CLIPS_URL}/{clip.id}", json={"visibility": "unlisted"}, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["visibility"] == "unlisted"
        assert resp.json()["is_public"] is False
        fetched = await client.get(f"{CLIPS_URL}/{clip.id}", headers=headers)
        assert fetched.json()["visibility"] == "unlisted"

        resp = await client.patch(f"{CLIPS_URL}/{clip.id}", json={"visibility": "public"}, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["visibility"] == "public"
        assert resp.json()["is_public"] is True
        fetched = await client.get(f"{CLIPS_URL}/{clip.id}", headers=headers)
        assert fetched.json()["visibility"] == "public"
        assert fetched.json()["is_public"] is True

        resp = await client.patch(f"{CLIPS_URL}/{clip.id}", json={"visibility": "private"}, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["visibility"] == "private"
        assert resp.json()["is_public"] is False
        stored = await Clip.get(clip.id)
        assert stored.visibility == VisibilityState.PRIVATE
        assert stored.is_public is False

    async def test_is_public_denormalization_synced_in_raw_bson(self, client, settings) -> None:
        # Reading a clip back through Clip.get()/ClipResponse re-runs the sync
        # validator and self-heals is_public, so it masks a stale stored value.
        # Server-side queries (search/explore/similar) filter the raw BSON on
        # {"is_public": True}, so the DENORMALIZATION IN STORAGE must be correct.
        # Assert on the raw pymongo document — this is what caught set-on-assign
        # not re-running the after-validator.
        user = await _make_user(f"vis-raw-bson-{next(_SEQ)}@example.com")
        workspace = await _make_workspace(user)
        clip = await _insert_clip(user, workspace)
        headers = _auth_headers(user, settings)
        raw = Clip.get_pymongo_collection()

        await client.patch(f"{CLIPS_URL}/{clip.id}", json={"visibility": "public"}, headers=headers)
        doc = await raw.find_one({"_id": clip.id})
        assert doc["visibility"] == "public" and doc["is_public"] is True

        await client.patch(f"{CLIPS_URL}/{clip.id}", json={"visibility": "unlisted"}, headers=headers)
        doc = await raw.find_one({"_id": clip.id})
        assert doc["visibility"] == "unlisted" and doc["is_public"] is False  # not stale True

    async def test_public_without_title_returns_422(self, client, settings) -> None:
        user = await _make_user(f"vis-no-title-{next(_SEQ)}@example.com")
        workspace = await _make_workspace(user)
        clip = await _insert_clip(user, workspace, title=None, style_tags=["lofi"])
        headers = _auth_headers(user, settings)

        resp = await client.patch(f"{CLIPS_URL}/{clip.id}", json={"visibility": "public"}, headers=headers)
        assert resp.status_code == 422
        assert (await Clip.get(clip.id)).visibility == VisibilityState.PRIVATE

    async def test_public_without_style_tags_returns_422(self, client, settings) -> None:
        user = await _make_user(f"vis-no-tags-{next(_SEQ)}@example.com")
        workspace = await _make_workspace(user)
        clip = await _insert_clip(user, workspace, title="Ready", style_tags=[])
        headers = _auth_headers(user, settings)

        resp = await client.patch(f"{CLIPS_URL}/{clip.id}", json={"visibility": "public"}, headers=headers)
        assert resp.status_code == 422
        assert (await Clip.get(clip.id)).visibility == VisibilityState.PRIVATE

    async def test_explicit_null_visibility_returns_422(self, client, settings) -> None:
        user = await _make_user(f"vis-null-{next(_SEQ)}@example.com")
        workspace = await _make_workspace(user)
        clip = await _insert_clip(user, workspace)
        headers = _auth_headers(user, settings)

        resp = await client.patch(f"{CLIPS_URL}/{clip.id}", json={"visibility": None}, headers=headers)
        assert resp.status_code == 422

    async def test_cross_user_patch_returns_404(self, client, settings) -> None:
        owner = await _make_user(f"vis-owner-{next(_SEQ)}@example.com")
        other = await _make_user(f"vis-other-{next(_SEQ)}@example.com")
        workspace = await _make_workspace(owner)
        clip = await _insert_clip(owner, workspace)

        resp = await client.patch(
            f"{CLIPS_URL}/{clip.id}",
            json={"visibility": "public"},
            headers=_auth_headers(other, settings),
        )
        assert resp.status_code == 404


@pytest.mark.integration
class TestVisibilityAudioAccess:
    async def test_non_owner_can_get_audio_for_unlisted_clip(self, client, settings, local_storage) -> None:
        owner = await _make_user(f"vis-audio-owner-{next(_SEQ)}@example.com")
        stranger = await _make_user(f"vis-audio-stranger-{next(_SEQ)}@example.com")
        workspace = await _make_workspace(owner)
        clip = await _insert_clip(
            owner, workspace, visibility=VisibilityState.UNLISTED, store_bytes=b"RIFF....WAVEfake"
        )

        resp = await client.get(f"{CLIPS_URL}/{clip.id}/audio", headers=_auth_headers(stranger, settings))
        assert resp.status_code == 200

    async def test_non_owner_gets_403_for_private_clip_audio(self, client, settings, local_storage) -> None:
        owner = await _make_user(f"vis-audio-private-owner-{next(_SEQ)}@example.com")
        stranger = await _make_user(f"vis-audio-private-stranger-{next(_SEQ)}@example.com")
        workspace = await _make_workspace(owner)
        clip = await _insert_clip(owner, workspace, visibility=VisibilityState.PRIVATE, store_bytes=b"RIFF....WAVEfake")

        resp = await client.get(f"{CLIPS_URL}/{clip.id}/audio", headers=_auth_headers(stranger, settings))
        assert resp.status_code == 403


@pytest.mark.integration
class TestUnlistedAnonymousLinkAccess:
    """AC5: an unlisted clip's direct link must open for a signed-out recipient
    (link sharing = "not hidden"), while a private clip stays an indistinguishable
    404. Both the anonymous metadata read and stream route through
    ``get_clip_for_streaming``, so this exercises that shared resolver."""

    async def test_anonymous_can_read_unlisted_clip_metadata(self, client) -> None:
        owner = await _make_user(f"vis-anon-unlisted-{next(_SEQ)}@example.com")
        workspace = await _make_workspace(owner)
        clip = await _insert_clip(owner, workspace, visibility=VisibilityState.UNLISTED)

        resp = await client.get(f"{CLIPS_URL}/{clip.id}/public")  # no auth header
        assert resp.status_code == 200
        assert resp.json()["visibility"] == "unlisted"

    async def test_anonymous_gets_404_for_private_clip_metadata(self, client) -> None:
        owner = await _make_user(f"vis-anon-private-{next(_SEQ)}@example.com")
        workspace = await _make_workspace(owner)
        clip = await _insert_clip(owner, workspace, visibility=VisibilityState.PRIVATE)

        resp = await client.get(f"{CLIPS_URL}/{clip.id}/public")  # no auth header
        assert resp.status_code == 404
