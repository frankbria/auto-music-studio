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
