"""Unit tests for DolbyClient (US-12.2).

Every HTTP call is mocked (``unittest.mock``), mirroring the ElevenLabs client
tests, so these run in CI without network access. They cover the full mastering
workflow contract: token acquisition/caching/refresh, the two-step upload, preview
submission (with output caps), status polling (success / failure / timeout),
metrics parsing, and download.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from acemusic.dolby_client import (
    MAX_PREVIEW_OUTPUTS,
    DolbyClient,
    DolbyError,
    master_output_config,
)

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
    # spec'd MagicMocks auto-mock is_redirect/headers as truthy; pin them so the
    # download() redirect branch only fires when a test explicitly opts in.
    resp.is_redirect = status_code in (301, 302, 303, 307, 308)
    resp.headers = headers if headers is not None else {}
    return resp


def _error_resp(status_code: int, json_data: dict | None = None) -> MagicMock:
    resp = _resp(status_code, json_data)
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(str(status_code), request=MagicMock(), response=resp)
    return resp


def _client() -> DolbyClient:
    return DolbyClient(api_key="app-key", api_secret="app-secret")


# ---------------------------------------------------------------------------
# Auth + token caching
# ---------------------------------------------------------------------------


class TestAuth:
    def test_get_token_returns_access_token(self) -> None:
        client = _client()
        with patch("acemusic.dolby_client.httpx.post", return_value=_resp(json_data={"access_token": "tok-1"})):
            assert client._get_token() == "tok-1"

    def test_token_is_cached_across_calls(self) -> None:
        client = _client()
        resp = _resp(json_data={"access_token": "tok-1", "expires_in": 1800})
        with patch("acemusic.dolby_client.httpx.post", return_value=resp) as mock_post:
            client._get_token()
            client._get_token()
        mock_post.assert_called_once()

    def test_token_refreshes_when_near_expiry(self) -> None:
        client = _client()
        # A token already past its (buffered) expiry must be re-fetched.
        resp = _resp(json_data={"access_token": "tok-2", "expires_in": 1})
        with patch("acemusic.dolby_client.httpx.post", return_value=resp) as mock_post:
            client._get_token()
            client._get_token()
        assert mock_post.call_count == 2

    def test_uses_basic_auth_and_client_credentials(self) -> None:
        client = _client()
        with patch(
            "acemusic.dolby_client.httpx.post", return_value=_resp(json_data={"access_token": "t"})
        ) as mock_post:
            client._get_token()
        kwargs = mock_post.call_args.kwargs
        assert kwargs["auth"] == ("app-key", "app-secret")
        assert kwargs["data"]["grant_type"] == "client_credentials"

    def test_missing_access_token_raises(self) -> None:
        client = _client()
        with patch("acemusic.dolby_client.httpx.post", return_value=_resp(json_data={"nope": 1})):
            with pytest.raises(DolbyError, match="no access_token"):
                client._get_token()

    def test_http_error_raises_dolby_error(self) -> None:
        client = _client()
        with patch("acemusic.dolby_client.httpx.post", return_value=_error_resp(401)):
            with pytest.raises(DolbyError, match="authentication failed: 401"):
                client._get_token()


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


class TestUpload:
    def test_upload_two_step_returns_dlb_url(self) -> None:
        client = _client()
        client._token, client._token_expiry = "tok", 1e12
        post_resp = _resp(json_data={"url": "https://presigned.example/put"})
        put_resp = _resp(200)
        with (
            patch("acemusic.dolby_client.httpx.post", return_value=post_resp) as mock_post,
            patch("acemusic.dolby_client.httpx.put", return_value=put_resp) as mock_put,
        ):
            result = client.upload(FAKE_AUDIO, "clip.wav")
        assert result == "dlb://clip.wav"
        # Step 1 asks for a presigned URL for the dlb handle.
        assert mock_post.call_args.kwargs["json"] == {"url": "dlb://clip.wav"}
        # Step 2 PUTs the bytes to the presigned URL with no bearer header leaked.
        assert mock_put.call_args.args[0] == "https://presigned.example/put"
        assert mock_put.call_args.kwargs["headers"] == {}
        assert mock_put.call_args.kwargs["content"] == FAKE_AUDIO

    def test_upload_missing_presigned_url_raises(self) -> None:
        client = _client()
        client._token, client._token_expiry = "tok", 1e12
        with patch("acemusic.dolby_client.httpx.post", return_value=_resp(json_data={})):
            with pytest.raises(DolbyError, match="no presigned url"):
                client.upload(FAKE_AUDIO, "clip.wav")

    def test_upload_put_failure_raises(self) -> None:
        client = _client()
        client._token, client._token_expiry = "tok", 1e12
        post_resp = _resp(json_data={"url": "https://presigned.example/put"})
        with (
            patch("acemusic.dolby_client.httpx.post", return_value=post_resp),
            patch("acemusic.dolby_client.httpx.put", return_value=_error_resp(403)),
        ):
            with pytest.raises(DolbyError, match="upload failed: 403"):
                client.upload(FAKE_AUDIO, "clip.wav")


# ---------------------------------------------------------------------------
# Submit preview
# ---------------------------------------------------------------------------


class TestSubmitPreview:
    def test_submit_returns_job_id(self) -> None:
        client = _client()
        client._token, client._token_expiry = "tok", 1e12
        outputs = [master_output_config("streaming", -14.0, "dlb://out.wav")]
        with patch("acemusic.dolby_client.httpx.post", return_value=_resp(json_data={"job_id": "job-42"})) as mock_post:
            job_id = client.submit_preview("dlb://in.wav", outputs)
        assert job_id == "job-42"
        body = mock_post.call_args.kwargs["json"]
        assert body["inputs"] == [{"source": "dlb://in.wav"}]
        assert body["outputs"] == outputs

    def test_empty_outputs_raises_before_network(self) -> None:
        client = _client()
        with patch("acemusic.dolby_client.httpx.post") as mock_post:
            with pytest.raises(DolbyError, match="at least one output"):
                client.submit_preview("dlb://in.wav", [])
        mock_post.assert_not_called()

    def test_too_many_outputs_raises(self) -> None:
        client = _client()
        outputs = [master_output_config("streaming", -14.0, f"dlb://o{i}.wav") for i in range(MAX_PREVIEW_OUTPUTS + 1)]
        with pytest.raises(DolbyError, match="at most 5 output"):
            client.submit_preview("dlb://in.wav", outputs)

    def test_missing_job_id_raises(self) -> None:
        client = _client()
        client._token, client._token_expiry = "tok", 1e12
        outputs = [master_output_config("club", -6.0, "dlb://o.wav")]
        with patch("acemusic.dolby_client.httpx.post", return_value=_resp(json_data={})):
            with pytest.raises(DolbyError, match="no job_id"):
                client.submit_preview("dlb://in.wav", outputs)

    def test_max_outputs_accepted(self) -> None:
        client = _client()
        client._token, client._token_expiry = "tok", 1e12
        outputs = [master_output_config("streaming", -14.0, f"dlb://o{i}.wav") for i in range(MAX_PREVIEW_OUTPUTS)]
        with patch("acemusic.dolby_client.httpx.post", return_value=_resp(json_data={"job_id": "j"})):
            assert client.submit_preview("dlb://in.wav", outputs) == "j"


# ---------------------------------------------------------------------------
# Status polling
# ---------------------------------------------------------------------------


class TestStatusPolling:
    def test_get_status_normalises_fields(self) -> None:
        client = _client()
        client._token, client._token_expiry = "tok", 1e12
        with patch(
            "acemusic.dolby_client.httpx.get", return_value=_resp(json_data={"status": "Running", "progress": 50})
        ):
            status = client.get_status("job-1")
        assert status["status"] == "running"
        assert status["progress"] == 50.0

    def test_wait_for_completion_returns_on_success(self) -> None:
        client = _client()
        client._token, client._token_expiry = "tok", 1e12
        responses = [
            _resp(json_data={"status": "Running", "progress": 10}),
            _resp(json_data={"status": "Success", "progress": 100}),
        ]
        with (
            patch("acemusic.dolby_client.httpx.get", side_effect=responses),
            patch("acemusic.dolby_client.time.sleep") as mock_sleep,
        ):
            result = client.wait_for_completion("job-1", poll_interval=0.01)
        assert result["status"] == "success"
        mock_sleep.assert_called()  # it polled at least once before success

    def test_wait_for_completion_raises_on_failure(self) -> None:
        client = _client()
        client._token, client._token_expiry = "tok", 1e12
        resp = _resp(json_data={"status": "Failed", "error": "bad input"})
        with patch("acemusic.dolby_client.httpx.get", return_value=resp):
            with pytest.raises(DolbyError, match="failed: bad input"):
                client.wait_for_completion("job-1", poll_interval=0.01)

    def test_wait_for_completion_times_out(self) -> None:
        client = _client()
        client._token, client._token_expiry = "tok", 1e12
        resp = _resp(json_data={"status": "Running", "progress": 5})
        # A zero timeout makes the deadline elapse on the first non-terminal poll.
        with (
            patch("acemusic.dolby_client.httpx.get", return_value=resp),
            patch("acemusic.dolby_client.time.sleep"),
        ):
            with pytest.raises(DolbyError, match="timed out"):
                client.wait_for_completion("job-1", timeout=0.0, poll_interval=0.01)


# ---------------------------------------------------------------------------
# Results / metrics + download
# ---------------------------------------------------------------------------


_SUCCESS_RESULT = {
    "status": "Success",
    "result": {
        "audio": {
            "loudness": {"measured": -14.1, "integrated": -20.0},
            "eq": {"bands": list(range(16))},
            "stereo": {"width": 0.8, "balance": -0.1},
        },
        "outputs": [
            {"destination": "dlb://out-1.wav", "preview": "dlb://preview-1.wav"},
        ],
    },
}


class TestResults:
    def test_get_results_parses_metrics_and_outputs(self) -> None:
        client = _client()
        client._token, client._token_expiry = "tok", 1e12
        with patch("acemusic.dolby_client.httpx.get", return_value=_resp(json_data=_SUCCESS_RESULT)):
            results = client.get_results("job-1")
        metrics = results["metrics"]
        assert metrics["loudness"] == -14.1  # measured preferred over integrated
        assert metrics["eq_bands"] == [float(i) for i in range(16)]
        assert metrics["stereo"] == {"width": 0.8, "balance": -0.1}
        assert results["outputs"] == [{"destination": "dlb://out-1.wav", "preview": "dlb://preview-1.wav"}]

    def test_get_results_when_not_complete_raises(self) -> None:
        client = _client()
        client._token, client._token_expiry = "tok", 1e12
        with patch("acemusic.dolby_client.httpx.get", return_value=_resp(json_data={"status": "Running"})):
            with pytest.raises(DolbyError, match="not complete"):
                client.get_results("job-1")

    def test_get_results_tolerates_missing_metrics(self) -> None:
        client = _client()
        client._token, client._token_expiry = "tok", 1e12
        payload = {"status": "Success", "result": {"outputs": [{"preview": "dlb://p.wav"}]}}
        with patch("acemusic.dolby_client.httpx.get", return_value=_resp(json_data=payload)):
            results = client.get_results("job-1")
        assert results["metrics"]["loudness"] is None
        assert results["metrics"]["eq_bands"] == []
        # Only a preview handle was provided; destination degrades to None.
        assert results["outputs"] == [{"destination": None, "preview": "dlb://p.wav"}]


class TestDownload:
    def test_download_returns_bytes(self) -> None:
        client = _client()
        client._token, client._token_expiry = "tok", 1e12
        with patch("acemusic.dolby_client.httpx.get", return_value=_resp(content=FAKE_AUDIO)) as mock_get:
            data = client.download("dlb://preview-1.wav")
        assert data == FAKE_AUDIO
        assert mock_get.call_args.kwargs["params"] == {"url": "dlb://preview-1.wav"}

    def test_download_http_error_raises(self) -> None:
        client = _client()
        client._token, client._token_expiry = "tok", 1e12
        with patch("acemusic.dolby_client.httpx.get", return_value=_error_resp(404)):
            with pytest.raises(DolbyError, match="download failed: 404"):
                client.download("dlb://missing.wav")

    def test_download_follows_redirect_without_bearer_token(self) -> None:
        client = _client()
        client._token, client._token_expiry = "tok", 1e12
        redirect = _resp(302, headers={"location": "https://cdn.example/blob"})
        final = _resp(content=FAKE_AUDIO)
        with patch("acemusic.dolby_client.httpx.get", side_effect=[redirect, final]) as mock_get:
            data = client.download("dlb://preview-1.wav")
        assert data == FAKE_AUDIO
        # The first call is auth-gated; the redirect target gets no bearer token.
        first, second = mock_get.call_args_list
        assert "Authorization" in first.kwargs["headers"]
        assert second.args[0] == "https://cdn.example/blob"
        assert second.kwargs["headers"] == {}


# ---------------------------------------------------------------------------
# Transient-error retry
# ---------------------------------------------------------------------------


class TestRetry:
    def test_5xx_retried_then_succeeds(self) -> None:
        client = _client()
        client._token, client._token_expiry = "tok", 1e12
        responses = [_resp(status_code=503), _resp(json_data={"job_id": "j"})]
        outputs = [master_output_config("streaming", -14.0, "dlb://o.wav")]
        with (
            patch("acemusic.dolby_client.httpx.post", side_effect=responses) as mock_post,
            patch("acemusic.dolby_client.time.sleep"),
        ):
            assert client.submit_preview("dlb://in.wav", outputs) == "j"
        assert mock_post.call_count == 2


class TestOutputConfig:
    def test_master_output_config_shape(self) -> None:
        cfg = master_output_config("vinyl", -18.0, "dlb://out.wav")
        assert cfg["destination"] == "dlb://out.wav"
        assert cfg["master"]["loudness"]["target_level"] == -18.0
        assert cfg["master"]["content"]["type"] == "music"
