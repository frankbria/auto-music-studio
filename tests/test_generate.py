"""Unit tests for acemusic generate command (US-2.3, US-2.4, US-3.2)."""

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
        """AceStepError during submit (connection error, no ElevenLabs key) exits 1."""
        from acemusic.client import AceStepError
        from acemusic.config import AceConfig

        # Explicitly disable ElevenLabs fallback so connection errors exit 1
        monkeypatch.setattr(
            "acemusic.cli.load_config",
            lambda: AceConfig(api_url="http://localhost:8001", api_key=None, elevenlabs_api_key=None),
        )

        client_mock = MagicMock()
        client_mock.submit_task.side_effect = AceStepError("connection refused")

        with patch("acemusic.cli.AceStepClient", return_value=client_mock):
            result = runner.invoke(app, ["generate", "rock", "--output", str(tmp_path)])

        assert result.exit_code == 1
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
    def test_generate_live_server(self, integration_url, tmp_path):
        """Integration: generate against a real ACE-Step server (prefers ACESTEP_LOCAL_URL)."""
        result = runner.invoke(
            app,
            ["generate", "upbeat pop", "--output", str(tmp_path), "--num-clips", "1", "--duration", "15"],
            env={"ACEMUSIC_BASE_URL": integration_url},
        )
        assert result.exit_code == 0, result.output
        wav_files = list(tmp_path.glob("*.wav"))
        assert len(wav_files) == 1
        assert wav_files[0].stat().st_size > 0
        assert wav_files[0].read_bytes()[:4] == b"RIFF", "Not a valid WAV file"

    @pytest.mark.integration
    def test_generate_live_with_name_flag(self, integration_url, tmp_path):
        """Integration: --name produces prefix-1.wav on a live server."""
        result = runner.invoke(
            app,
            [
                "generate",
                "soft piano",
                "--output",
                str(tmp_path),
                "--name",
                "mytrack",
                "--num-clips",
                "1",
                "--duration",
                "15",
            ],
            env={"ACEMUSIC_BASE_URL": integration_url},
        )
        assert result.exit_code == 0, result.output
        names = sorted(f.name for f in tmp_path.glob("*.wav"))
        assert names == ["mytrack-1.wav"]
        assert (tmp_path / "mytrack-1.wav").read_bytes()[:4] == b"RIFF"

    @pytest.mark.integration
    def test_generate_live_creates_output_dir(self, integration_url, tmp_path):
        """Integration: --output creates the directory automatically if missing."""
        new_dir = tmp_path / "auto-created"
        result = runner.invoke(
            app,
            ["generate", "upbeat pop", "--output", str(new_dir), "--num-clips", "1", "--duration", "15"],
            env={"ACEMUSIC_BASE_URL": integration_url},
        )
        assert result.exit_code == 0, result.output
        assert new_dir.exists()
        assert len(list(new_dir.glob("*.wav"))) == 1


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
            result = runner.invoke(app, ["generate", "upbeat pop", "--output", str(tmp_path), "--name", "my-song"])

        assert result.exit_code == 0, result.output
        names = [f.name for f in tmp_path.glob("*.wav")]
        assert len(names) == len(COMPLETED_RESULT["audio_urls"])
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

    def test_output_flag_overrides_config_output_dir(self, monkeypatch, tmp_path):
        """--output takes precedence over config output_dir."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")

        config_dir = tmp_path / "config-output"
        config_dir.mkdir()
        cli_out = tmp_path / "cli-out"

        from acemusic.config import AceConfig

        monkeypatch.setattr(
            "acemusic.cli.load_config",
            lambda: AceConfig(api_url="http://localhost:8001", api_key=None, output_dir=str(config_dir)),
        )

        client_mock = _make_client_mock([COMPLETED_RESULT])

        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(app, ["generate", "test", "--output", str(cli_out)])

        assert result.exit_code == 0, result.output
        assert len(list(cli_out.glob("*.wav"))) == 2
        assert len(list(config_dir.glob("*.wav"))) == 0

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


class TestStyleLyricsFlags:
    """Tests for US-3.1: --style, --lyrics, --lyrics-file, --vocal-language, --instrumental."""

    def test_style_flag_passed_to_submit_task(self, monkeypatch, tmp_path):
        """--style value is forwarded as 'style' kwarg to AceStepClient.submit_task."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")

        client_mock = _make_client_mock([COMPLETED_RESULT])

        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(
                app,
                ["generate", "pop song", "--style", "upbeat, synth-pop", "--output", str(tmp_path)],
            )

        assert result.exit_code == 0, result.output
        assert client_mock.submit_task.call_args is not None
        assert client_mock.submit_task.call_args.kwargs["style"] == "upbeat, synth-pop"

    def test_lyrics_flag_passed_to_submit_task(self, monkeypatch, tmp_path):
        """--lyrics value is forwarded as 'lyrics' kwarg to AceStepClient.submit_task."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")

        client_mock = _make_client_mock([COMPLETED_RESULT])

        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(
                app,
                ["generate", "pop song", "--lyrics", "[Verse]\nHello world", "--output", str(tmp_path)],
            )

        assert result.exit_code == 0, result.output
        assert client_mock.submit_task.call_args is not None
        assert client_mock.submit_task.call_args.kwargs["lyrics"] == "[Verse]\nHello world"

    def test_lyrics_file_flag_reads_file_and_passes_content(self, monkeypatch, tmp_path):
        """--lyrics-file reads lyrics from disk and sends file content to the API."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")

        lyrics_file = tmp_path / "song.txt"
        lyrics_file.write_text("[Verse]\nHello world\n[Chorus]\nSing along")

        client_mock = _make_client_mock([COMPLETED_RESULT])

        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(
                app,
                ["generate", "pop song", "--lyrics-file", str(lyrics_file), "--output", str(tmp_path)],
            )

        assert result.exit_code == 0, result.output
        call_kwargs = client_mock.submit_task.call_args
        assert "Hello world" in str(call_kwargs)

    def test_lyrics_file_missing_exits_one(self, monkeypatch, tmp_path):
        """--lyrics-file with a missing path exits 1 with a clear error."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")

        result = runner.invoke(
            app,
            ["generate", "pop song", "--lyrics-file", "/nonexistent/lyrics.txt", "--output", str(tmp_path)],
        )

        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "lyrics" in result.output.lower()

    def test_vocal_language_passed_to_submit_task(self, monkeypatch, tmp_path):
        """--vocal-language is forwarded as 'vocal_language' kwarg to AceStepClient.submit_task."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")

        client_mock = _make_client_mock([COMPLETED_RESULT])

        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(
                app,
                ["generate", "pop song", "--vocal-language", "ja", "--output", str(tmp_path)],
            )

        assert result.exit_code == 0, result.output
        assert client_mock.submit_task.call_args is not None
        assert client_mock.submit_task.call_args.kwargs["vocal_language"] == "ja"

    def test_instrumental_flag_passed_to_submit_task(self, monkeypatch, tmp_path):
        """--instrumental is forwarded as instrumental=True to AceStepClient.submit_task."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")

        client_mock = _make_client_mock([COMPLETED_RESULT])

        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(
                app,
                ["generate", "pop song", "--instrumental", "--output", str(tmp_path)],
            )

        assert result.exit_code == 0, result.output
        assert client_mock.submit_task.call_args is not None
        assert client_mock.submit_task.call_args.kwargs["instrumental"] is True

    def test_all_three_inputs_ace_step(self, monkeypatch, tmp_path):
        """All three inputs (prompt + style + lyrics) are passed together to ACE-Step."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")

        client_mock = _make_client_mock([COMPLETED_RESULT])

        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(
                app,
                [
                    "generate",
                    "pop song",
                    "--style",
                    "upbeat, synth-pop",
                    "--lyrics",
                    "[Verse]\nHello world",
                    "--output",
                    str(tmp_path),
                ],
            )

        assert result.exit_code == 0, result.output
        call_str = str(client_mock.submit_task.call_args)
        assert "upbeat, synth-pop" in call_str
        assert "Hello world" in call_str


class TestStyleLyricsElevenLabs:
    """Tests for US-3.1: --style, --lyrics, --instrumental forwarded to ElevenLabs."""

    def test_style_forwarded_to_elevenlabs(self, monkeypatch, tmp_path):
        """--style is forwarded to ElevenLabsClient.generate() as 'style'."""
        from acemusic.config import AceConfig

        monkeypatch.setattr(
            "acemusic.cli.load_config",
            lambda: AceConfig(
                api_url="http://localhost:8001",
                api_key=None,
                elevenlabs_api_key="test-key",
                elevenlabs_output_format="mp3_44100_128",
            ),
        )

        el_mock = MagicMock()
        el_mock.generate.return_value = b"ID3" + b"\x00" * 100

        with (
            patch("acemusic.cli.ElevenLabsClient", return_value=el_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(
                app,
                [
                    "generate",
                    "pop song",
                    "--backend",
                    "elevenlabs",
                    "--style",
                    "dark electro",
                    "--output",
                    str(tmp_path),
                ],
            )

        assert result.exit_code == 0, result.output
        assert el_mock.generate.call_args is not None
        assert el_mock.generate.call_args.kwargs["style"] == "dark electro"

    def test_lyrics_forwarded_to_elevenlabs(self, monkeypatch, tmp_path):
        """--lyrics is forwarded to ElevenLabsClient.generate() as 'lyrics'."""
        from acemusic.config import AceConfig

        monkeypatch.setattr(
            "acemusic.cli.load_config",
            lambda: AceConfig(
                api_url="http://localhost:8001",
                api_key=None,
                elevenlabs_api_key="test-key",
                elevenlabs_output_format="mp3_44100_128",
            ),
        )

        el_mock = MagicMock()
        el_mock.generate.return_value = b"ID3" + b"\x00" * 100

        with (
            patch("acemusic.cli.ElevenLabsClient", return_value=el_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(
                app,
                [
                    "generate",
                    "pop song",
                    "--backend",
                    "elevenlabs",
                    "--lyrics",
                    "[Chorus]\nSing",
                    "--output",
                    str(tmp_path),
                ],
            )

        assert result.exit_code == 0, result.output
        assert el_mock.generate.call_args is not None
        assert el_mock.generate.call_args.kwargs["lyrics"] == "[Chorus]\nSing"

    def test_instrumental_forwarded_to_elevenlabs(self, monkeypatch, tmp_path):
        """--instrumental is forwarded to ElevenLabsClient.generate() as instrumental=True."""
        from acemusic.config import AceConfig

        monkeypatch.setattr(
            "acemusic.cli.load_config",
            lambda: AceConfig(
                api_url="http://localhost:8001",
                api_key=None,
                elevenlabs_api_key="test-key",
                elevenlabs_output_format="mp3_44100_128",
            ),
        )

        el_mock = MagicMock()
        el_mock.generate.return_value = b"ID3" + b"\x00" * 100

        with (
            patch("acemusic.cli.ElevenLabsClient", return_value=el_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(
                app,
                ["generate", "pop song", "--backend", "elevenlabs", "--instrumental", "--output", str(tmp_path)],
            )

        assert result.exit_code == 0, result.output
        assert el_mock.generate.call_args is not None
        assert el_mock.generate.call_args.kwargs["instrumental"] is True

    def test_vocal_language_elevenlabs_prints_warning(self, monkeypatch, tmp_path):
        """--vocal-language with ElevenLabs backend prints a warning and is ignored."""
        from acemusic.config import AceConfig

        monkeypatch.setattr(
            "acemusic.cli.load_config",
            lambda: AceConfig(
                api_url="http://localhost:8001",
                api_key=None,
                elevenlabs_api_key="test-key",
                elevenlabs_output_format="mp3_44100_128",
            ),
        )

        el_mock = MagicMock()
        el_mock.generate.return_value = b"ID3" + b"\x00" * 100

        with (
            patch("acemusic.cli.ElevenLabsClient", return_value=el_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(
                app,
                [
                    "generate",
                    "pop song",
                    "--backend",
                    "elevenlabs",
                    "--vocal-language",
                    "ja",
                    "--output",
                    str(tmp_path),
                ],
            )

        assert result.exit_code == 0, result.output
        assert "warning" in result.output.lower() or "ignored" in result.output.lower()


class TestMusicalParametersAceStep:
    """Tests for US-3.2: --bpm, --key, --time-signature, --seed forwarded to ACE-Step."""

    def test_bpm_integer_passed_to_submit_task(self, monkeypatch, tmp_path):
        """--bpm 128 forwards bpm=128 to AceStepClient.submit_task."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        client_mock = _make_client_mock([COMPLETED_RESULT])
        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(app, ["generate", "pop", "--bpm", "128", "--output", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert client_mock.submit_task.call_args.kwargs["bpm"] == 128

    def test_bpm_auto_passed_to_submit_task(self, monkeypatch, tmp_path):
        """--bpm auto forwards bpm='auto' to AceStepClient.submit_task."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        client_mock = _make_client_mock([COMPLETED_RESULT])
        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(app, ["generate", "pop", "--bpm", "auto", "--output", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert client_mock.submit_task.call_args.kwargs["bpm"] == "auto"

    def test_bpm_too_high_exits_one(self, monkeypatch, tmp_path):
        """--bpm 999 exits 1 with a validation error (not an API crash)."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        result = runner.invoke(app, ["generate", "pop", "--bpm", "999", "--output", str(tmp_path)])
        assert result.exit_code == 1
        assert "bpm" in result.output.lower()
        assert "Traceback" not in result.output

    def test_bpm_too_low_exits_one(self, monkeypatch, tmp_path):
        """--bpm 50 exits 1 (below 60 minimum)."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        result = runner.invoke(app, ["generate", "pop", "--bpm", "50", "--output", str(tmp_path)])
        assert result.exit_code == 1
        assert "bpm" in result.output.lower()
        assert "Traceback" not in result.output

    def test_bpm_invalid_string_exits_one(self, monkeypatch, tmp_path):
        """--bpm 'fast' (not a number or 'auto') exits 1 with a validation error."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        result = runner.invoke(app, ["generate", "pop", "--bpm", "fast", "--output", str(tmp_path)])
        assert result.exit_code == 1
        assert "bpm" in result.output.lower()
        assert "Traceback" not in result.output

    def test_key_passed_to_submit_task(self, monkeypatch, tmp_path):
        """--key 'C major' forwards key='C major' to AceStepClient.submit_task."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        client_mock = _make_client_mock([COMPLETED_RESULT])
        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(app, ["generate", "pop", "--key", "C major", "--output", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert client_mock.submit_task.call_args.kwargs["key"] == "C major"

    def test_time_signature_passed_to_submit_task(self, monkeypatch, tmp_path):
        """--time-signature '3/4' forwards time_signature='3/4' to AceStepClient.submit_task."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        client_mock = _make_client_mock([COMPLETED_RESULT])
        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(app, ["generate", "pop", "--time-signature", "3/4", "--output", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert client_mock.submit_task.call_args.kwargs["time_signature"] == "3/4"

    def test_time_signature_invalid_exits_one(self, monkeypatch, tmp_path):
        """--time-signature '11/4' exits 1 (not in allowed set)."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        result = runner.invoke(app, ["generate", "pop", "--time-signature", "11/4", "--output", str(tmp_path)])
        assert result.exit_code == 1
        assert "time" in result.output.lower() or "signature" in result.output.lower()
        assert "Traceback" not in result.output

    def test_seed_passed_to_submit_task(self, monkeypatch, tmp_path):
        """--seed 42 forwards seed=42 to AceStepClient.submit_task."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        client_mock = _make_client_mock([COMPLETED_RESULT])
        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(app, ["generate", "pop", "--seed", "42", "--output", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert client_mock.submit_task.call_args.kwargs["seed"] == 42

    def test_seed_minus_one_passed_to_submit_task(self, monkeypatch, tmp_path):
        """--seed -1 is accepted and forwarded (means 'random')."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        client_mock = _make_client_mock([COMPLETED_RESULT])
        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(app, ["generate", "pop", "--seed", "-1", "--output", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert client_mock.submit_task.call_args.kwargs["seed"] == -1

    def test_duration_too_short_exits_one(self, monkeypatch, tmp_path):
        """--duration 10 exits 1 (below 30s minimum)."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        result = runner.invoke(app, ["generate", "pop", "--duration", "10", "--output", str(tmp_path)])
        assert result.exit_code == 1
        assert "duration" in result.output.lower()
        assert "Traceback" not in result.output

    def test_duration_too_long_exits_one(self, monkeypatch, tmp_path):
        """--duration 500 exits 1 (above 240s maximum)."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        result = runner.invoke(app, ["generate", "pop", "--duration", "500", "--output", str(tmp_path)])
        assert result.exit_code == 1
        assert "duration" in result.output.lower()
        assert "Traceback" not in result.output

    def test_duration_valid_range_accepted(self, monkeypatch, tmp_path):
        """--duration 60 is within range and forwarded to submit_task."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        client_mock = _make_client_mock([COMPLETED_RESULT])
        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=60.0),
        ):
            result = runner.invoke(app, ["generate", "pop", "--duration", "60", "--output", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert client_mock.submit_task.call_args.kwargs["audio_duration"] == 60.0

    def test_key_empty_string_exits_one(self, monkeypatch, tmp_path):
        """--key '' exits 1 with a validation error."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        result = runner.invoke(app, ["generate", "pop", "--key", "", "--output", str(tmp_path)])
        assert result.exit_code == 1
        assert "key" in result.output.lower()
        assert "Traceback" not in result.output

    def test_key_whitespace_only_exits_one(self, monkeypatch, tmp_path):
        """--key '   ' (whitespace-only) exits 1 with a validation error."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        result = runner.invoke(app, ["generate", "pop", "--key", "   ", "--output", str(tmp_path)])
        assert result.exit_code == 1
        assert "key" in result.output.lower()
        assert "Traceback" not in result.output


class TestMusicalParametersElevenLabs:
    """Tests for US-3.2: musical params warn + inject into prompt on ElevenLabs backend."""

    def _el_config(self, monkeypatch):
        from acemusic.config import AceConfig

        monkeypatch.setattr(
            "acemusic.cli.load_config",
            lambda: AceConfig(
                api_url="http://localhost:8001",
                api_key=None,
                elevenlabs_api_key="test-key",
                elevenlabs_output_format="mp3_44100_128",
            ),
        )

    def _el_mock(self):
        el_mock = MagicMock()
        el_mock.generate.return_value = b"ID3" + b"\x00" * 100
        return el_mock

    def test_bpm_elevenlabs_warns_and_injects_into_prompt(self, monkeypatch, tmp_path):
        """--bpm with ElevenLabs prints a warning and injects '128 BPM' into the prompt."""
        self._el_config(monkeypatch)
        el_mock = self._el_mock()
        with (
            patch("acemusic.cli.ElevenLabsClient", return_value=el_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(
                app,
                ["generate", "pop", "--backend", "elevenlabs", "--bpm", "128", "--output", str(tmp_path)],
            )
        assert result.exit_code == 0, result.output
        assert "bpm" in result.output.lower()
        prompt_sent = el_mock.generate.call_args.kwargs["prompt"]
        assert "128 bpm" in prompt_sent.lower() or "128bpm" in prompt_sent.lower()

    def test_key_elevenlabs_warns_and_injects_into_prompt(self, monkeypatch, tmp_path):
        """--key with ElevenLabs prints a warning and injects 'C major' into the prompt."""
        self._el_config(monkeypatch)
        el_mock = self._el_mock()
        with (
            patch("acemusic.cli.ElevenLabsClient", return_value=el_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(
                app,
                ["generate", "pop", "--backend", "elevenlabs", "--key", "C major", "--output", str(tmp_path)],
            )
        assert result.exit_code == 0, result.output
        assert "key" in result.output.lower()
        prompt_sent = el_mock.generate.call_args.kwargs["prompt"]
        assert "c major" in prompt_sent.lower()

    def test_time_signature_elevenlabs_warns_and_injects_into_prompt(self, monkeypatch, tmp_path):
        """--time-signature with ElevenLabs prints a warning and injects the value into the prompt."""
        self._el_config(monkeypatch)
        el_mock = self._el_mock()
        with (
            patch("acemusic.cli.ElevenLabsClient", return_value=el_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(
                app,
                [
                    "generate",
                    "pop",
                    "--backend",
                    "elevenlabs",
                    "--time-signature",
                    "3/4",
                    "--output",
                    str(tmp_path),
                ],
            )
        assert result.exit_code == 0, result.output
        assert "time" in result.output.lower() or "signature" in result.output.lower()
        prompt_sent = el_mock.generate.call_args.kwargs["prompt"]
        assert "3/4" in prompt_sent

    def test_seed_elevenlabs_warns_only_no_injection(self, monkeypatch, tmp_path):
        """--seed with ElevenLabs prints a warning; seed value is not injected into the prompt."""
        self._el_config(monkeypatch)
        el_mock = self._el_mock()
        with (
            patch("acemusic.cli.ElevenLabsClient", return_value=el_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(
                app,
                ["generate", "pop", "--backend", "elevenlabs", "--seed", "42", "--output", str(tmp_path)],
            )
        assert result.exit_code == 0, result.output
        assert "seed" in result.output.lower()
        prompt_sent = el_mock.generate.call_args.kwargs["prompt"]
        assert "42" not in prompt_sent
        assert "seed" not in prompt_sent.lower()

    def test_no_musical_params_prompt_unchanged(self, monkeypatch, tmp_path):
        """When no musical params set, prompt sent to ElevenLabs is unchanged."""
        self._el_config(monkeypatch)
        el_mock = self._el_mock()
        with (
            patch("acemusic.cli.ElevenLabsClient", return_value=el_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(
                app,
                ["generate", "soft jazz", "--backend", "elevenlabs", "--output", str(tmp_path)],
            )
        assert result.exit_code == 0, result.output
        prompt_sent = el_mock.generate.call_args.kwargs["prompt"]
        assert prompt_sent == "soft jazz"

    def test_multiple_params_all_injected(self, monkeypatch, tmp_path):
        """All three ACE-Step params injected together produce a combined augmented prompt."""
        self._el_config(monkeypatch)
        el_mock = self._el_mock()
        with (
            patch("acemusic.cli.ElevenLabsClient", return_value=el_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(
                app,
                [
                    "generate",
                    "pop",
                    "--backend",
                    "elevenlabs",
                    "--bpm",
                    "120",
                    "--key",
                    "A minor",
                    "--time-signature",
                    "4/4",
                    "--output",
                    str(tmp_path),
                ],
            )
        assert result.exit_code == 0, result.output
        prompt_sent = el_mock.generate.call_args.kwargs["prompt"]
        assert "120" in prompt_sent
        assert "a minor" in prompt_sent.lower()
        assert "4/4" in prompt_sent

    def test_bpm_auto_elevenlabs_skips_injection(self, monkeypatch, tmp_path):
        """--bpm auto with ElevenLabs warns and does NOT inject 'auto' into the prompt."""
        self._el_config(monkeypatch)
        el_mock = self._el_mock()
        with (
            patch("acemusic.cli.ElevenLabsClient", return_value=el_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(
                app,
                ["generate", "pop", "--backend", "elevenlabs", "--bpm", "auto", "--output", str(tmp_path)],
            )
        assert result.exit_code == 0, result.output
        assert "bpm" in result.output.lower()
        prompt_sent = el_mock.generate.call_args.kwargs["prompt"]
        assert "auto" not in prompt_sent.lower()

    def test_key_any_elevenlabs_skips_injection(self, monkeypatch, tmp_path):
        """--key any with ElevenLabs warns and does NOT inject 'any' into the prompt."""
        self._el_config(monkeypatch)
        el_mock = self._el_mock()
        with (
            patch("acemusic.cli.ElevenLabsClient", return_value=el_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(
                app,
                ["generate", "pop", "--backend", "elevenlabs", "--key", "any", "--output", str(tmp_path)],
            )
        assert result.exit_code == 0, result.output
        assert "key" in result.output.lower()
        prompt_sent = el_mock.generate.call_args.kwargs["prompt"]
        assert "any" not in prompt_sent.lower()


# ---------------------------------------------------------------------------
# US-3.3: Quality/speed and creative parameters
# ---------------------------------------------------------------------------


class TestQualityCreativeParamsAceStep:
    """Tests for US-3.3: --inference-steps, --weirdness, --style-influence, --thinking forwarded to ACE-Step."""

    def test_inference_steps_forwarded(self, monkeypatch, tmp_path):
        """--inference-steps 8 forwards inference_steps=8 to submit_task."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        client_mock = _make_client_mock([COMPLETED_RESULT])
        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(app, ["generate", "pop", "--inference-steps", "8", "--output", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert client_mock.submit_task.call_args.kwargs["inference_steps"] == 8

    def test_inference_steps_default_is_none(self, monkeypatch, tmp_path):
        """When --inference-steps not given, inference_steps=None is forwarded."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        client_mock = _make_client_mock([COMPLETED_RESULT])
        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(app, ["generate", "pop", "--output", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert client_mock.submit_task.call_args.kwargs["inference_steps"] is None

    def test_weirdness_forwarded(self, monkeypatch, tmp_path):
        """--weirdness 75 forwards weirdness=75 to submit_task."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        client_mock = _make_client_mock([COMPLETED_RESULT])
        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(app, ["generate", "pop", "--weirdness", "75", "--output", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert client_mock.submit_task.call_args.kwargs["weirdness"] == 75

    def test_style_influence_forwarded(self, monkeypatch, tmp_path):
        """--style-influence 80 forwards style_influence=80 to submit_task."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        client_mock = _make_client_mock([COMPLETED_RESULT])
        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(app, ["generate", "pop", "--style-influence", "80", "--output", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert client_mock.submit_task.call_args.kwargs["style_influence"] == 80

    def test_thinking_forwarded(self, monkeypatch, tmp_path):
        """--thinking forwards thinking=True to submit_task."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        client_mock = _make_client_mock([COMPLETED_RESULT])
        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(app, ["generate", "pop", "--thinking", "--output", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert client_mock.submit_task.call_args.kwargs["thinking"] is True

    def test_thinking_default_is_false(self, monkeypatch, tmp_path):
        """When --thinking not given, thinking=False is forwarded."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        client_mock = _make_client_mock([COMPLETED_RESULT])
        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(app, ["generate", "pop", "--output", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert client_mock.submit_task.call_args.kwargs["thinking"] is False

    def test_inference_steps_zero_exits_one(self, monkeypatch, tmp_path):
        """--inference-steps 0 exits 1 with a validation error."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        result = runner.invoke(app, ["generate", "pop", "--inference-steps", "0", "--output", str(tmp_path)])
        assert result.exit_code == 1
        assert "inference-steps" in result.output.lower()
        assert "Traceback" not in result.output

    def test_inference_steps_negative_exits_one(self, monkeypatch, tmp_path):
        """--inference-steps -1 exits 1 with a validation error."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        result = runner.invoke(app, ["generate", "pop", "--inference-steps", "-1", "--output", str(tmp_path)])
        assert result.exit_code == 1
        assert "inference-steps" in result.output.lower()
        assert "Traceback" not in result.output

    def test_weirdness_too_low_exits_one(self, monkeypatch, tmp_path):
        """--weirdness -1 exits 1 with a validation error."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        result = runner.invoke(app, ["generate", "pop", "--weirdness", "-1", "--output", str(tmp_path)])
        assert result.exit_code == 1
        assert "weirdness" in result.output.lower()
        assert "Traceback" not in result.output

    def test_weirdness_too_high_exits_one(self, monkeypatch, tmp_path):
        """--weirdness 101 exits 1 with a validation error."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        result = runner.invoke(app, ["generate", "pop", "--weirdness", "101", "--output", str(tmp_path)])
        assert result.exit_code == 1
        assert "weirdness" in result.output.lower()
        assert "Traceback" not in result.output

    def test_style_influence_too_low_exits_one(self, monkeypatch, tmp_path):
        """--style-influence -1 exits 1 with a validation error."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        result = runner.invoke(app, ["generate", "pop", "--style-influence", "-1", "--output", str(tmp_path)])
        assert result.exit_code == 1
        assert "style-influence" in result.output.lower() or "style_influence" in result.output.lower()
        assert "Traceback" not in result.output

    def test_style_influence_too_high_exits_one(self, monkeypatch, tmp_path):
        """--style-influence 101 exits 1 with a validation error."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        result = runner.invoke(app, ["generate", "pop", "--style-influence", "101", "--output", str(tmp_path)])
        assert result.exit_code == 1
        assert "style-influence" in result.output.lower() or "style_influence" in result.output.lower()
        assert "Traceback" not in result.output


class TestFormatValidation:
    """Tests for US-3.3: --format validation."""

    def test_valid_format_wav_accepted(self, monkeypatch, tmp_path):
        """--format wav is accepted."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        client_mock = _make_client_mock([COMPLETED_RESULT])
        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(app, ["generate", "pop", "--format", "wav", "--output", str(tmp_path)])
        assert result.exit_code == 0, result.output

    def test_valid_format_mp3_accepted(self, monkeypatch, tmp_path):
        """--format mp3 is accepted."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        client_mock = _make_client_mock([COMPLETED_RESULT])
        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(app, ["generate", "pop", "--format", "mp3", "--output", str(tmp_path)])
        assert result.exit_code == 0, result.output

    def test_valid_formats_all_accepted(self, monkeypatch, tmp_path):
        """All valid formats (wav, flac, mp3, aac, opus) are accepted."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        for fmt in ("wav", "flac", "mp3", "aac", "opus"):
            client_mock = _make_client_mock([COMPLETED_RESULT])
            with (
                patch("acemusic.cli.AceStepClient", return_value=client_mock),
                patch("acemusic.cli.get_duration", return_value=3.0),
            ):
                result = runner.invoke(app, ["generate", "pop", "--format", fmt, "--output", str(tmp_path)])
            assert result.exit_code == 0, f"Format {fmt!r} was rejected: {result.output}"

    def test_invalid_format_exits_one(self, monkeypatch, tmp_path):
        """--format ogg exits 1 with a validation error."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        result = runner.invoke(app, ["generate", "pop", "--format", "ogg", "--output", str(tmp_path)])
        assert result.exit_code == 1
        assert "format" in result.output.lower()
        assert "Traceback" not in result.output

    def test_invalid_format_mp4_exits_one(self, monkeypatch, tmp_path):
        """--format mp4 exits 1 with a validation error."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        result = runner.invoke(app, ["generate", "pop", "--format", "mp4", "--output", str(tmp_path)])
        assert result.exit_code == 1
        assert "format" in result.output.lower()
        assert "Traceback" not in result.output


class TestQualityCreativeParamsElevenLabs:
    """Tests for US-3.3: ElevenLabs warnings for ACE-Step-only quality params."""

    def _el_config(self, monkeypatch):
        from acemusic.config import AceConfig

        monkeypatch.setattr(
            "acemusic.cli.load_config",
            lambda: AceConfig(
                api_url="http://localhost:8001",
                api_key=None,
                elevenlabs_api_key="el-key",
                elevenlabs_output_format="mp3_44100_128",
            ),
        )

    def _el_mock(self):
        el_mock = MagicMock()
        el_mock.generate.return_value = FAKE_WAV
        return el_mock

    def test_inference_steps_warns_on_elevenlabs(self, monkeypatch, tmp_path):
        """--inference-steps warns when used with ElevenLabs backend."""
        self._el_config(monkeypatch)
        el_mock = self._el_mock()
        with (
            patch("acemusic.cli.ElevenLabsClient", return_value=el_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(
                app,
                ["generate", "pop", "--backend", "elevenlabs", "--inference-steps", "8", "--output", str(tmp_path)],
            )
        assert result.exit_code == 0, result.output
        assert "inference" in result.output.lower() or "warning" in result.output.lower()

    def test_weirdness_nondefault_warns_on_elevenlabs(self, monkeypatch, tmp_path):
        """--weirdness 75 (non-default) warns when used with ElevenLabs backend."""
        self._el_config(monkeypatch)
        el_mock = self._el_mock()
        with (
            patch("acemusic.cli.ElevenLabsClient", return_value=el_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(
                app,
                ["generate", "pop", "--backend", "elevenlabs", "--weirdness", "75", "--output", str(tmp_path)],
            )
        assert result.exit_code == 0, result.output
        assert "weirdness" in result.output.lower()

    def test_weirdness_default_no_warning(self, monkeypatch, tmp_path):
        """--weirdness 50 (default) does NOT warn when used with ElevenLabs backend."""
        self._el_config(monkeypatch)
        el_mock = self._el_mock()
        with (
            patch("acemusic.cli.ElevenLabsClient", return_value=el_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(
                app,
                ["generate", "pop", "--backend", "elevenlabs", "--weirdness", "50", "--output", str(tmp_path)],
            )
        assert result.exit_code == 0, result.output
        assert "--weirdness is ace-step-specific" not in result.output.lower()

    def test_style_influence_nondefault_warns_on_elevenlabs(self, monkeypatch, tmp_path):
        """--style-influence 80 (non-default) warns when used with ElevenLabs backend."""
        self._el_config(monkeypatch)
        el_mock = self._el_mock()
        with (
            patch("acemusic.cli.ElevenLabsClient", return_value=el_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(
                app,
                ["generate", "pop", "--backend", "elevenlabs", "--style-influence", "80", "--output", str(tmp_path)],
            )
        assert result.exit_code == 0, result.output
        assert "style-influence" in result.output.lower() or "style_influence" in result.output.lower()

    def test_thinking_warns_on_elevenlabs(self, monkeypatch, tmp_path):
        """--thinking warns when used with ElevenLabs backend."""
        self._el_config(monkeypatch)
        el_mock = self._el_mock()
        with (
            patch("acemusic.cli.ElevenLabsClient", return_value=el_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(
                app,
                ["generate", "pop", "--backend", "elevenlabs", "--thinking", "--output", str(tmp_path)],
            )
        assert result.exit_code == 0, result.output
        assert "thinking" in result.output.lower()
