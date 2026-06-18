"""Unit tests for BakuageClient (US-12.3).

Every HTTP call is mocked (``unittest.mock``), mirroring the Dolby/LANDR client
tests, so these run in CI without network access. Bakuage exposes a simpler open
REST API than Dolby/LANDR (API-key auth, no OAuth token dance), so the contract
tests are correspondingly focused: API-key header injection, the single
create-mastering call that uploads the audio, status polling (success / failure /
timeout), download with redirect handling, transient-5xx retry, and the
high-level ``master()`` entrypoint returning the shared :class:`MasteringOutput`.

Bakuage's REST API is documented publicly (spec §41.2.3: base
``https://api.bakuage.com:443``, bearer-token auth); the tests pin the workflow
contract the client implements.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from acemusic.bakuage_client import (
    BakuageClient,
    BakuageError,
    bakuage_master_params,
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


def _client() -> BakuageClient:
    return BakuageClient(api_key="bakuage-key")


# ---------------------------------------------------------------------------
# Auth (API-key-only — no token dance)
# ---------------------------------------------------------------------------


class TestAuth:
    def test_api_key_injected_as_bearer_header(self) -> None:
        client = _client()
        # Every call carries the bearer header; check via a create() call.
        with patch("acemusic.bakuage_client.httpx.post", return_value=_resp(json_data={"id": "bk-1"})) as mock_post:
            client.create_mastering(FAKE_AUDIO, "clip.wav", "streaming", -14.0, "wav")
        headers = mock_post.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer bakuage-key"


# ---------------------------------------------------------------------------
# Create mastering (single upload+submit call)
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_returns_job_id(self) -> None:
        client = _client()
        with patch("acemusic.bakuage_client.httpx.post", return_value=_resp(json_data={"id": "bk-1"})):
            assert client.create_mastering(FAKE_AUDIO, "clip.wav", "streaming", -14.0, "wav") == "bk-1"

    def test_create_missing_id_raises(self) -> None:
        client = _client()
        with patch("acemusic.bakuage_client.httpx.post", return_value=_resp(json_data={})):
            with pytest.raises(BakuageError, match="no id"):
                client.create_mastering(FAKE_AUDIO, "clip.wav", "streaming", -14.0, "wav")

    def test_create_auth_failure_raises(self) -> None:
        client = _client()
        with patch("acemusic.bakuage_client.httpx.post", return_value=_error_resp(401)):
            with pytest.raises(BakuageError):
                client.create_mastering(FAKE_AUDIO, "clip.wav", "streaming", -14.0, "wav")


# ---------------------------------------------------------------------------
# Polling
# ---------------------------------------------------------------------------


class TestPolling:
    def test_wait_for_completion_returns_on_success(self) -> None:
        client = _client()
        responses = [
            _resp(json_data={"status": "processing", "progress": 10}),
            _resp(json_data={"status": "completed", "progress": 100, "result": {"loudness_lufs": -9.0}}),
        ]
        with (
            patch("acemusic.bakuage_client.httpx.get", side_effect=responses),
            patch("acemusic.bakuage_client.time.sleep") as mock_sleep,
        ):
            result = client.wait_for_completion("bk-1", poll_interval=0.01)
        assert result["status"] == "completed"
        mock_sleep.assert_called()

    def test_wait_for_completion_failure_raises(self) -> None:
        client = _client()
        with patch("acemusic.bakuage_client.httpx.get", return_value=_resp(json_data={"status": "failed"})):
            with patch("acemusic.bakuage_client.time.sleep"):
                with pytest.raises(BakuageError, match="failed"):
                    client.wait_for_completion("bk-1", poll_interval=0.01)

    def test_wait_for_completion_timeout_raises(self) -> None:
        client = _client()
        with patch("acemusic.bakuage_client.httpx.get", return_value=_resp(json_data={"status": "processing"})):
            with patch("acemusic.bakuage_client.time.sleep"):
                with pytest.raises(BakuageError, match="timed out"):
                    client.wait_for_completion("bk-1", timeout=0.0, poll_interval=0.01)


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


class TestDownload:
    def test_download_returns_bytes(self) -> None:
        client = _client()
        with patch("acemusic.bakuage_client.httpx.get", return_value=_resp(content=b"MASTERED")):
            assert client.download("bk-1") == b"MASTERED"

    def test_download_follows_redirect_without_bearer(self) -> None:
        client = _client()
        redirect = _resp(status_code=302, headers={"location": "https://cdn.example/m.wav"})
        direct = _resp(content=b"MASTERED")
        with patch("acemusic.bakuage_client.httpx.get", side_effect=[redirect, direct]) as mock_get:
            assert client.download("bk-1") == b"MASTERED"
        assert mock_get.call_args_list[1].kwargs["headers"] == {}


# ---------------------------------------------------------------------------
# Transient-error retry
# ---------------------------------------------------------------------------


class TestRetry:
    def test_5xx_retried_then_succeeds(self) -> None:
        client = _client()
        responses = [_resp(status_code=503), _resp(json_data={"id": "bk"})]
        with (
            patch("acemusic.bakuage_client.httpx.post", side_effect=responses) as mock_post,
            patch("acemusic.bakuage_client.time.sleep"),
        ):
            assert client.create_mastering(FAKE_AUDIO, "clip.wav", "streaming", -14.0, "wav") == "bk"
        assert mock_post.call_count == 2


# ---------------------------------------------------------------------------
# Profile -> Bakuage params mapping
# ---------------------------------------------------------------------------


class TestBakuageParams:
    def test_streaming_maps_to_default_level(self) -> None:
        params = bakuage_master_params("streaming", -14.0, "wav")
        assert params["output_format"] == "wav"
        assert "mastering_level" in params

    def test_custom_uses_target_lufs(self) -> None:
        params = bakuage_master_params("custom", -10.0, "flac")
        assert params["target_lufs"] == -10.0


# ---------------------------------------------------------------------------
# High-level master() entrypoint (US-12.3 shared interface)
# ---------------------------------------------------------------------------


class TestMasterEntrypoint:
    def test_master_returns_normalized_output(self) -> None:
        client = _client()
        create_resp = _resp(json_data={"id": "bk-1"})
        status_resp = _resp(
            json_data={
                "status": "completed",
                "progress": 100,
                "result": {"loudness_lufs": -9.5},
            }
        )
        download_resp = _resp(content=b"MASTERED")
        with (
            patch("acemusic.bakuage_client.httpx.post", return_value=create_resp),
            patch("acemusic.bakuage_client.httpx.get", side_effect=[status_resp, download_resp]),
            patch("acemusic.bakuage_client.time.sleep"),
        ):
            out = client.master(FAKE_AUDIO, "clip-1-job-1.wav", "streaming", -14.0, "wav")
        assert isinstance(out, MasteringOutput)
        assert out.audio_bytes == b"MASTERED"
        assert out.service == "bakuage"
        assert out.metrics["loudness"] == -9.5
        assert isinstance(client, MasteringService)

    def test_master_propagates_bakuage_error(self) -> None:
        client = _client()
        with (
            patch("acemusic.bakuage_client.httpx.post", return_value=_resp(status_code=500)),
            patch("acemusic.bakuage_client.time.sleep"),
        ):
            with pytest.raises(BakuageError):
                client.master(FAKE_AUDIO, "f.wav", "streaming", -14.0, "wav")

    def test_bakuage_error_is_mastering_error_subclass(self) -> None:
        from acemusic.mastering_protocol import MasteringError

        assert issubclass(BakuageError, MasteringError)
