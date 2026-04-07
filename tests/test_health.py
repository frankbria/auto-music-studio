"""Unit tests for acemusic health command (US-2.2)."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from typer.testing import CliRunner

from acemusic.cli import app

runner = CliRunner()

HEALTHY_STATS = {
    "data": {
        "jobs": {"total": 10, "running": 0, "queued": 0, "succeeded": 10, "failed": 0},
        "models": [{"name": "ace-step-base"}, {"name": "ace-step-turbo"}],
        "avg_job_seconds": 4.2,
    },
    "code": 200,
    "error": None,
}


def _mock_response(status_code: int, json_data: dict) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = json_data
    response.text = str(json_data)
    response.raise_for_status.return_value = None
    return response


class TestHealthCommand:
    def test_health_shows_healthy_on_success(self, monkeypatch):
        """health command prints 'Server: healthy' and stats on 200 OK."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        mock_resp = _mock_response(200, HEALTHY_STATS)

        with patch("acemusic.client.httpx.get", return_value=mock_resp):
            result = runner.invoke(app, ["health"])

        assert result.exit_code == 0, result.output
        assert "healthy" in result.output.lower()
        assert "http://localhost:8001" in result.output

    def test_health_shows_models_in_output(self, monkeypatch):
        """health command includes loaded model names in output."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        mock_resp = _mock_response(200, HEALTHY_STATS)

        with patch("acemusic.client.httpx.get", return_value=mock_resp):
            result = runner.invoke(app, ["health"])

        assert result.exit_code == 0
        assert "ace-step-base" in result.output or "ace-step-turbo" in result.output

    def test_health_exits_one_on_timeout(self, monkeypatch):
        """health command prints 'unreachable' and exits 1 on timeout."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")

        with patch("acemusic.client.httpx.get", side_effect=httpx.TimeoutException("timed out")):
            result = runner.invoke(app, ["health"])

        assert result.exit_code == 1
        assert "unreachable" in result.output.lower()
        assert "timed out" in result.output.lower()

    def test_health_exits_one_on_non_200(self, monkeypatch):
        """health command prints error and exits 1 on non-200 response."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        mock_resp = _mock_response(503, {"error": "service unavailable"})
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError("503", request=MagicMock(), response=mock_resp)

        with patch("acemusic.client.httpx.get", return_value=mock_resp):
            result = runner.invoke(app, ["health"])

        assert result.exit_code == 1
        assert "error" in result.output.lower() or "503" in result.output

    def test_health_exits_one_on_connection_error(self, monkeypatch):
        """health command exits 1 when server is unreachable (connection refused)."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")

        with patch("acemusic.client.httpx.get", side_effect=httpx.ConnectError("Connection refused")):
            result = runner.invoke(app, ["health"])

        assert result.exit_code == 1
        assert "unreachable" in result.output.lower()

    def test_health_missing_url_exits_one(self, monkeypatch):
        """health command exits 1 with friendly error when ACEMUSIC_BASE_URL is not set."""
        monkeypatch.delenv("ACEMUSIC_BASE_URL", raising=False)
        from acemusic import config as cfg_mod

        def _no_url():
            return cfg_mod.AceConfig(api_url=None, api_key=None)

        monkeypatch.setattr(cfg_mod, "load_config", _no_url)

        result = runner.invoke(app, ["health"])
        assert result.exit_code != 0

    @pytest.mark.integration
    def test_health_live_server(self, integration_url, monkeypatch):
        """Integration: health command against a real ACE-Step server (prefers ACESTEP_LOCAL_URL)."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", integration_url)
        result = runner.invoke(app, ["health"])
        assert result.exit_code == 0, result.output
        assert "healthy" in result.output.lower()
