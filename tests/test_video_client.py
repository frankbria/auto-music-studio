"""Unit tests for HttpVideoClient (US-22.1).

Every HTTP call is stubbed with real ``httpx.Response`` objects (no network),
so these run in CI. They cover the three-call workflow contract (submit ->
get_status -> download), state normalisation onto the platform vocabulary, and
the shared transient-retry policy: up to 3 retries with backoff on 5xx, 4xx
failing fast.
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from acemusic.video_client import (
    HttpVideoClient,
    VideoGenerationError,
    normalize_state,
)

FAKE_MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64


def _resp(status_code: int = 200, json_data: dict | None = None, content: bytes | None = None) -> httpx.Response:
    resp = httpx.Response(
        status_code,
        json=json_data if content is None else None,
        content=content,
        request=httpx.Request("GET", "https://video.test/jobs"),
    )
    return resp


def _client() -> HttpVideoClient:
    return HttpVideoClient(base_url="https://video.test/", api_key="vk-test")


class TestNormalizeState:
    def test_known_aliases(self) -> None:
        assert normalize_state("PENDING") == "queued"
        assert normalize_state("processing") == "rendering"
        assert normalize_state("encoding") == "encoding"
        assert normalize_state("succeeded") == "complete"
        assert normalize_state("error") == "failed"

    def test_unknown_state_treated_as_still_rendering(self) -> None:
        assert normalize_state("warming-up-gpus") == "rendering"


class TestSubmit:
    def test_returns_provider_job_id(self) -> None:
        with patch("acemusic._http.request", return_value=_resp(200, {"id": "pj-1"})) as req:
            job_id = _client().submit(b"RIFF", "song.wav", {"resolution": "720p", "reference_image_urls": ["u1"]})
        assert job_id == "pj-1"
        # Trailing slash stripped; auth header carried; params serialised as form strings.
        args, kwargs = req.call_args
        assert args[1] == "https://video.test/jobs"
        assert kwargs["headers"]["Authorization"] == "Bearer vk-test"
        assert kwargs["data"]["resolution"] == "720p"
        assert kwargs["data"]["reference_image_urls"] == ["u1"]

    def test_none_params_omitted(self) -> None:
        with patch("acemusic._http.request", return_value=_resp(200, {"id": "pj-1"})) as req:
            _client().submit(b"RIFF", "song.wav", {"prompt": None, "lyrics_sync": False})
        assert "prompt" not in req.call_args.kwargs["data"]
        assert req.call_args.kwargs["data"]["lyrics_sync"] == "False"

    def test_missing_job_id_raises(self) -> None:
        with patch("acemusic._http.request", return_value=_resp(200, {})):
            with pytest.raises(VideoGenerationError, match="no job id"):
                _client().submit(b"RIFF", "song.wav", {})

    def test_4xx_fails_fast(self) -> None:
        with patch("acemusic._http.request", return_value=_resp(401, {"detail": "bad key"})) as req:
            with pytest.raises(VideoGenerationError, match="401"):
                _client().submit(b"RIFF", "song.wav", {})
        assert req.call_count == 1

    def test_connection_error_wrapped(self) -> None:
        with patch("acemusic._http.request", side_effect=httpx.ConnectError("refused")):
            with pytest.raises(VideoGenerationError, match="request failed"):
                _client().submit(b"RIFF", "song.wav", {})


class TestRetryPolicy:
    """The client goes through the shared ``_http.request`` policy: a 5xx is
    retried up to 3 times with backoff (4 attempts total), then surfaces as a
    :class:`VideoGenerationError`."""

    def test_5xx_retried_then_succeeds(self) -> None:
        responses = [_resp(500), _resp(502), _resp(200, {"id": "pj-9"})]
        with patch("httpx.post", side_effect=responses) as post, patch("acemusic._http.time.sleep") as slept:
            job_id = _client().submit(b"RIFF", "song.wav", {})
        assert job_id == "pj-9"
        assert post.call_count == 3
        assert slept.call_count == 2

    def test_5xx_exhausts_retries_then_raises(self) -> None:
        with patch("httpx.post", return_value=_resp(503)) as post, patch("acemusic._http.time.sleep") as slept:
            with pytest.raises(VideoGenerationError, match="503"):
                _client().submit(b"RIFF", "song.wav", {})
        # Initial attempt + MAX_RETRIES retries.
        assert post.call_count == 4
        assert slept.call_count == 3


class TestGetStatus:
    def test_parses_state_progress_and_eta(self) -> None:
        payload = {"status": "rendering", "progress": "42", "eta_seconds": 30, "error": None}
        with patch("acemusic._http.request", return_value=_resp(200, payload)):
            update = _client().get_status("pj-1")
        assert update.state == "rendering"
        assert update.progress == 42
        assert update.eta_seconds == 30.0
        assert update.error is None

    def test_garbage_numbers_degrade_to_none(self) -> None:
        payload = {"status": "queued", "progress": "soon", "eta_seconds": "dunno"}
        with patch("acemusic._http.request", return_value=_resp(200, payload)):
            update = _client().get_status("pj-1")
        assert update.progress is None and update.eta_seconds is None

    def test_failure_carries_provider_error(self) -> None:
        payload = {"status": "failed", "error": "NSFW prompt rejected"}
        with patch("acemusic._http.request", return_value=_resp(200, payload)):
            update = _client().get_status("pj-1")
        assert update.state == "failed"
        assert update.error == "NSFW prompt rejected"


class TestDownload:
    def test_returns_mp4_bytes(self) -> None:
        with patch("acemusic._http.request", return_value=_resp(200, content=FAKE_MP4)) as req:
            data = _client().download("pj-1")
        assert data == FAKE_MP4
        assert req.call_args.args[1] == "https://video.test/jobs/pj-1/result"

    def test_empty_result_raises(self) -> None:
        with patch("acemusic._http.request", return_value=_resp(200, content=b"")):
            with pytest.raises(VideoGenerationError, match="empty"):
                _client().download("pj-1")
