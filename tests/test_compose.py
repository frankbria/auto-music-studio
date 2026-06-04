"""Unit tests for the acemusic compose command (issue #96)."""

import re
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from acemusic.cli import app
from acemusic.elevenlabs_client import ElevenLabsError

runner = CliRunner()

FAKE_MP3 = b"ID3" + b"\x00" * 100

FAKE_PLAN = {
    "positive_global_styles": ["upbeat pop", "120 BPM"],
    "negative_global_styles": ["metal"],
    "sections": [
        {
            "section_name": "Intro",
            "positive_local_styles": ["atmospheric build"],
            "negative_local_styles": ["vocals"],
            "duration_ms": 8000,
            "lines": [],
        },
        {
            "section_name": "Chorus",
            "positive_local_styles": ["hook", "energetic"],
            "negative_local_styles": [],
            "duration_ms": 16000,
            "lines": ["Breaking through", "Nothing stops me now"],
        },
    ],
}


def _plain(text: str) -> str:
    """Strip ANSI escape codes from text (Rich emits these in CI environments)."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _el_config(monkeypatch, api_key="test-key"):
    """Point load_config at an ElevenLabs-enabled config."""
    from acemusic.config import AceConfig

    monkeypatch.setattr(
        "acemusic.cli.load_config",
        lambda: AceConfig(
            api_url="http://localhost:8001",
            api_key=None,
            elevenlabs_api_key=api_key,
            elevenlabs_output_format="mp3_44100_128",
        ),
    )


def _el_mock():
    el = MagicMock()
    el.create_plan.return_value = FAKE_PLAN
    el.generate_from_plan.return_value = FAKE_MP3
    return el


class TestComposeCommand:
    """Tests for the compose command happy path."""

    def test_compose_writes_mp3_and_displays_sections(self, monkeypatch, tmp_path):
        """compose creates a plan, shows its sections, and writes the MP3."""
        import acemusic.db as _db

        monkeypatch.setattr(_db, "DB_DIR", tmp_path / ".acemusic")
        _el_config(monkeypatch)
        el = _el_mock()

        with (
            patch("acemusic.cli.ElevenLabsClient", return_value=el),
            patch("acemusic.cli.get_duration", return_value=24.0),
        ):
            result = runner.invoke(app, ["compose", "an upbeat pop anthem", "--output", str(tmp_path)])

        assert result.exit_code == 0, result.output
        mp3_files = list(tmp_path.glob("*.mp3"))
        assert len(mp3_files) == 1
        assert mp3_files[0].read_bytes() == FAKE_MP3
        plain = _plain(result.output)
        assert "Intro" in plain
        assert "Chorus" in plain

    def test_compose_forwards_prompt_and_duration_to_create_plan(self, monkeypatch, tmp_path):
        """The prompt and --duration are forwarded to create_plan()."""
        import acemusic.db as _db

        monkeypatch.setattr(_db, "DB_DIR", tmp_path / ".acemusic")
        _el_config(monkeypatch)
        el = _el_mock()

        with (
            patch("acemusic.cli.ElevenLabsClient", return_value=el),
            patch("acemusic.cli.get_duration", return_value=120.0),
        ):
            result = runner.invoke(
                app, ["compose", "an upbeat pop anthem", "--duration", "120", "--output", str(tmp_path)]
            )

        assert result.exit_code == 0, result.output
        kwargs = el.create_plan.call_args.kwargs
        assert kwargs["prompt"] == "an upbeat pop anthem"
        assert kwargs["duration"] == 120.0

    def test_compose_generates_from_the_created_plan(self, monkeypatch, tmp_path):
        """The plan returned by create_plan() is passed to generate_from_plan()."""
        import acemusic.db as _db

        monkeypatch.setattr(_db, "DB_DIR", tmp_path / ".acemusic")
        _el_config(monkeypatch)
        el = _el_mock()

        with (
            patch("acemusic.cli.ElevenLabsClient", return_value=el),
            patch("acemusic.cli.get_duration", return_value=24.0),
        ):
            result = runner.invoke(app, ["compose", "anthem", "--output", str(tmp_path)])

        assert result.exit_code == 0, result.output
        assert el.generate_from_plan.call_args.kwargs["composition_plan"] == FAKE_PLAN

    def test_compose_seed_forwarded_to_generate_from_plan(self, monkeypatch, tmp_path):
        """--seed is forwarded to generate_from_plan() (plan mode supports seeds)."""
        import acemusic.db as _db

        monkeypatch.setattr(_db, "DB_DIR", tmp_path / ".acemusic")
        _el_config(monkeypatch)
        el = _el_mock()

        with (
            patch("acemusic.cli.ElevenLabsClient", return_value=el),
            patch("acemusic.cli.get_duration", return_value=24.0),
        ):
            result = runner.invoke(app, ["compose", "anthem", "--seed", "42", "--output", str(tmp_path)])

        assert result.exit_code == 0, result.output
        assert el.generate_from_plan.call_args.kwargs["seed"] == 42

    def test_compose_instrumental_appended_to_plan_prompt(self, monkeypatch, tmp_path):
        """--instrumental steers the plan prompt (force_instrumental is prompt-mode-only)."""
        import acemusic.db as _db

        monkeypatch.setattr(_db, "DB_DIR", tmp_path / ".acemusic")
        _el_config(monkeypatch)
        el = _el_mock()

        with (
            patch("acemusic.cli.ElevenLabsClient", return_value=el),
            patch("acemusic.cli.get_duration", return_value=24.0),
        ):
            result = runner.invoke(app, ["compose", "anthem", "--instrumental", "--output", str(tmp_path)])

        assert result.exit_code == 0, result.output
        prompt_sent = el.create_plan.call_args.kwargs["prompt"]
        assert "instrumental" in prompt_sent.lower()

    def test_compose_saves_clip_with_compose_mode(self, monkeypatch, tmp_path):
        """A Clip record is created with generation_mode='compose' and model='elevenlabs'."""
        import acemusic.db as _db

        monkeypatch.setattr(_db, "DB_DIR", tmp_path / ".acemusic")
        _el_config(monkeypatch)
        el = _el_mock()

        with (
            patch("acemusic.cli.ElevenLabsClient", return_value=el),
            patch("acemusic.cli.get_duration", return_value=24.0),
        ):
            result = runner.invoke(app, ["compose", "an upbeat pop anthem", "--output", str(tmp_path)])

        assert result.exit_code == 0, result.output

        from acemusic.db import list_clips
        from acemusic.workspace import get_active_workspace

        clips = list_clips(get_active_workspace().id)
        assert len(clips) == 1
        clip = clips[0]
        assert clip.generation_mode == "compose"
        assert clip.model == "elevenlabs"
        assert clip.format == "mp3"
        assert clip.duration == 24.0

    def test_compose_name_flag_used_for_filename(self, monkeypatch, tmp_path):
        """--name produces a prefixed filename."""
        import acemusic.db as _db

        monkeypatch.setattr(_db, "DB_DIR", tmp_path / ".acemusic")
        _el_config(monkeypatch)
        el = _el_mock()

        with (
            patch("acemusic.cli.ElevenLabsClient", return_value=el),
            patch("acemusic.cli.get_duration", return_value=24.0),
        ):
            result = runner.invoke(app, ["compose", "anthem", "--name", "My Theme", "--output", str(tmp_path)])

        assert result.exit_code == 0, result.output
        assert (tmp_path / "my-theme.mp3").exists()


class TestComposeValidation:
    """Tests for compose command validation and error handling."""

    def test_compose_requires_api_key(self, monkeypatch, tmp_path):
        """Without ELEVENLABS_API_KEY, compose exits 1 with a clear message."""
        _el_config(monkeypatch, api_key=None)

        result = runner.invoke(app, ["compose", "anthem", "--output", str(tmp_path)])

        assert result.exit_code == 1
        assert "elevenlabs_api_key" in _plain(result.output).lower()

    def test_compose_rejects_out_of_range_duration(self, monkeypatch, tmp_path):
        """Durations outside 3–600s exit 1 with the valid range in the message."""
        _el_config(monkeypatch)
        el = _el_mock()

        with patch("acemusic.cli.ElevenLabsClient", return_value=el):
            result = runner.invoke(app, ["compose", "anthem", "--duration", "601", "--output", str(tmp_path)])

        assert result.exit_code == 1
        plain = _plain(result.output)
        assert "3" in plain and "600" in plain
        el.create_plan.assert_not_called()

    def test_compose_plan_error_exits_one(self, monkeypatch, tmp_path):
        """An ElevenLabsError during plan creation exits 1."""
        _el_config(monkeypatch)
        el = _el_mock()
        el.create_plan.side_effect = ElevenLabsError("ElevenLabs plan creation failed: 422")

        with patch("acemusic.cli.ElevenLabsClient", return_value=el):
            result = runner.invoke(app, ["compose", "anthem", "--output", str(tmp_path)])

        assert result.exit_code == 1
        assert "422" in _plain(result.output)

    def test_compose_generation_error_exits_one(self, monkeypatch, tmp_path):
        """An ElevenLabsError during generation exits 1."""
        _el_config(monkeypatch)
        el = _el_mock()
        el.generate_from_plan.side_effect = ElevenLabsError("ElevenLabs plan generation failed: 500")

        with patch("acemusic.cli.ElevenLabsClient", return_value=el):
            result = runner.invoke(app, ["compose", "anthem", "--output", str(tmp_path)])

        assert result.exit_code == 1
        assert "500" in _plain(result.output)

    def test_compose_appears_in_help(self):
        """compose is registered on the root app."""
        result = runner.invoke(app, ["--help"])
        assert "compose" in _plain(result.output)
