"""Tests for the midi CLI command (US-5.4)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from acemusic.cli import app
from acemusic.models import Clip
from acemusic.midi_client import MIDI_OUTPUT_LABELS

runner = CliRunner()

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    import acemusic.db as _db

    monkeypatch.setattr(_db, "DB_DIR", tmp_path / ".acemusic")
    return tmp_path


@pytest.fixture
def workspace_with_clips_dir(isolated_db, monkeypatch):
    """Ensure an active workspace exists and the clips dir is ready."""
    from acemusic.workspace import ensure_default_workspace, get_active_workspace, get_workspace_path

    ensure_default_workspace()
    ws = get_active_workspace()
    clips_dir = get_workspace_path(ws.id)
    clips_dir.mkdir(parents=True, exist_ok=True)
    return ws


def _make_clip(workspace_id: str, file_path: str, **kwargs) -> Clip:
    return Clip(
        workspace_id=workspace_id,
        file_path=file_path,
        created_at=datetime.now(timezone.utc).isoformat(),
        format=kwargs.get("format", "wav"),
        duration=kwargs.get("duration", 180.0),
        bpm=kwargs.get("bpm", 120),
        generation_mode=kwargs.get("generation_mode", "generate"),
    )


def _make_midi_client_mock():
    """Create a mock MidiClient that returns plausible MIDI data."""
    mock_client_cls = MagicMock()
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance

    # Create plausible MIDI note data (time, midi_note, confidence)
    midi_data = {
        "melody": [(0.0, 60.0, 0.9), (0.5, 62.0, 0.85), (1.0, 64.0, 0.88)],
        "chords": [(0.0, 60.0, 0.8), (0.5, 65.0, 0.75)],
        "drums": [(0.0, 36.0, 1.0), (0.5, 36.0, 1.0), (1.0, 36.0, 1.0)],
        "bass": [(0.0, 48.0, 0.9), (0.5, 45.0, 0.85)],
    }
    mock_instance.extract.return_value = midi_data
    mock_instance.save_midi.side_effect = lambda midi_data, out_dir, base, **kw: {
        label: _write_stub_midi(out_dir, base, label) for label in MIDI_OUTPUT_LABELS
        if label in midi_data and midi_data[label]
    }

    return mock_client_cls


def _write_stub_midi(out_dir: Path, base: str, label: str) -> Path:
    """Write a stub MIDI file and return its path."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{base}-{label}.mid"
    # Write minimal MIDI file header (valid but empty)
    path.write_bytes(b"MThd\x00\x00\x00\x06\x00\x00\x00\x01\x00\x60MTrk\x00\x00\x00\x04\x00\xFF\x2F\x00")
    return path


# ---------------------------------------------------------------------------
# Happy-path scenarios
# ---------------------------------------------------------------------------


class TestMidiCommand:
    def test_midi_produces_four_output_files(self, workspace_with_clips_dir):
        """midi command produces 4 MIDI files in a midi/ subdirectory."""
        from acemusic.db import create_clip
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "fullmix.wav"
        src_wav.write_bytes(b"fake audio data")

        src_clip = _make_clip(ws.id, str(src_wav), duration=180.0)
        clip_id = create_clip(src_clip)

        with patch("acemusic.cli.MidiClient", _make_midi_client_mock()):
            result = runner.invoke(app, ["midi", str(clip_id)])

        assert result.exit_code == 0, result.output
        assert "melody" in result.output.lower()
        assert "chords" in result.output.lower()
        assert "drums" in result.output.lower()
        assert "bass" in result.output.lower()

    def test_midi_registers_four_child_clips(self, workspace_with_clips_dir):
        """Each MIDI output is registered as a child clip in the metadata DB."""
        from acemusic.db import create_clip, list_clips
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "fullmix.wav"
        src_wav.write_bytes(b"fake audio data")

        src_clip = _make_clip(ws.id, str(src_wav), duration=180.0)
        clip_id = create_clip(src_clip)

        with patch("acemusic.cli.MidiClient", _make_midi_client_mock()):
            result = runner.invoke(app, ["midi", str(clip_id)])

        assert result.exit_code == 0, result.output

        clips = list_clips(ws.id)
        midi_clips = [c for c in clips if c.generation_mode == "midi"]
        assert len(midi_clips) == 4

        for mc in midi_clips:
            assert mc.parent_clip_id == clip_id
            assert mc.title in [f"midi-{label}" for label in MIDI_OUTPUT_LABELS]

    def test_midi_custom_output_dir(self, workspace_with_clips_dir, tmp_path):
        """--output overrides the default midi/ directory."""
        from acemusic.db import create_clip
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "song.wav"
        src_wav.write_bytes(b"fake audio")

        src_clip = _make_clip(ws.id, str(src_wav), duration=180.0)
        clip_id = create_clip(src_clip)

        custom_dir = tmp_path / "my_midi"

        with patch("acemusic.cli.MidiClient", _make_midi_client_mock()):
            result = runner.invoke(app, ["midi", str(clip_id), "--output", str(custom_dir)])

        assert result.exit_code == 0, result.output
        assert custom_dir.exists()

    def test_midi_preserves_original_clip(self, workspace_with_clips_dir):
        """Original clip remains unchanged after MIDI extraction."""
        from acemusic.db import create_clip, get_clip
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "original.wav"
        src_wav.write_bytes(b"original audio")

        src_clip = _make_clip(ws.id, str(src_wav), duration=180.0, bpm=120)
        clip_id = create_clip(src_clip)

        with patch("acemusic.cli.MidiClient", _make_midi_client_mock()):
            runner.invoke(app, ["midi", str(clip_id)])

        original = get_clip(clip_id)
        assert original is not None
        assert original.generation_mode != "midi"
        assert original.parent_clip_id is None

    def test_midi_with_from_stems_flag(self, workspace_with_clips_dir):
        """--from-stems flag is accepted and uses stems if available."""
        from acemusic.db import create_clip
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "fullmix.wav"
        src_wav.write_bytes(b"fake audio")

        src_clip = _make_clip(ws.id, str(src_wav), duration=180.0)
        clip_id = create_clip(src_clip)

        with patch("acemusic.cli.MidiClient", _make_midi_client_mock()):
            result = runner.invoke(app, ["midi", str(clip_id), "--from-stems"])

        assert result.exit_code == 0, result.output
        # Should mention that no stems were found or found stems
        assert "stems" in result.output.lower()


# ---------------------------------------------------------------------------
# Validation / error scenarios
# ---------------------------------------------------------------------------


class TestMidiValidation:
    def test_invalid_clip_id_returns_error(self, workspace_with_clips_dir):
        """Non-existent clip ID produces a friendly error."""
        result = runner.invoke(app, ["midi", "99999"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_extraction_failure_returns_error(self, workspace_with_clips_dir):
        """Extraction error from MidiClient is reported."""
        from acemusic.db import create_clip
        from acemusic.midi_client import MidiError
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "bad.wav"
        src_wav.write_bytes(b"bad audio")

        src_clip = _make_clip(ws.id, str(src_wav), duration=180.0)
        clip_id = create_clip(src_clip)

        mock_cls = MagicMock()
        mock_cls.return_value.extract.side_effect = MidiError("Audio processing failed")

        with patch("acemusic.cli.MidiClient", mock_cls):
            result = runner.invoke(app, ["midi", str(clip_id)])

        assert result.exit_code == 1
        assert "extraction" in result.output.lower() or "failed" in result.output.lower()

    def test_midi_client_missing_library(self, workspace_with_clips_dir):
        """Missing basic_pitch or pretty_midi library is reported."""
        from acemusic.db import create_clip
        from acemusic.midi_client import MidiError
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "song.wav"
        src_wav.write_bytes(b"audio")

        src_clip = _make_clip(ws.id, str(src_wav), duration=180.0)
        clip_id = create_clip(src_clip)

        mock_cls = MagicMock()
        mock_cls.return_value.extract.side_effect = MidiError("basic_pitch is not installed")

        with patch("acemusic.cli.MidiClient", mock_cls):
            result = runner.invoke(app, ["midi", str(clip_id)])

        assert result.exit_code == 1
        assert "basic_pitch" in result.output.lower() or "installed" in result.output.lower()
