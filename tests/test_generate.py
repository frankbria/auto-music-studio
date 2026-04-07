"""Unit tests for acemusic generate command (US-2.3, US-2.4)."""

import os
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
        assert len(names) == 2
        assert all("upbeat-pop" in n for n in names)

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
        from acemusic.config import AceConfig

        monkeypatch.setattr("acemusic.cli.load_config", lambda: AceConfig(api_url=None, api_key=None))

        result = runner.invoke(app, ["generate", "test", "--output", str(tmp_path)])
        assert result.exit_code != 0

    @pytest.mark.integration
    @pytest.mark.skipif(not os.environ.get("ACEMUSIC_BASE_URL"), reason="ACEMUSIC_BASE_URL not set — no live server")
    def test_generate_live_server(self, tmp_path):
        """Integration: generate against real ACE-Step server."""
        result = runner.invoke(app, ["generate", "upbeat pop", "--output", str(tmp_path)])
        assert result.exit_code == 0
        assert len(list(tmp_path.glob("*.wav"))) == 2


class TestGenerateOutputNaming:
    """Tests for US-2.4: --name flag and output_dir config fallback."""

    def test_name_flag_produces_prefixed_filenames(self, monkeypatch, tmp_path):
        """--name sets the filename prefix: demo-1.wav, demo-2.wav."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")

        client_mock = _make_client_mock([COMPLETED_RESULT])

        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(app, ["generate", "test", "--output", str(tmp_path), "--name", "demo"])

        assert result.exit_code == 0, result.output
        names = sorted(f.name for f in tmp_path.glob("*.wav"))
        assert names == ["demo-1.wav", "demo-2.wav"]

    def test_name_flag_does_not_include_slug_or_timestamp(self, monkeypatch, tmp_path):
        """--name prefix files contain no slug or timestamp in filename."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")

        client_mock = _make_client_mock([COMPLETED_RESULT])

        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            runner.invoke(app, ["generate", "upbeat pop", "--output", str(tmp_path), "--name", "my-song"])

        names = [f.name for f in tmp_path.glob("*.wav")]
        assert all(n.startswith("my-song-") for n in names)
        # No slug-like or timestamp digits beyond the index
        assert not any("upbeat" in n for n in names)

    def test_output_dir_created_when_missing(self, monkeypatch, tmp_path):
        """--output creates the directory automatically if it does not exist."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        new_dir = tmp_path / "songs" / "new"

        client_mock = _make_client_mock([COMPLETED_RESULT])

        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(app, ["generate", "test", "--output", str(new_dir)])

        assert result.exit_code == 0, result.output
        assert new_dir.exists()

    def test_output_falls_back_to_config_output_dir(self, monkeypatch, tmp_path):
        """When --output is omitted, config output_dir is used."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")

        from acemusic.config import AceConfig

        config_dir = tmp_path / "config-output"
        config_dir.mkdir()
        monkeypatch.setattr(
            "acemusic.cli.load_config",
            lambda: AceConfig(api_url="http://localhost:8001", api_key=None, output_dir=str(config_dir)),
        )

        client_mock = _make_client_mock([COMPLETED_RESULT])

        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(app, ["generate", "test"])

        assert result.exit_code == 0, result.output
        assert len(list(config_dir.glob("*.wav"))) == 2

    def test_output_falls_back_to_cwd_when_no_config(self, monkeypatch, tmp_path):
        """When --output omitted and no config output_dir, files go to CWD."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        monkeypatch.chdir(tmp_path)

        from acemusic.config import AceConfig

        monkeypatch.setattr(
            "acemusic.cli.load_config",
            lambda: AceConfig(api_url="http://localhost:8001", api_key=None, output_dir=None),
        )

        client_mock = _make_client_mock([COMPLETED_RESULT])

        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(app, ["generate", "test"])

        assert result.exit_code == 0, result.output
        assert len(list(tmp_path.glob("*.wav"))) == 2
