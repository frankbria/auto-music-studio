"""Tests for the stems CLI command (US-5.3)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from acemusic.cli import app
from acemusic.models import Clip
from acemusic.stems_client import STEM_LABELS

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


def _make_stems_client_mock():
    """Create a mock StemsClient that returns plausible stem data."""
    import torch

    mock_client_cls = MagicMock()
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance

    stems = {label: torch.randn(2, 44100) for label in STEM_LABELS}
    mock_instance.separate.return_value = stems
    mock_instance.save_stems.side_effect = lambda stems, out_dir, base, **kw: [
        _write_stub_stem(out_dir, base, label, kw.get("output_format", "wav")) for label in STEM_LABELS
    ]

    return mock_client_cls


def _write_stub_stem(out_dir: Path, base: str, label: str, fmt: str) -> Path:
    """Write a stub stem file and return its path."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{base}-{label}.{fmt}"
    path.write_bytes(b"fake stem audio")
    return path


# ---------------------------------------------------------------------------
# Happy-path scenarios
# ---------------------------------------------------------------------------


class TestStemsCommand:
    def test_stems_produces_four_output_files(self, workspace_with_clips_dir):
        """stems command produces 4 stem files in a stems/ subdirectory."""
        from acemusic.db import create_clip
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "fullmix.wav"
        src_wav.write_bytes(b"fake audio data")

        src_clip = _make_clip(ws.id, str(src_wav), duration=180.0)
        clip_id = create_clip(src_clip)

        with patch("acemusic.cli.StemsClient", _make_stems_client_mock()):
            with patch("acemusic.cli.get_duration", return_value=180.0):
                result = runner.invoke(app, ["stems", str(clip_id)])

        assert result.exit_code == 0, result.output
        assert "vocals" in result.output.lower()
        assert "drums" in result.output.lower()
        assert "bass" in result.output.lower()
        assert "other" in result.output.lower()

    def test_stems_registers_four_child_clips(self, workspace_with_clips_dir):
        """Each stem is registered as a child clip in the metadata DB."""
        from acemusic.db import create_clip, list_clips
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "fullmix.wav"
        src_wav.write_bytes(b"fake audio data")

        src_clip = _make_clip(ws.id, str(src_wav), duration=180.0)
        clip_id = create_clip(src_clip)

        with patch("acemusic.cli.StemsClient", _make_stems_client_mock()):
            with patch("acemusic.cli.get_duration", return_value=180.0):
                result = runner.invoke(app, ["stems", str(clip_id)])

        assert result.exit_code == 0, result.output

        clips = list_clips(ws.id)
        stem_clips = [c for c in clips if c.generation_mode == "stems"]
        assert len(stem_clips) == 4

        for sc in stem_clips:
            assert sc.parent_clip_id == clip_id
            assert sc.title in STEM_LABELS

    def test_stems_flac_output_format(self, workspace_with_clips_dir):
        """--output-format flac produces FLAC stem files."""
        from acemusic.db import create_clip
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "song.wav"
        src_wav.write_bytes(b"fake audio")

        src_clip = _make_clip(ws.id, str(src_wav), duration=180.0)
        clip_id = create_clip(src_clip)

        with patch("acemusic.cli.StemsClient", _make_stems_client_mock()):
            with patch("acemusic.cli.get_duration", return_value=180.0):
                result = runner.invoke(app, ["stems", str(clip_id), "--output-format", "flac"])

        assert result.exit_code == 0, result.output
        assert ".flac" in result.output

    def test_stems_custom_output_dir(self, workspace_with_clips_dir, tmp_path):
        """--output overrides the default stems/ directory."""
        from acemusic.db import create_clip
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "song.wav"
        src_wav.write_bytes(b"fake audio")

        src_clip = _make_clip(ws.id, str(src_wav), duration=180.0)
        clip_id = create_clip(src_clip)

        custom_dir = tmp_path / "my_stems"

        with patch("acemusic.cli.StemsClient", _make_stems_client_mock()):
            with patch("acemusic.cli.get_duration", return_value=180.0):
                result = runner.invoke(app, ["stems", str(clip_id), "--output", str(custom_dir)])

        assert result.exit_code == 0, result.output
        assert custom_dir.exists()

    def test_stems_preserves_original_clip(self, workspace_with_clips_dir):
        """Original clip remains unchanged after stem separation."""
        from acemusic.db import create_clip, get_clip
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "original.wav"
        src_wav.write_bytes(b"original audio")

        src_clip = _make_clip(ws.id, str(src_wav), duration=180.0, bpm=120)
        clip_id = create_clip(src_clip)

        with patch("acemusic.cli.StemsClient", _make_stems_client_mock()):
            with patch("acemusic.cli.get_duration", return_value=180.0):
                runner.invoke(app, ["stems", str(clip_id)])

        original = get_clip(clip_id)
        assert original is not None
        assert original.generation_mode != "stems"
        assert original.parent_clip_id is None


# ---------------------------------------------------------------------------
# Validation / error scenarios
# ---------------------------------------------------------------------------


class TestStemsValidation:
    def test_invalid_clip_id_returns_error(self, workspace_with_clips_dir):
        """Non-existent clip ID produces a friendly error."""
        result = runner.invoke(app, ["stems", "99999"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_separation_failure_returns_error(self, workspace_with_clips_dir):
        """Separation error from StemsClient is reported."""
        from acemusic.db import create_clip
        from acemusic.stems_client import StemsError
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "bad.wav"
        src_wav.write_bytes(b"bad audio")

        src_clip = _make_clip(ws.id, str(src_wav), duration=180.0)
        clip_id = create_clip(src_clip)

        mock_cls = MagicMock()
        mock_cls.return_value.separate.side_effect = StemsError("CUDA OOM")

        with patch("acemusic.cli.StemsClient", mock_cls):
            result = runner.invoke(app, ["stems", str(clip_id)])

        assert result.exit_code == 1
        assert "cuda oom" in result.output.lower() or "separation" in result.output.lower()

    def test_invalid_output_format_returns_error(self, workspace_with_clips_dir):
        """Unsupported output format is rejected."""
        from acemusic.db import create_clip
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "song.wav"
        src_wav.write_bytes(b"audio")

        src_clip = _make_clip(ws.id, str(src_wav), duration=180.0)
        clip_id = create_clip(src_clip)

        result = runner.invoke(app, ["stems", str(clip_id), "--output-format", "mp3"])
        assert result.exit_code == 1
        assert "wav" in result.output.lower() and "flac" in result.output.lower()
