"""Tests for the release package CRUD endpoints (US-13.3, issue #134).

The 401 auth-gate tests run in CI (the router dependency rejects before any DB
access; plain ``TestClient`` does not run the lifespan). The CRUD tests are
``integration``: they drive the real app with ``httpx.AsyncClient`` over a local
MongoDB (``mongo_db``), mirroring ``tests/test_presets_api.py``.
"""

import itertools

import httpx
import pytest
from beanie import PydanticObjectId
from fastapi.testclient import TestClient

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import Clip, Release, ReleaseStatus, Workspace
from acemusic.api.services import users as user_service
from acemusic.api.services.mastering import APPROVED_GENERATION_MODE
from acemusic.api.settings import ApiSettings

RELEASES_URL = f"{API_V1_PREFIX}/releases"

# A representative complete create payload (clip_id is filled in per-test).
FULL_METADATA = {
    "title": "Midnight Drive",
    "artist": "The Algorithm",
    "genre": "synthwave",
    "release_date": "2026-07-01T00:00:00Z",
    "album_name": "Neon Highways",
    "description": "A late-night cruise.",
    "isrc": "USABC1234567",
    "upc": "012345678905",
    "copyright": "© 2026 The Algorithm",
    "is_explicit": False,
    "language": "en",
    "credits": "Produced by The Algorithm",
}


# ---------------------------------------------------------------------------
# Auth gate — runs in CI (no DB)
# ---------------------------------------------------------------------------


class TestAuthGate:
    @pytest.mark.parametrize(
        ("method", "url"),
        [
            ("GET", RELEASES_URL),
            ("POST", RELEASES_URL),
            ("GET", f"{RELEASES_URL}/{PydanticObjectId()}"),
            ("PATCH", f"{RELEASES_URL}/{PydanticObjectId()}"),
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


_SEQ = itertools.count(1)


async def _make_workspace(user) -> Workspace:
    # Unique per (user, name): the workspaces collection enforces it, and a test
    # user may own several clips (hence several workspaces).
    workspace = Workspace(name=f"WS-{next(_SEQ)}", user_id=user.id)
    await workspace.insert()
    return workspace


async def _insert_clip(user, *, mastered: bool = False, artwork: bool = False) -> Clip:
    workspace = await _make_workspace(user)
    clip_id = PydanticObjectId()
    clip = Clip(
        id=clip_id,
        user_id=user.id,
        workspace_id=workspace.id,
        file_path=f"{user.id}/{workspace.id}/clips/{clip_id}.wav",
        format="wav",
        title="Source",
        generation_mode=APPROVED_GENERATION_MODE if mastered else "generate",
        artwork_path=f"{user.id}/art/{clip_id}.png" if artwork else None,
    )
    await clip.insert()
    return clip


async def _create_release(client, user, settings, clip, **overrides) -> httpx.Response:
    payload = {"clip_id": str(clip.id), **FULL_METADATA, **overrides}
    return await client.post(RELEASES_URL, json=payload, headers=_auth_headers(user, settings))


@pytest.mark.integration
class TestCreate:
    async def test_create_complete_returns_201_ready(self, client, settings) -> None:
        user = await _make_user("rel-create@example.com")
        clip = await _insert_clip(user, mastered=True, artwork=True)
        resp = await _create_release(client, settings=settings, user=user, clip=clip)
        assert resp.status_code == 201
        body = resp.json()
        assert body["id"]
        assert body["status"] == "ready"
        assert body["clip_id"] == str(clip.id)
        assert body["warnings"] == []  # mastered + has artwork
        for field, value in FULL_METADATA.items():
            assert body[field] == value, f"field {field!r}: {body[field]!r} != {value!r}"

        stored = await Release.get(PydanticObjectId(body["id"]))
        assert stored is not None
        assert stored.status is ReleaseStatus.READY
        assert stored.title == FULL_METADATA["title"]

    async def test_unmastered_clip_without_art_warns_but_creates(self, client, settings) -> None:
        user = await _make_user("rel-warn@example.com")
        clip = await _insert_clip(user, mastered=False, artwork=False)
        resp = await _create_release(client, settings=settings, user=user, clip=clip)
        assert resp.status_code == 201  # soft block, not hard block
        warnings = resp.json()["warnings"]
        assert "Audio has not been mastered" in warnings
        assert "Cover art has not been added" in warnings

    async def test_mastered_clip_has_no_mastering_warning(self, client, settings) -> None:
        user = await _make_user("rel-mastered@example.com")
        clip = await _insert_clip(user, mastered=True, artwork=False)
        resp = await _create_release(client, settings=settings, user=user, clip=clip)
        assert resp.status_code == 201
        warnings = resp.json()["warnings"]
        assert "Audio has not been mastered" not in warnings
        assert "Cover art has not been added" in warnings

    @pytest.mark.parametrize("missing", ["title", "artist", "genre", "release_date"])
    async def test_missing_required_field_returns_422(self, client, settings, missing: str) -> None:
        user = await _make_user(f"rel-422-{missing}@example.com")
        clip = await _insert_clip(user, mastered=True, artwork=True)
        payload = {"clip_id": str(clip.id), **FULL_METADATA}
        del payload[missing]
        resp = await client.post(RELEASES_URL, json=payload, headers=_auth_headers(user, settings))
        assert resp.status_code == 422
        # The error names the offending field.
        assert any(missing in str(err.get("loc", [])) for err in resp.json()["detail"])

    async def test_unknown_field_returns_422(self, client, settings) -> None:
        user = await _make_user("rel-extra@example.com")
        clip = await _insert_clip(user, mastered=True, artwork=True)
        resp = await _create_release(client, settings=settings, user=user, clip=clip, nope=True)
        assert resp.status_code == 422

    async def test_unknown_clip_returns_404(self, client, settings) -> None:
        user = await _make_user("rel-noclip@example.com")
        payload = {"clip_id": str(PydanticObjectId()), **FULL_METADATA}
        resp = await client.post(RELEASES_URL, json=payload, headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    async def test_other_users_clip_returns_404(self, client, settings) -> None:
        owner = await _make_user("rel-owner@example.com")
        intruder = await _make_user("rel-intruder@example.com")
        clip = await _insert_clip(owner, mastered=True, artwork=True)
        payload = {"clip_id": str(clip.id), **FULL_METADATA}
        resp = await client.post(RELEASES_URL, json=payload, headers=_auth_headers(intruder, settings))
        assert resp.status_code == 404


@pytest.mark.integration
class TestList:
    async def test_lists_only_own_releases_newest_first(self, client, settings) -> None:
        user = await _make_user("rel-list@example.com")
        other = await _make_user("rel-list-other@example.com")
        clip_a = await _insert_clip(user, mastered=True, artwork=True)
        clip_b = await _insert_clip(user, mastered=True, artwork=True)
        other_clip = await _insert_clip(other, mastered=True, artwork=True)
        first = (await _create_release(client, settings=settings, user=user, clip=clip_a, title="A")).json()
        second = (await _create_release(client, settings=settings, user=user, clip=clip_b, title="B")).json()
        await _create_release(client, settings=settings, user=other, clip=other_clip, title="Theirs")

        resp = await client.get(RELEASES_URL, headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        ids = [r["id"] for r in body["releases"]]
        assert ids == [second["id"], first["id"]]  # newest first

    async def test_empty_list_for_new_user(self, client, settings) -> None:
        user = await _make_user("rel-list-empty@example.com")
        resp = await client.get(RELEASES_URL, headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        assert resp.json() == {"releases": [], "total": 0}


@pytest.mark.integration
class TestGet:
    async def test_get_own_release_returns_200(self, client, settings) -> None:
        user = await _make_user("rel-get@example.com")
        clip = await _insert_clip(user, mastered=True, artwork=True)
        created = (await _create_release(client, settings=settings, user=user, clip=clip)).json()
        resp = await client.get(f"{RELEASES_URL}/{created['id']}", headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        assert resp.json()["id"] == created["id"]

    async def test_unknown_release_returns_404(self, client, settings) -> None:
        user = await _make_user("rel-get-unknown@example.com")
        resp = await client.get(f"{RELEASES_URL}/{PydanticObjectId()}", headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    async def test_other_users_release_returns_404(self, client, settings) -> None:
        owner = await _make_user("rel-get-owner@example.com")
        intruder = await _make_user("rel-get-intruder@example.com")
        clip = await _insert_clip(owner, mastered=True, artwork=True)
        created = (await _create_release(client, settings=settings, user=owner, clip=clip)).json()
        resp = await client.get(f"{RELEASES_URL}/{created['id']}", headers=_auth_headers(intruder, settings))
        assert resp.status_code == 404


@pytest.mark.integration
class TestUpdate:
    async def test_update_persists_changes(self, client, settings) -> None:
        user = await _make_user("rel-update@example.com")
        clip = await _insert_clip(user, mastered=True, artwork=True)
        created = (await _create_release(client, settings=settings, user=user, clip=clip)).json()
        resp = await client.patch(
            f"{RELEASES_URL}/{created['id']}",
            json={"title": "Renamed", "isrc": None},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["title"] == "Renamed"
        assert body["isrc"] is None
        assert body["updated_at"] is not None

    async def test_empty_body_is_noop(self, client, settings) -> None:
        user = await _make_user("rel-update-noop@example.com")
        clip = await _insert_clip(user, mastered=True, artwork=True)
        created = (await _create_release(client, settings=settings, user=user, clip=clip)).json()
        resp = await client.patch(f"{RELEASES_URL}/{created['id']}", json={}, headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        assert resp.json()["title"] == FULL_METADATA["title"]
        assert resp.json()["updated_at"] is None  # untouched

    async def test_update_other_users_release_returns_404(self, client, settings) -> None:
        owner = await _make_user("rel-update-owner@example.com")
        intruder = await _make_user("rel-update-intruder@example.com")
        clip = await _insert_clip(owner, mastered=True, artwork=True)
        created = (await _create_release(client, settings=settings, user=owner, clip=clip)).json()
        resp = await client.patch(
            f"{RELEASES_URL}/{created['id']}",
            json={"title": "Hijacked"},
            headers=_auth_headers(intruder, settings),
        )
        assert resp.status_code == 404

    async def test_update_after_submission_returns_409(self, client, settings) -> None:
        user = await _make_user("rel-update-locked@example.com")
        clip = await _insert_clip(user, mastered=True, artwork=True)
        created = (await _create_release(client, settings=settings, user=user, clip=clip)).json()
        # Move it past the editable window directly.
        release = await Release.get(PydanticObjectId(created["id"]))
        release.status = ReleaseStatus.SUBMITTED
        await release.save()

        resp = await client.patch(
            f"{RELEASES_URL}/{created['id']}",
            json={"title": "Too late"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 409

    @pytest.mark.parametrize("field", ["title", "artist", "genre", "release_date"])
    async def test_clearing_required_field_returns_422(self, client, settings, field: str) -> None:
        # A null on a required field would persist an unserializable release (→ 500
        # on later reads); the update schema must reject it up front.
        user = await _make_user(f"rel-clear-{field}@example.com")
        clip = await _insert_clip(user, mastered=True, artwork=True)
        created = (await _create_release(client, settings=settings, user=user, clip=clip)).json()
        resp = await client.patch(
            f"{RELEASES_URL}/{created['id']}",
            json={field: None},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422
        # The release is left intact and still readable (the required field was
        # not cleared to null).
        again = await client.get(f"{RELEASES_URL}/{created['id']}", headers=_auth_headers(user, settings))
        assert again.status_code == 200
        assert again.json()[field] is not None


@pytest.mark.integration
class TestDanglingClip:
    async def test_release_readable_after_source_clip_deleted(self, client, settings) -> None:
        # The release is a self-contained package; deleting its source clip must
        # not make it (or a list containing it) unreadable.
        user = await _make_user("rel-dangling@example.com")
        clip = await _insert_clip(user, mastered=True, artwork=True)
        created = (await _create_release(client, settings=settings, user=user, clip=clip)).json()
        await clip.delete()

        got = await client.get(f"{RELEASES_URL}/{created['id']}", headers=_auth_headers(user, settings))
        assert got.status_code == 200
        assert "Source clip is no longer available" in got.json()["warnings"]

        listed = await client.get(RELEASES_URL, headers=_auth_headers(user, settings))
        assert listed.status_code == 200
        assert listed.json()["total"] == 1
