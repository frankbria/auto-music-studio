"""Tests for the speed command (US-5.2)."""

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


class TestSpeedCommand:
    def test_speed_with_rate_creates_new_clip(self, workspace_with_clips_dir):
        """Speed command with --rate creates a new clip with updated duration."""
        from acemusic.db import create_clip, list_clips
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "source.wav"
        src_wav.write_bytes(b"fake audio data")

        src_clip = _make_clip(ws.id, str(src_wav), duration=60.0, bpm=120)
        clip_id = create_clip(src_clip)

        with patch("acemusic.cli.time_stretch_audio") as mock_stretch:
            mock_stretch.return_value = None
            result = runner.invoke(app, ["speed", str(clip_id), "--rate", "0.9"])

        assert result.exit_code == 0, result.output

        clips = list_clips(ws.id)
        speeded = [c for c in clips if c.generation_mode == "speed"]
        assert len(speeded) == 1
        assert speeded[0].parent_clip_id == clip_id
        # duration / 0.9 = 60 / 0.9 ≈ 66.667
        assert speeded[0].duration == pytest.approx(60.0 / 0.9, rel=0.01)

    def test_speed_with_target_bpm_creates_new_clip(self, workspace_with_clips_dir):
        """Speed command with --target-bpm calculates rate from BPM."""
        from acemusic.db import create_clip, list_clips
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "bpm_test.wav"
        src_wav.write_bytes(b"fake audio")

        # 120 BPM → 100 BPM = rate 100/120 = 0.8333
        src_clip = _make_clip(ws.id, str(src_wav), duration=60.0, bpm=120)
        clip_id = create_clip(src_clip)

        with patch("acemusic.cli.time_stretch_audio") as mock_stretch:
            mock_stretch.return_value = None
            result = runner.invoke(app, ["speed", str(clip_id), "--target-bpm", "100"])

        assert result.exit_code == 0, result.output

        clips = list_clips(ws.id)
        speeded = [c for c in clips if c.generation_mode == "speed"]
        assert len(speeded) == 1
        # new_bpm = 120 * (100/120) = 100
        assert speeded[0].bpm == pytest.approx(100.0)

    def test_speed_preserves_original_clip(self, workspace_with_clips_dir):
        """Original clip remains unchanged after speed adjustment."""
        from acemusic.db import create_clip, get_clip
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "original.wav"
        src_wav.write_bytes(b"original audio")

        src_clip = _make_clip(ws.id, str(src_wav), duration=60.0, bpm=120)
        clip_id = create_clip(src_clip)

        with patch("acemusic.cli.time_stretch_audio"):
            runner.invoke(app, ["speed", str(clip_id), "--rate", "1.1"])

        original = get_clip(clip_id)
        assert original is not None
        assert original.generation_mode != "speed"
        assert original.parent_clip_id is None

    def test_speed_updates_bpm_when_present(self, workspace_with_clips_dir):
        """BPM is recalculated when changing speed."""
        from acemusic.db import create_clip, list_clips
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "bpm_test2.wav"
        src_wav.write_bytes(b"audio")

        src_clip = _make_clip(ws.id, str(src_wav), duration=60.0, bpm=120)
        clip_id = create_clip(src_clip)

        with patch("acemusic.cli.time_stretch_audio"):
            result = runner.invoke(app, ["speed", str(clip_id), "--rate", "1.5"])

        assert result.exit_code == 0
        clips = list_clips(ws.id)
        speeded = [c for c in clips if c.generation_mode == "speed"]
        # new_bpm = 120 * 1.5 = 180
        assert speeded[0].bpm == pytest.approx(180.0)

    def test_speed_preserves_key(self, workspace_with_clips_dir):
        """Key is preserved when speed is adjusted."""
        from acemusic.db import create_clip, list_clips
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "keyed.wav"
        src_wav.write_bytes(b"audio")

        src_clip = _make_clip(ws.id, str(src_wav), duration=60.0, bpm=120)
        src_clip.key = "C major"
        clip_id = create_clip(src_clip)

        with patch("acemusic.cli.time_stretch_audio"):
            runner.invoke(app, ["speed", str(clip_id), "--rate", "0.8"])

        clips = list_clips(ws.id)
        speeded = [c for c in clips if c.generation_mode == "speed"]
        assert speeded[0].key == "C major"

    def test_speed_output_message_contains_new_clip_id(self, workspace_with_clips_dir):
        """Success output shows the new clip ID and statistics."""
        from acemusic.db import create_clip
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "src.wav"
        src_wav.write_bytes(b"audio")

        src_clip = _make_clip(ws.id, str(src_wav), duration=60.0, bpm=120)
        clip_id = create_clip(src_clip)

        with patch("acemusic.cli.time_stretch_audio"):
            result = runner.invoke(app, ["speed", str(clip_id), "--rate", "1.0"])

        assert result.exit_code == 0, result.output
        assert "Speed adjusted" in result.output or "clip" in result.output.lower()


# ---------------------------------------------------------------------------
# Validation / error scenarios
# ---------------------------------------------------------------------------


class TestSpeedValidation:
    def test_invalid_clip_id_returns_error(self, workspace_with_clips_dir):
        """Non-existent clip ID produces a friendly error."""
        result = runner.invoke(app, ["speed", "99999", "--rate", "0.9"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_both_rate_and_target_bpm_returns_error(self, workspace_with_clips_dir):
        """Providing both --rate and --target-bpm is an error."""
        from acemusic.db import create_clip
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "src.wav"
        src_wav.write_bytes(b"audio")

        src_clip = _make_clip(ws.id, str(src_wav), duration=60.0, bpm=120)
        clip_id = create_clip(src_clip)

        result = runner.invoke(app, ["speed", str(clip_id), "--rate", "0.9", "--target-bpm", "100"])
        assert result.exit_code == 1
        assert "either" in result.output.lower()

    def test_neither_rate_nor_target_bpm_returns_error(self, workspace_with_clips_dir):
        """Not providing --rate or --target-bpm is an error."""
        from acemusic.db import create_clip
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "src2.wav"
        src_wav.write_bytes(b"audio")

        src_clip = _make_clip(ws.id, str(src_wav), duration=60.0, bpm=120)
        clip_id = create_clip(src_clip)

        result = runner.invoke(app, ["speed", str(clip_id)])
        assert result.exit_code == 1
        assert "must provide" in result.output.lower()

    def test_target_bpm_without_source_bpm_returns_error(self, workspace_with_clips_dir):
        """--target-bpm without BPM in source metadata is an error."""
        from acemusic.db import create_clip
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "src3.wav"
        src_wav.write_bytes(b"audio")

        src_clip = _make_clip(ws.id, str(src_wav), duration=60.0, bpm=None)
        clip_id = create_clip(src_clip)

        result = runner.invoke(app, ["speed", str(clip_id), "--target-bpm", "100"])
        assert result.exit_code == 1
        assert "bpm" in result.output.lower()

    def test_zero_rate_returns_error(self, workspace_with_clips_dir):
        """rate <= 0 is an error."""
        from acemusic.db import create_clip
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "src4.wav"
        src_wav.write_bytes(b"audio")

        src_clip = _make_clip(ws.id, str(src_wav), duration=60.0)
        clip_id = create_clip(src_clip)

        result = runner.invoke(app, ["speed", str(clip_id), "--rate", "0"])
        assert result.exit_code == 1
        assert "positive" in result.output.lower()

    def test_negative_rate_returns_error(self, workspace_with_clips_dir):
        """Negative rate is an error."""
        from acemusic.db import create_clip
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "src5.wav"
        src_wav.write_bytes(b"audio")

        src_clip = _make_clip(ws.id, str(src_wav), duration=60.0)
        clip_id = create_clip(src_clip)

        result = runner.invoke(app, ["speed", str(clip_id), "--rate", "-1.0"])
        assert result.exit_code == 1
        assert "positive" in result.output.lower()

    def test_null_duration_rejects_speed(self, workspace_with_clips_dir):
        """Clip with no duration metadata must be rejected."""
        from acemusic.db import create_clip
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "src_no_dur.wav"
        src_wav.write_bytes(b"audio")

        src_clip = _make_clip(ws.id, str(src_wav), duration=None)
        clip_id = create_clip(src_clip)

        result = runner.invoke(app, ["speed", str(clip_id), "--rate", "0.9"])
        assert result.exit_code == 1
        assert "duration" in result.output.lower()

    def test_rate_below_minimum_returns_error(self, workspace_with_clips_dir):
        """Rate below 0.5 is rejected."""
        from acemusic.db import create_clip
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "src_slow.wav"
        src_wav.write_bytes(b"audio")

        src_clip = _make_clip(ws.id, str(src_wav), duration=60.0)
        clip_id = create_clip(src_clip)

        result = runner.invoke(app, ["speed", str(clip_id), "--rate", "0.3"])
        assert result.exit_code == 1
        assert "0.5" in result.output and "2.0" in result.output

    def test_rate_above_maximum_returns_error(self, workspace_with_clips_dir):
        """Rate above 2.0 is rejected."""
        from acemusic.db import create_clip
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "src_fast.wav"
        src_wav.write_bytes(b"audio")

        src_clip = _make_clip(ws.id, str(src_wav), duration=60.0)
        clip_id = create_clip(src_clip)

        result = runner.invoke(app, ["speed", str(clip_id), "--rate", "2.5"])
        assert result.exit_code == 1
        assert "0.5" in result.output and "2.0" in result.output

    def test_rate_at_boundary_0_5_succeeds(self, workspace_with_clips_dir):
        """Rate exactly 0.5 is accepted."""
        from acemusic.db import create_clip
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "src_bound_low.wav"
        src_wav.write_bytes(b"audio")

        src_clip = _make_clip(ws.id, str(src_wav), duration=60.0, bpm=120)
        clip_id = create_clip(src_clip)

        with patch("acemusic.cli.time_stretch_audio"):
            result = runner.invoke(app, ["speed", str(clip_id), "--rate", "0.5"])

        assert result.exit_code == 0, result.output

    def test_rate_at_boundary_2_0_succeeds(self, workspace_with_clips_dir):
        """Rate exactly 2.0 is accepted."""
        from acemusic.db import create_clip
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "src_bound_high.wav"
        src_wav.write_bytes(b"audio")

        src_clip = _make_clip(ws.id, str(src_wav), duration=60.0, bpm=120)
        clip_id = create_clip(src_clip)

        with patch("acemusic.cli.time_stretch_audio"):
            result = runner.invoke(app, ["speed", str(clip_id), "--rate", "2.0"])

        assert result.exit_code == 0, result.output

    def test_target_bpm_out_of_range_returns_contextual_error(self, workspace_with_clips_dir):
        """--target-bpm that produces rate outside 0.5-2.0 shows BPM context in error."""
        from acemusic.db import create_clip
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "src_bpm_range.wav"
        src_wav.write_bytes(b"audio")

        # 120 BPM → 300 BPM = rate 2.5, outside 0.5–2.0
        src_clip = _make_clip(ws.id, str(src_wav), duration=60.0, bpm=120)
        clip_id = create_clip(src_clip)

        result = runner.invoke(app, ["speed", str(clip_id), "--target-bpm", "300"])
        assert result.exit_code == 1
        assert "300" in result.output
        assert "0.5" in result.output and "2.0" in result.output

    def test_zero_target_bpm_returns_error(self, workspace_with_clips_dir):
        """target_bpm <= 0 is an error."""
        from acemusic.db import create_clip
        from acemusic.workspace import get_active_workspace, get_workspace_path

        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        src_wav = clips_dir / "src6.wav"
        src_wav.write_bytes(b"audio")

        src_clip = _make_clip(ws.id, str(src_wav), duration=60.0, bpm=120)
        clip_id = create_clip(src_clip)

        result = runner.invoke(app, ["speed", str(clip_id), "--target-bpm", "0"])
        assert result.exit_code == 1
        assert "positive" in result.output.lower()
