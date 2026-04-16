"""Tests for the remaster CLI command (US-5.5)."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest
import soundfile as sf
from typer.testing import CliRunner

from acemusic.cli import app
from acemusic.models import Clip

runner = CliRunner()


def _make_test_wav(path, amplitude=0.3, duration_s=1.0, sample_rate=44100):
    """Create a minimal valid WAV file for testing."""
    t = np.linspace(0, duration_s, int(sample_rate * duration_s), endpoint=False)
    mono = (amplitude * np.sin(2 * np.pi * 440.0 * t)).astype(np.float64)
    stereo = np.column_stack([mono, mono])
    sf.write(str(path), stereo, sample_rate)


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    import acemusic.db as _db

    monkeypatch.setattr(_db, "DB_DIR", tmp_path / ".acemusic")
    return tmp_path


@pytest.fixture
def workspace_with_clip(isolated_db):
    """Set up a workspace with a single clip for remaster testing."""
    from acemusic.db import create_clip
    from acemusic.workspace import ensure_default_workspace, get_active_workspace, get_workspace_path

    ensure_default_workspace()
    ws = get_active_workspace()
    clips_dir = get_workspace_path(ws.id)
    clips_dir.mkdir(parents=True, exist_ok=True)

    src_wav = clips_dir / "source.wav"
    _make_test_wav(src_wav, amplitude=0.3, duration_s=1.0)

    clip = Clip(
        workspace_id=ws.id,
        file_path=str(src_wav),
        created_at=datetime.now(timezone.utc).isoformat(),
        format="wav",
        duration=1.0,
        generation_mode="generate",
    )
    clip_id = create_clip(clip)
    return ws, clip_id, src_wav


class TestRemasterCommand:
    def test_successful_remaster(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        result = runner.invoke(app, ["remaster", str(clip_id)])
        assert result.exit_code == 0, result.output
        assert "remaster" in result.output.lower() or "LUFS" in result.output

    def test_creates_child_clip_in_db(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        result = runner.invoke(app, ["remaster", str(clip_id)])
        assert result.exit_code == 0, result.output

        from acemusic.db import list_clips

        clips = list_clips(ws.id)
        remastered = [c for c in clips if c.generation_mode == "remaster"]
        assert len(remastered) == 1
        assert remastered[0].parent_clip_id == clip_id

    def test_target_lufs_option(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        result = runner.invoke(app, ["remaster", str(clip_id), "--target-lufs", "-12"])
        assert result.exit_code == 0, result.output

    def test_output_option(self, workspace_with_clip, tmp_path):
        ws, clip_id, src_wav = workspace_with_clip
        output_path = tmp_path / "custom_output.wav"
        result = runner.invoke(app, ["remaster", str(clip_id), "--output", str(output_path)])
        assert result.exit_code == 0, result.output
        assert output_path.exists()

    def test_original_file_unchanged(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        original_bytes = src_wav.read_bytes()
        result = runner.invoke(app, ["remaster", str(clip_id)])
        assert result.exit_code == 0, result.output
        assert src_wav.read_bytes() == original_bytes


class TestRemasterValidation:
    def test_nonexistent_clip_returns_error(self, isolated_db):
        from acemusic.workspace import ensure_default_workspace

        ensure_default_workspace()
        result = runner.invoke(app, ["remaster", "99999"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_unsupported_format_returns_error(self, isolated_db):
        from acemusic.db import create_clip
        from acemusic.workspace import ensure_default_workspace, get_active_workspace, get_workspace_path

        ensure_default_workspace()
        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        clips_dir.mkdir(parents=True, exist_ok=True)

        txt_file = clips_dir / "not_audio.txt"
        txt_file.write_text("this is not audio")

        clip = Clip(
            workspace_id=ws.id,
            file_path=str(txt_file),
            created_at=datetime.now(timezone.utc).isoformat(),
            format="txt",
            duration=10.0,
            generation_mode="upload",
        )
        clip_id = create_clip(clip)

        result = runner.invoke(app, ["remaster", str(clip_id)])
        assert result.exit_code == 1
        assert "unsupported" in result.output.lower() or "format" in result.output.lower()

    def test_missing_file_returns_error(self, isolated_db):
        from acemusic.db import create_clip
        from acemusic.workspace import ensure_default_workspace, get_active_workspace

        ensure_default_workspace()
        ws = get_active_workspace()

        clip = Clip(
            workspace_id=ws.id,
            file_path="/nonexistent/path/audio.wav",
            created_at=datetime.now(timezone.utc).isoformat(),
            format="wav",
            duration=10.0,
            generation_mode="generate",
        )
        clip_id = create_clip(clip)

        result = runner.invoke(app, ["remaster", str(clip_id)])
        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "exist" in result.output.lower()
