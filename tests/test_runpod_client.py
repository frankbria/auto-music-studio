"""Unit tests for RunPodClient (US-11.2).

All HTTP is mocked at the module-level ``httpx.get``/``httpx.post`` (the client uses
module-level calls, mirroring AceStepClient) so these run in CI without the network.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from acemusic.runpod_client import (
    RunPodClient,
    RunPodError,
    _extract_audio_urls,
)

ENDPOINT = "ep-123"
API_KEY = "rp-secret"


def _ok(json_data: dict, *, content: bytes = b"") -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = json_data
    resp.text = str(json_data)
    resp.content = content
    resp.is_success = True
    resp.raise_for_status.return_value = None
    return resp


def _err(status_code: int, *, text: str = "error") -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text
    resp.json.return_value = {}
    resp.content = b""
    resp.is_success = False
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(text, request=MagicMock(), response=resp)
    return resp


def _client() -> RunPodClient:
    return RunPodClient(endpoint_id=ENDPOINT, api_key=API_KEY)


class TestConstruction:
    def test_base_url_includes_endpoint_id(self):
        client = _client()
        assert client.base_url == f"https://api.runpod.ai/v2/{ENDPOINT}"

    def test_authorization_header_is_bearer_api_key(self):
        client = _client()
        assert client._headers == {"Authorization": f"Bearer {API_KEY}"}

    def test_trailing_slash_base_url_is_normalised(self):
        client = RunPodClient(endpoint_id=ENDPOINT, api_key=API_KEY, base_url="https://x.test/v2/")
        assert client.base_url == f"https://x.test/v2/{ENDPOINT}"


class TestSubmit:
    def test_returns_job_id(self):
        resp = _ok({"id": "job-1", "status": "IN_QUEUE"})
        with patch("acemusic.runpod_client.httpx.post", return_value=resp):
            assert _client().submit({"prompt": "calm piano"}) == "job-1"

    def test_wraps_params_in_input_envelope(self):
        resp = _ok({"id": "job-1"})
        with patch("acemusic.runpod_client.httpx.post", return_value=resp) as mock_post:
            _client().submit({"prompt": "calm piano", "audio_duration": 30})
        assert mock_post.call_args.kwargs["json"] == {"input": {"prompt": "calm piano", "audio_duration": 30}}

    def test_sends_bearer_header(self):
        resp = _ok({"id": "job-1"})
        with patch("acemusic.runpod_client.httpx.post", return_value=resp) as mock_post:
            _client().submit({"prompt": "x"})
        assert mock_post.call_args.kwargs["headers"]["Authorization"] == f"Bearer {API_KEY}"

    def test_missing_id_raises_runpod_error(self):
        resp = _ok({"status": "IN_QUEUE"})
        with patch("acemusic.runpod_client.httpx.post", return_value=resp):
            with pytest.raises(RunPodError, match="No job id"):
                _client().submit({"prompt": "x"})

    def test_submit_task_alias_wraps_kwargs(self):
        resp = _ok({"id": "job-7"})
        with patch("acemusic.runpod_client.httpx.post", return_value=resp) as mock_post:
            assert _client().submit_task(prompt="x", format="wav") == "job-7"
        assert mock_post.call_args.kwargs["json"] == {"input": {"prompt": "x", "format": "wav"}}

    def test_connection_timeout_raises_connection_error_with_flag(self):
        with patch("acemusic.runpod_client.httpx.post", side_effect=httpx.ReadTimeout("slow")):
            with pytest.raises(RunPodError) as exc:
                _client().submit({"prompt": "x"})
        assert exc.value.is_timeout is True

    def test_connection_refused_is_not_timeout(self):
        with patch("acemusic.runpod_client.httpx.post", side_effect=httpx.ConnectError("refused")):
            with pytest.raises(RunPodError) as exc:
                _client().submit({"prompt": "x"})
        assert exc.value.is_timeout is False


class TestQueryResult:
    def test_completed_returns_audio_urls_from_list_output(self):
        resp = _ok({"status": "COMPLETED", "output": ["http://x/a.wav", "http://x/b.wav"]})
        with patch("acemusic.runpod_client.httpx.get", return_value=resp):
            result = _client().query_result("job-1")
        assert result == {
            "status": "completed",
            "audio_urls": ["http://x/a.wav", "http://x/b.wav"],
            "error": None,
        }

    def test_completed_extracts_urls_from_dict_output(self):
        resp = _ok({"status": "COMPLETED", "output": {"audio_urls": ["http://x/a.wav"]}})
        with patch("acemusic.runpod_client.httpx.get", return_value=resp):
            result = _client().query_result("job-1")
        assert result["audio_urls"] == ["http://x/a.wav"]

    def test_completed_extracts_urls_from_object_list(self):
        resp = _ok({"status": "COMPLETED", "output": [{"url": "http://x/a.wav"}, {"file": "http://x/b.wav"}]})
        with patch("acemusic.runpod_client.httpx.get", return_value=resp):
            result = _client().query_result("job-1")
        assert result["audio_urls"] == ["http://x/a.wav", "http://x/b.wav"]

    @pytest.mark.parametrize("raw_status", ["IN_QUEUE", "IN_PROGRESS"])
    def test_in_flight_states_normalise_to_pending(self, raw_status):
        resp = _ok({"status": raw_status})
        with patch("acemusic.runpod_client.httpx.get", return_value=resp):
            result = _client().query_result("job-1")
        assert result == {"status": "pending", "audio_urls": [], "error": None}

    def test_failed_surfaces_error_message(self):
        resp = _ok({"status": "FAILED", "error": "worker OOM"})
        with patch("acemusic.runpod_client.httpx.get", return_value=resp):
            result = _client().query_result("job-1")
        assert result["status"] == "failed"
        assert result["error"] == "worker OOM"

    def test_4xx_raises_immediately_without_retry(self):
        resp = _err(404)
        with patch("acemusic.runpod_client.httpx.get", return_value=resp) as mock_get:
            with patch("acemusic._http.time.sleep") as mock_sleep:
                with pytest.raises(RunPodError):
                    _client().query_result("job-1")
        assert mock_get.call_count == 1
        mock_sleep.assert_not_called()

    def test_5xx_retries_three_times_then_raises(self):
        resp = _err(503)
        with patch("acemusic.runpod_client.httpx.get", return_value=resp) as mock_get:
            with patch("acemusic._http.time.sleep") as mock_sleep:
                with pytest.raises(RunPodError):
                    _client().query_result("job-1")
        # Initial attempt + 3 retries == 4 calls; 3 backoff sleeps between them.
        assert mock_get.call_count == 4
        assert mock_sleep.call_count == 3

    def test_5xx_then_success_recovers(self):
        responses = [_err(503), _ok({"status": "COMPLETED", "output": ["http://x/a.wav"]})]
        with patch("acemusic.runpod_client.httpx.get", side_effect=responses):
            with patch("acemusic._http.time.sleep"):
                result = _client().query_result("job-1")
        assert result["status"] == "completed"

    def test_exponential_backoff_delays(self):
        resp = _err(500)
        with patch("acemusic.runpod_client.httpx.get", return_value=resp):
            with patch("acemusic._http.random.uniform", return_value=0.0):
                with patch("acemusic._http.time.sleep") as mock_sleep:
                    with pytest.raises(RunPodError):
                        _client().query_result("job-1")
        assert [call.args[0] for call in mock_sleep.call_args_list] == [1.0, 2.0, 4.0]

    def test_connection_error_raises_connection_error(self):
        with patch("acemusic.runpod_client.httpx.get", side_effect=httpx.ReadTimeout("slow")):
            with pytest.raises(RunPodError) as exc:
                _client().query_result("job-1")
        assert exc.value.is_timeout is True


class TestDownloadAudio:
    def test_returns_bytes(self):
        resp = _ok({}, content=b"WAV-BYTES")
        with patch("acemusic.runpod_client.httpx.get", return_value=resp):
            assert _client().download_audio("http://x/a.wav") == b"WAV-BYTES"

    def test_http_error_raises_runpod_error(self):
        resp = _err(403)
        with patch("acemusic.runpod_client.httpx.get", return_value=resp):
            with pytest.raises(RunPodError):
                _client().download_audio("http://x/a.wav")

    def test_connection_error_raises_connection_error(self):
        with patch("acemusic.runpod_client.httpx.get", side_effect=httpx.ConnectError("refused")):
            with pytest.raises(RunPodError) as exc:
                _client().download_audio("http://x/a.wav")
        assert exc.value.is_timeout is False

    def test_does_not_send_auth_header_to_external_url(self):
        # The audio URL is pre-authorized (presigned/public); the bearer token must
        # not leak to an external host.
        resp = _ok({}, content=b"WAV")
        with patch("acemusic.runpod_client.httpx.get", return_value=resp) as mock_get:
            _client().download_audio("https://cdn.example/a.wav")
        assert mock_get.call_args.kwargs["headers"] == {}

    def test_5xx_is_retried_then_recovers(self):
        responses = [_err(503), _ok({}, content=b"WAV")]
        with patch("acemusic.runpod_client.httpx.get", side_effect=responses) as mock_get:
            with patch("acemusic._http.time.sleep"):
                assert _client().download_audio("http://x/a.wav") == b"WAV"
        assert mock_get.call_count == 2


class TestOutputExtraction:
    def test_completed_with_no_output_yields_empty(self):
        resp = _ok({"status": "COMPLETED"})
        with patch("acemusic.runpod_client.httpx.get", return_value=resp):
            assert _client().query_result("job-1")["audio_urls"] == []

    def test_unknown_status_treated_as_pending(self):
        resp = _ok({"status": "SOMETHING_NEW"})
        with patch("acemusic.runpod_client.httpx.get", return_value=resp):
            assert _client().query_result("job-1")["status"] == "pending"

    def test_cancelled_status_is_failed(self):
        resp = _ok({"status": "CANCELLED", "error": "user cancelled"})
        with patch("acemusic.runpod_client.httpx.get", return_value=resp):
            assert _client().query_result("job-1")["status"] == "failed"


class TestLocalhostFiltering:
    """US-11.x: worker-local URLs must never escape to the platform."""

    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost:8001/v1/audio?path=a.wav",
            "http://127.0.0.1:8001/v1/audio?path=a.wav",
            "http://[::1]:8001/v1/audio?path=a.wav",
        ],
    )
    def test_localhost_urls_are_dropped(self, url):
        assert _extract_audio_urls({"audio_urls": [url]}) == []

    def test_presigned_s3_url_passes_through_with_query_intact(self):
        url = "https://bucket.s3.example.test/runpod/job/0.wav?sig=abc&expires=3600"
        assert _extract_audio_urls({"audio_urls": [url]}) == [url]

    def test_mixed_list_keeps_only_reachable_urls(self):
        urls = [
            "http://localhost:8001/v1/audio?path=a.wav",
            "https://bucket.s3.example.test/b.wav?sig=x",
        ]
        assert _extract_audio_urls({"audio_urls": urls}) == ["https://bucket.s3.example.test/b.wav?sig=x"]

    def test_filtering_applies_to_dict_list_shape(self):
        # The dict/file shape routes through _urls_from_list, not the direct path.
        output = {"clips": [{"file": "http://127.0.0.1:8001/v1/audio?path=a.wav"}]}
        assert _extract_audio_urls(output) == []

    def test_completed_job_drops_localhost(self):
        resp = _ok({"status": "COMPLETED", "output": {"audio_urls": ["http://localhost:8001/x.wav"]}})
        with patch("acemusic.runpod_client.httpx.get", return_value=resp):
            assert _client().query_result("job-1")["audio_urls"] == []


class TestHealth:
    def test_2xx_is_healthy(self):
        resp = _ok({})
        with patch("acemusic.runpod_client.httpx.get", return_value=resp):
            assert _client().health() is True

    def test_non_2xx_is_unhealthy(self):
        resp = MagicMock(spec=httpx.Response)
        resp.is_success = False
        with patch("acemusic.runpod_client.httpx.get", return_value=resp):
            assert _client().health() is False

    def test_connection_error_is_unhealthy(self):
        with patch("acemusic.runpod_client.httpx.get", side_effect=httpx.ConnectError("refused")):
            assert _client().health() is False
