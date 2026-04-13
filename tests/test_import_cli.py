"""Tests for the import command (US-4.4)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from acemusic.cli import app

runner = CliRunner()

FAKE_WAV = (
    b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00"
    b"\x01\x00\x01\x00\x44\xac\x00\x00\x88X\x01\x00"
    b"\x02\x00\x10\x00data\x00\x00\x00\x00"
)


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    import acemusic.db as _db

    monkeypatch.setattr(_db, "DB_DIR", tmp_path / ".acemusic")
    return tmp_path


@pytest.fixture
def workspace_with_clips_dir(isolated_db, monkeypatch):
    """Ensure an active workspace exists and clips dir is created."""
    from acemusic.workspace import ensure_default_workspace, get_active_workspace, get_workspace_path

    ensure_default_workspace()
    ws = get_active_workspace()
    clips_dir = get_workspace_path(ws.id)
    clips_dir.mkdir(parents=True, exist_ok=True)
    return ws


class TestImportCommand:
    def test_import_wav_copies_and_creates_record(self, workspace_with_clips_dir, tmp_path):
        source_wav = tmp_path / "my_song.wav"
        source_wav.write_bytes(FAKE_WAV)

        with (
            patch("acemusic.cli.detect_bpm", return_value=120.0),
            patch("acemusic.cli.detect_key", return_value="C major"),
            patch("acemusic.cli.get_duration", return_value=30.0),
        ):
            result = runner.invoke(app, ["import", str(source_wav)])

        assert result.exit_code == 0, result.output
        assert "Imported" in result.output or "imported" in result.output.lower()

        from acemusic.db import list_clips
        from acemusic.workspace import get_active_workspace

        ws = get_active_workspace()
        clips = list_clips(ws.id)
        assert len(clips) == 1
        assert clips[0].generation_mode == "upload"
        assert clips[0].file_path.endswith(".wav")

    def test_import_uses_filename_stem_as_title(self, workspace_with_clips_dir, tmp_path):
        source_wav = tmp_path / "my_cool_track.wav"
        source_wav.write_bytes(FAKE_WAV)

        with (
            patch("acemusic.cli.detect_bpm", return_value=None),
            patch("acemusic.cli.detect_key", return_value=None),
            patch("acemusic.cli.get_duration", return_value=None),
        ):
            result = runner.invoke(app, ["import", str(source_wav)])

        assert result.exit_code == 0, result.output
        from acemusic.db import list_clips
        from acemusic.workspace import get_active_workspace

        ws = get_active_workspace()
        clips = list_clips(ws.id)
        assert len(clips) == 1
        assert clips[0].title == "my_cool_track"

    def test_import_with_custom_title(self, workspace_with_clips_dir, tmp_path):
        source_wav = tmp_path / "raw.wav"
        source_wav.write_bytes(FAKE_WAV)

        with (
            patch("acemusic.cli.detect_bpm", return_value=None),
            patch("acemusic.cli.detect_key", return_value=None),
            patch("acemusic.cli.get_duration", return_value=None),
        ):
            result = runner.invoke(app, ["import", str(source_wav), "--title", "My Custom Title"])

        assert result.exit_code == 0, result.output
        from acemusic.db import list_clips
        from acemusic.workspace import get_active_workspace

        ws = get_active_workspace()
        clips = list_clips(ws.id)
        assert len(clips) == 1
        assert clips[0].title == "My Custom Title"

    def test_import_records_bpm_and_key(self, workspace_with_clips_dir, tmp_path):
        source_wav = tmp_path / "song.wav"
        source_wav.write_bytes(FAKE_WAV)

        with (
            patch("acemusic.cli.detect_bpm", return_value=140.0),
            patch("acemusic.cli.detect_key", return_value="G minor"),
            patch("acemusic.cli.get_duration", return_value=45.0),
        ):
            result = runner.invoke(app, ["import", str(source_wav)])

        assert result.exit_code == 0, result.output
        from acemusic.db import list_clips
        from acemusic.workspace import get_active_workspace

        ws = get_active_workspace()
        clips = list_clips(ws.id)
        assert len(clips) == 1
        assert clips[0].bpm == 140
        assert clips[0].key == "G minor"
        assert clips[0].duration == 45.0

    def test_import_shows_bpm_in_output(self, workspace_with_clips_dir, tmp_path):
        source_wav = tmp_path / "song.wav"
        source_wav.write_bytes(FAKE_WAV)

        with (
            patch("acemusic.cli.detect_bpm", return_value=128.0),
            patch("acemusic.cli.detect_key", return_value="D major"),
            patch("acemusic.cli.get_duration", return_value=60.0),
        ):
            result = runner.invoke(app, ["import", str(source_wav)])

        assert result.exit_code == 0, result.output
        assert "128" in result.output
        assert "D major" in result.output

    def test_import_shows_unknown_when_bpm_not_detected(self, workspace_with_clips_dir, tmp_path):
        source_wav = tmp_path / "song.wav"
        source_wav.write_bytes(FAKE_WAV)

        with (
            patch("acemusic.cli.detect_bpm", return_value=None),
            patch("acemusic.cli.detect_key", return_value=None),
            patch("acemusic.cli.get_duration", return_value=None),
        ):
            result = runner.invoke(app, ["import", str(source_wav)])

        assert result.exit_code == 0, result.output
        assert "unknown" in result.output.lower()

    def test_import_nonexistent_file_errors(self, workspace_with_clips_dir):
        result = runner.invoke(app, ["import", "/no/such/file.wav"])
        assert result.exit_code != 0 or "error" in result.output.lower() or "not found" in result.output.lower()

    def test_import_unsupported_format_errors(self, workspace_with_clips_dir, tmp_path):
        bad_file = tmp_path / "video.mp4"
        bad_file.write_bytes(b"fake video")
        result = runner.invoke(app, ["import", str(bad_file)])
        assert result.exit_code != 0 or "unsupported" in result.output.lower() or "error" in result.output.lower()


class TestClipsListShowsUploadBadge:
    def test_list_shows_upload_badge(self, isolated_db, tmp_path):
        from datetime import datetime, timezone

        import acemusic.db as _db

        _db.get_db().close()

        from acemusic.db import create_clip
        from acemusic.models import Clip
        from acemusic.workspace import ensure_default_workspace, get_active_workspace, get_workspace_path

        ensure_default_workspace()
        ws = get_active_workspace()

        clips_dir = get_workspace_path(ws.id)
        clips_dir.mkdir(parents=True, exist_ok=True)

        audio_file = clips_dir / "imported.wav"
        audio_file.write_bytes(b"fake audio")

        create_clip(
            Clip(
                title="My Import",
                workspace_id=ws.id,
                file_path=str(audio_file),
                format="wav",
                duration=30.0,
                bpm=120,
                key="C major",
                generation_mode="upload",
                created_at=datetime.now(timezone.utc).isoformat(),
            )
        )

        result = runner.invoke(app, ["clips", "list"])
        assert result.exit_code == 0, result.output
        assert "My Import" in result.output
        assert "upload" in result.output.lower()
