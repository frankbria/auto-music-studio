"""Tests for ``POST /clips/upload`` (US-24.5, issue #324).

The VST3 plugin pushes locally generated clips back to the musician's workspace.
There was no audio upload endpoint anywhere in the platform API before this — the
only ``UploadFile`` was cover art — so this is the whole of the push half of clip
sync.

The 401 auth-gate and the format sniffer run in CI (no DB); the rest are
``integration`` and drive the real app with ``httpx.AsyncClient`` over a local
MongoDB, mirroring ``tests/test_clips_crud_api.py``.
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import Clip, Workspace
from acemusic.api.services import users as user_service
from acemusic.api.services.clips import CLIP_UPLOAD_MAX_BYTES, sniff_audio_format
from acemusic.api.settings import ApiSettings
from acemusic.storage import get_storage_backend

UPLOAD_URL = f"{API_V1_PREFIX}/clips/upload"


def _wav(payload: bytes = b"\x00" * 64) -> bytes:
    """A minimal but genuine RIFF/WAVE container."""
    return b"RIFF" + (36 + len(payload)).to_bytes(4, "little") + b"WAVEfmt " + payload


# ---------------------------------------------------------------------------
# Format sniffing — runs in CI (no DB)
# ---------------------------------------------------------------------------


class TestFormatSniffing:
    @pytest.mark.parametrize(
        ("data", "expected"),
        [
            (_wav(), "wav"),
            (b"fLaC" + b"\x00" * 32, "flac"),
            (b"ID3\x03\x00" + b"\x00" * 32, "mp3"),
            (b"\xff\xfb\x90\x00" + b"\x00" * 32, "mp3"),
        ],
    )
    def test_recognises_the_audio_containers_the_platform_stores(self, data: bytes, expected: str) -> None:
        assert sniff_audio_format(data) == expected

    def test_riff_that_is_not_wave_is_rejected(self) -> None:
        # A RIFF AVI starts with the same four bytes as a WAV. Checking only the
        # magic prefix would let a video in as audio.
        avi = b"RIFF" + (1000).to_bytes(4, "little") + b"AVI LIST" + b"\x00" * 32
        assert sniff_audio_format(avi) is None

    @pytest.mark.parametrize("data", [b"", b"RI", b"not audio at all, just text", b"\x89PNG\r\n\x1a\n"])
    def test_non_audio_is_rejected(self, data: bytes) -> None:
        assert sniff_audio_format(data) is None


# ---------------------------------------------------------------------------
# Auth gate — runs in CI (no DB)
# ---------------------------------------------------------------------------


class TestAuthGate:
    def test_upload_without_a_token_is_401(self) -> None:
        client = TestClient(create_app())
        resp = client.post(
            UPLOAD_URL,
            files={"file": ("clip.wav", _wav(), "audio/wav")},
            data={"workspace_id": "000000000000000000000000"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Integration — real MongoDB
# ---------------------------------------------------------------------------

pytestmark_integration = pytest.mark.integration


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


@pytest.mark.integration
class TestUpload:
    async def test_pushes_a_clip_into_the_workspace_with_its_metadata(self, client, settings, local_storage) -> None:
        user = await _make_user("push@example.com")
        workspace = await _make_workspace(user)
        audio = _wav(b"\x01\x02" * 512)

        resp = await client.post(
            UPLOAD_URL,
            headers=_auth_headers(user, settings),
            files={"file": ("layer.wav", audio, "audio/wav")},
            data={
                "workspace_id": str(workspace.id),
                "title": "Bass layer",
                "bpm": "120",
                "key": "C minor",
                "duration": "16.0",
                "style_tags": "funk, bass ,  ",
                "model": "ace-step-1.5",
            },
        )

        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["title"] == "Bass layer"
        assert body["bpm"] == 120
        assert body["key"] == "C minor"
        assert body["format"] == "wav"
        assert body["workspace_id"] == str(workspace.id)
        # Blank entries are dropped rather than stored as empty tags.
        assert body["style_tags"] == ["funk", "bass"]
        # An imported clip must stay distinguishable from a generated one.
        assert body["generation_mode"] == "imported"

        # The bytes really are in storage, and are the ones that were sent.
        clip = await Clip.get(body["id"])
        assert clip is not None
        assert get_storage_backend().download(clip.file_path) == audio

        # And it comes back through the ordinary listing the plugin browses with.
        listed = await client.get(
            f"{API_V1_PREFIX}/clips",
            headers=_auth_headers(user, settings),
            params={"workspace_id": str(workspace.id)},
        )
        assert listed.status_code == 200
        assert [c["id"] for c in listed.json()["clips"]] == [body["id"]]

    async def test_a_non_audio_body_is_refused(self, client, settings, local_storage) -> None:
        user = await _make_user("nonaudio@example.com")
        workspace = await _make_workspace(user)

        resp = await client.post(
            UPLOAD_URL,
            headers=_auth_headers(user, settings),
            files={"file": ("clip.wav", b"this is definitely not audio", "audio/wav")},
            data={"workspace_id": str(workspace.id)},
        )

        # The declared filename and content type both say WAV; only the bytes are trusted.
        assert resp.status_code == 415
        assert await Clip.find_all().count() == 0

    async def test_an_empty_file_is_refused(self, client, settings, local_storage) -> None:
        user = await _make_user("empty@example.com")
        workspace = await _make_workspace(user)

        resp = await client.post(
            UPLOAD_URL,
            headers=_auth_headers(user, settings),
            files={"file": ("clip.wav", b"", "audio/wav")},
            data={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 422
        assert await Clip.find_all().count() == 0

    async def test_cannot_push_into_another_users_workspace(self, client, settings, local_storage) -> None:
        owner = await _make_user("owner@example.com")
        intruder = await _make_user("intruder@example.com")
        workspace = await _make_workspace(owner)

        resp = await client.post(
            UPLOAD_URL,
            headers=_auth_headers(intruder, settings),
            files={"file": ("clip.wav", _wav(), "audio/wav")},
            data={"workspace_id": str(workspace.id)},
        )

        assert resp.status_code == 404
        # Nothing is stored before ownership is established.
        assert await Clip.find_all().count() == 0

    async def test_an_unknown_workspace_is_refused(self, client, settings, local_storage) -> None:
        user = await _make_user("noworkspace@example.com")

        resp = await client.post(
            UPLOAD_URL,
            headers=_auth_headers(user, settings),
            files={"file": ("clip.wav", _wav(), "audio/wav")},
            data={"workspace_id": "000000000000000000000000"},
        )
        assert resp.status_code == 404

    async def test_oversized_audio_is_refused(self, client, settings, local_storage, monkeypatch) -> None:
        user = await _make_user("big@example.com")
        workspace = await _make_workspace(user)

        # Lowered rather than actually sending 200MB through the test transport.
        monkeypatch.setattr("acemusic.api.services.clips.CLIP_UPLOAD_MAX_BYTES", 128)
        monkeypatch.setattr("acemusic.api.routers.clips.clip_service.CLIP_UPLOAD_MAX_BYTES", 128)

        resp = await client.post(
            UPLOAD_URL,
            headers=_auth_headers(user, settings),
            files={"file": ("clip.wav", _wav(b"\x00" * 4096), "audio/wav")},
            data={"workspace_id": str(workspace.id)},
        )

        assert resp.status_code == 413
        assert await Clip.find_all().count() == 0

    async def test_the_upload_route_is_not_shadowed_by_the_clip_id_route(self, client, settings, local_storage) -> None:
        # `/clips/upload` sits alongside `/clips/{clip_id}`. Mounted in the wrong
        # order, "upload" is parsed as a clip id and the POST 404s or 405s.
        user = await _make_user("routing@example.com")
        workspace = await _make_workspace(user)

        resp = await client.post(
            UPLOAD_URL,
            headers=_auth_headers(user, settings),
            files={"file": ("clip.wav", _wav(), "audio/wav")},
            data={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 201, f"upload route shadowed: {resp.status_code} {resp.text}"

    @pytest.mark.parametrize(
        ("field", "value"),
        [("bpm", "-120"), ("bpm", "0"), ("bpm", "9999"), ("duration", "-1"), ("duration", "0")],
    )
    async def test_nonsensical_metadata_is_refused(
        self, client, settings, local_storage, field: str, value: str
    ) -> None:
        # A direct caller could otherwise persist bpm=-120 onto the Clip, and it would
        # then surface in every listing and in the plugin's browser.
        user = await _make_user(f"bounds-{field}-{value}@example.com")
        workspace = await _make_workspace(user)

        resp = await client.post(
            UPLOAD_URL,
            headers=_auth_headers(user, settings),
            files={"file": ("clip.wav", _wav(), "audio/wav")},
            data={"workspace_id": str(workspace.id), field: value},
        )

        assert resp.status_code == 422, f"{field}={value} was accepted"
        assert await Clip.find_all().count() == 0

    async def test_metadata_at_the_bounds_is_accepted(self, client, settings, local_storage) -> None:
        user = await _make_user("atbounds@example.com")
        workspace = await _make_workspace(user)

        resp = await client.post(
            UPLOAD_URL,
            headers=_auth_headers(user, settings),
            files={"file": ("clip.wav", _wav(), "audio/wav")},
            data={"workspace_id": str(workspace.id), "bpm": "60", "duration": "0.5"},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["bpm"] == 60

    async def test_a_clip_with_no_metadata_still_uploads(self, client, settings, local_storage) -> None:
        # The plugin may know nothing but the audio; that must not be an error.
        user = await _make_user("bare@example.com")
        workspace = await _make_workspace(user)

        resp = await client.post(
            UPLOAD_URL,
            headers=_auth_headers(user, settings),
            files={"file": ("clip.flac", b"fLaC" + b"\x00" * 64, "application/octet-stream")},
            data={"workspace_id": str(workspace.id)},
        )

        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["format"] == "flac"
        assert body["title"] is None
        assert body["style_tags"] == []


def test_the_upload_bound_is_a_sane_size() -> None:
    # Guards against a zero or absurd bound slipping in: big enough for a few
    # minutes of WAV, small enough not to be a memory hazard.
    assert 10 * 1024 * 1024 <= CLIP_UPLOAD_MAX_BYTES <= 500 * 1024 * 1024
