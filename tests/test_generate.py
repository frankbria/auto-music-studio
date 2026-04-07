"""Unit tests for acemusic generate command (US-2.3)."""

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from acemusic.cli import app

runner = CliRunner()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TASK_ID = "task-abc-123"
AUDIO_URL_1 = "http://localhost:8001/audio/clip1.wav"
AUDIO_URL_2 = "http://localhost:8001/audio/clip2.wav"

PENDING_RESULT = {"status": "pending", "audio_urls": []}
COMPLETED_RESULT = {
    "status": "completed",
    "audio_urls": [AUDIO_URL_1, AUDIO_URL_2],
}
FAILED_RESULT = {"status": "failed", "error": "model overloaded"}

FAKE_WAV = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x44\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00"


def _make_client_mock(query_sequence, audio_bytes=FAKE_WAV):
    """Return a patched AceStepClient instance."""
    client = MagicMock()
    client.submit_task.return_value = TASK_ID
    client.query_result.side_effect = query_sequence
    client.download_audio.return_value = audio_bytes
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGenerateCommand:
    """Tests for the acemusic generate CLI command (US-2.3)."""

    def test_generate_creates_two_wav_files(self, monkeypatch, tmp_path):
        """Successful generation writes 2 WAV files to the output directory."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")

        client_mock = _make_client_mock([COMPLETED_RESULT])

        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=3.5),
        ):
            result = runner.invoke(app, ["generate", "upbeat pop", "--output", str(tmp_path)])

        assert result.exit_code == 0, result.output
        wav_files = list(tmp_path.glob("*.wav"))
        assert len(wav_files) == 2

    def test_generate_filenames_contain_slug(self, monkeypatch, tmp_path):
        """Generated filenames include a slug derived from the prompt."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")

        client_mock = _make_client_mock([COMPLETED_RESULT])

        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=3.5),
        ):
            runner.invoke(app, ["generate", "upbeat pop", "--output", str(tmp_path)])

        names = [f.name for f in tmp_path.glob("*.wav")]
        assert any("upbeat-pop" in n for n in names)

    def test_generate_prints_file_paths(self, monkeypatch, tmp_path):
        """Output includes the absolute path of each generated file."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")

        client_mock = _make_client_mock([COMPLETED_RESULT])

        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=3.5),
        ):
            result = runner.invoke(app, ["generate", "upbeat pop", "--output", str(tmp_path)])

        assert str(tmp_path) in result.output

    def test_generate_prints_duration(self, monkeypatch, tmp_path):
        """Output includes the duration of each generated file."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")

        client_mock = _make_client_mock([COMPLETED_RESULT])

        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=3.5),
        ):
            result = runner.invoke(app, ["generate", "upbeat pop", "--output", str(tmp_path)])

        assert "3.5" in result.output

    def test_generate_polls_until_complete(self, monkeypatch, tmp_path):
        """generate polls query_result multiple times before completion."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")

        client_mock = _make_client_mock([PENDING_RESULT, PENDING_RESULT, COMPLETED_RESULT])

        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=2.0),
            patch("acemusic.cli.time.sleep"),
        ):
            result = runner.invoke(app, ["generate", "folk rain", "--output", str(tmp_path)])

        assert result.exit_code == 0
        assert client_mock.query_result.call_count == 3

    def test_generate_api_failure_exits_one(self, monkeypatch, tmp_path):
        """API failure prints a friendly message and exits 1."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")

        client_mock = _make_client_mock([FAILED_RESULT])

        with patch("acemusic.cli.AceStepClient", return_value=client_mock):
            result = runner.invoke(app, ["generate", "jazz", "--output", str(tmp_path)])

        assert result.exit_code == 1
        assert "model overloaded" in result.output.lower() or "failed" in result.output.lower()
        assert "Traceback" not in result.output

    def test_generate_submit_error_exits_one(self, monkeypatch, tmp_path):
        """AceStepError during submit prints friendly message and exits 1."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")

        from acemusic.client import AceStepError

        client_mock = MagicMock()
        client_mock.submit_task.side_effect = AceStepError("connection refused")

        with patch("acemusic.cli.AceStepClient", return_value=client_mock):
            result = runner.invoke(app, ["generate", "rock", "--output", str(tmp_path)])

        assert result.exit_code == 1
        assert "connection refused" in result.output.lower()
        assert "Traceback" not in result.output

    def test_generate_timeout_exits_one(self, monkeypatch, tmp_path):
        """Polling timeout exits 1 with a clear message."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")

        client_mock = _make_client_mock([PENDING_RESULT] * 1000)

        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.time.sleep"),
            patch("acemusic.cli.time.monotonic", side_effect=[0.0] + [700.0] * 1000),
        ):
            result = runner.invoke(
                app,
                ["generate", "ambient", "--output", str(tmp_path)],
                env={"ACEMUSIC_BASE_URL": "http://localhost:8001", "ACEMUSIC_POLL_TIMEOUT": "600"},
            )

        assert result.exit_code == 1
        assert "timed out" in result.output.lower()

    def test_generate_missing_url_exits_one(self, monkeypatch, tmp_path):
        """Missing ACEMUSIC_BASE_URL exits 1 with a friendly error."""
        monkeypatch.delenv("ACEMUSIC_BASE_URL", raising=False)
        from acemusic import config as cfg_mod

        monkeypatch.setattr(cfg_mod, "load_config", lambda: cfg_mod.AceConfig(api_url=None, api_key=None))

        result = runner.invoke(app, ["generate", "test", "--output", str(tmp_path)])
        assert result.exit_code != 0

    @pytest.mark.integration
    def test_generate_live_server(self, tmp_path):
        """Integration: generate against real ACE-Step server."""
        result = runner.invoke(app, ["generate", "upbeat pop", "--output", str(tmp_path)])
        assert result.exit_code == 0
        assert len(list(tmp_path.glob("*.wav"))) == 2
