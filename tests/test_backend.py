"""Unit tests for --backend flag and ElevenLabs fallback logic (US-2.5)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from acemusic.cli import app

runner = CliRunner()

FAKE_MP3 = b"ID3" + b"\x00" * 100

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _elevenlabs_client_mock(audio_bytes: bytes = FAKE_MP3) -> MagicMock:
    client = MagicMock()
    client.generate.return_value = audio_bytes
    client.validate_key.return_value = True
    return client


def _make_ace_client_mock(raises: Exception | None = None) -> MagicMock:
    client = MagicMock()
    if raises:
        client.submit_task.side_effect = raises
    else:
        client.submit_task.return_value = "task-123"
        client.query_result.return_value = {"status": "completed", "audio_urls": []}
        client.download_audio.return_value = b""
    return client


# ---------------------------------------------------------------------------
# --backend elevenlabs: explicit selection
# ---------------------------------------------------------------------------


class TestBackendElevenLabsExplicit:
    """Tests for acemusic generate --backend elevenlabs."""

    def test_explicit_elevenlabs_produces_audio_file(self, monkeypatch, tmp_path):
        """--backend elevenlabs generates a file via ElevenLabsClient."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")

        el_mock = _elevenlabs_client_mock(FAKE_MP3)

        with (
            patch("acemusic.cli.ElevenLabsClient", return_value=el_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(
                app,
                ["generate", "upbeat pop", "--backend", "elevenlabs", "--output", str(tmp_path)],
            )

        assert result.exit_code == 0, result.output
        assert len(list(tmp_path.iterdir())) >= 1

    def test_explicit_elevenlabs_no_key_exits_one(self, monkeypatch, tmp_path):
        """--backend elevenlabs exits 1 with clear error when ELEVENLABS_API_KEY is not set."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)

        from acemusic.config import AceConfig

        monkeypatch.setattr(
            "acemusic.cli.load_config",
            lambda: AceConfig(api_url="http://localhost:8001", api_key=None, elevenlabs_api_key=None),
        )

        result = runner.invoke(
            app,
            ["generate", "test", "--backend", "elevenlabs", "--output", str(tmp_path)],
        )

        assert result.exit_code == 1
        assert "ELEVENLABS_API_KEY" in result.output or "elevenlabs" in result.output.lower()

    def test_explicit_elevenlabs_num_clips_2_produces_2_files(self, monkeypatch, tmp_path):
        """--backend elevenlabs --num-clips 2 calls ElevenLabsClient.generate() twice."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")

        el_mock = _elevenlabs_client_mock(FAKE_MP3)

        with (
            patch("acemusic.cli.ElevenLabsClient", return_value=el_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(
                app,
                [
                    "generate",
                    "test",
                    "--backend",
                    "elevenlabs",
                    "--num-clips",
                    "2",
                    "--output",
                    str(tmp_path),
                ],
            )

        assert result.exit_code == 0, result.output
        assert el_mock.generate.call_count == 2

    def test_explicit_elevenlabs_uses_elevenlabs_output_format_env(self, monkeypatch, tmp_path):
        """ElevenLabsClient is instantiated with ELEVENLABS_OUTPUT_FORMAT from env."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
        monkeypatch.setenv("ELEVENLABS_OUTPUT_FORMAT", "opus_48000_128")

        el_mock = _elevenlabs_client_mock(FAKE_MP3)

        with (
            patch("acemusic.cli.ElevenLabsClient", return_value=el_mock) as mock_cls,
            patch("acemusic.cli.get_duration", return_value=2.0),
        ):
            runner.invoke(
                app,
                ["generate", "test", "--backend", "elevenlabs", "--output", str(tmp_path)],
            )

        call_kwargs = mock_cls.call_args.kwargs if mock_cls.call_args.kwargs else {}
        call_args = mock_cls.call_args.args if mock_cls.call_args.args else ()
        # Accept either positional or keyword argument
        all_args = str(call_args) + str(call_kwargs)
        assert "opus_48000_128" in all_args

    def test_explicit_elevenlabs_filenames_same_convention(self, monkeypatch, tmp_path):
        """ElevenLabs output filenames follow the same slug-timestamp-N.ext convention."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")

        el_mock = _elevenlabs_client_mock(FAKE_MP3)

        with (
            patch("acemusic.cli.ElevenLabsClient", return_value=el_mock),
            patch("acemusic.cli.get_duration", return_value=2.0),
        ):
            runner.invoke(
                app,
                ["generate", "upbeat pop", "--backend", "elevenlabs", "--output", str(tmp_path)],
            )

        files = sorted(tmp_path.iterdir())
        assert len(files) == 2  # default --num-clips 2
        assert all("upbeat-pop" in f.name for f in files)


# ---------------------------------------------------------------------------
# Auto-fallback: ACE-Step unreachable
# ---------------------------------------------------------------------------


class TestAutoFallback:
    """Tests for auto-fallback to ElevenLabs when ACE-Step is unreachable."""

    def test_fallback_prints_warning_message(self, monkeypatch, tmp_path):
        """Auto-fallback prints 'ACE-Step unavailable — falling back to ElevenLabs' on stderr/stdout."""

        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")

        from acemusic.client import AceStepError
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

        ace_mock = MagicMock()
        ace_mock.submit_task.side_effect = AceStepError("connection refused")

        el_mock = _elevenlabs_client_mock(FAKE_MP3)

        with (
            patch("acemusic.cli.AceStepClient", return_value=ace_mock),
            patch("acemusic.cli.ElevenLabsClient", return_value=el_mock),
            patch("acemusic.cli.get_duration", return_value=2.0),
        ):
            result = runner.invoke(app, ["generate", "test", "--output", str(tmp_path)])

        combined = result.output + (result.stderr if hasattr(result, "stderr") and result.stderr else "")
        assert "falling back to elevenlabs" in combined.lower() or "ace-step unavailable" in combined.lower()

    def test_fallback_produces_audio_file(self, monkeypatch, tmp_path):
        """Auto-fallback produces an audio file when ACE-Step is down."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")

        from acemusic.client import AceStepError
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

        ace_mock = MagicMock()
        ace_mock.submit_task.side_effect = AceStepError("connection refused")

        el_mock = _elevenlabs_client_mock(FAKE_MP3)

        with (
            patch("acemusic.cli.AceStepClient", return_value=ace_mock),
            patch("acemusic.cli.ElevenLabsClient", return_value=el_mock),
            patch("acemusic.cli.get_duration", return_value=2.0),
        ):
            result = runner.invoke(app, ["generate", "test", "--output", str(tmp_path)])

        assert result.exit_code == 0, result.output
        assert len(list(tmp_path.iterdir())) >= 1  # default --num-clips 2 produces 2 files

    def test_fallback_no_key_exits_one_with_clear_error(self, monkeypatch, tmp_path):
        """Auto-fallback with no ELEVENLABS_API_KEY exits 1 with a clear error."""
        from acemusic.client import AceStepError
        from acemusic.config import AceConfig

        monkeypatch.setattr(
            "acemusic.cli.load_config",
            lambda: AceConfig(
                api_url="http://localhost:8001",
                api_key=None,
                elevenlabs_api_key=None,
            ),
        )

        ace_mock = MagicMock()
        ace_mock.submit_task.side_effect = AceStepError("connection refused")

        with patch("acemusic.cli.AceStepClient", return_value=ace_mock):
            result = runner.invoke(app, ["generate", "test", "--output", str(tmp_path)])

        assert result.exit_code == 1
        # Should mention the problem clearly, not just traceback
        assert "Traceback" not in result.output
        output_lower = result.output.lower()
        assert "elevenlabs" in output_lower or "api key" in output_lower or "unreachable" in output_lower

    def test_no_fallback_on_api_error(self, monkeypatch, tmp_path):
        """API errors (4xx) from ACE-Step do NOT trigger ElevenLabs fallback."""
        from acemusic.client import AceStepError
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

        ace_mock = MagicMock()
        # This is an API error (server responded with an error), not a connection error
        ace_mock.submit_task.side_effect = AceStepError("Submit failed: 400 Bad Request")

        el_mock = _elevenlabs_client_mock(FAKE_MP3)

        with (
            patch("acemusic.cli.AceStepClient", return_value=ace_mock),
            patch("acemusic.cli.ElevenLabsClient", return_value=el_mock),
        ):
            result = runner.invoke(app, ["generate", "test", "--output", str(tmp_path)])

        assert result.exit_code == 1
        el_mock.generate.assert_not_called()


# ---------------------------------------------------------------------------
# Health command: ElevenLabs key status
# ---------------------------------------------------------------------------


class TestHealthElevenLabsStatus:
    """Tests for acemusic health showing ElevenLabs key status."""

    def test_health_shows_elevenlabs_key_configured(self, monkeypatch):
        """health shows ElevenLabs key as 'configured' when ELEVENLABS_API_KEY is set."""

        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")

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
        el_mock.validate_key.return_value = True

        ace_mock = MagicMock()
        ace_mock.get_stats.return_value = {"models": [], "active_jobs": 0, "avg_job_time": None}

        with (
            patch("acemusic.cli.AceStepClient", return_value=ace_mock),
            patch("acemusic.cli.ElevenLabsClient", return_value=el_mock),
        ):
            result = runner.invoke(app, ["health"])

        assert result.exit_code == 0, result.output
        assert "elevenlabs" in result.output.lower()
        assert "configured" in result.output.lower() or "valid" in result.output.lower()

    def test_health_shows_elevenlabs_key_not_configured(self, monkeypatch):
        """health shows ElevenLabs key as 'not configured' when key is absent."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")

        from acemusic.config import AceConfig

        monkeypatch.setattr(
            "acemusic.cli.load_config",
            lambda: AceConfig(
                api_url="http://localhost:8001",
                api_key=None,
                elevenlabs_api_key=None,
            ),
        )

        ace_mock = MagicMock()
        ace_mock.get_stats.return_value = {"models": [], "active_jobs": 0, "avg_job_time": None}

        with patch("acemusic.cli.AceStepClient", return_value=ace_mock):
            result = runner.invoke(app, ["health"])

        assert result.exit_code == 0, result.output
        assert "elevenlabs" in result.output.lower()
        assert "not configured" in result.output.lower()

    def test_health_shows_elevenlabs_key_invalid(self, monkeypatch):
        """health shows ElevenLabs key as 'invalid' when validate_key returns False."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")

        from acemusic.config import AceConfig

        monkeypatch.setattr(
            "acemusic.cli.load_config",
            lambda: AceConfig(
                api_url="http://localhost:8001",
                api_key=None,
                elevenlabs_api_key="bad-key",
                elevenlabs_output_format="mp3_44100_128",
            ),
        )

        el_mock = MagicMock()
        el_mock.validate_key.return_value = False

        ace_mock = MagicMock()
        ace_mock.get_stats.return_value = {"models": [], "active_jobs": 0, "avg_job_time": None}

        with (
            patch("acemusic.cli.AceStepClient", return_value=ace_mock),
            patch("acemusic.cli.ElevenLabsClient", return_value=el_mock),
        ):
            result = runner.invoke(app, ["health"])

        assert result.exit_code == 0, result.output
        assert "invalid" in result.output.lower() or "error" in result.output.lower()
