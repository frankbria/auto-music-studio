"""Tests for the clip audio retrieval endpoint (US-9.3, issue #77).

The utility tests and the 401 auth-gate test run in CI (no DB; plain
``TestClient`` does not run the lifespan). The retrieval/authorization/range
tests are ``integration``: they drive the real app with ``httpx.AsyncClient``
over a local MongoDB (``mongo_db``) and real LocalStorage, mirroring
``tests/test_jobs_api.py``. Format-conversion tests additionally require ffmpeg
and skip when it is absent (CI does not install it).
"""

import shutil

import httpx
import pytest
from beanie import PydanticObjectId
from fastapi import HTTPException
from fastapi.testclient import TestClient

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import Clip
from acemusic.api.services import users as user_service
from acemusic.api.services.audio_conversion import convert_audio_format
from acemusic.api.settings import ApiSettings
from acemusic.api.utils.media_types import get_audio_content_type
from acemusic.api.utils.range_requests import parse_range_header
from acemusic.storage import get_storage_backend

requires_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="format conversion requires ffmpeg (not installed in CI)"
)


def _audio_url(clip_id: str) -> str:
    return f"{API_V1_PREFIX}/clips/{clip_id}/audio"


# ---------------------------------------------------------------------------
# Media-type utility — runs in CI
# ---------------------------------------------------------------------------


class TestGetAudioContentType:
    @pytest.mark.parametrize(
        ("fmt", "expected"),
        [
            ("wav", "audio/wav"),
            ("flac", "audio/flac"),
            ("mp3", "audio/mpeg"),
            ("ogg", "audio/ogg"),
            ("aac", "audio/aac"),
            ("opus", "audio/opus"),
        ],
    )
    def test_known_formats_map_to_mime_types(self, fmt: str, expected: str) -> None:
        assert get_audio_content_type(fmt) == expected

    def test_lookup_is_case_insensitive(self) -> None:
        assert get_audio_content_type("WAV") == "audio/wav"

    def test_unknown_format_falls_back_to_octet_stream(self) -> None:
        assert get_audio_content_type("xyz") == "application/octet-stream"


# ---------------------------------------------------------------------------
# Range header parser — runs in CI
# ---------------------------------------------------------------------------


class TestParseRangeHeader:
    def test_explicit_range(self) -> None:
        assert parse_range_header("bytes=0-99", 1000) == (0, 99)

    def test_open_ended_range_runs_to_last_byte(self) -> None:
        assert parse_range_header("bytes=100-", 1000) == (100, 999)

    def test_suffix_range_returns_last_n_bytes(self) -> None:
        assert parse_range_header("bytes=-100", 1000) == (900, 999)

    def test_suffix_longer_than_content_clamps_to_full(self) -> None:
        assert parse_range_header("bytes=-5000", 1000) == (0, 999)

    def test_end_beyond_content_clamps_to_last_byte(self) -> None:
        assert parse_range_header("bytes=500-9999", 1000) == (500, 999)

    def test_start_at_or_past_length_raises_416(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            parse_range_header("bytes=1000-", 1000)
        assert exc_info.value.status_code == 416
        assert exc_info.value.headers["Content-Range"] == "bytes */1000"

    def test_zero_suffix_raises_416(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            parse_range_header("bytes=-0", 1000)
        assert exc_info.value.status_code == 416

    @pytest.mark.parametrize(
        "header",
        [
            "bytes=5-2",  # end before start: syntactically invalid per RFC 9110
            "bytes=abc-def",
            "bytes=0-99,200-299",  # multipart ranges unsupported — serve full body
            "items=0-99",  # unknown unit
            "bytes=",
            "bytes=-",
            "garbage",
        ],
    )
    def test_invalid_or_unsupported_headers_are_ignored(self, header: str) -> None:
        assert parse_range_header(header, 1000) is None

    def test_empty_content_is_never_range_served(self) -> None:
        assert parse_range_header("bytes=0-99", 0) is None


# ---------------------------------------------------------------------------
# Conversion service — runs in CI except where ffmpeg is required
# ---------------------------------------------------------------------------


class TestConvertAudioFormat:
    def test_unsupported_target_format_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unsupported conversion format"):
            convert_audio_format(b"\x00", "wav", "xm")

    @requires_ffmpeg
    def test_wav_to_flac_round_trip_preserves_duration(self, write_tone, tmp_path) -> None:
        from pydub import AudioSegment

        path = tmp_path / "tone.wav"
        write_tone(path, duration_s=1.0)
        flac_bytes = convert_audio_format(path.read_bytes(), "wav", "flac")
        assert flac_bytes[:4] == b"fLaC"

        wav_bytes = convert_audio_format(flac_bytes, "flac", "wav")
        import io

        segment = AudioSegment.from_file(io.BytesIO(wav_bytes), format="wav")
        assert segment.duration_seconds == pytest.approx(1.0, abs=0.05)


# ---------------------------------------------------------------------------
# Auth gate — runs in CI (no DB)
# ---------------------------------------------------------------------------


class TestAuthGate:
    def test_missing_auth_header_returns_401(self) -> None:
        client = TestClient(create_app())
        resp = client.get(_audio_url(str(PydanticObjectId())))
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Integration — real MongoDB + real LocalStorage
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


async def _make_clip(user, audio_bytes: bytes, *, fmt: str = "wav", is_public: bool = False, store: bool = True):
    """Insert a clip owned by ``user`` and (optionally) store its audio bytes."""
    clip_id = PydanticObjectId()
    workspace_id = PydanticObjectId()
    file_path = f"{user.id}/{workspace_id}/clips/{clip_id}.{fmt}"
    if store:
        get_storage_backend().upload(file_path, audio_bytes)
    clip = Clip(
        id=clip_id,
        user_id=user.id,
        workspace_id=workspace_id,
        file_path=file_path,
        format=fmt,
        is_public=is_public,
    )
    await clip.insert()
    return clip


def _tone_bytes(write_tone, tmp_path_factory, duration_s: float = 1.0) -> bytes:
    path = tmp_path_factory.mktemp("tone") / "tone.wav"
    write_tone(path, duration_s=duration_s)
    return path.read_bytes()


@pytest.fixture
def wav_bytes(write_tone, tmp_path_factory) -> bytes:
    return _tone_bytes(write_tone, tmp_path_factory)


@pytest.mark.integration
class TestClipAudioRetrieval:
    async def test_own_clip_returns_playable_audio_with_content_type(
        self, client, settings, local_storage, wav_bytes
    ) -> None:
        user = await _make_user("clips-own@example.com")
        clip = await _make_clip(user, wav_bytes)

        resp = await client.get(_audio_url(str(clip.id)), headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "audio/wav"
        assert resp.headers["accept-ranges"] == "bytes"
        assert int(resp.headers["content-length"]) == len(wav_bytes)
        assert resp.content == wav_bytes
        assert resp.content[:4] == b"RIFF"  # playable WAV, not an error payload

    async def test_nonexistent_clip_returns_404(self, client, settings, local_storage) -> None:
        user = await _make_user("clips-missing@example.com")
        resp = await client.get(_audio_url(str(PydanticObjectId())), headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    async def test_malformed_clip_id_returns_404(self, client, settings, local_storage) -> None:
        user = await _make_user("clips-malformed@example.com")
        resp = await client.get(_audio_url("not-an-object-id"), headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    async def test_other_users_private_clip_returns_403(self, client, settings, local_storage, wav_bytes) -> None:
        owner = await _make_user("clips-owner@example.com")
        other = await _make_user("clips-other@example.com")
        clip = await _make_clip(owner, wav_bytes, is_public=False)

        resp = await client.get(_audio_url(str(clip.id)), headers=_auth_headers(other, settings))
        assert resp.status_code == 403

    async def test_other_users_public_clip_returns_200(self, client, settings, local_storage, wav_bytes) -> None:
        owner = await _make_user("clips-pub-owner@example.com")
        other = await _make_user("clips-pub-other@example.com")
        clip = await _make_clip(owner, wav_bytes, is_public=True)

        resp = await client.get(_audio_url(str(clip.id)), headers=_auth_headers(other, settings))
        assert resp.status_code == 200
        assert resp.content == wav_bytes

    async def test_clip_with_missing_audio_file_returns_404(self, client, settings, local_storage) -> None:
        user = await _make_user("clips-nofile@example.com")
        clip = await _make_clip(user, b"", store=False)

        resp = await client.get(_audio_url(str(clip.id)), headers=_auth_headers(user, settings))
        assert resp.status_code == 404


@pytest.mark.integration
class TestClipAudioRangeRequests:
    async def test_first_100_bytes(self, client, settings, local_storage, wav_bytes) -> None:
        user = await _make_user("clips-range1@example.com")
        clip = await _make_clip(user, wav_bytes)

        headers = {**_auth_headers(user, settings), "Range": "bytes=0-99"}
        resp = await client.get(_audio_url(str(clip.id)), headers=headers)
        assert resp.status_code == 206
        assert resp.content == wav_bytes[:100]
        assert resp.headers["content-range"] == f"bytes 0-99/{len(wav_bytes)}"
        assert int(resp.headers["content-length"]) == 100

    async def test_last_100_bytes_via_suffix_range(self, client, settings, local_storage, wav_bytes) -> None:
        user = await _make_user("clips-range2@example.com")
        clip = await _make_clip(user, wav_bytes)

        headers = {**_auth_headers(user, settings), "Range": "bytes=-100"}
        resp = await client.get(_audio_url(str(clip.id)), headers=headers)
        assert resp.status_code == 206
        assert resp.content == wav_bytes[-100:]
        total = len(wav_bytes)
        assert resp.headers["content-range"] == f"bytes {total - 100}-{total - 1}/{total}"

    async def test_open_ended_range_returns_tail(self, client, settings, local_storage, wav_bytes) -> None:
        user = await _make_user("clips-range3@example.com")
        clip = await _make_clip(user, wav_bytes)

        headers = {**_auth_headers(user, settings), "Range": "bytes=1000-"}
        resp = await client.get(_audio_url(str(clip.id)), headers=headers)
        assert resp.status_code == 206
        assert resp.content == wav_bytes[1000:]

    async def test_unsatisfiable_range_returns_416(self, client, settings, local_storage, wav_bytes) -> None:
        user = await _make_user("clips-range4@example.com")
        clip = await _make_clip(user, wav_bytes)

        headers = {**_auth_headers(user, settings), "Range": f"bytes={len(wav_bytes)}-"}
        resp = await client.get(_audio_url(str(clip.id)), headers=headers)
        assert resp.status_code == 416
        assert resp.headers["content-range"] == f"bytes */{len(wav_bytes)}"

    async def test_invalid_range_header_serves_full_content(self, client, settings, local_storage, wav_bytes) -> None:
        user = await _make_user("clips-range5@example.com")
        clip = await _make_clip(user, wav_bytes)

        headers = {**_auth_headers(user, settings), "Range": "bytes=5-2"}
        resp = await client.get(_audio_url(str(clip.id)), headers=headers)
        assert resp.status_code == 200
        assert resp.content == wav_bytes


@pytest.mark.integration
class TestClipAudioFormatConversion:
    @requires_ffmpeg
    async def test_format_mp3_returns_mpeg_audio(self, client, settings, local_storage, wav_bytes) -> None:
        user = await _make_user("clips-conv1@example.com")
        clip = await _make_clip(user, wav_bytes)

        resp = await client.get(_audio_url(str(clip.id)) + "?format=mp3", headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "audio/mpeg"
        # MP3 bitstream: either an ID3 tag or an MPEG frame-sync header.
        assert resp.content[:3] == b"ID3" or resp.content[0] == 0xFF
        assert int(resp.headers["content-length"]) == len(resp.content)

    async def test_same_format_as_native_serves_bytes_unchanged(
        self, client, settings, local_storage, wav_bytes
    ) -> None:
        user = await _make_user("clips-conv2@example.com")
        clip = await _make_clip(user, wav_bytes)

        resp = await client.get(_audio_url(str(clip.id)) + "?format=wav", headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "audio/wav"
        assert resp.content == wav_bytes

    async def test_unsupported_format_returns_422(self, client, settings, local_storage, wav_bytes) -> None:
        user = await _make_user("clips-conv3@example.com")
        clip = await _make_clip(user, wav_bytes)

        resp = await client.get(_audio_url(str(clip.id)) + "?format=xm", headers=_auth_headers(user, settings))
        assert resp.status_code == 422

    @requires_ffmpeg
    async def test_undecodable_audio_returns_500(self, client, settings, local_storage) -> None:
        user = await _make_user("clips-conv5@example.com")
        clip = await _make_clip(user, b"this is not audio data", fmt="wav")

        resp = await client.get(_audio_url(str(clip.id)) + "?format=mp3", headers=_auth_headers(user, settings))
        assert resp.status_code == 500
        assert "convert" in resp.json()["detail"].lower()

    @requires_ffmpeg
    async def test_range_header_is_ignored_for_converted_content(
        self, client, settings, local_storage, wav_bytes
    ) -> None:
        # Conversion changes the byte layout, so byte ranges against the native
        # file are meaningless — the endpoint serves the full converted body.
        user = await _make_user("clips-conv4@example.com")
        clip = await _make_clip(user, wav_bytes)

        headers = {**_auth_headers(user, settings), "Range": "bytes=0-99"}
        resp = await client.get(_audio_url(str(clip.id)) + "?format=mp3", headers=headers)
        assert resp.status_code == 200
        assert len(resp.content) > 100
