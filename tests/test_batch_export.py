"""Tests for batch export (`acemusic export --workspace ...`) — US-7.3."""

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


def _make_clip(ws_id, source, title):
    from acemusic.db import create_clip
    from acemusic.models import Clip

    return create_clip(
        Clip(
            workspace_id=ws_id,
            file_path=str(source),
            created_at=datetime.now(timezone.utc).isoformat(),
            title=title,
            format="wav",
            duration=0.5,
        )
    )


@pytest.fixture
def workspace_with_clips(isolated_db, write_tone):
    """An active workspace named 'My Album' holding three distinct WAV clips."""
    from acemusic.workspace import (
        create_workspace,
        get_workspace_path,
        switch_workspace,
    )

    ws = create_workspace("My Album")
    switch_workspace("My Album")
    clips_dir = get_workspace_path(ws.id)
    clips_dir.mkdir(parents=True, exist_ok=True)

    titles = ["First Song", "Second Song", "Third Song"]
    clip_ids = []
    for i, title in enumerate(titles):
        source = clips_dir / f"clip{i}.wav"
        write_tone(source, duration_s=0.5)
        clip_ids.append(_make_clip(ws.id, source, title))
    return ws, clip_ids, clips_dir


def _fake_export(s, d, f):
    Path(d).write_bytes(b"x" * 1024)


class TestBatchExportRouting:
    def test_neither_clip_id_nor_workspace_errors(self, isolated_db):
        result = runner.invoke(app, ["export"])
        assert result.exit_code == 1
        assert "workspace" in result.output.lower() or "clip" in result.output.lower()

    def test_both_clip_id_and_workspace_errors(self, workspace_with_clips):
        _, clip_ids, _ = workspace_with_clips
        result = runner.invoke(app, ["export", str(clip_ids[0]), "--workspace", "My Album"])
        assert result.exit_code == 1
        assert "exactly one" in result.output.lower() or "both" in result.output.lower()

    def test_unknown_workspace_errors(self, isolated_db):
        result = runner.invoke(app, ["export", "--workspace", "Nope"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()


class TestBatchExportAllClips:
    def test_exports_every_clip(self, workspace_with_clips, tmp_path, monkeypatch):
        _, clip_ids, _ = workspace_with_clips
        out = tmp_path / "out"
        with patch("acemusic.cli.export_audio", side_effect=_fake_export) as mock_exp:
            result = runner.invoke(app, ["export", "--workspace", "My Album", "--output", str(out)])
        assert result.exit_code == 0, result.output
        assert mock_exp.call_count == len(clip_ids)
        produced = sorted(p.name for p in out.glob("*.wav"))
        assert produced == ["first-song.wav", "second-song.wav", "third-song.wav"]

    def test_default_output_is_cwd(self, workspace_with_clips, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch("acemusic.cli.export_audio", side_effect=_fake_export):
            result = runner.invoke(app, ["export", "--workspace", "My Album"])
        assert result.exit_code == 0, result.output
        assert (tmp_path / "first-song.wav").exists()

    def test_daw_format_routes_through_bundle(self, workspace_with_clips, tmp_path):
        _, clip_ids, _ = workspace_with_clips
        out = tmp_path / "daw"

        def fake_bundle(clip, *, output_path, **kwargs):
            Path(output_path).write_bytes(b"PK\x03\x04zipdata")
            return Path(output_path)

        with patch("acemusic.cli.build_daw_bundle", side_effect=fake_bundle) as mock_b:
            result = runner.invoke(app, ["export", "--workspace", "My Album", "--format", "daw", "--output", str(out)])
        assert result.exit_code == 0, result.output
        assert mock_b.call_count == len(clip_ids)
        zips = sorted(p.name for p in out.glob("*.zip"))
        assert zips == ["first-song_Export.zip", "second-song_Export.zip", "third-song_Export.zip"]


class TestDistinctFilenames:
    def test_duplicate_titles_get_distinct_names(self, isolated_db, write_tone, tmp_path):
        from acemusic.workspace import create_workspace, get_workspace_path, switch_workspace

        ws = create_workspace("Dupes")
        switch_workspace("Dupes")
        clips_dir = get_workspace_path(ws.id)
        clips_dir.mkdir(parents=True, exist_ok=True)
        ids = []
        for i in range(2):
            src = clips_dir / f"d{i}.wav"
            write_tone(src, duration_s=0.5)
            ids.append(_make_clip(ws.id, src, "Same Title"))

        out = tmp_path / "out"
        with patch("acemusic.cli.export_audio", side_effect=_fake_export):
            result = runner.invoke(app, ["export", "--workspace", "Dupes", "--output", str(out)])
        assert result.exit_code == 0, result.output
        names = sorted(p.name for p in out.glob("*.wav"))
        assert len(names) == 2
        assert len(set(names)) == 2  # distinct

    def test_untitled_clips_use_clip_id(self, isolated_db, write_tone, tmp_path):
        from acemusic.workspace import create_workspace, get_workspace_path, switch_workspace

        ws = create_workspace("Untitled")
        switch_workspace("Untitled")
        clips_dir = get_workspace_path(ws.id)
        clips_dir.mkdir(parents=True, exist_ok=True)
        src = clips_dir / "u.wav"
        write_tone(src, duration_s=0.5)
        cid = _make_clip(ws.id, src, None)

        out = tmp_path / "out"
        with patch("acemusic.cli.export_audio", side_effect=_fake_export):
            result = runner.invoke(app, ["export", "--workspace", "Untitled", "--output", str(out)])
        assert result.exit_code == 0, result.output
        assert (out / f"clip-{cid}.wav").exists()


class TestSummaryAndFailures:
    def test_summary_shows_count_and_size(self, workspace_with_clips, tmp_path):
        out = tmp_path / "out"
        with patch("acemusic.cli.export_audio", side_effect=_fake_export):
            result = runner.invoke(app, ["export", "--workspace", "My Album", "--output", str(out)])
        assert result.exit_code == 0, result.output
        flat = result.output.replace("\n", "")
        assert "3 clips" in flat
        assert "total" in flat.lower()
        assert "KB" in flat or "bytes" in flat or "MB" in flat

    def test_partial_failure_continues_and_reports(self, workspace_with_clips, tmp_path):
        _, clip_ids, _ = workspace_with_clips
        out = tmp_path / "out"
        calls = {"n": 0}

        def flaky(s, d, f):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("ffmpeg blew up")
            Path(d).write_bytes(b"x" * 1024)

        with patch("acemusic.cli.export_audio", side_effect=flaky):
            result = runner.invoke(app, ["export", "--workspace", "My Album", "--output", str(out)])
        # Individual failures must not abort the batch — the other clips still export —
        # but a partial failure surfaces as a non-zero exit code for scripts/CI.
        assert result.exit_code == 1, result.output
        flat = result.output.replace("\n", "")
        assert "2 of 3" in flat
        assert "1 failed" in flat
        assert len(list(out.glob("*.wav"))) == 2

    def test_output_pointing_at_existing_file_errors(self, workspace_with_clips, tmp_path):
        existing_file = tmp_path / "not-a-dir"
        existing_file.write_text("i am a file")
        result = runner.invoke(app, ["export", "--workspace", "My Album", "--output", str(existing_file)])
        assert result.exit_code == 1
        assert "error" in result.output.lower()

    def test_empty_workspace_reports_zero(self, isolated_db):
        from acemusic.workspace import create_workspace, switch_workspace

        create_workspace("Empty")
        switch_workspace("Empty")
        result = runner.invoke(app, ["export", "--workspace", "Empty"])
        assert result.exit_code == 0, result.output
        assert "0 clips" in result.output.replace("\n", "")
