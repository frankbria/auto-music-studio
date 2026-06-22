"""Tests for guided distribution prep (US-13.5, issue #136).

Distinct from ``tests/test_distribution_api.py`` (SoundCloud upload, US-13.2):
these cover the LANDR/DistroKid/TuneCore *manual* prep endpoints on the releases
router. Unit tests (target config + readiness helper) run in CI. The endpoint
tests are ``integration``: they drive the real app over a local MongoDB and a
throwaway local storage root, seeding real audio + a 3000x3000 cover so
validation has something to download and bundle.
"""

import io
import itertools
import zipfile

import httpx
import pytest
from beanie import PydanticObjectId
from PIL import Image

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import Clip, Release, ReleaseStatus, Workspace
from acemusic.api.services import users as user_service
from acemusic.api.services.distribution import (
    TARGET_CONFIGS,
    ChecklistItem,
    DistributionTarget,
    instructions_for,
    is_release_ready,
)
from acemusic.api.services.mastering import APPROVED_GENERATION_MODE
from acemusic.api.settings import ApiSettings
from acemusic.storage import get_storage_backend

RELEASES_URL = f"{API_V1_PREFIX}/releases"

FULL_METADATA = {
    "title": "Midnight Drive",
    "artist": "The Algorithm",
    "genre": "synthwave",
    "release_date": "2026-07-01T00:00:00Z",
    "album_name": "Neon Highways",
    "description": "A late-night cruise.",
    "copyright": "© 2026 The Algorithm",
    "is_explicit": False,
    "language": "en",
    "credits": "Produced by The Algorithm",
}


# ---------------------------------------------------------------------------
# Unit — runs in CI (no DB, no storage)
# ---------------------------------------------------------------------------


class TestTargetConfig:
    def test_all_targets_configured_with_distinct_instructions(self) -> None:
        assert set(TARGET_CONFIGS) == set(DistributionTarget)
        instructions = {instructions_for(t) for t in DistributionTarget}
        assert len(instructions) == len(DistributionTarget)  # each target speaks for itself
        assert "LANDR" in instructions_for(DistributionTarget.LANDR)

    def test_is_release_ready(self) -> None:
        ok = [ChecklistItem(item="a", passed=True, message=""), ChecklistItem(item="b", passed=True, message="")]
        bad = [ChecklistItem(item="a", passed=True, message=""), ChecklistItem(item="b", passed=False, message="x")]
        assert is_release_ready(ok) is True
        assert is_release_ready(bad) is False
        assert is_release_ready([]) is True


# ---------------------------------------------------------------------------
# Integration — real MongoDB + local storage
# ---------------------------------------------------------------------------


def _async_client(app) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@pytest.fixture
def settings(mongo_db, mongo_settings) -> ApiSettings:
    return mongo_settings.model_copy(
        update={"jwt_secret_key": "test-secret-key-at-least-32-bytes-long-xx", "job_processor_enabled": False}
    )


@pytest.fixture
def local_storage(monkeypatch, tmp_path):
    """Point the storage backend at a throwaway local root."""
    monkeypatch.setenv("ACEMUSIC_STORAGE_BACKEND", "local")
    monkeypatch.setenv("ACEMUSIC_STORAGE_LOCAL_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture
async def client(settings):
    async with _async_client(create_app(settings)) as ac:
        yield ac


def _auth_headers(user, settings: ApiSettings) -> dict[str, str]:
    token = create_access_token(
        user_id=str(user.id), email=user.email, subscription_tier=user.subscription_tier, settings=settings
    )
    return {"Authorization": f"Bearer {token}"}


async def _make_user(email: str):
    return await user_service.get_or_create_user(email=email, provider="google", oauth_id=f"g-{email}", name="T")


_SEQ = itertools.count(1)


def _png_bytes(size: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (size, size), "navy").save(out, format="PNG")
    return out.getvalue()


async def _insert_clip(user, *, fmt: str = "wav", artwork: bool = True, art_size: int = 3000) -> Clip:
    """Insert a clip and seed its audio (and optionally cover art) into storage."""
    workspace = Workspace(name=f"WS-{next(_SEQ)}", user_id=user.id)
    await workspace.insert()
    clip_id = PydanticObjectId()
    audio_path = f"{user.id}/{workspace.id}/clips/{clip_id}.{fmt}"
    art_path = f"{user.id}/art/{clip_id}.png" if artwork else None
    clip = Clip(
        id=clip_id,
        user_id=user.id,
        workspace_id=workspace.id,
        file_path=audio_path,
        format=fmt,
        title="Source",
        generation_mode=APPROVED_GENERATION_MODE,
        artwork_path=art_path,
    )
    await clip.insert()
    storage = get_storage_backend()
    storage.upload(audio_path, b"RIFF....fake-audio")
    if art_path:
        storage.upload(art_path, _png_bytes(art_size))
    return clip


async def _create_release(client, user, settings, clip, **overrides) -> httpx.Response:
    payload = {"clip_id": str(clip.id), **FULL_METADATA, **overrides}
    return await client.post(RELEASES_URL, json=payload, headers=_auth_headers(user, settings))


async def _new_release(client, settings, *, email, **clip_kwargs):
    user = await _make_user(email)
    clip = await _insert_clip(user, **clip_kwargs)
    resp = await _create_release(client, user=user, settings=settings, clip=clip)
    assert resp.status_code == 201, resp.text
    return user, resp.json()


@pytest.mark.integration
class TestPrepare:
    async def test_compliant_release_passes_and_returns_bundle(self, client, settings, local_storage) -> None:
        user, release = await _new_release(client, settings, email="prep-ok@example.com")
        resp = await client.post(f"{RELEASES_URL}/{release['id']}/prepare/landr", headers=_auth_headers(user, settings))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["target"] == "landr"
        assert body["all_checks_passed"] is True
        assert all(item["passed"] for item in body["checklist"])
        assert "LANDR" in body["instructions"]
        assert body["bundle_url"]

        # The bundle is a real, downloadable zip with the target-formatted contents.
        with zipfile.ZipFile(body["bundle_url"]) as zf:
            names = {n.split("/", 1)[1] for n in zf.namelist()}
        assert names == {"audio.wav", "cover.png", "metadata.json", "README.txt"}

    async def test_mp3_audio_flagged_non_compliant_and_no_bundle(self, client, settings, local_storage) -> None:
        user, release = await _new_release(client, settings, email="prep-mp3@example.com", fmt="mp3")
        resp = await client.post(
            f"{RELEASES_URL}/{release['id']}/prepare/distrokid", headers=_auth_headers(user, settings)
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["all_checks_passed"] is False
        assert body["bundle_url"] is None
        audio_fmt = next(i for i in body["checklist"] if i["item"] == "Audio format")
        assert audio_fmt["passed"] is False

    async def test_missing_cover_art_flagged(self, client, settings, local_storage) -> None:
        user, release = await _new_release(client, settings, email="prep-noart@example.com", artwork=False)
        resp = await client.post(
            f"{RELEASES_URL}/{release['id']}/prepare/tunecore", headers=_auth_headers(user, settings)
        )
        body = resp.json()
        assert body["all_checks_passed"] is False
        cover = next(i for i in body["checklist"] if i["item"] == "Cover art")
        assert cover["passed"] is False

    async def test_low_resolution_cover_art_flagged(self, client, settings, local_storage) -> None:
        user, release = await _new_release(client, settings, email="prep-smallart@example.com", art_size=512)
        resp = await client.post(f"{RELEASES_URL}/{release['id']}/prepare/landr", headers=_auth_headers(user, settings))
        body = resp.json()
        cover = next(i for i in body["checklist"] if i["item"] == "Cover art")
        assert cover["passed"] is False
        assert "512x512" in cover["message"]

    async def test_missing_upc_flagged(self, client, settings, local_storage) -> None:
        user, release = await _new_release(client, settings, email="prep-noupc@example.com")
        # Clear the UPC via PATCH, then prepare should flag it.
        await client.patch(f"{RELEASES_URL}/{release['id']}", json={"upc": None}, headers=_auth_headers(user, settings))
        resp = await client.post(f"{RELEASES_URL}/{release['id']}/prepare/landr", headers=_auth_headers(user, settings))
        body = resp.json()
        upc = next(i for i in body["checklist"] if i["item"] == "UPC assigned")
        assert upc["passed"] is False
        assert body["all_checks_passed"] is False

    async def test_invalid_target_returns_422(self, client, settings, local_storage) -> None:
        user, release = await _new_release(client, settings, email="prep-bad@example.com")
        resp = await client.post(
            f"{RELEASES_URL}/{release['id']}/prepare/spotify", headers=_auth_headers(user, settings)
        )
        assert resp.status_code == 422

    async def test_other_users_release_is_404(self, client, settings, local_storage) -> None:
        _owner, release = await _new_release(client, settings, email="prep-owner@example.com")
        intruder = await _make_user("prep-intruder@example.com")
        resp = await client.post(
            f"{RELEASES_URL}/{release['id']}/prepare/landr", headers=_auth_headers(intruder, settings)
        )
        assert resp.status_code == 404


@pytest.mark.integration
class TestSubmit:
    async def test_confirm_moves_release_to_submitted_and_records_channel(
        self, client, settings, local_storage
    ) -> None:
        user, release = await _new_release(client, settings, email="submit-ok@example.com")
        resp = await client.post(f"{RELEASES_URL}/{release['id']}/submit/landr", headers=_auth_headers(user, settings))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "submitted"
        assert body["submitted_channels"] == ["landr"]

        stored = await Release.get(PydanticObjectId(release["id"]))
        assert stored.status is ReleaseStatus.SUBMITTED

    async def test_confirm_second_target_appends_channel(self, client, settings, local_storage) -> None:
        user, release = await _new_release(client, settings, email="submit-two@example.com")
        headers = _auth_headers(user, settings)
        await client.post(f"{RELEASES_URL}/{release['id']}/submit/landr", headers=headers)
        # Re-confirm the same target (dedup) then a second target.
        await client.post(f"{RELEASES_URL}/{release['id']}/submit/landr", headers=headers)
        resp = await client.post(f"{RELEASES_URL}/{release['id']}/submit/distrokid", headers=headers)
        assert resp.json()["submitted_channels"] == ["landr", "distrokid"]

    async def test_other_users_release_is_404(self, client, settings, local_storage) -> None:
        _owner, release = await _new_release(client, settings, email="submit-owner@example.com")
        intruder = await _make_user("submit-intruder@example.com")
        resp = await client.post(
            f"{RELEASES_URL}/{release['id']}/submit/landr", headers=_auth_headers(intruder, settings)
        )
        assert resp.status_code == 404

    async def test_invalid_target_returns_422(self, client, settings, local_storage) -> None:
        user, release = await _new_release(client, settings, email="submit-bad@example.com")
        resp = await client.post(
            f"{RELEASES_URL}/{release['id']}/submit/bandcamp", headers=_auth_headers(user, settings)
        )
        assert resp.status_code == 422
