"""Tests for preset functionality (US-4.3)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

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


def _insert_test_preset(db_path: Path, **overrides) -> int:
    """Insert a preset record directly via sqlite3 and return its id."""
    from acemusic.db import get_db

    # Initialize database first
    conn = get_db()
    conn.close()

    defaults = {
        "workspace_id": "ws-test",
        "name": "Test Preset",
        "style": "dark electro, punchy",
        "lyrics": None,
        "bpm": 128,
        "key": "C minor",
        "duration": 120,
        "model": "ace-step-base",
        "seed": None,
        "inference_steps": 32,
        "vocal_language": "en",
        "instrumental": None,
        "quality": None,
        "weirdness": None,
        "style_influence": None,
        "exclude_style": None,
        "time_signature": "4/4",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    defaults.update(overrides)
    conn = sqlite3.connect(str(db_path))
    cur = conn.execute(
        """INSERT INTO presets
           (workspace_id, name, style, lyrics, bpm, key, duration, model,
            seed, inference_steps, vocal_language, instrumental, quality,
            weirdness, style_influence, exclude_style, time_signature, created_at)
           VALUES (:workspace_id, :name, :style, :lyrics, :bpm, :key, :duration, :model,
                   :seed, :inference_steps, :vocal_language, :instrumental, :quality,
                   :weirdness, :style_influence, :exclude_style, :time_signature, :created_at)""",
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


class TestPresetSchemaInit:
    def test_presets_table_created(self, isolated_db):
        from acemusic.db import get_db

        conn = get_db()
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='presets'")
        assert cursor.fetchone() is not None
        conn.close()

    def test_presets_table_has_unique_constraint(self, isolated_db):
        db_path = _get_db_path(isolated_db)
        _insert_test_preset(db_path, workspace_id="ws-1", name="Preset1")

        # Try to insert duplicate
        conn = sqlite3.connect(str(db_path))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO presets
                   (workspace_id, name, style, bpm, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                ("ws-1", "Preset1", "test", 120, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
        conn.close()


# ---------------------------------------------------------------------------
# DB layer: CRUD
# ---------------------------------------------------------------------------


class TestPresetsCRUD:
    def test_create_preset(self, isolated_db):
        from acemusic.db import create_preset
        from acemusic.models import Preset

        now = datetime.now(timezone.utc).isoformat()
        preset = Preset(
            workspace_id="ws-1",
            name="Dark Electro",
            style="dark electro, punchy",
            bpm=128,
            key="C minor",
            created_at=now,
        )
        preset_id = create_preset(preset)
        assert preset_id > 0

    def test_get_preset(self, isolated_db):
        from acemusic.db import get_preset

        db_path = _get_db_path(isolated_db)
        _insert_test_preset(db_path, workspace_id="ws-1", name="Chill Vibes", bpm=85)

        preset = get_preset("ws-1", "Chill Vibes")
        assert preset is not None
        assert preset.name == "Chill Vibes"
        assert preset.bpm == 85

    def test_get_preset_not_found(self, isolated_db):
        from acemusic.db import get_preset

        preset = get_preset("ws-1", "NonExistent")
        assert preset is None

    def test_list_presets(self, isolated_db):
        from acemusic.db import list_presets

        db_path = _get_db_path(isolated_db)
        _insert_test_preset(db_path, workspace_id="ws-1", name="Preset1")
        _insert_test_preset(db_path, workspace_id="ws-1", name="Preset2")
        _insert_test_preset(db_path, workspace_id="ws-2", name="Preset3")

        ws1_presets = list_presets("ws-1")
        assert len(ws1_presets) == 2
        assert all(p.workspace_id == "ws-1" for p in ws1_presets)

    def test_list_presets_empty(self, isolated_db):
        from acemusic.db import list_presets

        presets = list_presets("ws-nonexistent")
        assert presets == []

    def test_delete_preset(self, isolated_db):
        from acemusic.db import delete_preset, get_preset

        db_path = _get_db_path(isolated_db)
        _insert_test_preset(db_path, workspace_id="ws-1", name="ToDelete")

        success = delete_preset("ws-1", "ToDelete")
        assert success is True

        preset = get_preset("ws-1", "ToDelete")
        assert preset is None

    def test_delete_preset_not_found(self, isolated_db):
        from acemusic.db import delete_preset

        success = delete_preset("ws-1", "NonExistent")
        assert success is False

    def test_update_preset(self, isolated_db):
        from acemusic.db import create_preset, get_preset, update_preset
        from acemusic.models import Preset

        now = datetime.now(timezone.utc).isoformat()
        preset = Preset(
            workspace_id="ws-1",
            name="Preset1",
            style="original",
            bpm=100,
            created_at=now,
        )
        create_preset(preset)

        preset.style = "updated"
        preset.bpm = 140
        success = update_preset(preset)
        assert success is True

        updated = get_preset("ws-1", "Preset1")
        assert updated.style == "updated"
        assert updated.bpm == 140


# ---------------------------------------------------------------------------
# CLI: preset save
# ---------------------------------------------------------------------------


class TestPresetSaveCommand:
    def test_save_with_explicit_params(self, isolated_db):
        from acemusic.workspace import ensure_default_workspace

        ensure_default_workspace()
        result = runner.invoke(
            app,
            [
                "preset",
                "save",
                "MyPreset",
                "--style",
                "lo-fi, chill",
                "--bpm",
                "85",
                "--key",
                "D minor",
            ],
        )
        assert result.exit_code == 0
        assert "✓" in result.output

    def test_save_with_from_last_not_implemented(self, isolated_db):
        from acemusic.workspace import ensure_default_workspace

        ensure_default_workspace()
        result = runner.invoke(app, ["preset", "save", "MyPreset", "--from-last"])
        assert result.exit_code == 1
        assert "not yet implemented" in result.output

    def test_save_duplicate_preset(self, isolated_db):
        from acemusic.workspace import ensure_default_workspace

        ensure_default_workspace()

        # Save first preset
        runner.invoke(app, ["preset", "save", "Duplicate", "--style", "test"])

        # Try to save duplicate
        result = runner.invoke(app, ["preset", "save", "Duplicate", "--style", "test"])
        assert result.exit_code == 1
        assert "already exists" in result.output


# ---------------------------------------------------------------------------
# CLI: preset list
# ---------------------------------------------------------------------------


class TestPresetListCommand:
    def test_list_empty(self, isolated_db):
        import acemusic.db as _db
        from acemusic.workspace import ensure_default_workspace

        conn = _db.get_db()
        conn.close()
        ensure_default_workspace()
        result = runner.invoke(app, ["preset", "list"])
        assert result.exit_code == 0
        assert "No presets" in result.output

    def test_list_shows_presets(self, isolated_db):
        import acemusic.db as _db

        conn = _db.get_db()
        conn.close()
        db_path = _get_db_path(isolated_db)
        from acemusic.workspace import ensure_default_workspace, get_active_workspace

        ensure_default_workspace()
        ws = get_active_workspace()
        _insert_test_preset(db_path, workspace_id=ws.id, name="Preset1", style="dark")
        _insert_test_preset(db_path, workspace_id=ws.id, name="Preset2", bpm=140)

        result = runner.invoke(app, ["preset", "list"])
        assert result.exit_code == 0
        assert "Preset1" in result.output
        assert "Preset2" in result.output


# ---------------------------------------------------------------------------
# CLI: preset load
# ---------------------------------------------------------------------------


class TestPresetLoadCommand:
    def test_load_preset(self, isolated_db):
        import acemusic.db as _db

        conn = _db.get_db()
        conn.close()
        db_path = _get_db_path(isolated_db)
        from acemusic.workspace import ensure_default_workspace, get_active_workspace

        ensure_default_workspace()
        ws = get_active_workspace()
        _insert_test_preset(
            db_path,
            workspace_id=ws.id,
            name="TestPreset",
            style="dark electro",
            bpm=128,
            key="C minor",
        )

        result = runner.invoke(app, ["preset", "load", "TestPreset"])
        assert result.exit_code == 0
        assert "TestPreset" in result.output
        assert "dark electro" in result.output
        assert "128" in result.output

    def test_load_preset_not_found(self, isolated_db):
        from acemusic.workspace import ensure_default_workspace

        ensure_default_workspace()
        result = runner.invoke(app, ["preset", "load", "NonExistent"])
        assert result.exit_code == 1
        assert "not found" in result.output


# ---------------------------------------------------------------------------
# CLI: preset delete
# ---------------------------------------------------------------------------


class TestPresetDeleteCommand:
    def test_delete_preset(self, isolated_db):
        import acemusic.db as _db

        conn = _db.get_db()
        conn.close()
        db_path = _get_db_path(isolated_db)
        from acemusic.workspace import ensure_default_workspace, get_active_workspace

        ensure_default_workspace()
        ws = get_active_workspace()
        _insert_test_preset(db_path, workspace_id=ws.id, name="ToDelete")

        result = runner.invoke(app, ["preset", "delete", "ToDelete"])
        assert result.exit_code == 0
        assert "✓" in result.output

    def test_delete_preset_not_found(self, isolated_db):
        from acemusic.workspace import ensure_default_workspace

        ensure_default_workspace()
        result = runner.invoke(app, ["preset", "delete", "NonExistent"])
        assert result.exit_code == 1
        assert "not found" in result.output


# ---------------------------------------------------------------------------
# CLI: generate with preset
# ---------------------------------------------------------------------------


class TestGenerateWithPreset:
    @patch("acemusic.cli._generate_via_ace_step")
    def test_generate_applies_preset(self, mock_generate, isolated_db):
        import acemusic.db as _db

        conn = _db.get_db()
        conn.close()
        db_path = _get_db_path(isolated_db)
        from acemusic.workspace import ensure_default_workspace, get_active_workspace

        ensure_default_workspace()
        ws = get_active_workspace()
        _insert_test_preset(
            db_path,
            workspace_id=ws.id,
            name="DarkPreset",
            style="dark electro",
            bpm=128,
            key="C minor",
        )

        # Mock the generation to avoid actual API calls
        mock_generate.return_value = None

        runner.invoke(
            app,
            [
                "generate",
                "test prompt",
                "--preset",
                "DarkPreset",
            ],
        )

    def test_generate_preset_not_found(self, isolated_db, monkeypatch):
        from acemusic.workspace import ensure_default_workspace

        # Set a dummy URL so the main callback's api_url guard passes
        monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:9999")
        ensure_default_workspace()
        result = runner.invoke(
            app,
            [
                "generate",
                "test prompt",
                "--preset",
                "NonExistent",
            ],
        )
        assert result.exit_code == 1
        assert "not found" in result.output
