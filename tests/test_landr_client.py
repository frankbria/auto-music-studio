"""Unit tests for LandrClient (US-12.3).

Every HTTP call is mocked (``unittest.mock``), mirroring the Dolby/ElevenLabs
client tests, so these run in CI without network access. They cover the same
mastering workflow contract as the Dolby client: token acquisition/caching, the
two-step upload, job submission (with profile -> LANDR loudness/style mapping),
status polling (success / failure / timeout), download, transient-5xx retry, and
the high-level ``master()`` entrypoint that returns the shared
:class:`MasteringOutput`.

LANDR's B2B REST API is partnership-gated, so the endpoint shapes here encode the
contract the client assumes (documented in :mod:`acemusic.landr_client`); the
tests pin that contract rather than the live service.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from acemusic.landr_client import (
    LandrClient,
    LandrError,
    landr_master_params,
)
from acemusic.mastering_protocol import MasteringOutput, MasteringService

FAKE_AUDIO = b"RIFF" + b"\x00" * 100


def _resp(
    status_code: int = 200,
    json_data: dict | None = None,
    content: bytes = b"",
    headers: dict | None = None,
) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.content = content
    resp.json.return_value = json_data if json_data is not None else {}
    resp.text = str(json_data or {})
    resp.raise_for_status.return_value = None
    resp.is_redirect = status_code in (301, 302, 303, 307, 308)
    resp.headers = headers if headers is not None else {}
    return resp


def _error_resp(status_code: int, json_data: dict | None = None) -> MagicMock:
    resp = _resp(status_code, json_data)
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(str(status_code), request=MagicMock(), response=resp)
    return resp


def _client() -> LandrClient:
    return LandrClient(api_key="landr-key", api_secret="landr-secret")


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class TestAuth:
    def test_get_token_returns_access_token(self) -> None:
        client = _client()
        with patch("acemusic.landr_client.httpx.post", return_value=_resp(json_data={"access_token": "tok-1"})):
            assert client._get_token() == "tok-1"

    def test_token_cached_until_near_expiry(self) -> None:
        client = _client()
        with patch("acemusic.landr_client.httpx.post", return_value=_resp(json_data={"access_token": "tok-1"})) as m:
            client._get_token()
            client._get_token()
        assert m.call_count == 1

    def test_auth_failure_raises_landr_error(self) -> None:
        client = _client()
        with patch("acemusic.landr_client.httpx.post", return_value=_error_resp(401)):
            with pytest.raises(LandrError, match="authentication failed"):
                client._get_token()

    def test_missing_access_token_raises(self) -> None:
        client = _client()
        with patch("acemusic.landr_client.httpx.post", return_value=_resp(json_data={})):
            with pytest.raises(LandrError, match="no access_token"):
                client._get_token()

    def test_transport_error_raises_landr_error(self) -> None:
        client = _client()
        with patch("acemusic.landr_client.httpx.post", side_effect=httpx.ConnectError("nope")):
            with pytest.raises(LandrError, match="authentication failed"):
                client._get_token()


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


class TestUpload:
    def test_upload_returns_audio_id(self) -> None:
        client = _client()
        client._token, client._token_expiry = "tok", 1e12
        post_resp = _resp(json_data={"upload_url": "https://put.example/u", "audio_id": "aud-1"})
        put_resp = _resp(status_code=200)
        with (
            patch("acemusic.landr_client.httpx.post", return_value=post_resp),
            patch("acemusic.landr_client.httpx.put", return_value=put_resp),
        ):
            assert client.upload(FAKE_AUDIO, "clip-1.wav") == "aud-1"

    def test_upload_presigned_put_sends_no_bearer(self) -> None:
        client = _client()
        client._token, client._token_expiry = "tok", 1e12
        post_resp = _resp(json_data={"upload_url": "https://put.example/u", "audio_id": "aud-1"})
        put_resp = _resp(status_code=200)
        with (
            patch("acemusic.landr_client.httpx.post", return_value=post_resp),
            patch("acemusic.landr_client.httpx.put", return_value=put_resp) as mock_put,
        ):
            client.upload(FAKE_AUDIO, "clip-1.wav")
        # The presigned URL is already authorized; no bearer token leaks to it.
        assert mock_put.call_args.kwargs["headers"] == {}

    def test_upload_missing_audio_id_raises(self) -> None:
        client = _client()
        client._token, client._token_expiry = "tok", 1e12
        with patch("acemusic.landr_client.httpx.post", return_value=_resp(json_data={"upload_url": "x"})):
            with pytest.raises(LandrError, match="no audio_id"):
                client.upload(FAKE_AUDIO, "clip-1.wav")


# ---------------------------------------------------------------------------
# Submission
# ---------------------------------------------------------------------------


class TestSubmit:
    def test_submit_returns_job_id(self) -> None:
        client = _client()
        client._token, client._token_expiry = "tok", 1e12
        with patch("acemusic.landr_client.httpx.post", return_value=_resp(json_data={"job_id": "lj-1"})):
            assert client.submit("aud-1", "streaming", -14.0, "wav") == "lj-1"

    def test_submit_missing_job_id_raises(self) -> None:
        client = _client()
        client._token, client._token_expiry = "tok", 1e12
        with patch("acemusic.landr_client.httpx.post", return_value=_resp(json_data={})):
            with pytest.raises(LandrError, match="no job_id"):
                client.submit("aud-1", "streaming", -14.0, "wav")


# ---------------------------------------------------------------------------
# Polling
# ---------------------------------------------------------------------------


class TestPolling:
    def test_wait_for_completion_returns_on_success(self) -> None:
        client = _client()
        client._token, client._token_expiry = "tok", 1e12
        responses = [
            _resp(json_data={"status": "processing", "progress": 10}),
            _resp(json_data={"status": "completed", "progress": 100}),
        ]
        with (
            patch("acemusic.landr_client.httpx.get", side_effect=responses),
            patch("acemusic.landr_client.time.sleep") as mock_sleep,
        ):
            result = client.wait_for_completion("lj-1", poll_interval=0.01)
        assert result["status"] == "completed"
        mock_sleep.assert_called()

    def test_wait_for_completion_failure_raises(self) -> None:
        client = _client()
        client._token, client._token_expiry = "tok", 1e12
        with patch("acemusic.landr_client.httpx.get", return_value=_resp(json_data={"status": "failed"})):
            with patch("acemusic.landr_client.time.sleep"):
                with pytest.raises(LandrError, match="failed"):
                    client.wait_for_completion("lj-1", poll_interval=0.01)

    def test_wait_for_completion_timeout_raises(self) -> None:
        client = _client()
        client._token, client._token_expiry = "tok", 1e12
        with patch("acemusic.landr_client.httpx.get", return_value=_resp(json_data={"status": "processing"})):
            with patch("acemusic.landr_client.time.sleep"):
                with pytest.raises(LandrError, match="timed out"):
                    client.wait_for_completion("lj-1", timeout=0.0, poll_interval=0.01)


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


class TestDownload:
    def test_download_returns_bytes(self) -> None:
        client = _client()
        client._token, client._token_expiry = "tok", 1e12
        with patch("acemusic.landr_client.httpx.get", return_value=_resp(content=b"MASTERED")):
            assert client.download("lj-1") == b"MASTERED"

    def test_download_follows_redirect_without_bearer(self) -> None:
        client = _client()
        client._token, client._token_expiry = "tok", 1e12
        redirect = _resp(status_code=302, headers={"location": "https://cdn.example/m.wav"})
        direct = _resp(content=b"MASTERED")
        with patch("acemusic.landr_client.httpx.get", side_effect=[redirect, direct]) as mock_get:
            assert client.download("lj-1") == b"MASTERED"
        # Second (redirect-following) call must carry no bearer token.
        assert mock_get.call_args_list[1].kwargs["headers"] == {}


# ---------------------------------------------------------------------------
# Transient-error retry
# ---------------------------------------------------------------------------


class TestRetry:
    def test_5xx_retried_then_succeeds(self) -> None:
        client = _client()
        client._token, client._token_expiry = "tok", 1e12
        responses = [_resp(status_code=503), _resp(json_data={"job_id": "lj"})]
        with (
            patch("acemusic.landr_client.httpx.post", side_effect=responses) as mock_post,
            patch("acemusic.landr_client.time.sleep"),
        ):
            assert client.submit("aud-1", "streaming", -14.0, "wav") == "lj"
        assert mock_post.call_count == 2


# ---------------------------------------------------------------------------
# Profile -> LANDR params mapping
# ---------------------------------------------------------------------------


class TestLandrParams:
    def test_streaming_maps_to_low_loudness(self) -> None:
        params = landr_master_params("streaming", -14.0, "wav")
        assert params["loudness"] == "low"
        assert params["style"] == "universal"
        assert params["output_format"] == "wav"

    def test_club_maps_to_high_loudness(self) -> None:
        params = landr_master_params("club", -6.0, "wav")
        assert params["loudness"] == "high"

    def test_custom_uses_target_lufs(self) -> None:
        params = landr_master_params("custom", -10.0, "flac")
        assert params["target_lufs"] == -10.0

    def test_unknown_profile_defaults(self) -> None:
        params = landr_master_params("mystery", -14.0, "wav")
        # Unknown profiles fall back to a neutral default rather than raising.
        assert "loudness" in params


# ---------------------------------------------------------------------------
# High-level master() entrypoint (US-12.3 shared interface)
# ---------------------------------------------------------------------------


class TestMasterEntrypoint:
    def test_master_returns_normalized_output(self) -> None:
        client = _client()
        client._token, client._token_expiry = "tok", 1e12
        upload_post = _resp(json_data={"upload_url": "https://put.example/u", "audio_id": "aud-1"})
        put_resp = _resp(status_code=200)
        submit_resp = _resp(json_data={"job_id": "lj-1"})
        # wait_for_completion polls GET /masters/{id}; success on first poll, with metrics.
        status_resp = _resp(
            json_data={
                "status": "completed",
                "progress": 100,
                "result": {"loudness_lufs": -14.2, "eq_bands": [0.1, 0.2]},
            }
        )
        download_resp = _resp(content=b"MASTERED")
        with (
            patch("acemusic.landr_client.httpx.post", side_effect=[upload_post, submit_resp]),
            patch("acemusic.landr_client.httpx.put", return_value=put_resp),
            patch("acemusic.landr_client.httpx.get", side_effect=[status_resp, download_resp]),
            patch("acemusic.landr_client.time.sleep"),
        ):
            out = client.master(FAKE_AUDIO, "clip-1-job-1.wav", "streaming", -14.0, "wav")
        assert isinstance(out, MasteringOutput)
        assert out.audio_bytes == b"MASTERED"
        assert out.service == "landr"
        assert out.metrics["loudness"] == -14.2
        assert isinstance(client, MasteringService)

    def test_master_propagates_landr_error(self) -> None:
        client = _client()
        client._token, client._token_expiry = "tok", 1e12
        with (
            patch("acemusic.landr_client.httpx.post", return_value=_resp(status_code=500)),
            patch("acemusic.landr_client.httpx.put"),
            patch("acemusic.landr_client.time.sleep"),
        ):
            with pytest.raises(LandrError):
                client.master(FAKE_AUDIO, "f.wav", "streaming", -14.0, "wav")

    def test_landr_error_is_mastering_error_subclass(self) -> None:
        from acemusic.mastering_protocol import MasteringError

        assert issubclass(LandrError, MasteringError)
