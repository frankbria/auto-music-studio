"""Tests for the clip audio retrieval endpoint (US-9.3, issue #77).

The utility tests and the 401 auth-gate test run in CI (no DB; plain
``TestClient`` does not run the lifespan). The retrieval/authorization/range
tests are ``integration``: they drive the real app with ``httpx.AsyncClient``
over a local MongoDB (``mongo_db``) and real LocalStorage, mirroring
``tests/test_jobs_api.py``. Format-conversion tests additionally require ffmpeg
and skip when it is absent (CI does not install it).
"""

import json
import shutil
import time

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
from acemusic.api.utils.range_requests import (
    build_multipart_ranges_response,
    parse_range_header,
    parse_range_header_multi,
)
from acemusic.api.utils.rate_limit import FixedWindowRateLimiter, _client_key
from acemusic.storage import get_storage_backend

requires_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="format conversion requires ffmpeg (not installed in CI)"
)


def _audio_url(clip_id: str) -> str:
    return f"{API_V1_PREFIX}/clips/{clip_id}/audio"


def _stream_url(clip_id: str) -> str:
    return f"{API_V1_PREFIX}/clips/{clip_id}/stream"


def _public_url(clip_id: str) -> str:
    return f"{API_V1_PREFIX}/clips/{clip_id}/public"


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

    @pytest.mark.parametrize("fmt", [None, "", "   "])
    def test_missing_or_blank_format_falls_back_to_octet_stream(self, fmt: str | None) -> None:
        assert get_audio_content_type(fmt) == "application/octet-stream"


# ---------------------------------------------------------------------------
# Multi-range parsing (US-14.2) — runs in CI (pure functions, no DB)
# ---------------------------------------------------------------------------


class TestParseRangeHeaderMulti:
    def test_single_range_returns_one_pair(self) -> None:
        assert parse_range_header_multi("bytes=0-99", 1000) == [(0, 99)]

    def test_two_ranges(self) -> None:
        assert parse_range_header_multi("bytes=0-99,200-299", 1000) == [(0, 99), (200, 299)]

    def test_many_ranges_preserve_order(self) -> None:
        header = "bytes=0-9,20-29,40-49,60-69"
        assert parse_range_header_multi(header, 1000) == [(0, 9), (20, 29), (40, 49), (60, 69)]

    def test_overlapping_ranges_served_as_is(self) -> None:
        # RFC permits serving overlapping ranges without merging.
        assert parse_range_header_multi("bytes=0-99,50-149", 1000) == [(0, 99), (50, 149)]

    def test_mixed_explicit_suffix_and_open_ended(self) -> None:
        assert parse_range_header_multi("bytes=0-99,-100,800-", 1000) == [(0, 99), (900, 999), (800, 999)]

    def test_whitespace_between_specs_is_tolerated(self) -> None:
        assert parse_range_header_multi("bytes=0-99, 200-299", 1000) == [(0, 99), (200, 299)]

    def test_end_clamped_to_content_length(self) -> None:
        assert parse_range_header_multi("bytes=0-99,500-9999", 1000) == [(0, 99), (500, 999)]

    def test_malformed_spec_invalidates_whole_header(self) -> None:
        assert parse_range_header_multi("bytes=0-99,abc", 1000) is None

    def test_non_bytes_unit_returns_none(self) -> None:
        assert parse_range_header_multi("items=0-99", 1000) is None

    def test_inverted_spec_invalidates_whole_header(self) -> None:
        assert parse_range_header_multi("bytes=0-99,5-2", 1000) is None

    def test_all_unsatisfiable_raises_416(self) -> None:
        with pytest.raises(HTTPException) as exc:
            parse_range_header_multi(f"bytes={2000}-,{3000}-", 1000)
        assert exc.value.status_code == 416
        assert exc.value.headers["Content-Range"] == "bytes */1000"

    def test_satisfiable_plus_unsatisfiable_drops_the_bad_one(self) -> None:
        # One valid, one past the end: serve the valid range, skip the rest.
        assert parse_range_header_multi("bytes=0-99,5000-6000", 1000) == [(0, 99)]

    def test_empty_content_returns_none(self) -> None:
        assert parse_range_header_multi("bytes=0-99", 0) is None

    def test_too_many_ranges_are_ignored(self) -> None:
        # Guards against multipart amplification: >10 ranges -> ignore Range,
        # serve the full body (None) rather than building an N×-sized response.
        many = "bytes=" + ",".join(f"{i}-{i}" for i in range(11))
        assert parse_range_header_multi(many, 1000) is None
        at_cap = "bytes=" + ",".join(f"{i}-{i}" for i in range(10))
        assert len(parse_range_header_multi(at_cap, 1000)) == 10

    def test_aggregate_bytes_exceeding_content_are_ignored(self) -> None:
        # Overlapping open-ended ranges stay under the count cap but each select
        # the whole file -> serve the full body once (None) instead of N× memory.
        assert parse_range_header_multi("bytes=0-,0-,0-", 1000) is None
        # Non-overlapping ranges summing within the file are still honored.
        assert parse_range_header_multi("bytes=0-99,200-299", 1000) == [(0, 99), (200, 299)]


class TestBuildMultipartRangesResponse:
    def test_mime_structure_for_two_ranges(self) -> None:
        content = bytes(range(256)) * 4  # 1024 deterministic bytes
        body, content_type = build_multipart_ranges_response(content, [(0, 9), (100, 119)], "audio/wav", "BOUNDARY123")
        assert content_type == "multipart/byteranges; boundary=BOUNDARY123"
        # Two parts, each with its own headers and the exact slice as payload.
        assert body.count(b"--BOUNDARY123\r\n") == 2
        assert b"Content-Type: audio/wav\r\n" in body
        assert b"Content-Range: bytes 0-9/1024\r\n" in body
        assert b"Content-Range: bytes 100-119/1024\r\n" in body
        assert content[0:10] in body
        assert content[100:120] in body
        # Closing boundary terminates the body.
        assert body.endswith(b"\r\n--BOUNDARY123--\r\n")


class TestFixedWindowRateLimiter:
    def test_rejects_over_the_limit_within_a_window(self) -> None:
        limiter = FixedWindowRateLimiter(limit=2, window_seconds=60.0)
        limiter.check("ip")  # 1
        limiter.check("ip")  # 2
        with pytest.raises(HTTPException) as exc:
            limiter.check("ip")  # 3 -> over
        assert exc.value.status_code == 429
        assert "Retry-After" in exc.value.headers

    def test_expired_keys_are_pruned(self) -> None:
        # One-off IPs must not accumulate forever on a public endpoint.
        limiter = FixedWindowRateLimiter(limit=5, window_seconds=0.02)
        limiter.check("old-ip")
        assert "old-ip" in limiter._hits
        time.sleep(0.03)  # let the window elapse
        limiter.check("new-ip")  # triggers a prune sweep
        assert "old-ip" not in limiter._hits
        assert "new-ip" in limiter._hits


class TestClientKey:
    """issue #283: key on the real client behind a trusted BFF proxy, but only
    when the peer is trusted — otherwise a forwarded header would be spoofable."""

    @staticmethod
    def _request(peer_ip: str | None, xff: str | None = None):
        from starlette.requests import Request

        headers = [(b"x-forwarded-for", xff.encode())] if xff is not None else []
        scope = {
            "type": "http",
            "headers": headers,
            "client": (peer_ip, 12345) if peer_ip else None,
        }
        return Request(scope)

    def test_untrusted_peer_ignores_forwarded_header(self) -> None:
        # AC2/AC3: a direct/untrusted caller's X-Forwarded-For is not trusted;
        # the limiter keys on the real socket peer.
        req = self._request("203.0.113.9", xff="1.1.1.1")
        assert _client_key(req, frozenset()) == "203.0.113.9"

    def test_trusted_proxy_uses_leftmost_forwarded_client(self) -> None:
        # AC1: behind a trusted BFF, key on the forwarded real client IP so two
        # visitors don't collapse into the proxy's single egress IP.
        req = self._request("10.0.0.2", xff="198.51.100.7, 10.0.0.2")
        assert _client_key(req, frozenset({"10.0.0.2"})) == "198.51.100.7"

    def test_trusted_proxy_without_forwarded_header_falls_back_to_peer(self) -> None:
        # AC4: nothing forwarded -> behave exactly like today (peer IP).
        req = self._request("10.0.0.2", xff=None)
        assert _client_key(req, frozenset({"10.0.0.2"})) == "10.0.0.2"

    def test_trusted_proxy_with_blank_forwarded_header_falls_back_to_peer(self) -> None:
        req = self._request("10.0.0.2", xff="  ")
        assert _client_key(req, frozenset({"10.0.0.2"})) == "10.0.0.2"

    def test_missing_client_is_anonymous(self) -> None:
        req = self._request(None)
        assert _client_key(req, frozenset()) == "anonymous"

    def test_ipv6_mapped_peer_matches_plain_trusted_ip(self) -> None:
        # A dual-stack socket may report ::ffff:127.0.0.1 for a proxy an operator
        # listed as 127.0.0.1; normalization must still recognize it as trusted.
        req = self._request("::ffff:127.0.0.1", xff="198.51.100.7")
        assert _client_key(req, frozenset({"127.0.0.1"})) == "198.51.100.7"

    def test_forwarded_client_is_normalized_to_one_bucket(self) -> None:
        # An IPv4-mapped and plain form of the same visitor key one bucket.
        trusted = frozenset({"10.0.0.2"})
        mapped = _client_key(self._request("10.0.0.2", xff="::ffff:1.1.1.1"), trusted)
        plain = _client_key(self._request("10.0.0.2", xff="1.1.1.1"), trusted)
        assert mapped == plain == "1.1.1.1"


class TestEnforceStreamRateLimit:
    """issue #283: the dependency must key per forwarded client behind a trusted
    proxy — exercises the real settings/limiter wiring, not just _client_key."""

    @staticmethod
    def _request(app, xff: str):
        from starlette.requests import Request

        return Request(
            {
                "type": "http",
                "app": app,
                "headers": [(b"x-forwarded-for", xff.encode())],
                "client": ("10.0.0.2", 12345),
            }
        )

    def test_distinct_forwarded_clients_get_distinct_buckets(self) -> None:
        from types import SimpleNamespace

        from acemusic.api.utils.rate_limit import enforce_stream_rate_limit

        app = SimpleNamespace(
            state=SimpleNamespace(
                settings=SimpleNamespace(trusted_proxy_set=frozenset({"10.0.0.2"})),
                stream_limiter=FixedWindowRateLimiter(limit=1, window_seconds=60.0),
            )
        )
        # Two visitors, one shared proxy IP: each is allowed its own single hit.
        enforce_stream_rate_limit(self._request(app, "1.1.1.1"))
        enforce_stream_rate_limit(self._request(app, "2.2.2.2"))
        # The first visitor's second hit exceeds their own bucket (not the other's).
        with pytest.raises(HTTPException) as exc:
            enforce_stream_rate_limit(self._request(app, "1.1.1.1"))
        assert exc.value.status_code == 429


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


async def _make_clip(
    user,
    audio_bytes: bytes,
    *,
    fmt: str = "wav",
    is_public: bool = False,
    store: bool = True,
    **fields,
):
    """Insert a clip owned by ``user`` and (optionally) store its audio bytes.

    Extra ``fields`` land on the Clip verbatim, so tests that assert on display
    or redacted metadata (title, seed, ...) can set just what they check.
    """
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
        **fields,
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
        assert resp.headers["accept-ranges"] == "bytes"

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
        # Converted output does not honor byte ranges, so it must not
        # advertise range support.
        assert "accept-ranges" not in resp.headers

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


@pytest.mark.integration
class TestClipStreaming:
    """US-14.2: GET /clips/{id}/stream — optional auth, multi-range, rate limit."""

    # --- Authentication / access control -----------------------------------

    async def test_anonymous_streams_public_clip(self, client, local_storage, wav_bytes) -> None:
        owner = await _make_user("stream-pub-owner@example.com")
        clip = await _make_clip(owner, wav_bytes, is_public=True)

        resp = await client.get(_stream_url(str(clip.id)))  # no auth header
        assert resp.status_code == 200
        assert resp.content == wav_bytes
        assert resp.headers["accept-ranges"] == "bytes"
        assert "public" in resp.headers["cache-control"]

    async def test_anonymous_private_clip_returns_404(self, client, local_storage, wav_bytes) -> None:
        owner = await _make_user("stream-priv-owner@example.com")
        clip = await _make_clip(owner, wav_bytes, is_public=False)

        # 404 (not 403) so a stranger cannot tell a private clip exists.
        resp = await client.get(_stream_url(str(clip.id)))
        assert resp.status_code == 404

    async def test_owner_streams_own_private_clip(self, client, settings, local_storage, wav_bytes) -> None:
        owner = await _make_user("stream-own-priv@example.com")
        clip = await _make_clip(owner, wav_bytes, is_public=False)

        resp = await client.get(_stream_url(str(clip.id)), headers=_auth_headers(owner, settings))
        assert resp.status_code == 200
        assert resp.content == wav_bytes
        assert "private" in resp.headers["cache-control"]

    async def test_authenticated_non_owner_private_clip_returns_403(
        self, client, settings, local_storage, wav_bytes
    ) -> None:
        owner = await _make_user("stream-other-owner@example.com")
        other = await _make_user("stream-other-user@example.com")
        clip = await _make_clip(owner, wav_bytes, is_public=False)

        resp = await client.get(_stream_url(str(clip.id)), headers=_auth_headers(other, settings))
        assert resp.status_code == 403

    async def test_invalid_token_is_rejected(self, client, local_storage, wav_bytes) -> None:
        owner = await _make_user("stream-badtoken@example.com")
        clip = await _make_clip(owner, wav_bytes, is_public=True)

        # An explicitly-supplied bad token is a 401, not an anonymous request.
        resp = await client.get(_stream_url(str(clip.id)), headers={"Authorization": "Bearer not-a-real-token"})
        assert resp.status_code == 401

    # --- Range requests ----------------------------------------------------

    async def test_single_range_returns_206(self, client, local_storage, wav_bytes) -> None:
        owner = await _make_user("stream-range1@example.com")
        clip = await _make_clip(owner, wav_bytes, is_public=True)

        resp = await client.get(_stream_url(str(clip.id)), headers={"Range": "bytes=0-99"})
        assert resp.status_code == 206
        assert resp.content == wav_bytes[:100]
        assert resp.headers["content-range"] == f"bytes 0-99/{len(wav_bytes)}"

    async def test_no_range_returns_200_full(self, client, local_storage, wav_bytes) -> None:
        owner = await _make_user("stream-range2@example.com")
        clip = await _make_clip(owner, wav_bytes, is_public=True)

        resp = await client.get(_stream_url(str(clip.id)))
        assert resp.status_code == 200
        assert resp.content == wav_bytes

    async def test_multi_range_returns_multipart_206(self, client, local_storage, wav_bytes) -> None:
        owner = await _make_user("stream-range3@example.com")
        clip = await _make_clip(owner, wav_bytes, is_public=True)

        resp = await client.get(_stream_url(str(clip.id)), headers={"Range": "bytes=0-99,200-299"})
        assert resp.status_code == 206
        assert resp.headers["content-type"].startswith("multipart/byteranges; boundary=")
        # Both requested slices are present in the multipart body.
        assert wav_bytes[0:100] in resp.content
        assert wav_bytes[200:300] in resp.content
        assert b"Content-Range: bytes 0-99/" in resp.content
        assert b"Content-Range: bytes 200-299/" in resp.content

    async def test_unsatisfiable_range_returns_416(self, client, local_storage, wav_bytes) -> None:
        owner = await _make_user("stream-range4@example.com")
        clip = await _make_clip(owner, wav_bytes, is_public=True)

        resp = await client.get(_stream_url(str(clip.id)), headers={"Range": f"bytes={len(wav_bytes)}-"})
        assert resp.status_code == 416
        assert resp.headers["content-range"] == f"bytes */{len(wav_bytes)}"

    # --- Format conversion -------------------------------------------------

    @requires_ffmpeg
    async def test_format_mp3_converts_and_disables_ranges(self, client, local_storage, wav_bytes) -> None:
        owner = await _make_user("stream-fmt@example.com")
        clip = await _make_clip(owner, wav_bytes, is_public=True)

        headers = {"Range": "bytes=0-99"}  # ranges ignored once converted
        resp = await client.get(_stream_url(str(clip.id)) + "?format=mp3", headers=headers)
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "audio/mpeg"
        assert resp.content[:3] == b"ID3" or resp.content[0] == 0xFF
        assert "accept-ranges" not in resp.headers

    # --- Rate limiting -----------------------------------------------------

    async def test_exceeding_rate_limit_returns_429(self, settings, local_storage, wav_bytes) -> None:
        owner = await _make_user("stream-ratelimit@example.com")
        clip = await _make_clip(owner, wav_bytes, is_public=True)

        # Dedicated app with a low limit; all requests share the test client IP.
        limited = settings.model_copy(update={"stream_rate_limit_per_minute": 2})
        async with _async_client(create_app(limited)) as limited_client:
            url = _stream_url(str(clip.id))
            assert (await limited_client.get(url)).status_code == 200
            assert (await limited_client.get(url)).status_code == 200
            third = await limited_client.get(url)
            assert third.status_code == 429
            assert "retry-after" in third.headers


# Fields the public read keeps owner-only: internal structural ids and the
# generation recipe. Nothing a visitor sees on the song page renders them.
OWNER_ONLY_FIELDS = ("workspace_id", "seed", "inference_steps")


@pytest.mark.integration
class TestGetClipPublic:
    """US-20.0: GET /clips/{id}/public — optional auth, is_public-scoped metadata."""

    # --- Authentication / access control -----------------------------------

    async def test_anonymous_reads_public_clip(self, client, local_storage, wav_bytes) -> None:
        owner = await _make_user("public-anon-pub@example.com")
        clip = await _make_clip(owner, wav_bytes, is_public=True, title="Midnight Drive", style_tags=["synthwave"])

        resp = await client.get(_public_url(str(clip.id)))  # no auth header
        assert resp.status_code == 200
        body = resp.json()
        assert body["title"] == "Midnight Drive"
        assert body["style_tags"] == ["synthwave"]
        assert body["is_public"] is True
        assert body["is_owner"] is False

    async def test_anonymous_private_clip_returns_404(self, client, local_storage, wav_bytes) -> None:
        owner = await _make_user("public-anon-priv@example.com")
        clip = await _make_clip(owner, wav_bytes, is_public=False, title="Secret Demo")

        # 404 (not 403) so a stranger cannot tell a private clip exists, and the
        # title must not leak through the error body.
        resp = await client.get(_public_url(str(clip.id)))
        assert resp.status_code == 404
        assert "Secret Demo" not in resp.text

    async def test_anonymous_unknown_clip_returns_404(self, client, local_storage) -> None:
        resp = await client.get(_public_url(str(PydanticObjectId())))
        assert resp.status_code == 404

    async def test_malformed_id_returns_404(self, client, local_storage) -> None:
        resp = await client.get(_public_url("not-an-object-id"))
        assert resp.status_code == 404

    async def test_authenticated_non_owner_reads_public_clip(self, client, settings, local_storage, wav_bytes) -> None:
        owner = await _make_user("public-nonowner-owner@example.com")
        other = await _make_user("public-nonowner-user@example.com")
        clip = await _make_clip(owner, wav_bytes, is_public=True)

        resp = await client.get(_public_url(str(clip.id)), headers=_auth_headers(other, settings))
        assert resp.status_code == 200
        assert resp.json()["is_owner"] is False

    async def test_authenticated_non_owner_private_clip_returns_403(
        self, client, settings, local_storage, wav_bytes
    ) -> None:
        owner = await _make_user("public-priv-owner@example.com")
        other = await _make_user("public-priv-user@example.com")
        clip = await _make_clip(owner, wav_bytes, is_public=False)

        # Authenticated callers get the 403/404 distinction (get_clip_for_streaming).
        resp = await client.get(_public_url(str(clip.id)), headers=_auth_headers(other, settings))
        assert resp.status_code == 403

    async def test_owner_reads_own_public_clip(self, client, settings, local_storage, wav_bytes) -> None:
        owner = await _make_user("public-own-pub@example.com")
        clip = await _make_clip(owner, wav_bytes, is_public=True)

        resp = await client.get(_public_url(str(clip.id)), headers=_auth_headers(owner, settings))
        assert resp.status_code == 200
        assert resp.json()["is_owner"] is True

    async def test_owner_reads_own_private_clip(self, client, settings, local_storage, wav_bytes) -> None:
        owner = await _make_user("public-own-priv@example.com")
        clip = await _make_clip(owner, wav_bytes, is_public=False)

        resp = await client.get(_public_url(str(clip.id)), headers=_auth_headers(owner, settings))
        assert resp.status_code == 200
        assert resp.json()["is_owner"] is True

    async def test_invalid_token_is_rejected(self, client, local_storage, wav_bytes) -> None:
        owner = await _make_user("public-badtoken@example.com")
        clip = await _make_clip(owner, wav_bytes, is_public=True)

        # An explicitly-supplied bad token is a 401, not an anonymous request.
        resp = await client.get(_public_url(str(clip.id)), headers={"Authorization": "Bearer not-a-real-token"})
        assert resp.status_code == 401

    # --- Redaction ---------------------------------------------------------

    async def test_non_owner_response_redacts_owner_only_fields(self, client, local_storage, wav_bytes) -> None:
        owner = await _make_user("public-redact-anon@example.com")
        clip = await _make_clip(owner, wav_bytes, is_public=True, seed=1234, inference_steps=30)

        body = (await client.get(_public_url(str(clip.id)))).json()
        for field in OWNER_ONLY_FIELDS:
            assert body[field] is None, f"{field} must not reach a non-owner"
        # The owner's internal ids must not leak anywhere in the payload.
        assert str(clip.workspace_id) not in json.dumps(body)
        assert str(clip.user_id) not in json.dumps(body)

    async def test_owner_response_keeps_owner_only_fields(self, client, settings, local_storage, wav_bytes) -> None:
        owner = await _make_user("public-redact-owner@example.com")
        clip = await _make_clip(owner, wav_bytes, is_public=True, seed=1234, inference_steps=30)

        body = (await client.get(_public_url(str(clip.id)), headers=_auth_headers(owner, settings))).json()
        assert body["workspace_id"] == str(clip.workspace_id)
        assert body["seed"] == 1234
        assert body["inference_steps"] == 30

    async def test_non_owner_response_redacts_ancestry(self, client, local_storage, wav_bytes) -> None:
        owner = await _make_user("public-lineage-anon@example.com")
        parent = await _make_clip(owner, wav_bytes, is_public=False)
        child = await _make_clip(owner, wav_bytes, is_public=True, parent_clip_ids=[parent.id])

        # Raw ancestor ids are the same correlation vector as workspace_id (and
        # an ObjectId embeds its creation time), so a public clip must not reveal
        # that a *private* parent exists. get_lineage already refuses to leak
        # other users' ancestors; this keeps the metadata read consistent.
        body = (await client.get(_public_url(str(child.id)))).json()
        assert body["parent_clip_ids"] == []
        assert str(parent.id) not in json.dumps(body)

    async def test_owner_response_keeps_ancestry(self, client, settings, local_storage, wav_bytes) -> None:
        owner = await _make_user("public-lineage-owner@example.com")
        parent = await _make_clip(owner, wav_bytes, is_public=False)
        child = await _make_clip(owner, wav_bytes, is_public=True, parent_clip_ids=[parent.id])

        body = (await client.get(_public_url(str(child.id)), headers=_auth_headers(owner, settings))).json()
        assert body["parent_clip_ids"] == [str(parent.id)]

    async def test_user_id_is_never_exposed(self, client, settings, local_storage, wav_bytes) -> None:
        owner = await _make_user("public-noleak-owner@example.com")
        clip = await _make_clip(owner, wav_bytes, is_public=True)

        # Even the owner's own read never carries the raw owner id — ownership
        # is communicated only through is_owner.
        body = (await client.get(_public_url(str(clip.id)), headers=_auth_headers(owner, settings))).json()
        assert "user_id" not in body

    # --- Rate limiting -----------------------------------------------------

    async def test_exceeding_rate_limit_returns_429(self, settings, local_storage, wav_bytes) -> None:
        owner = await _make_user("public-ratelimit@example.com")
        clip = await _make_clip(owner, wav_bytes, is_public=True)

        limited = settings.model_copy(update={"stream_rate_limit_per_minute": 2})
        async with _async_client(create_app(limited)) as limited_client:
            url = _public_url(str(clip.id))
            assert (await limited_client.get(url)).status_code == 200
            assert (await limited_client.get(url)).status_code == 200
            assert (await limited_client.get(url)).status_code == 429
