"""Characterization tests for cli.py shared helpers (US-15.4).

These lock the byte-for-byte behavior of the extracted helpers so the refactor
that replaces the inline duplicates cannot drift.
"""

import io

import pytest
from rich.console import Console

import acemusic.cli as cli
from acemusic.cli import _build_elevenlabs_prompt, _render_table


@pytest.fixture
def captured_console(monkeypatch):
    """Replace cli.console with a wide, non-terminal console we can read back."""
    buf = io.StringIO()
    console = Console(file=buf, width=200, force_terminal=False, no_color=True)
    monkeypatch.setattr(cli, "console", console)
    return buf


class TestBuildElevenlabsPrompt:
    """Mirrors the two inline injection blocks (generate + sounds)."""

    def test_no_params_returns_prompt_unchanged(self, captured_console):
        assert _build_elevenlabs_prompt("pop", bpm=None, key=None) == "pop"
        assert captured_console.getvalue() == ""

    def test_generate_style_all_fields(self, captured_console):
        result = _build_elevenlabs_prompt(
            "pop",
            bpm=120,
            key="C major",
            time_signature="4/4",
            vocal_language=None,
            term="specific",
            warn_skip=True,
        )
        assert result == "pop, 120 BPM, C major, 4/4 time signature"
        out = captured_console.getvalue()
        assert "--bpm is ACE-Step-specific; injecting '120 BPM'" in out
        assert "--key is ACE-Step-specific; injecting 'C major'" in out
        assert "--time-signature is ACE-Step-specific; injecting '4/4 time signature'" in out

    def test_generate_auto_and_any_emit_skip_warnings(self, captured_console):
        result = _build_elevenlabs_prompt("pop", bpm="auto", key="any", term="specific", warn_skip=True)
        assert result == "pop"
        out = captured_console.getvalue()
        assert "--bpm auto has no ElevenLabs equivalent" in out
        assert "--key any has no ElevenLabs equivalent" in out

    def test_sounds_style_prefix_native_no_skip_warnings(self, captured_console):
        result = _build_elevenlabs_prompt(
            "808 kick",
            bpm="auto",
            key="any",
            term="native",
            warn_skip=False,
            prefix=["drum sample"],
        )
        # auto/any inject nothing and (warn_skip=False) emit no skip notices,
        # but the prefix is always present.
        assert result == "808 kick, drum sample"
        out = captured_console.getvalue()
        assert "has no ElevenLabs equivalent" not in out

    def test_sounds_style_native_wording(self, captured_console):
        result = _build_elevenlabs_prompt(
            "808 kick",
            bpm=90,
            key="A minor",
            term="native",
            warn_skip=False,
            prefix=["drum sample"],
        )
        assert result == "808 kick, drum sample, 90 BPM, A minor"
        out = captured_console.getvalue()
        assert "--bpm is ACE-Step-native; injecting '90 BPM'" in out
        assert "--key is ACE-Step-native; injecting 'A minor'" in out


class TestRenderTable:
    """Confirms data-shape and detail-shape tables render their content."""

    def test_data_shape_table(self, captured_console):
        _render_table(
            title="Workspaces",
            show_header=True,
            columns=[("Name", {"style": "cyan"}), ("Clips", {"justify": "right"})],
            rows=[("alpha", "3"), ("beta", "0")],
        )
        out = captured_console.getvalue()
        assert "Workspaces" in out
        assert "alpha" in out and "beta" in out

    def test_detail_shape_table(self, captured_console):
        _render_table(
            columns=[("Key", {"style": "bold"}), ("Value", {})],
            rows=[("Server URL", "http://x"), ("Active jobs", "2")],
            show_header=False,
            box=None,
            padding=(0, 1),
        )
        out = captured_console.getvalue()
        assert "Server URL" in out and "http://x" in out
        assert "Active jobs" in out and "2" in out
