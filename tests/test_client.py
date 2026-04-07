"""Unit tests for AceStepClient new methods (US-2.3)."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from acemusic.client import AceStepClient, AceStepError


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


class TestSubmitTask:
    """Tests for AceStepClient.submit_task()."""

    def test_returns_task_id(self):
        """Returns the task_id string from a successful 200 response."""
        resp = _make_response(200, {"task_id": "abc-123"})
        client = AceStepClient("http://localhost:8001")
        with patch("acemusic.client.httpx.post", return_value=resp):
            task_id = client.submit_task("upbeat pop")
        assert task_id == "abc-123"

    def test_accepts_id_field_as_fallback(self):
        """Falls back to 'id' key if 'task_id' is absent from the response."""
        resp = _make_response(200, {"id": "xyz-456"})
        client = AceStepClient("http://localhost:8001")
        with patch("acemusic.client.httpx.post", return_value=resp):
            task_id = client.submit_task("jazz")
        assert task_id == "xyz-456"

    def test_raises_acestep_error_on_missing_task_id(self):
        """Raises AceStepError when neither task_id nor id appears in the response."""
        resp = _make_response(200, {"result": "ok"})
        client = AceStepClient("http://localhost:8001")
        with patch("acemusic.client.httpx.post", return_value=resp):
            with pytest.raises(AceStepError, match="No task_id"):
                client.submit_task("ambient")

    def test_raises_acestep_error_on_http_error(self):
        """Raises AceStepError wrapping an HTTP status error from the server."""
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

    def test_includes_audio_duration_when_provided(self):
        """Includes audio_duration in the POST payload when a value is given."""
        resp = _make_response(200, {"task_id": "dur-123"})
        client = AceStepClient("http://localhost:8001")
        with patch("acemusic.client.httpx.post", return_value=resp) as mock_post:
            client.submit_task("pop", audio_duration=30.0)
        payload = mock_post.call_args.kwargs["json"]
        assert payload["audio_duration"] == 30.0

    def test_omits_audio_duration_when_none(self):
        """Omits audio_duration from the POST payload when None is passed."""
        resp = _make_response(200, {"task_id": "no-dur"})
        client = AceStepClient("http://localhost:8001")
        with patch("acemusic.client.httpx.post", return_value=resp) as mock_post:
            client.submit_task("pop", audio_duration=None)
        payload = mock_post.call_args.kwargs["json"]
        assert "audio_duration" not in payload


class TestQueryResult:
    """Tests for AceStepClient.query_result()."""

    def test_returns_result_dict(self):
        """Returns the parsed JSON dict from a successful poll response."""
        resp = _make_response(200, {"status": "pending"})
        client = AceStepClient("http://localhost:8001")
        with patch("acemusic.client.httpx.get", return_value=resp):
            result = client.query_result("task-1")
        assert result["status"] == "pending"

    def test_raises_acestep_error_on_http_error(self):
        """Raises AceStepError on a non-2xx response from the query endpoint."""
        resp = _make_error_response(500)
        client = AceStepClient("http://localhost:8001")
        with patch("acemusic.client.httpx.get", return_value=resp):
            with pytest.raises(AceStepError, match="Query failed"):
                client.query_result("task-1")

    def test_raises_acestep_error_on_request_error(self):
        """Raises AceStepError when the request itself fails (e.g. timeout)."""
        client = AceStepClient("http://localhost:8001")
        with patch("acemusic.client.httpx.get", side_effect=httpx.TimeoutException("timeout")):
            with pytest.raises(AceStepError, match="Query failed"):
                client.query_result("task-1")


class TestDownloadAudio:
    """Tests for AceStepClient.download_audio()."""

    def test_returns_bytes(self):
        """Returns raw bytes from a successful audio download."""
        resp = _make_response(200, content=b"audio-data")
        client = AceStepClient("http://localhost:8001")
        with patch("acemusic.client.httpx.get", return_value=resp):
            data = client.download_audio("http://localhost:8001/clip.wav")
        assert data == b"audio-data"

    def test_raises_acestep_error_on_http_error(self):
        """Raises AceStepError when the audio URL returns a non-2xx response."""
        resp = _make_error_response(404)
        client = AceStepClient("http://localhost:8001")
        with patch("acemusic.client.httpx.get", return_value=resp):
            with pytest.raises(AceStepError, match="Download failed"):
                client.download_audio("http://localhost:8001/missing.wav")

    def test_raises_acestep_error_on_request_error(self):
        """Raises AceStepError when the download connection fails."""
        client = AceStepClient("http://localhost:8001")
        with patch("acemusic.client.httpx.get", side_effect=httpx.ConnectError("refused")):
            with pytest.raises(AceStepError, match="Download failed"):
                client.download_audio("http://localhost:8001/clip.wav")
