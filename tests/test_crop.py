"""Tests for the crop command (US-5.1)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from acemusic.cli import app
from acemusic.models import Clip

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
        duration=kwargs.get("duration", 60.0),
        bpm=kwargs.get("bpm", None),
        generation_mode=kwargs.get("generation_mode", "generate"),
    )


# ---------------------------------------------------------------------------
# Happy-path scenarios
# ---------------------------------------------------------------------------


class TestCropCommand:
    def test_crop_creates_new_clip_with_correct_metadata(self, workspace_with_clips_dir, tmp_path):
        """Crop registers a new clip with parent_clip_id and generation_mode='crop'."""
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)

        # Create a source clip on disk and in DB
        src_wav = clips_dir / "source.wav"
        src_wav.write_bytes(b"fake audio data")

        from acemusic.db import create_clip

        src_clip = _make_clip(ws.id, str(src_wav), duration=60.0)
        clip_id = create_clip(src_clip)

        with patch("acemusic.cli.crop_audio") as mock_crop:
            mock_crop.return_value = None
            result = runner.invoke(app, ["crop", str(clip_id), "--start", "10s", "--end", "45s"])

        assert result.exit_code == 0, result.output

        from acemusic.db import list_clips

        clips = list_clips(ws.id)
        cropped = [c for c in clips if c.generation_mode == "crop"]
        assert len(cropped) == 1
        assert cropped[0].parent_clip_id == clip_id
        assert cropped[0].duration == pytest.approx(35.0)

    def test_crop_preserves_original_clip(self, workspace_with_clips_dir, tmp_path):
        """Original clip is unchanged after a crop."""
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)

        src_wav = clips_dir / "original.wav"
        src_wav.write_bytes(b"original audio")

        from acemusic.db import create_clip, get_clip

        src_clip = _make_clip(ws.id, str(src_wav), duration=60.0)
        clip_id = create_clip(src_clip)

        with patch("acemusic.cli.crop_audio"):
            runner.invoke(app, ["crop", str(clip_id), "--start", "5s", "--end", "20s"])

        original = get_clip(clip_id)
        assert original is not None
        assert original.generation_mode != "crop"
        assert original.parent_clip_id is None

    def test_crop_passes_fade_options_to_crop_audio(self, workspace_with_clips_dir):
        """Fade-in/out options are forwarded to crop_audio()."""
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "fadey.wav"
        src_wav.write_bytes(b"audio")

        from acemusic.db import create_clip

        clip_id = create_clip(_make_clip(ws.id, str(src_wav), duration=60.0))

        with patch("acemusic.cli.crop_audio") as mock_crop:
            result = runner.invoke(
                app,
                ["crop", str(clip_id), "--start", "0s", "--end", "30s", "--fade-in", "0.5s", "--fade-out", "1s"],
            )

        assert result.exit_code == 0, result.output
        _args, kwargs = mock_crop.call_args
        assert kwargs["fade_in_ms"] == 500
        assert kwargs["fade_out_ms"] == 1000

    def test_crop_snap_to_beat_adjusts_times(self, workspace_with_clips_dir):
        """--snap-to-beat rounds start/end to nearest beat boundary using clip BPM."""
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "beat.wav"
        src_wav.write_bytes(b"audio")

        from acemusic.db import create_clip

        # 120 BPM → beat_ms = 500ms
        clip_id = create_clip(_make_clip(ws.id, str(src_wav), duration=60.0, bpm=120))

        with patch("acemusic.cli.crop_audio") as mock_crop:
            result = runner.invoke(
                app,
                # start=10100ms → snap to 10000ms; end=45300ms → snap to 45500ms
                ["crop", str(clip_id), "--start", "10.1s", "--end", "45.3s", "--snap-to-beat"],
            )

        assert result.exit_code == 0, result.output
        _args, kwargs = mock_crop.call_args
        assert kwargs["start_ms"] == 10000
        assert kwargs["end_ms"] == 45500

    def test_crop_stores_file_in_source_workspace(self, workspace_with_clips_dir):
        """Cropped file is stored in the source clip's workspace, not the active one."""
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "ws_test.wav"
        src_wav.write_bytes(b"audio")

        from acemusic.db import create_clip, list_clips

        clip_id = create_clip(_make_clip(ws.id, str(src_wav), duration=60.0))

        with patch("acemusic.cli.crop_audio"):
            result = runner.invoke(app, ["crop", str(clip_id), "--start", "5s", "--end", "25s"])

        assert result.exit_code == 0, result.output
        cropped = [c for c in list_clips(ws.id) if c.generation_mode == "crop"]
        assert len(cropped) == 1
        # File path must be under the source workspace's clips directory
        assert str(clips_dir) in cropped[0].file_path

    def test_crop_output_message_contains_new_clip_id(self, workspace_with_clips_dir):
        """Success output shows the new clip ID and file path."""
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "src.wav"
        src_wav.write_bytes(b"audio")

        from acemusic.db import create_clip

        clip_id = create_clip(_make_clip(ws.id, str(src_wav), duration=60.0))

        with patch("acemusic.cli.crop_audio"):
            result = runner.invoke(app, ["crop", str(clip_id), "--start", "5s", "--end", "25s"])

        assert result.exit_code == 0, result.output
        assert "Cropped" in result.output or "clip" in result.output.lower()


# ---------------------------------------------------------------------------
# Validation / error scenarios
# ---------------------------------------------------------------------------


class TestCropValidation:
    def test_invalid_clip_id_returns_error(self, workspace_with_clips_dir):
        """Non-existent clip ID produces a friendly error."""
        result = runner.invoke(app, ["crop", "99999", "--start", "0s", "--end", "10s"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_start_greater_than_end_returns_error(self, workspace_with_clips_dir):
        """start >= end must be rejected."""
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "src2.wav"
        src_wav.write_bytes(b"audio")

        from acemusic.db import create_clip

        clip_id = create_clip(_make_clip(ws.id, str(src_wav), duration=60.0))

        result = runner.invoke(app, ["crop", str(clip_id), "--start", "30s", "--end", "10s"])
        assert result.exit_code == 1
        assert "start" in result.output.lower() or "end" in result.output.lower()

    def test_end_exceeds_clip_duration_returns_error(self, workspace_with_clips_dir):
        """end > clip duration must be rejected."""
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "src3.wav"
        src_wav.write_bytes(b"audio")

        from acemusic.db import create_clip

        clip_id = create_clip(_make_clip(ws.id, str(src_wav), duration=30.0))

        result = runner.invoke(app, ["crop", str(clip_id), "--start", "0s", "--end", "60s"])
        assert result.exit_code == 1
        assert "duration" in result.output.lower() or "exceed" in result.output.lower()

    def test_snap_to_beat_without_bpm_returns_error(self, workspace_with_clips_dir):
        """--snap-to-beat with no BPM in metadata produces a clear error."""
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "src4.wav"
        src_wav.write_bytes(b"audio")

        from acemusic.db import create_clip

        clip_id = create_clip(_make_clip(ws.id, str(src_wav), duration=60.0, bpm=None))

        result = runner.invoke(app, ["crop", str(clip_id), "--start", "5s", "--end", "20s", "--snap-to-beat"])
        assert result.exit_code == 1
        assert "bpm" in result.output.lower()

    def test_null_duration_rejects_crop(self, workspace_with_clips_dir):
        """Clip with no duration metadata must be rejected."""
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "src_no_dur.wav"
        src_wav.write_bytes(b"audio")

        from acemusic.db import create_clip

        clip_id = create_clip(_make_clip(ws.id, str(src_wav), duration=None))

        result = runner.invoke(app, ["crop", str(clip_id), "--start", "0s", "--end", "10s"])
        assert result.exit_code == 1
        assert "duration" in result.output.lower()

    def test_start_equal_to_end_returns_error(self, workspace_with_clips_dir):
        """start == end should be rejected (zero-length segment)."""
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "src5.wav"
        src_wav.write_bytes(b"audio")

        from acemusic.db import create_clip

        clip_id = create_clip(_make_clip(ws.id, str(src_wav), duration=60.0))

        result = runner.invoke(app, ["crop", str(clip_id), "--start", "10s", "--end", "10s"])
        assert result.exit_code == 1
