"""Tests for the `acemusic export` CLI command (US-7.1)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from acemusic.cli import app

runner = CliRunner()


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
