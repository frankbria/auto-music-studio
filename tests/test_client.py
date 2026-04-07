"""Unit tests for AceStepClient — actual ACE-Step 1.5 API contract."""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from acemusic.client import AceStepClient, AceStepError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(status_code: int, json_data: dict | None = None, content: bytes = b"") -> MagicMock:
    """Build a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = str(json_data)
    resp.content = content
    resp.raise_for_status.return_value = None
    return resp


def _make_error_response(status_code: int, text: str = "error") -> MagicMock:
    """Build a mock httpx.Response that raises HTTPStatusError on raise_for_status."""
    resp = _make_response(status_code)
    resp.text = text
    resp.raise_for_status.side_effect = httpx.HTTPStatusError("err", request=MagicMock(), response=resp)
    return resp


def _wrapped(data: dict | list) -> dict:
    """Wrap a payload in the ACE-Step API response envelope."""
    return {"data": data, "code": 200, "error": None, "timestamp": 1700000000000}


# ---------------------------------------------------------------------------
# submit_task
# ---------------------------------------------------------------------------


class TestSubmitTask:
    """Tests for AceStepClient.submit_task() against the real ACE-Step envelope."""

    def test_returns_task_id_from_wrapped_response(self):
        """Unwraps data envelope and returns task_id."""
        resp = _make_response(200, _wrapped({"task_id": "abc-123", "status": "queued"}))
        client = AceStepClient("http://localhost:8001")
        with patch("acemusic.client.httpx.post", return_value=resp):
            assert client.submit_task("upbeat pop") == "abc-123"

    def test_accepts_id_field_as_fallback(self):
        """Falls back to 'id' key if 'task_id' absent inside data envelope."""
        resp = _make_response(200, _wrapped({"id": "xyz-456"}))
        client = AceStepClient("http://localhost:8001")
        with patch("acemusic.client.httpx.post", return_value=resp):
            assert client.submit_task("jazz") == "xyz-456"

    def test_raises_acestep_error_on_missing_task_id(self):
        """Raises AceStepError when neither task_id nor id appears in data."""
        resp = _make_response(200, _wrapped({"status": "queued"}))
        client = AceStepClient("http://localhost:8001")
        with patch("acemusic.client.httpx.post", return_value=resp):
            with pytest.raises(AceStepError, match="No task_id"):
                client.submit_task("ambient")

    def test_raises_acestep_error_on_http_error(self):
        """Raises AceStepError wrapping an HTTP status error."""
        resp = _make_error_response(503)
        client = AceStepClient("http://localhost:8001")
        with patch("acemusic.client.httpx.post", return_value=resp):
            with pytest.raises(AceStepError, match="Submit failed"):
                client.submit_task("folk")

    def test_raises_acestep_error_on_request_error(self):
        """Raises AceStepError when the server is unreachable."""
        client = AceStepClient("http://localhost:8001")
        with patch("acemusic.client.httpx.post", side_effect=httpx.ConnectError("refused")):
            with pytest.raises(AceStepError, match="Submit failed"):
                client.submit_task("rock")

    def test_sends_batch_size_not_num_clips(self):
        """Payload uses 'batch_size' (ACE-Step field name), not 'num_clips'."""
        resp = _make_response(200, _wrapped({"task_id": "t1"}))
        client = AceStepClient("http://localhost:8001")
        with patch("acemusic.client.httpx.post", return_value=resp) as mock_post:
            client.submit_task("pop", num_clips=3)
        payload = mock_post.call_args.kwargs["json"]
        assert payload.get("batch_size") == 3
        assert "num_clips" not in payload

    def test_sends_audio_format_not_format(self):
        """Payload uses 'audio_format' (ACE-Step field name), not 'format'."""
        resp = _make_response(200, _wrapped({"task_id": "t1"}))
        client = AceStepClient("http://localhost:8001")
        with patch("acemusic.client.httpx.post", return_value=resp) as mock_post:
            client.submit_task("pop", format="mp3")
        payload = mock_post.call_args.kwargs["json"]
        assert payload.get("audio_format") == "mp3"
        assert "format" not in payload

    def test_includes_audio_duration_when_provided(self):
        """Includes audio_duration in the POST payload when a value is given."""
        resp = _make_response(200, _wrapped({"task_id": "dur-123"}))
        client = AceStepClient("http://localhost:8001")
        with patch("acemusic.client.httpx.post", return_value=resp) as mock_post:
            client.submit_task("pop", audio_duration=30.0)
        payload = mock_post.call_args.kwargs["json"]
        assert payload["audio_duration"] == 30.0

    def test_omits_audio_duration_when_none(self):
        """Omits audio_duration from the POST payload when None."""
        resp = _make_response(200, _wrapped({"task_id": "no-dur"}))
        client = AceStepClient("http://localhost:8001")
        with patch("acemusic.client.httpx.post", return_value=resp) as mock_post:
            client.submit_task("pop", audio_duration=None)
        payload = mock_post.call_args.kwargs["json"]
        assert "audio_duration" not in payload


# ---------------------------------------------------------------------------
# query_result
# ---------------------------------------------------------------------------


def _query_response(status_int: int, clips: list[dict] | None = None) -> dict:
    """Build a wrapped /query_result response with integer status and result JSON string."""
    result_str = json.dumps(clips or [])
    return _wrapped([{"task_id": "t1", "status": status_int, "result": result_str}])


class TestQueryResult:
    """Tests for AceStepClient.query_result() — POST-based, integer status, wrapped response."""

    def test_uses_post_not_get(self):
        """query_result sends a POST request, not GET."""
        resp = _make_response(200, _query_response(0))
        client = AceStepClient("http://localhost:8001")
        with patch("acemusic.client.httpx.post", return_value=resp) as mock_post:
            client.query_result("t1")
        mock_post.assert_called_once()
        assert "/query_result" in mock_post.call_args.args[0]

    def test_sends_task_id_list(self):
        """Payload contains task_id_list array."""
        resp = _make_response(200, _query_response(0))
        client = AceStepClient("http://localhost:8001")
        with patch("acemusic.client.httpx.post", return_value=resp) as mock_post:
            client.query_result("my-task")
        payload = mock_post.call_args.kwargs["json"]
        assert payload == {"task_id_list": ["my-task"]}

    def test_status_0_maps_to_pending(self):
        """Integer status 0 (queued/running) maps to 'pending'."""
        resp = _make_response(200, _query_response(0))
        client = AceStepClient("http://localhost:8001")
        with patch("acemusic.client.httpx.post", return_value=resp):
            result = client.query_result("t1")
        assert result["status"] == "pending"

    def test_status_1_maps_to_completed(self):
        """Integer status 1 (succeeded) maps to 'completed'."""
        clips = [{"file": "/v1/audio?path=clip1.wav"}, {"file": "/v1/audio?path=clip2.wav"}]
        resp = _make_response(200, _query_response(1, clips))
        client = AceStepClient("http://localhost:8001")
        with patch("acemusic.client.httpx.post", return_value=resp):
            result = client.query_result("t1")
        assert result["status"] == "completed"

    def test_status_2_maps_to_failed(self):
        """Integer status 2 (failed) maps to 'failed'."""
        resp = _make_response(200, _query_response(2))
        client = AceStepClient("http://localhost:8001")
        with patch("acemusic.client.httpx.post", return_value=resp):
            result = client.query_result("t1")
        assert result["status"] == "failed"

    def test_audio_urls_built_from_result_json(self):
        """Parses result JSON string and prepends base_url to relative /v1/audio paths."""
        clips = [{"file": "/v1/audio?path=clip1.wav"}, {"file": "/v1/audio?path=clip2.wav"}]
        resp = _make_response(200, _query_response(1, clips))
        client = AceStepClient("http://localhost:8001")
        with patch("acemusic.client.httpx.post", return_value=resp):
            result = client.query_result("t1")
        assert result["audio_urls"] == [
            "http://localhost:8001/v1/audio?path=clip1.wav",
            "http://localhost:8001/v1/audio?path=clip2.wav",
        ]

    def test_audio_urls_empty_when_pending(self):
        """audio_urls is empty when status is still pending."""
        resp = _make_response(200, _query_response(0))
        client = AceStepClient("http://localhost:8001")
        with patch("acemusic.client.httpx.post", return_value=resp):
            result = client.query_result("t1")
        assert result["audio_urls"] == []

    def test_raises_acestep_error_on_http_error(self):
        """Raises AceStepError on a non-2xx response."""
        resp = _make_error_response(500)
        client = AceStepClient("http://localhost:8001")
        with patch("acemusic.client.httpx.post", return_value=resp):
            with pytest.raises(AceStepError, match="Query failed"):
                client.query_result("t1")

    def test_raises_acestep_error_on_request_error(self):
        """Raises AceStepError when the connection fails."""
        client = AceStepClient("http://localhost:8001")
        with patch("acemusic.client.httpx.post", side_effect=httpx.TimeoutException("timeout")):
            with pytest.raises(AceStepError, match="Query failed"):
                client.query_result("t1")


# ---------------------------------------------------------------------------
# get_stats
# ---------------------------------------------------------------------------


class TestGetStats:
    """Tests for AceStepClient.get_stats() — wrapped response, normalized field names."""

    def test_returns_active_jobs_from_jobs_running(self):
        """Maps data.jobs.running to active_jobs."""
        data = {"jobs": {"total": 10, "running": 3, "queued": 1, "succeeded": 5, "failed": 1}, "avg_job_seconds": 8.5}
        resp = _make_response(200, _wrapped(data))
        client = AceStepClient("http://localhost:8001")
        with patch("acemusic.client.httpx.get", return_value=resp):
            stats = client.get_stats()
        assert stats["active_jobs"] == 3

    def test_returns_avg_job_time_from_avg_job_seconds(self):
        """Maps data.avg_job_seconds to avg_job_time."""
        data = {"jobs": {}, "avg_job_seconds": 12.3}
        resp = _make_response(200, _wrapped(data))
        client = AceStepClient("http://localhost:8001")
        with patch("acemusic.client.httpx.get", return_value=resp):
            stats = client.get_stats()
        assert stats["avg_job_time"] == pytest.approx(12.3)

    def test_returns_empty_models_when_absent_from_stats(self):
        """models key is empty list when /v1/stats has no models field."""
        data = {"jobs": {"running": 0}, "avg_job_seconds": 5.0}
        resp = _make_response(200, _wrapped(data))
        client = AceStepClient("http://localhost:8001")
        with patch("acemusic.client.httpx.get", return_value=resp):
            stats = client.get_stats()
        assert stats["models"] == []


# ---------------------------------------------------------------------------
# download_audio (unchanged contract)
# ---------------------------------------------------------------------------


class TestDownloadAudio:
    """Tests for AceStepClient.download_audio()."""

    def test_returns_bytes(self):
        """Returns raw bytes from a successful audio download."""
        resp = _make_response(200, content=b"audio-data")
        client = AceStepClient("http://localhost:8001")
        with patch("acemusic.client.httpx.get", return_value=resp):
            data = client.download_audio("http://localhost:8001/v1/audio?path=clip.wav")
        assert data == b"audio-data"

    def test_raises_acestep_error_on_http_error(self):
        """Raises AceStepError when the audio URL returns a non-2xx response."""
        resp = _make_error_response(404)
        client = AceStepClient("http://localhost:8001")
        with patch("acemusic.client.httpx.get", return_value=resp):
            with pytest.raises(AceStepError, match="Download failed"):
                client.download_audio("http://localhost:8001/v1/audio?path=missing.wav")

    def test_raises_acestep_error_on_request_error(self):
        """Raises AceStepError when the download connection fails."""
        client = AceStepClient("http://localhost:8001")
        with patch("acemusic.client.httpx.get", side_effect=httpx.ConnectError("refused")):
            with pytest.raises(AceStepError, match="Download failed"):
                client.download_audio("http://localhost:8001/v1/audio?path=clip.wav")
