"""Integration tests for the SoundCloud distribution router (US-13.2).

These drive the real app over ``httpx.AsyncClient`` against a local MongoDB
(``mongo_db``) and real LocalStorage. The outbound SoundCloud HTTP calls are
monkeypatched at the service seam (the pattern ``tests/test_auth_routes.py`` uses
for route tests, since ``respx`` does not intercept the in-process ASGITransport).
The HTTP wire format of those calls is covered by ``tests/test_soundcloud_service.py``.
"""

from datetime import datetime, timedelta, timezone

import httpx
import pytest
from beanie import PydanticObjectId

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import Clip, SoundCloudConnection
from acemusic.api.services import soundcloud as sc, users as user_service
from acemusic.api.settings import ApiSettings
from acemusic.storage import get_storage_backend

pytestmark = pytest.mark.integration


def _url(path: str) -> str:
    return f"{API_V1_PREFIX}/distribution{path}"


def _async_client(app) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@pytest.fixture
def settings(mongo_db, mongo_settings) -> ApiSettings:
    return mongo_settings.model_copy(
        update={
            "jwt_secret_key": "test-secret-key-at-least-32-bytes-long-xx",
            "job_processor_enabled": False,
            "soundcloud_client_id": "sc-id",
            "soundcloud_client_secret": "sc-secret",
            "soundcloud_redirect_uri": "https://app.test/distribution/soundcloud/callback",
            "oauth_cookie_secure": False,  # allow cookies over http in tests
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
        user_id=str(user.id), email=user.email, subscription_tier=user.subscription_tier, settings=settings
    )
    return {"Authorization": f"Bearer {token}"}


async def _make_user(email: str):
    return await user_service.get_or_create_user(email=email, provider="google", oauth_id=f"g-{email}", name="T")


async def _make_clip(
    user,
    audio: bytes,
    *,
    fmt: str = "wav",
    title: str | None = "Tune",
    store: bool = True,
    artwork: bytes | None = None,
):
    clip_id = PydanticObjectId()
    workspace_id = PydanticObjectId()
    file_path = f"{user.id}/{workspace_id}/clips/{clip_id}.{fmt}"
    if store:
        get_storage_backend().upload(file_path, audio)
    artwork_path = None
    if artwork is not None:
        artwork_path = f"{user.id}/{workspace_id}/clips/{clip_id}.png"
        get_storage_backend().upload(artwork_path, artwork)
    clip = Clip(
        id=clip_id,
        user_id=user.id,
        workspace_id=workspace_id,
        file_path=file_path,
        format=fmt,
        title=title,
        bpm=120,
        key="Am",
        style_tags=["techno"],
        artwork_path=artwork_path,
    )
    await clip.insert()
    return clip


async def _make_connection(user, *, expires_in_seconds: int = 3600) -> SoundCloudConnection:
    conn = SoundCloudConnection(
        user_id=user.id,
        soundcloud_user_id="sc-42",
        soundcloud_username="dj",
        access_token="at",
        refresh_token="rt",
        token_expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in_seconds),
    )
    await conn.insert()
    return conn


# --- connect ----------------------------------------------------------------
class TestConnect:
    async def test_returns_authorization_url_and_sets_cookies(self, client, settings) -> None:
        user = await _make_user("connect@example.com")
        resp = await client.post(_url("/soundcloud/connect"), headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        assert resp.json()["authorization_url"].startswith(sc.SOUNDCLOUD_AUTHORIZE_URL)
        set_cookie = resp.headers.get("set-cookie", "")
        assert sc.NONCE_COOKIE_PREFIX in set_cookie
        assert sc.VERIFIER_COOKIE_PREFIX in set_cookie

    async def test_unconfigured_returns_503(self, client, settings) -> None:
        # Rebuild the app without SoundCloud credentials.
        bare = settings.model_copy(update={"soundcloud_client_id": None})
        async with _async_client(create_app(bare)) as ac:
            user = await _make_user("connect-503@example.com")
            resp = await ac.post(_url("/soundcloud/connect"), headers=_auth_headers(user, bare))
        assert resp.status_code == 503

    async def test_requires_auth(self, client) -> None:
        resp = await client.post(_url("/soundcloud/connect"))
        assert resp.status_code == 401


# --- callback (AC: OAuth completes and stores tokens) -----------------------
class TestCallback:
    async def test_completes_flow_and_persists_connection(self, client, settings, monkeypatch) -> None:
        user = await _make_user("cb@example.com")
        headers = _auth_headers(user, settings)

        # Start the flow so the client holds the nonce/verifier cookies, then
        # extract the signed state from the returned URL.
        started = await client.post(_url("/soundcloud/connect"), headers=headers)
        state = httpx.URL(started.json()["authorization_url"]).params["state"]

        async def _exchange(code, verifier, _settings):
            assert code == "auth-code"
            return {"access_token": "at", "refresh_token": "rt", "expires_in": 3600}

        async def _me(token):
            assert token == "at"
            return {"id": 42, "username": "dj"}

        monkeypatch.setattr(sc, "exchange_code", _exchange)
        monkeypatch.setattr(sc, "get_soundcloud_user", _me)

        resp = await client.post(
            _url("/soundcloud/callback"), headers=headers, json={"code": "auth-code", "state": state}
        )
        assert resp.status_code == 200
        assert resp.json()["connected"] is True
        assert resp.json()["soundcloud_username"] == "dj"

        stored = await SoundCloudConnection.find_one(SoundCloudConnection.user_id == user.id)
        assert stored is not None
        assert stored.access_token == "at"
        assert stored.refresh_token == "rt"

    async def test_bad_state_returns_400(self, client, settings) -> None:
        user = await _make_user("cb-bad@example.com")
        resp = await client.post(
            _url("/soundcloud/callback"),
            headers=_auth_headers(user, settings),
            json={"code": "c", "state": "not-a-jwt"},
        )
        assert resp.status_code == 400


# --- status -----------------------------------------------------------------
class TestStatus:
    async def test_not_connected(self, client, settings) -> None:
        user = await _make_user("status-off@example.com")
        resp = await client.get(_url("/soundcloud/status"), headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        assert resp.json() == {
            "connected": False,
            "soundcloud_username": None,
            "connected_at": None,
            "token_valid": None,
        }

    async def test_connected_reports_username_and_token_valid(self, client, settings) -> None:
        user = await _make_user("status-on@example.com")
        await _make_connection(user)
        resp = await client.get(_url("/soundcloud/status"), headers=_auth_headers(user, settings))
        body = resp.json()
        assert body["connected"] is True
        assert body["soundcloud_username"] == "dj"
        assert body["token_valid"] is True


# --- upload (AC: creates track, sets metadata, cover art, token refresh) -----
class TestUpload:
    async def test_happy_path_uploads_with_merged_metadata(self, client, settings, local_storage, monkeypatch) -> None:
        user = await _make_user("up@example.com")
        clip = await _make_clip(user, b"RIFFaudio")
        await _make_connection(user)

        captured = {}

        async def _upload(token, audio, filename, metadata, artwork=None):
            captured.update(token=token, audio=audio, filename=filename, metadata=metadata, artwork=artwork)
            return {"id": 777, "permalink_url": "https://snd.sc/x"}

        monkeypatch.setattr(sc, "upload_track", _upload)

        resp = await client.post(
            _url("/soundcloud/upload"),
            headers=_auth_headers(user, settings),
            json={"clip_id": str(clip.id), "metadata_overrides": {"genre": "house"}},
        )
        assert resp.status_code == 200
        assert resp.json() == {"track_id": "777", "permalink_url": "https://snd.sc/x"}
        # Clip-derived metadata with the override taking precedence.
        assert captured["metadata"]["title"] == "Tune"
        assert captured["metadata"]["bpm"] == 120
        assert captured["metadata"]["key_signature"] == "Am"
        assert captured["metadata"]["genre"] == "house"  # override beat the style_tag default
        assert captured["audio"] == b"RIFFaudio"

    async def test_untitled_clip_falls_back_to_clip_id_as_title(
        self, client, settings, local_storage, monkeypatch
    ) -> None:
        user = await _make_user("up-untitled@example.com")
        clip = await _make_clip(user, b"audio", title=None)
        await _make_connection(user)

        captured = {}

        async def _upload(token, audio, filename, metadata, artwork=None):
            captured["metadata"] = metadata
            return {"id": 5}

        monkeypatch.setattr(sc, "upload_track", _upload)
        resp = await client.post(
            _url("/soundcloud/upload"), headers=_auth_headers(user, settings), json={"clip_id": str(clip.id)}
        )
        assert resp.status_code == 200
        assert captured["metadata"]["title"] == str(clip.id)  # never empty for SoundCloud

    async def test_clip_artwork_uploaded_by_default(self, client, settings, local_storage, monkeypatch) -> None:
        user = await _make_user("up-defaultart@example.com")
        clip = await _make_clip(user, b"audio", artwork=b"COVERPNG")
        await _make_connection(user)

        captured = {}

        async def _upload(token, audio, filename, metadata, artwork=None):
            captured["artwork"] = artwork
            return {"id": 6}

        monkeypatch.setattr(sc, "upload_track", _upload)
        resp = await client.post(
            _url("/soundcloud/upload"), headers=_auth_headers(user, settings), json={"clip_id": str(clip.id)}
        )
        assert resp.status_code == 200
        assert captured["artwork"] == b"COVERPNG"  # the clip's own cover art, no override needed

    async def test_transient_refresh_failure_preserves_connection(
        self, client, settings, local_storage, monkeypatch
    ) -> None:
        user = await _make_user("up-transient@example.com")
        clip = await _make_clip(user, b"audio")
        await _make_connection(user, expires_in_seconds=-10)  # expired → triggers refresh

        async def _refresh(refresh_token, _settings):
            raise sc.SoundCloudError("SoundCloud token request failed.")

        monkeypatch.setattr(sc, "refresh_access_token", _refresh)
        resp = await client.post(
            _url("/soundcloud/upload"), headers=_auth_headers(user, settings), json={"clip_id": str(clip.id)}
        )
        assert resp.status_code == 502
        # The link survives a transient outage so a later retry can succeed.
        assert await SoundCloudConnection.find_one(SoundCloudConnection.user_id == user.id) is not None

    async def test_revoked_refresh_token_unlinks_and_returns_401(
        self, client, settings, local_storage, monkeypatch
    ) -> None:
        user = await _make_user("up-revoked@example.com")
        clip = await _make_clip(user, b"audio")
        await _make_connection(user, expires_in_seconds=-10)

        async def _refresh(refresh_token, _settings):
            raise sc.SoundCloudAuthError("SoundCloud rejected the authorization grant.")

        monkeypatch.setattr(sc, "refresh_access_token", _refresh)
        resp = await client.post(
            _url("/soundcloud/upload"), headers=_auth_headers(user, settings), json={"clip_id": str(clip.id)}
        )
        assert resp.status_code == 401
        assert await SoundCloudConnection.find_one(SoundCloudConnection.user_id == user.id) is None

    async def test_artwork_url_is_fetched_and_forwarded(self, client, settings, local_storage, monkeypatch) -> None:
        user = await _make_user("up-art@example.com")
        clip = await _make_clip(user, b"audio")
        await _make_connection(user)

        captured = {}

        async def _fetch_artwork(url):
            assert url == "https://img.test/cover.png"
            return b"PNGBYTES"

        async def _upload(token, audio, filename, metadata, artwork=None):
            captured["artwork"] = artwork
            return {"id": 1}

        monkeypatch.setattr(sc, "fetch_artwork", _fetch_artwork)
        monkeypatch.setattr(sc, "upload_track", _upload)

        resp = await client.post(
            _url("/soundcloud/upload"),
            headers=_auth_headers(user, settings),
            json={"clip_id": str(clip.id), "metadata_overrides": {"artwork_url": "https://img.test/cover.png"}},
        )
        assert resp.status_code == 200
        assert captured["artwork"] == b"PNGBYTES"

    async def test_token_refreshed_when_expired(self, client, settings, local_storage, monkeypatch) -> None:
        user = await _make_user("up-refresh@example.com")
        clip = await _make_clip(user, b"audio")
        await _make_connection(user, expires_in_seconds=-10)  # already expired

        async def _refresh(refresh_token, _settings):
            assert refresh_token == "rt"
            return {"access_token": "fresh-at", "refresh_token": "fresh-rt", "expires_in": 3600}

        used_token = {}

        async def _upload(token, audio, filename, metadata, artwork=None):
            used_token["token"] = token
            return {"id": 2}

        monkeypatch.setattr(sc, "refresh_access_token", _refresh)
        monkeypatch.setattr(sc, "upload_track", _upload)

        resp = await client.post(
            _url("/soundcloud/upload"),
            headers=_auth_headers(user, settings),
            json={"clip_id": str(clip.id)},
        )
        assert resp.status_code == 200
        assert used_token["token"] == "fresh-at"  # refreshed token used for upload
        stored = await SoundCloudConnection.find_one(SoundCloudConnection.user_id == user.id)
        assert stored.access_token == "fresh-at"
        assert stored.refresh_token == "fresh-rt"

    async def test_not_owned_clip_returns_404(self, client, settings, local_storage, monkeypatch) -> None:
        owner = await _make_user("up-owner@example.com")
        other = await _make_user("up-other@example.com")
        clip = await _make_clip(owner, b"audio")
        await _make_connection(other)
        monkeypatch.setattr(sc, "upload_track", lambda *a, **k: {"id": 1})

        resp = await client.post(
            _url("/soundcloud/upload"),
            headers=_auth_headers(other, settings),
            json={"clip_id": str(clip.id)},
        )
        assert resp.status_code == 404

    async def test_not_connected_returns_400(self, client, settings, local_storage) -> None:
        user = await _make_user("up-noconn@example.com")
        clip = await _make_clip(user, b"audio")
        resp = await client.post(
            _url("/soundcloud/upload"),
            headers=_auth_headers(user, settings),
            json={"clip_id": str(clip.id)},
        )
        assert resp.status_code == 400

    async def test_oversized_audio_returns_413(self, client, settings, local_storage, monkeypatch) -> None:
        user = await _make_user("up-big@example.com")
        clip = await _make_clip(user, b"x" * 100)
        await _make_connection(user)
        monkeypatch.setattr(sc, "MAX_UPLOAD_BYTES", 10)  # shrink the cap to trip the guard
        resp = await client.post(
            _url("/soundcloud/upload"),
            headers=_auth_headers(user, settings),
            json={"clip_id": str(clip.id)},
        )
        assert resp.status_code == 413


# --- disconnect -------------------------------------------------------------
class TestDisconnect:
    async def test_deletes_connection_and_is_idempotent(self, client, settings) -> None:
        user = await _make_user("disc@example.com")
        await _make_connection(user)
        headers = _auth_headers(user, settings)

        first = await client.delete(_url("/soundcloud/connect"), headers=headers)
        assert first.status_code == 204
        assert await SoundCloudConnection.find_one(SoundCloudConnection.user_id == user.id) is None

        second = await client.delete(_url("/soundcloud/connect"), headers=headers)
        assert second.status_code == 204  # idempotent
