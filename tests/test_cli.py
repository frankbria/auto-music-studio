"""Tests for acemusic CLI entry point (US-2.1)."""

from typer.testing import CliRunner

from acemusic import __version__
from acemusic.cli import app

runner = CliRunner()


def test_help_exits_zero():
    """uv run acemusic --help must exit with code 0."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0


def test_help_shows_subcommands():
    """--help output must list available subcommands."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "generate" in result.output, "Expected 'generate' subcommand in help output"
    assert "status" in result.output, "Expected 'status' subcommand in help output"


def test_version_exits_zero():
    """uv run acemusic --version must exit with code 0."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0


def test_version_prints_version_string():
    """--version must print a non-empty version string."""
    result = runner.invoke(app, ["--version"])
    assert __version__ in result.output


def test_missing_api_url_produces_friendly_error(monkeypatch):
    """When ACEMUSIC_BASE_URL is not set, an ACE-Step command prints a friendly error.

    The check moved from the root callback into the command's ACE-Step path
    (#96), so a prompt argument is required to reach it.
    """
    monkeypatch.delenv("ACEMUSIC_BASE_URL", raising=False)
    from acemusic.config import AceConfig

    monkeypatch.setattr("acemusic.cli.load_config", lambda: AceConfig(api_url=None, api_key=None))

    result = runner.invoke(app, ["generate", "pop"])
    assert result.exit_code != 0
    assert "ACEMUSIC_BASE_URL" in result.output
    assert "traceback" not in result.output.lower()
    assert "Traceback" not in result.output


class TestModelsCommand:
    """Tests for US-3.4: acemusic models command."""

    def test_models_exits_zero(self):
        """acemusic models exits with code 0."""
        result = runner.invoke(app, ["models"])
        assert result.exit_code == 0

    def test_models_lists_all_variants(self):
        """acemusic models output contains all six ACE-Step model names."""
        result = runner.invoke(app, ["models"])
        assert result.exit_code == 0
        for name in ("turbo", "base", "sft", "xl-base", "xl-sft", "xl-turbo"):
            assert name in result.output, f"Expected model '{name}' in output"

    def test_models_shows_vram_info(self):
        """acemusic models output includes VRAM information."""
        result = runner.invoke(app, ["models"])
        assert result.exit_code == 0
        assert "GB" in result.output or "vram" in result.output.lower()

    def test_models_shows_inference_steps(self):
        """acemusic models output includes inference steps information."""
        result = runner.invoke(app, ["models"])
        assert result.exit_code == 0
        # Should show step counts like "8" for turbo or "32" for standard models
        assert any(s in result.output for s in ("8", "32", "64", "steps"))

    def test_models_works_without_api_url(self, monkeypatch):
        """acemusic models succeeds even when ACEMUSIC_BASE_URL is not configured."""
        monkeypatch.delenv("ACEMUSIC_BASE_URL", raising=False)
        from acemusic import config as cfg_mod

        monkeypatch.setattr(cfg_mod, "load_config", lambda: cfg_mod.AceConfig(api_url=None, api_key=None))
        result = runner.invoke(app, ["models"])
        assert result.exit_code == 0
        assert "turbo" in result.output


class TestElevenLabsBackendSkipsAceStepUrlCheck:
    """Explicit --backend elevenlabs must not require ACEMUSIC_BASE_URL (#96)."""

    def _no_ace_config(self, monkeypatch):
        from acemusic.config import AceConfig

        monkeypatch.setattr(
            "acemusic.cli.load_config",
            lambda: AceConfig(
                api_url=None,
                api_key=None,
                elevenlabs_api_key="test-key",
                elevenlabs_output_format="mp3_44100_128",
            ),
        )

    def test_generate_backend_elevenlabs_flag_skips_url_check(self, monkeypatch, tmp_path):
        from unittest.mock import MagicMock, patch

        self._no_ace_config(monkeypatch)
        el_mock = MagicMock()
        el_mock.generate.return_value = b"ID3" + b"\x00" * 100

        with (
            patch("acemusic.cli.ElevenLabsClient", return_value=el_mock),
            patch("acemusic.cli.get_duration", return_value=3.0),
        ):
            result = runner.invoke(app, ["generate", "pop", "--backend", "elevenlabs", "--output", str(tmp_path)])

        assert result.exit_code == 0, result.output
        assert "ACE-Step server URL" not in result.output

    def test_sounds_backend_elevenlabs_equals_form_skips_url_check(self, monkeypatch, tmp_path):
        from unittest.mock import MagicMock, patch

        self._no_ace_config(monkeypatch)
        el_mock = MagicMock()
        el_mock.generate.return_value = b"ID3" + b"\x00" * 100

        with (
            patch("acemusic.cli.ElevenLabsClient", return_value=el_mock),
            patch("acemusic.cli.get_duration", return_value=1.5),
        ):
            result = runner.invoke(
                app,
                ["sounds", "kick", "--type", "one-shot", "--backend=elevenlabs", "--output", str(tmp_path)],
            )

        assert result.exit_code == 0, result.output
        assert "ACE-Step server URL" not in result.output

    def test_generate_without_backend_still_requires_url(self, monkeypatch, tmp_path):
        self._no_ace_config(monkeypatch)

        result = runner.invoke(app, ["generate", "pop", "--output", str(tmp_path)])

        assert result.exit_code == 1
        assert "ACE-Step server URL" in result.output

    def test_generate_backend_ace_step_still_requires_url(self, monkeypatch, tmp_path):
        self._no_ace_config(monkeypatch)

        result = runner.invoke(app, ["generate", "pop", "--backend", "ace-step", "--output", str(tmp_path)])

        assert result.exit_code == 1
        assert "ACE-Step server URL" in result.output
