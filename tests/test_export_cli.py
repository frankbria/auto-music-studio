"""Tests for the `acemusic export` CLI command (US-7.1)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from acemusic.cli import app
from acemusic.midi_client import MIDI_OUTPUT_LABELS
from acemusic.stems_client import STEM_LABELS

runner = CliRunner()

# Canonical stem filenames produced by `export --format stems`.
CANONICAL_STEMS = ("vocals", "drums", "bass", "other")


def _write_real_wav(path: Path, frames: int = 44100, sample_rate: int = 44100) -> None:
    import numpy as np
    import soundfile as sf

    data = np.zeros((frames, 2), dtype=np.float32)
    sf.write(str(path), data, sample_rate)


def _make_stems_client_factory():
    """Factory producing a mock StemsClient that writes real WAV stems on disk."""
    instance = MagicMock()
    instance.model_samplerate = 44100
    instance.separate.return_value = {label: MagicMock() for label in STEM_LABELS}

    def _save(stems, out_dir, base, **kw):
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        fmt = kw.get("output_format", "wav")
        paths = {}
        for label in STEM_LABELS:
            p = out_dir / f"{base}-{label}.{fmt}"
            _write_real_wav(p)
            paths[label] = p
        return paths

    instance.save_stems.side_effect = _save
    factory = MagicMock(return_value=instance)
    factory.instance = instance
    return factory


def _make_midi_client_factory():
    """Factory producing a mock MidiClient that writes real Type-1 MIDI on disk."""
    from acemusic.midi_client import MidiClient

    instance = MagicMock()
    instance.extract.return_value = {
        "melody": [(0.0, 0.5, 72, 100), (0.5, 1.0, 74, 90)],
        "chords": [(0.0, 1.0, 60, 80)],
        "drums": [(0.0, 0.1, 36, 127), (0.5, 0.6, 38, 100)],
        "bass": [(0.0, 1.0, 40, 100)],
    }
    real = MidiClient()
    instance.save_midi.side_effect = lambda data, out_dir, base, **kw: real.save_midi(data, out_dir, base, **kw)
    factory = MagicMock(return_value=instance)
    factory.instance = instance
    return factory


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    import acemusic.db as _db

    monkeypatch.setattr(_db, "DB_DIR", tmp_path / ".acemusic")
    return tmp_path


@pytest.fixture
def workspace_with_clip(isolated_db, write_tone):
    """Create an active workspace containing one real WAV clip on disk."""
    from acemusic.db import create_clip
    from acemusic.models import Clip
    from acemusic.workspace import ensure_default_workspace, get_active_workspace, get_workspace_path

    ensure_default_workspace()
    ws = get_active_workspace()
    clips_dir = get_workspace_path(ws.id)
    clips_dir.mkdir(parents=True, exist_ok=True)

    source = clips_dir / "source.wav"
    write_tone(source, duration_s=0.5)

    clip = Clip(
        workspace_id=ws.id,
        file_path=str(source),
        created_at=datetime.now(timezone.utc).isoformat(),
        title="My Cool Track",
        format="wav",
        duration=0.5,
    )
    clip_id = create_clip(clip)
    return ws, clip_id, source


class TestExportCommand:
    def test_unknown_clip_id_errors(self, isolated_db):
        result = runner.invoke(app, ["export", "999"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_missing_source_file_errors(self, workspace_with_clip):
        _, clip_id, source = workspace_with_clip
        source.unlink()
        result = runner.invoke(app, ["export", str(clip_id)])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_default_format_is_wav(self, workspace_with_clip, tmp_path, monkeypatch):
        _, clip_id, _ = workspace_with_clip
        monkeypatch.chdir(tmp_path)

        captured: dict = {}

        def fake_export(source, dest, fmt):
            captured["source"] = source
            captured["dest"] = dest
            captured["fmt"] = fmt
            Path(dest).write_bytes(b"fake")

        with patch("acemusic.cli.export_audio", side_effect=fake_export):
            result = runner.invoke(app, ["export", str(clip_id)])

        assert result.exit_code == 0, result.output
        assert captured["fmt"] == "wav"

    def test_default_filename_falls_back_to_clip_id_when_title_is_none(
        self, isolated_db, write_tone, tmp_path, monkeypatch
    ):
        """When the clip has no title, the default output filename uses `clip-<id>` instead."""
        from acemusic.db import create_clip
        from acemusic.models import Clip
        from acemusic.workspace import ensure_default_workspace, get_active_workspace, get_workspace_path

        ensure_default_workspace()
        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        clips_dir.mkdir(parents=True, exist_ok=True)
        source = clips_dir / "untitled.wav"
        write_tone(source, duration_s=0.5)

        clip_id = create_clip(
            Clip(
                workspace_id=ws.id,
                file_path=str(source),
                created_at=datetime.now(timezone.utc).isoformat(),
                title=None,
                format="wav",
                duration=0.5,
            )
        )

        monkeypatch.chdir(tmp_path)
        with patch("acemusic.cli.export_audio", side_effect=lambda s, d, f: Path(d).write_bytes(b"x")):
            result = runner.invoke(app, ["export", str(clip_id)])

        assert result.exit_code == 0, result.output
        assert (tmp_path / f"clip-{clip_id}.wav").exists()

    def test_default_output_path_uses_slugified_clip_title(self, workspace_with_clip, tmp_path, monkeypatch):
        _, clip_id, _ = workspace_with_clip
        monkeypatch.chdir(tmp_path)

        with patch("acemusic.cli.export_audio", side_effect=lambda s, d, f: Path(d).write_bytes(b"x")):
            result = runner.invoke(app, ["export", str(clip_id)])

        assert result.exit_code == 0, result.output
        expected = tmp_path / "my-cool-track.wav"
        assert expected.exists()

    def test_output_flag_uses_given_path(self, workspace_with_clip, tmp_path):
        _, clip_id, _ = workspace_with_clip
        dest = tmp_path / "subdir" / "custom-name.flac"
        dest.parent.mkdir(parents=True, exist_ok=True)

        with patch("acemusic.cli.export_audio", side_effect=lambda s, d, f: Path(d).write_bytes(b"x")) as mock_exp:
            result = runner.invoke(app, ["export", str(clip_id), "--format", "flac", "--output", str(dest)])

        assert result.exit_code == 0, result.output
        called_dest = mock_exp.call_args[0][1]
        assert Path(called_dest) == dest

    @pytest.mark.parametrize("fmt", ["wav", "wav32", "flac", "mp3"])
    def test_all_formats_passed_through(self, workspace_with_clip, tmp_path, monkeypatch, fmt):
        _, clip_id, _ = workspace_with_clip
        monkeypatch.chdir(tmp_path)

        captured: dict = {}

        def fake_export(source, dest, f):
            captured["fmt"] = f
            Path(dest).write_bytes(b"fake")

        with patch("acemusic.cli.export_audio", side_effect=fake_export):
            result = runner.invoke(app, ["export", str(clip_id), "--format", fmt])

        assert result.exit_code == 0, result.output
        assert captured["fmt"] == fmt

    def test_invalid_format_errors(self, workspace_with_clip):
        _, clip_id, _ = workspace_with_clip
        result = runner.invoke(app, ["export", str(clip_id), "--format", "ogg"])
        assert result.exit_code == 1
        assert "format" in result.output.lower()

    def test_default_output_extension_matches_format(self, workspace_with_clip, tmp_path, monkeypatch):
        """wav32 → .wav extension; other formats → matching extension."""
        _, clip_id, _ = workspace_with_clip
        monkeypatch.chdir(tmp_path)

        with patch("acemusic.cli.export_audio", side_effect=lambda s, d, f: Path(d).write_bytes(b"x")):
            result = runner.invoke(app, ["export", str(clip_id), "--format", "wav32"])
        assert result.exit_code == 0, result.output
        assert (tmp_path / "my-cool-track.wav").exists()

        with patch("acemusic.cli.export_audio", side_effect=lambda s, d, f: Path(d).write_bytes(b"x")):
            result = runner.invoke(app, ["export", str(clip_id), "--format", "mp3"])
        assert result.exit_code == 0, result.output
        assert (tmp_path / "my-cool-track.mp3").exists()

    def test_success_message_includes_path(self, workspace_with_clip, tmp_path, monkeypatch):
        _, clip_id, _ = workspace_with_clip
        monkeypatch.chdir(tmp_path)

        with patch("acemusic.cli.export_audio", side_effect=lambda s, d, f: Path(d).write_bytes(b"hello-bytes")):
            result = runner.invoke(app, ["export", str(clip_id)])

        assert result.exit_code == 0, result.output
        # Rich may soft-wrap the path on narrow terminals — strip newlines before substring check.
        flattened = result.output.replace("\n", "")
        assert "my-cool-track.wav" in flattened
        assert "Exported" in flattened

    def test_output_creates_missing_parent_directories(self, workspace_with_clip, tmp_path):
        """When --output points into a non-existent directory, the parent is created."""
        _, clip_id, _ = workspace_with_clip
        dest = tmp_path / "new" / "nested" / "out.flac"

        with patch("acemusic.cli.export_audio", side_effect=lambda s, d, f: Path(d).write_bytes(b"x")):
            result = runner.invoke(app, ["export", str(clip_id), "--format", "flac", "--output", str(dest)])

        assert result.exit_code == 0, result.output
        assert dest.parent.is_dir()

    def test_export_audio_failure_exits_one(self, workspace_with_clip, tmp_path, monkeypatch):
        _, clip_id, _ = workspace_with_clip
        monkeypatch.chdir(tmp_path)

        with patch("acemusic.cli.export_audio", side_effect=RuntimeError("ffmpeg blew up")):
            result = runner.invoke(app, ["export", str(clip_id)])

        assert result.exit_code == 1
        assert "ffmpeg blew up" in result.output or "error" in result.output.lower()


# ---------------------------------------------------------------------------
# US-7.4: stems-only and MIDI-only export
# ---------------------------------------------------------------------------


def _register_stem_children(ws_id, parent_id, source: Path):
    """Create four on-disk stem child clips so reuse can short-circuit separation."""
    from acemusic.db import create_clip
    from acemusic.models import Clip

    stems_dir = source.parent / "stems"
    stems_dir.mkdir(parents=True, exist_ok=True)
    for label in STEM_LABELS:
        path = stems_dir / f"{source.stem}-{label}.wav"
        _write_real_wav(path)
        create_clip(
            Clip(
                workspace_id=ws_id,
                file_path=str(path.resolve()),
                created_at=datetime.now(timezone.utc).isoformat(),
                format="wav",
                title=label,
                parent_clip_id=parent_id,
                generation_mode="stems",
            )
        )


def _register_midi_children(ws_id, parent_id, source: Path):
    """Create four on-disk MIDI child clips so reuse can short-circuit extraction."""
    from acemusic.db import create_clip
    from acemusic.midi_client import MidiClient
    from acemusic.models import Clip

    midi_dir = source.parent / "midi"
    midi_dir.mkdir(parents=True, exist_ok=True)
    real = MidiClient()
    written = real.save_midi(
        {label: [(0.0, 1.0, 60, 100)] for label in MIDI_OUTPUT_LABELS},
        midi_dir,
        source.stem,
    )
    for label in MIDI_OUTPUT_LABELS:
        create_clip(
            Clip(
                workspace_id=ws_id,
                file_path=str(Path(written[label]).resolve()),
                created_at=datetime.now(timezone.utc).isoformat(),
                format="mid",
                title=f"midi-{label}",
                parent_clip_id=parent_id,
                generation_mode="midi",
            )
        )


class TestStemsExport:
    def test_produces_four_wavs_no_midi_no_zip(self, workspace_with_clip, tmp_path):
        _, clip_id, _ = workspace_with_clip
        out = tmp_path / "stems_out"
        factory = _make_stems_client_factory()

        with patch("acemusic.cli.StemsClient", factory):
            result = runner.invoke(app, ["export", str(clip_id), "--format", "stems", "--output", str(out)])

        assert result.exit_code == 0, result.output
        wavs = sorted(p.name for p in out.glob("*.wav"))
        assert wavs == sorted(f"{s}.wav" for s in CANONICAL_STEMS)
        assert list(out.glob("*.mid")) == []
        assert list(out.glob("*.zip")) == []

    def test_auto_triggers_separation_when_no_children(self, workspace_with_clip, tmp_path):
        _, clip_id, _ = workspace_with_clip
        out = tmp_path / "stems_out"
        factory = _make_stems_client_factory()

        with patch("acemusic.cli.StemsClient", factory):
            result = runner.invoke(app, ["export", str(clip_id), "--format", "stems", "--output", str(out)])

        assert result.exit_code == 0, result.output
        factory.instance.separate.assert_called_once()

    def test_reuses_existing_children_without_separating(self, workspace_with_clip, tmp_path):
        ws, clip_id, source = workspace_with_clip
        _register_stem_children(ws.id, clip_id, source)
        out = tmp_path / "stems_out"
        factory = _make_stems_client_factory()

        with patch("acemusic.cli.StemsClient", factory):
            result = runner.invoke(app, ["export", str(clip_id), "--format", "stems", "--output", str(out)])

        assert result.exit_code == 0, result.output
        factory.instance.separate.assert_not_called()
        assert sorted(p.name for p in out.glob("*.wav")) == sorted(f"{s}.wav" for s in CANONICAL_STEMS)

    def test_default_output_dir_next_to_cwd(self, workspace_with_clip, tmp_path, monkeypatch):
        _, clip_id, _ = workspace_with_clip
        monkeypatch.chdir(tmp_path)
        factory = _make_stems_client_factory()

        with patch("acemusic.cli.StemsClient", factory):
            result = runner.invoke(app, ["export", str(clip_id), "--format", "stems"])

        assert result.exit_code == 0, result.output
        out = tmp_path / "my-cool-track-stems"
        assert out.is_dir()
        assert len(list(out.glob("*.wav"))) == 4

    def test_reuse_works_when_source_deleted(self, workspace_with_clip, tmp_path):
        """Cached stem children let export succeed even if the original mix is gone."""
        ws, clip_id, source = workspace_with_clip
        _register_stem_children(ws.id, clip_id, source)
        source.unlink()  # archive/cleanup scenario: only derived assets remain
        out = tmp_path / "stems_out"
        factory = _make_stems_client_factory()

        with patch("acemusic.cli.StemsClient", factory):
            result = runner.invoke(app, ["export", str(clip_id), "--format", "stems", "--output", str(out)])

        assert result.exit_code == 0, result.output
        factory.instance.separate.assert_not_called()
        assert sorted(p.name for p in out.glob("*.wav")) == sorted(f"{s}.wav" for s in CANONICAL_STEMS)

    def test_workspace_with_stems_rejected(self, workspace_with_clip):
        result = runner.invoke(app, ["export", "--workspace", "default", "--format", "stems"])
        assert result.exit_code == 1
        assert "single-clip" in result.output.lower() or "clip_id" in result.output.lower()


class TestMidiExport:
    def test_produces_four_midis_no_audio(self, workspace_with_clip, tmp_path):
        _, clip_id, _ = workspace_with_clip
        out = tmp_path / "midi_out"
        factory = _make_midi_client_factory()

        with patch("acemusic.cli.MidiClient", factory):
            result = runner.invoke(app, ["export", str(clip_id), "--format", "midi", "--output", str(out)])

        assert result.exit_code == 0, result.output
        mids = sorted(p.name for p in out.glob("*.mid"))
        assert mids == sorted(f"{m}.mid" for m in MIDI_OUTPUT_LABELS)
        assert list(out.glob("*.wav")) == []
        assert list(out.glob("*.zip")) == []

    def test_auto_triggers_extraction_when_no_children(self, workspace_with_clip, tmp_path):
        _, clip_id, _ = workspace_with_clip
        out = tmp_path / "midi_out"
        factory = _make_midi_client_factory()

        with patch("acemusic.cli.MidiClient", factory):
            result = runner.invoke(app, ["export", str(clip_id), "--format", "midi", "--output", str(out)])

        assert result.exit_code == 0, result.output
        factory.instance.extract.assert_called_once()

    def test_reuses_existing_children_without_extracting(self, workspace_with_clip, tmp_path):
        ws, clip_id, source = workspace_with_clip
        _register_midi_children(ws.id, clip_id, source)
        out = tmp_path / "midi_out"
        factory = _make_midi_client_factory()

        with patch("acemusic.cli.MidiClient", factory):
            result = runner.invoke(app, ["export", str(clip_id), "--format", "midi", "--output", str(out)])

        assert result.exit_code == 0, result.output
        factory.instance.extract.assert_not_called()
        assert sorted(p.name for p in out.glob("*.mid")) == sorted(f"{m}.mid" for m in MIDI_OUTPUT_LABELS)
