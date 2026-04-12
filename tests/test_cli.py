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
    """When ACEMUSIC_BASE_URL is not set, invoking a subcommand prints a friendly error."""
    monkeypatch.delenv("ACEMUSIC_BASE_URL", raising=False)
    # Ensure no .env or config file interferes by patching load_config
    from acemusic import config as cfg_mod

    def _no_url():
        return cfg_mod.AceConfig(api_url=None, api_key=None)

    monkeypatch.setattr(cfg_mod, "load_config", _no_url)

    result = runner.invoke(app, ["generate"])
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
