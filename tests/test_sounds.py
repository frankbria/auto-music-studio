"""Unit tests for acemusic sounds command (US-3.5)."""

import re
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from acemusic.cli import app


def _plain(text: str) -> str:
    """Strip ANSI escape codes from text (Rich emits these in CI environments)."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


runner = CliRunner()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TASK_ID = "task-sounds-123"
AUDIO_URL_1 = "http://localhost:8001/audio/oneshot1.wav"

COMPLETED_RESULT = {
    "status": "completed",
    "audio_urls": [AUDIO_URL_1],
}
FAILED_RESULT = {"status": "failed", "error": "model overloaded"}

FAKE_WAV = (
    b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00"
    b"\x01\x00\x01\x00\x44\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00"
    b"data\x00\x00\x00\x00"
)


def _make_client_mock(query_sequence=None, audio_bytes=FAKE_WAV):
    """Return a patched AceStepClient instance."""
    client = MagicMock()
    client.submit_task.return_value = TASK_ID
    client.query_result.side_effect = query_sequence or [COMPLETED_RESULT]
    client.download_audio.return_value = audio_bytes
    return client


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


class TestSoundsValidation:
    """Tests for sounds command parameter validation."""

    def test_missing_type_exits_nonzero(self, monkeypatch):
        """--type is required; omitting it exits non-zero."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        result = runner.invoke(app, ["sounds", "deep kick drum"])
        assert result.exit_code != 0

    def test_invalid_type_exits_one(self, monkeypatch, tmp_path):
        """--type must be 'one-shot' or 'loop'; any other value exits 1."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        result = runner.invoke(app, ["sounds", "deep kick drum", "--type", "full-song", "--output", str(tmp_path)])
        assert result.exit_code == 1
        assert "one-shot" in result.output or "loop" in result.output or "invalid" in result.output.lower()

    def test_invalid_bpm_exits_one(self, monkeypatch, tmp_path):
        """BPM outside 60-180 exits 1 with an error message."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        result = runner.invoke(app, ["sounds", "hi-hat", "--type", "loop", "--bpm", "999", "--output", str(tmp_path)])
        assert result.exit_code == 1
        assert "bpm" in result.output.lower() or "180" in result.output

    def test_empty_key_exits_one(self, monkeypatch, tmp_path):
        """--key with blank value exits 1."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        result = runner.invoke(app, ["sounds", "pad", "--type", "loop", "--key", "   ", "--output", str(tmp_path)])
        assert result.exit_code == 1

    def test_missing_api_url_exits_one(self, monkeypatch, tmp_path):
        """Missing ACEMUSIC_BASE_URL exits 1 with a friendly error."""
        monkeypatch.delenv("ACEMUSIC_BASE_URL", raising=False)
        from acemusic.config import AceConfig

        monkeypatch.setattr("acemusic.cli.load_config", lambda: AceConfig(api_url=None, api_key=None))
        result = runner.invoke(app, ["sounds", "kick", "--type", "one-shot", "--output", str(tmp_path)])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


class TestSoundsCommand:
    """Tests for the acemusic sounds CLI command (US-3.5)."""

    def test_oneshot_creates_wav_file(self, monkeypatch, tmp_path):
        """One-shot generation writes a WAV file to the output directory."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")

        client_mock = _make_client_mock()

        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=1.5),
        ):
            result = runner.invoke(
                app, ["sounds", "deep punchy kick drum", "--type", "one-shot", "--output", str(tmp_path)]
            )

        assert result.exit_code == 0, result.output
        wav_files = list(tmp_path.glob("*.wav"))
        assert len(wav_files) == 1

    def test_loop_creates_wav_file(self, monkeypatch, tmp_path):
        """Loop generation writes a WAV file to the output directory."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")

        client_mock = _make_client_mock()

        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=8.0),
        ):
            result = runner.invoke(
                app,
                [
                    "sounds",
                    "ambient pad",
                    "--type",
                    "loop",
                    "--bpm",
                    "120",
                    "--key",
                    "A minor",
                    "--output",
                    str(tmp_path),
                ],
            )

        assert result.exit_code == 0, result.output
        wav_files = list(tmp_path.glob("*.wav"))
        assert len(wav_files) == 1

    def test_sounds_passes_mode_to_client(self, monkeypatch, tmp_path):
        """sounds command passes mode='sound' to submit_task."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")

        client_mock = _make_client_mock()

        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=1.0),
        ):
            runner.invoke(app, ["sounds", "snare hit", "--type", "one-shot", "--output", str(tmp_path)])

        call_kwargs = client_mock.submit_task.call_args
        assert call_kwargs is not None
        kwargs = call_kwargs.kwargs if call_kwargs.kwargs else {}
        # mode="sound" must be passed
        assert kwargs.get("mode") == "sound" or "sound" in str(call_kwargs)

    def test_sounds_passes_sound_type_to_client(self, monkeypatch, tmp_path):
        """sounds command passes sound_type to submit_task."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")

        client_mock = _make_client_mock()

        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=2.0),
        ):
            runner.invoke(app, ["sounds", "hi-hat pattern", "--type", "loop", "--output", str(tmp_path)])

        call_kwargs = client_mock.submit_task.call_args
        assert call_kwargs is not None
        kwargs = call_kwargs.kwargs if call_kwargs.kwargs else {}
        assert kwargs.get("sound_type") == "loop"

    def test_sounds_passes_bpm_to_client(self, monkeypatch, tmp_path):
        """--bpm is forwarded to submit_task."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")

        client_mock = _make_client_mock()

        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=2.0),
        ):
            runner.invoke(
                app, ["sounds", "hi-hat pattern", "--type", "loop", "--bpm", "140", "--output", str(tmp_path)]
            )

        call_kwargs = client_mock.submit_task.call_args
        assert call_kwargs is not None
        kwargs = call_kwargs.kwargs if call_kwargs.kwargs else {}
        assert kwargs.get("bpm") == 140

    def test_sounds_passes_key_to_client(self, monkeypatch, tmp_path):
        """--key is forwarded to submit_task."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")

        client_mock = _make_client_mock()

        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=2.0),
        ):
            runner.invoke(
                app, ["sounds", "ambient pad", "--type", "loop", "--key", "A minor", "--output", str(tmp_path)]
            )

        call_kwargs = client_mock.submit_task.call_args
        assert call_kwargs is not None
        kwargs = call_kwargs.kwargs if call_kwargs.kwargs else {}
        assert kwargs.get("key") == "A minor"

    def test_sounds_filenames_contain_slug(self, monkeypatch, tmp_path):
        """Generated filenames include a slug derived from the prompt."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")

        client_mock = _make_client_mock()

        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=1.5),
        ):
            runner.invoke(app, ["sounds", "deep kick", "--type", "one-shot", "--output", str(tmp_path)])

        names = [f.name for f in tmp_path.glob("*.wav")]
        assert len(names) == 1
        assert "deep-kick" in names[0]

    def test_sounds_name_flag_produces_prefixed_filename(self, monkeypatch, tmp_path):
        """--name sets the filename prefix: kick-1.wav."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")

        client_mock = _make_client_mock()

        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=1.5),
        ):
            runner.invoke(
                app, ["sounds", "kick drum", "--type", "one-shot", "--name", "kick", "--output", str(tmp_path)]
            )

        names = [f.name for f in tmp_path.glob("*.wav")]
        assert "kick-1.wav" in names

    def test_sounds_prints_file_path(self, monkeypatch, tmp_path):
        """Output includes the absolute path of the generated file."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")

        client_mock = _make_client_mock()

        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=1.5),
        ):
            result = runner.invoke(app, ["sounds", "snare", "--type", "one-shot", "--output", str(tmp_path)])

        assert str(tmp_path) in result.output

    def test_sounds_prints_duration(self, monkeypatch, tmp_path):
        """Output includes the duration of the generated file."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")

        client_mock = _make_client_mock()

        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=2.5),
        ):
            result = runner.invoke(app, ["sounds", "snare", "--type", "one-shot", "--output", str(tmp_path)])

        assert "2.5" in result.output

    def test_sounds_api_failure_exits_one(self, monkeypatch, tmp_path):
        """API failure prints a friendly message and exits 1."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")

        client_mock = _make_client_mock(query_sequence=[FAILED_RESULT])

        with patch("acemusic.cli.AceStepClient", return_value=client_mock):
            result = runner.invoke(app, ["sounds", "kick", "--type", "one-shot", "--output", str(tmp_path)])

        assert result.exit_code == 1
        assert "Traceback" not in result.output

    def test_sounds_connection_error_exits_one(self, monkeypatch, tmp_path):
        """Connection error exits 1 with a friendly message (no ElevenLabs fallback)."""
        from acemusic.client import AceStepError
        from acemusic.config import AceConfig

        monkeypatch.setattr(
            "acemusic.cli.load_config",
            lambda: AceConfig(api_url="http://localhost:8001", api_key=None, elevenlabs_api_key=None),
        )

        client_mock = MagicMock()
        client_mock.submit_task.side_effect = AceStepError("connection refused")

        with patch("acemusic.cli.AceStepClient", return_value=client_mock):
            result = runner.invoke(app, ["sounds", "kick", "--type", "one-shot", "--output", str(tmp_path)])

        assert result.exit_code == 1
        assert "Traceback" not in result.output

    def test_sounds_appears_in_help(self):
        """'sounds' subcommand is listed in top-level --help output."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "sounds" in result.output

    def test_sounds_help_shows_type_option(self, monkeypatch):
        """acemusic sounds --help mentions the --type option."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        result = runner.invoke(app, ["sounds", "--help"])
        assert result.exit_code == 0
        assert "--type" in _plain(result.output)

    def test_bpm_auto_accepted_for_loop(self, monkeypatch, tmp_path):
        """--bpm auto is accepted for loops."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")

        client_mock = _make_client_mock()

        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=4.0),
        ):
            result = runner.invoke(
                app, ["sounds", "groove", "--type", "loop", "--bpm", "auto", "--output", str(tmp_path)]
            )

        assert result.exit_code == 0, result.output

    def test_num_clips_default_is_one(self, monkeypatch, tmp_path):
        """Default --num-clips for sounds is 1."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")

        client_mock = _make_client_mock()

        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=1.5),
        ):
            runner.invoke(app, ["sounds", "kick", "--type", "one-shot", "--output", str(tmp_path)])

        call_kwargs = client_mock.submit_task.call_args
        assert call_kwargs is not None
        kwargs = call_kwargs.kwargs if call_kwargs.kwargs else {}
        assert kwargs.get("num_clips", 1) == 1
