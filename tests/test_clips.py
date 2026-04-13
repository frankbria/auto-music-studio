"""Tests for clip metadata storage and CLI commands (US-4.2)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from acemusic.cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Redirect DB_DIR to tmp_path for full isolation."""
    import acemusic.db as _db

    monkeypatch.setattr(_db, "DB_DIR", tmp_path / ".acemusic")
    return tmp_path


def _insert_test_clip(db_path: Path, **overrides) -> int:
    """Insert a clip record directly via sqlite3 and return its id."""
    defaults = {
        "title": "Test Clip",
        "workspace_id": "ws-test",
        "file_path": "/tmp/test.wav",
        "format": "wav",
        "duration": 30.0,
        "bpm": 120,
        "key": "C major",
        "style_tags": "pop, upbeat",
        "lyrics": None,
        "vocal_language": None,
        "model": "ace-step-base",
        "seed": 42,
        "inference_steps": 32,
        "parent_clip_id": None,
        "generation_mode": "generate",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    defaults.update(overrides)
    conn = sqlite3.connect(str(db_path))
    cur = conn.execute(
        """INSERT INTO clips
           (title, workspace_id, file_path, format, duration, bpm, key,
            style_tags, lyrics, vocal_language, model, seed, inference_steps,
            parent_clip_id, generation_mode, created_at)
           VALUES (:title, :workspace_id, :file_path, :format, :duration, :bpm, :key,
                   :style_tags, :lyrics, :vocal_language, :model, :seed, :inference_steps,
                   :parent_clip_id, :generation_mode, :created_at)""",
        defaults,
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return row_id


def _get_db_path(isolated_db: Path) -> Path:
    return isolated_db / ".acemusic" / "metadata.db"


# ---------------------------------------------------------------------------
# DB layer: schema init
# ---------------------------------------------------------------------------


class TestSchemaInit:
    def test_clips_table_created(self, isolated_db):
        import acemusic.db as _db

        conn = _db.get_db()
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        conn.close()
        assert "clips" in tables

    def test_workspaces_table_still_present(self, isolated_db):
        import acemusic.db as _db

        conn = _db.get_db()
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        conn.close()
        assert "workspaces" in tables


# ---------------------------------------------------------------------------
# DB layer: CRUD
# ---------------------------------------------------------------------------


class TestClipsCRUD:
    def test_create_and_get_clip(self, isolated_db):
        from acemusic.db import create_clip, get_clip
        from acemusic.models import Clip

        clip = Clip(
            title="My Track",
            workspace_id="ws-1",
            file_path="/tmp/my-track.wav",
            format="wav",
            duration=45.0,
            bpm=130,
            key="A minor",
            style_tags="rock",
            lyrics=None,
            vocal_language="en",
            model="ace-step-base",
            seed=7,
            inference_steps=32,
            parent_clip_id=None,
            generation_mode="generate",
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        clip_id = create_clip(clip)
        assert isinstance(clip_id, int)
        assert clip_id > 0

        retrieved = get_clip(clip_id)
        assert retrieved is not None
        assert retrieved.title == "My Track"
        assert retrieved.bpm == 130
        assert retrieved.key == "A minor"
        assert retrieved.seed == 7

    def test_get_clip_not_found(self, isolated_db):
        from acemusic.db import get_clip

        assert get_clip(9999) is None

    def test_list_clips_empty(self, isolated_db):
        import acemusic.db as _db

        _db.get_db().close()  # ensure schema is initialized
        from acemusic.db import list_clips

        clips = list_clips("ws-empty")
        assert clips == []

    def test_list_clips_returns_workspace_clips(self, isolated_db):
        import acemusic.db as _db

        conn = _db.get_db()
        conn.close()
        from acemusic.db import create_clip, list_clips
        from acemusic.models import Clip

        def _make(title: str, ws: str) -> Clip:
            return Clip(
                title=title,
                workspace_id=ws,
                file_path=f"/tmp/{title}.wav",
                format="wav",
                duration=30.0,
                created_at=datetime.now(timezone.utc).isoformat(),
            )

        create_clip(_make("Alpha", "ws-a"))
        create_clip(_make("Beta", "ws-a"))
        create_clip(_make("Gamma", "ws-b"))

        clips_a = list_clips("ws-a")
        clips_b = list_clips("ws-b")
        assert len(clips_a) == 2
        assert len(clips_b) == 1
        assert {c.title for c in clips_a} == {"Alpha", "Beta"}

    def test_list_clips_ordered_newest_first(self, isolated_db):
        import acemusic.db as _db

        conn = _db.get_db()
        conn.close()
        from acemusic.db import create_clip, list_clips
        from acemusic.models import Clip

        ts1 = "2026-01-01T10:00:00"
        ts2 = "2026-01-01T11:00:00"
        create_clip(Clip(title="Older", workspace_id="ws-x", file_path="/tmp/older.wav", format="wav", created_at=ts1))
        create_clip(Clip(title="Newer", workspace_id="ws-x", file_path="/tmp/newer.wav", format="wav", created_at=ts2))

        clips = list_clips("ws-x")
        assert clips[0].title == "Newer"

    def test_update_clip_title(self, isolated_db):
        import acemusic.db as _db

        conn = _db.get_db()
        conn.close()
        db_path = _get_db_path(isolated_db)
        clip_id = _insert_test_clip(db_path, workspace_id="ws-1")

        from acemusic.db import get_clip, update_clip_title

        result = update_clip_title(clip_id, "Renamed Track")
        assert result is True

        updated = get_clip(clip_id)
        assert updated.title == "Renamed Track"

    def test_update_clip_title_not_found(self, isolated_db):
        import acemusic.db as _db

        _db.get_db().close()
        from acemusic.db import update_clip_title

        result = update_clip_title(9999, "Ghost Track")
        assert result is False

    def test_delete_clip_returns_file_path(self, isolated_db):
        import acemusic.db as _db

        conn = _db.get_db()
        conn.close()
        db_path = _get_db_path(isolated_db)
        clip_id = _insert_test_clip(db_path, file_path="/tmp/track.wav")

        from acemusic.db import delete_clip, get_clip

        returned_path = delete_clip(clip_id)
        assert returned_path == "/tmp/track.wav"
        assert get_clip(clip_id) is None

    def test_delete_clip_not_found(self, isolated_db):
        import acemusic.db as _db

        _db.get_db().close()
        from acemusic.db import delete_clip

        assert delete_clip(9999) is None


# ---------------------------------------------------------------------------
# DB layer: search
# ---------------------------------------------------------------------------


class TestClipsSearch:
    def _seed_clips(self, isolated_db):
        import acemusic.db as _db

        conn = _db.get_db()
        conn.close()
        db_path = _get_db_path(isolated_db)
        _insert_test_clip(
            db_path,
            title="Rock Track",
            workspace_id="ws-1",
            style_tags="rock, hard",
            bpm=140,
            key="E minor",
            model="ace-step-base",
            created_at="2026-01-01T10:00:00",
        )
        _insert_test_clip(
            db_path,
            title="Pop Track",
            workspace_id="ws-1",
            style_tags="pop, bright",
            bpm=100,
            key="C major",
            model="elevenlabs",
            created_at="2026-01-02T10:00:00",
        )
        _insert_test_clip(
            db_path,
            title="Jazz Track",
            workspace_id="ws-1",
            style_tags="jazz, smooth",
            bpm=90,
            key="Bb major",
            model="ace-step-xl",
            created_at="2026-01-03T10:00:00",
        )
        _insert_test_clip(
            db_path,
            title="Other WS",
            workspace_id="ws-2",
            style_tags="rock",
            bpm=120,
            key="G major",
            model="ace-step-base",
            created_at="2026-01-01T12:00:00",
        )

    def test_search_no_filters_returns_all_workspace_clips(self, isolated_db):
        self._seed_clips(isolated_db)
        from acemusic.db import search_clips

        clips = search_clips("ws-1")
        assert len(clips) == 3

    def test_search_by_style(self, isolated_db):
        self._seed_clips(isolated_db)
        from acemusic.db import search_clips

        clips = search_clips("ws-1", style="rock")
        assert len(clips) == 1
        assert clips[0].title == "Rock Track"

    def test_search_by_bpm_range(self, isolated_db):
        self._seed_clips(isolated_db)
        from acemusic.db import search_clips

        clips = search_clips("ws-1", bpm_min=95, bpm_max=145)
        assert len(clips) == 2
        titles = {c.title for c in clips}
        assert "Rock Track" in titles
        assert "Pop Track" in titles

    def test_search_by_key(self, isolated_db):
        self._seed_clips(isolated_db)
        from acemusic.db import search_clips

        clips = search_clips("ws-1", key="C major")
        assert len(clips) == 1
        assert clips[0].title == "Pop Track"

    def test_search_by_model(self, isolated_db):
        self._seed_clips(isolated_db)
        from acemusic.db import search_clips

        clips = search_clips("ws-1", model="elevenlabs")
        assert len(clips) == 1
        assert clips[0].title == "Pop Track"

    def test_search_by_date_from(self, isolated_db):
        self._seed_clips(isolated_db)
        from acemusic.db import search_clips

        clips = search_clips("ws-1", date_from="2026-01-02")
        assert len(clips) == 2
        titles = {c.title for c in clips}
        assert "Pop Track" in titles
        assert "Jazz Track" in titles

    def test_search_by_date_to(self, isolated_db):
        self._seed_clips(isolated_db)
        from acemusic.db import search_clips

        clips = search_clips("ws-1", date_to="2026-01-01")
        assert len(clips) == 1
        assert clips[0].title == "Rock Track"

    def test_search_isolates_to_workspace(self, isolated_db):
        self._seed_clips(isolated_db)
        from acemusic.db import search_clips

        clips = search_clips("ws-2")
        assert len(clips) == 1
        assert clips[0].title == "Other WS"


# ---------------------------------------------------------------------------
# CLI: clips list
# ---------------------------------------------------------------------------


class TestClipsListCommand:
    def test_list_empty(self, isolated_db):
        from acemusic.workspace import ensure_default_workspace

        ensure_default_workspace()
        result = runner.invoke(app, ["clips", "list"])
        assert result.exit_code == 0
        assert "No clips" in result.output

    def test_list_shows_clips(self, isolated_db):
        import acemusic.db as _db

        conn = _db.get_db()
        conn.close()
        db_path = _get_db_path(isolated_db)
        from acemusic.workspace import ensure_default_workspace, get_active_workspace

        ensure_default_workspace()
        ws = get_active_workspace()
        _insert_test_clip(db_path, title="My Song", workspace_id=ws.id, bpm=120, duration=65.0, model="ace-step-base")

        result = runner.invoke(app, ["clips", "list"])
        assert result.exit_code == 0
        assert "My Song" in result.output


# ---------------------------------------------------------------------------
# CLI: clips info
# ---------------------------------------------------------------------------


class TestClipsInfoCommand:
    def test_info_valid_id(self, isolated_db):
        import acemusic.db as _db

        conn = _db.get_db()
        conn.close()
        db_path = _get_db_path(isolated_db)
        from acemusic.workspace import ensure_default_workspace, get_active_workspace

        ensure_default_workspace()
        ws = get_active_workspace()
        clip_id = _insert_test_clip(db_path, title="Info Track", workspace_id=ws.id, seed=99)

        result = runner.invoke(app, ["clips", "info", str(clip_id)])
        assert result.exit_code == 0
        assert "Info Track" in result.output
        assert "99" in result.output

    def test_info_not_found(self, isolated_db):
        import acemusic.db as _db

        _db.get_db().close()
        from acemusic.workspace import ensure_default_workspace

        ensure_default_workspace()
        result = runner.invoke(app, ["clips", "info", "9999"])
        assert result.exit_code != 0 or "not found" in result.output.lower()


# ---------------------------------------------------------------------------
# CLI: clips rename
# ---------------------------------------------------------------------------


class TestClipsRenameCommand:
    def test_rename_success(self, isolated_db):
        import acemusic.db as _db

        conn = _db.get_db()
        conn.close()
        db_path = _get_db_path(isolated_db)
        from acemusic.workspace import ensure_default_workspace, get_active_workspace

        ensure_default_workspace()
        ws = get_active_workspace()
        clip_id = _insert_test_clip(db_path, title="Old Title", workspace_id=ws.id)

        result = runner.invoke(app, ["clips", "rename", str(clip_id), "New Title"])
        assert result.exit_code == 0
        assert "New Title" in result.output or "renamed" in result.output.lower() or "success" in result.output.lower()

        from acemusic.db import get_clip

        updated = get_clip(clip_id)
        assert updated.title == "New Title"

    def test_rename_not_found(self, isolated_db):
        import acemusic.db as _db

        _db.get_db().close()
        from acemusic.workspace import ensure_default_workspace

        ensure_default_workspace()
        result = runner.invoke(app, ["clips", "rename", "9999", "Ghost"])
        assert result.exit_code != 0 or "not found" in result.output.lower()


# ---------------------------------------------------------------------------
# CLI: clips delete
# ---------------------------------------------------------------------------


class TestClipsDeleteCommand:
    def test_delete_removes_record_and_file(self, isolated_db, tmp_path):
        import acemusic.db as _db

        conn = _db.get_db()
        conn.close()
        db_path = _get_db_path(isolated_db)
        from acemusic.workspace import ensure_default_workspace, get_active_workspace

        ensure_default_workspace()
        ws = get_active_workspace()

        audio_file = tmp_path / "track.wav"
        audio_file.write_bytes(b"fake audio data")
        clip_id = _insert_test_clip(db_path, title="Delete Me", workspace_id=ws.id, file_path=str(audio_file))

        result = runner.invoke(app, ["clips", "delete", str(clip_id), "--yes"])
        assert result.exit_code == 0
        assert not audio_file.exists()

        from acemusic.db import get_clip

        assert get_clip(clip_id) is None

    def test_delete_not_found(self, isolated_db):
        import acemusic.db as _db

        _db.get_db().close()
        from acemusic.workspace import ensure_default_workspace

        ensure_default_workspace()
        result = runner.invoke(app, ["clips", "delete", "9999", "--yes"])
        assert result.exit_code != 0 or "not found" in result.output.lower()


# ---------------------------------------------------------------------------
# CLI: clips search
# ---------------------------------------------------------------------------


class TestClipsSearchCommand:
    def test_search_by_style_option(self, isolated_db):
        import acemusic.db as _db

        conn = _db.get_db()
        conn.close()
        db_path = _get_db_path(isolated_db)
        from acemusic.workspace import ensure_default_workspace, get_active_workspace

        ensure_default_workspace()
        ws = get_active_workspace()
        _insert_test_clip(db_path, title="Rock Hit", workspace_id=ws.id, style_tags="rock, electric")
        _insert_test_clip(db_path, title="Pop Song", workspace_id=ws.id, style_tags="pop, bright")

        result = runner.invoke(app, ["clips", "search", "--style", "rock"])
        assert result.exit_code == 0
        assert "Rock Hit" in result.output
        assert "Pop Song" not in result.output

    def test_search_by_bpm_range(self, isolated_db):
        import acemusic.db as _db

        conn = _db.get_db()
        conn.close()
        db_path = _get_db_path(isolated_db)
        from acemusic.workspace import ensure_default_workspace, get_active_workspace

        ensure_default_workspace()
        ws = get_active_workspace()
        _insert_test_clip(db_path, title="Fast Track", workspace_id=ws.id, bpm=160)
        _insert_test_clip(db_path, title="Slow Track", workspace_id=ws.id, bpm=80)

        result = runner.invoke(app, ["clips", "search", "--bpm-range", "100-180"])
        assert result.exit_code == 0
        assert "Fast Track" in result.output
        assert "Slow Track" not in result.output

    def test_search_bpm_range_invalid(self, isolated_db):
        import acemusic.db as _db

        _db.get_db().close()
        from acemusic.workspace import ensure_default_workspace

        ensure_default_workspace()
        result = runner.invoke(app, ["clips", "search", "--bpm-range", "abc"])
        assert result.exit_code != 0 or "invalid" in result.output.lower()

    def test_search_bpm_range_min_gt_max(self, isolated_db):
        import acemusic.db as _db

        _db.get_db().close()
        from acemusic.workspace import ensure_default_workspace

        ensure_default_workspace()
        result = runner.invoke(app, ["clips", "search", "--bpm-range", "140-100"])
        assert result.exit_code != 0 or "invalid" in result.output.lower()

    def test_search_no_results(self, isolated_db):
        import acemusic.db as _db

        _db.get_db().close()
        from acemusic.workspace import ensure_default_workspace

        ensure_default_workspace()
        result = runner.invoke(app, ["clips", "search", "--style", "noresults"])
        assert result.exit_code == 0
        assert "no clips" in result.output.lower() or "0" in result.output


# ---------------------------------------------------------------------------
# Generation integration: metadata recorded after generate
# ---------------------------------------------------------------------------

TASK_ID = "task-clips-123"
AUDIO_URL_1 = "http://localhost:8001/audio/clip1.wav"
AUDIO_URL_2 = "http://localhost:8001/audio/clip2.wav"
COMPLETED_RESULT = {"status": "completed", "audio_urls": [AUDIO_URL_1, AUDIO_URL_2]}
FAKE_WAV = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x44\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00"


class TestGenerationCreatesClipMetadata:
    def test_generate_creates_clip_records(self, isolated_db, monkeypatch, tmp_path):
        """After a successful generate, clips appear in the database."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        from acemusic.workspace import ensure_default_workspace

        ensure_default_workspace()

        client_mock = MagicMock()
        client_mock.submit_task.return_value = TASK_ID
        client_mock.query_result.return_value = COMPLETED_RESULT
        client_mock.download_audio.return_value = FAKE_WAV

        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=30.0),
        ):
            result = runner.invoke(
                app,
                ["generate", "upbeat pop", "--output", str(tmp_path), "--num-clips", "2"],
            )

        assert result.exit_code == 0, result.output

        from acemusic.db import list_clips
        from acemusic.workspace import get_active_workspace

        ws = get_active_workspace()
        clips = list_clips(ws.id)
        assert len(clips) == 2
        for clip in clips:
            assert clip.generation_mode == "generate"
            assert clip.file_path.endswith(".wav")

    def test_generate_records_style_and_model(self, isolated_db, monkeypatch, tmp_path):
        """Clip metadata includes style_tags and model from generate args."""
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
        from acemusic.workspace import ensure_default_workspace

        ensure_default_workspace()

        client_mock = MagicMock()
        client_mock.submit_task.return_value = TASK_ID
        client_mock.query_result.return_value = {"status": "completed", "audio_urls": [AUDIO_URL_1]}
        client_mock.download_audio.return_value = FAKE_WAV

        with (
            patch("acemusic.cli.AceStepClient", return_value=client_mock),
            patch("acemusic.cli.get_duration", return_value=45.0),
        ):
            result = runner.invoke(
                app,
                [
                    "generate",
                    "dark electro",
                    "--output",
                    str(tmp_path),
                    "--num-clips",
                    "1",
                    "--style",
                    "dark, synth",
                    "--model",
                    "base",
                    "--seed",
                    "123",
                ],
            )

        assert result.exit_code == 0, result.output

        from acemusic.db import list_clips
        from acemusic.workspace import get_active_workspace

        ws = get_active_workspace()
        clips = list_clips(ws.id)
        assert len(clips) == 1
        assert clips[0].style_tags == "dark, synth"
        assert clips[0].model == "base"
        assert clips[0].seed == 123
        assert clips[0].duration == 45.0
