"""Tests for workspace repository and CLI commands (US-4.1)."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from acemusic.cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_workspace(tmp_path, monkeypatch):
    """Redirect DB and workspace dirs to tmp_path for full isolation."""
    import acemusic.db as _db

    monkeypatch.setattr(_db, "DB_DIR", tmp_path / ".acemusic")
    return tmp_path


# ---------------------------------------------------------------------------
# ensure_default_workspace
# ---------------------------------------------------------------------------


class TestEnsureDefaultWorkspace:
    def test_creates_default_on_first_access(self, isolated_workspace):
        from acemusic.workspace import ensure_default_workspace, list_workspaces

        ensure_default_workspace()
        workspaces = list_workspaces()
        assert len(workspaces) == 1
        assert workspaces[0].name == "Default"
        assert workspaces[0].is_active

    def test_is_idempotent(self, isolated_workspace):
        from acemusic.workspace import ensure_default_workspace, list_workspaces

        ensure_default_workspace()
        ensure_default_workspace()
        assert len(list_workspaces()) == 1


# ---------------------------------------------------------------------------
# create_workspace
# ---------------------------------------------------------------------------


class TestCreateWorkspace:
    def test_creates_workspace(self, isolated_workspace):
        from acemusic.workspace import create_workspace, list_workspaces

        ws = create_workspace("My Album")
        assert ws.name == "My Album"
        assert any(w.name == "My Album" for w in list_workspaces())

    def test_raises_on_duplicate_name(self, isolated_workspace):
        from acemusic.workspace import create_workspace

        create_workspace("My Album")
        with pytest.raises(ValueError, match="already exists"):
            create_workspace("My Album")


# ---------------------------------------------------------------------------
# list_workspaces
# ---------------------------------------------------------------------------


class TestListWorkspaces:
    def test_returns_all_workspaces(self, isolated_workspace):
        from acemusic.workspace import create_workspace, list_workspaces

        create_workspace("Alpha")
        create_workspace("Beta")
        names = [w.name for w in list_workspaces()]
        assert "Alpha" in names
        assert "Beta" in names

    def test_sorted_by_created_at(self, isolated_workspace):
        from acemusic.workspace import create_workspace, list_workspaces

        create_workspace("First")
        create_workspace("Second")
        names = [w.name for w in list_workspaces()]
        assert names.index("First") < names.index("Second")


# ---------------------------------------------------------------------------
# get_active_workspace
# ---------------------------------------------------------------------------


class TestGetActiveWorkspace:
    def test_returns_default_on_first_access(self, isolated_workspace):
        from acemusic.workspace import get_active_workspace

        ws = get_active_workspace()
        assert ws.name == "Default"
        assert ws.is_active

    def test_returns_switched_workspace(self, isolated_workspace):
        from acemusic.workspace import create_workspace, get_active_workspace, switch_workspace

        create_workspace("Custom")
        switch_workspace("Custom")
        assert get_active_workspace().name == "Custom"


# ---------------------------------------------------------------------------
# switch_workspace
# ---------------------------------------------------------------------------


class TestSwitchWorkspace:
    def test_switches_active_workspace(self, isolated_workspace):
        from acemusic.workspace import create_workspace, get_active_workspace, switch_workspace

        create_workspace("New")
        switch_workspace("New")
        assert get_active_workspace().name == "New"

    def test_only_one_active_at_a_time(self, isolated_workspace):
        from acemusic.workspace import create_workspace, list_workspaces, switch_workspace

        create_workspace("A")
        create_workspace("B")
        switch_workspace("A")
        switch_workspace("B")
        active = [w for w in list_workspaces() if w.is_active]
        assert len(active) == 1
        assert active[0].name == "B"

    def test_raises_on_not_found(self, isolated_workspace):
        from acemusic.workspace import switch_workspace

        with pytest.raises(ValueError, match="not found"):
            switch_workspace("NonExistent")


# ---------------------------------------------------------------------------
# rename_workspace
# ---------------------------------------------------------------------------


class TestRenameWorkspace:
    def test_renames_workspace(self, isolated_workspace):
        from acemusic.workspace import create_workspace, list_workspaces, rename_workspace

        create_workspace("Old Name")
        rename_workspace("Old Name", "New Name")
        names = [w.name for w in list_workspaces()]
        assert "New Name" in names
        assert "Old Name" not in names

    def test_raises_on_not_found(self, isolated_workspace):
        from acemusic.workspace import rename_workspace

        with pytest.raises(ValueError, match="not found"):
            rename_workspace("NonExistent", "New")

    def test_raises_on_duplicate_target(self, isolated_workspace):
        from acemusic.workspace import create_workspace, rename_workspace

        create_workspace("Alpha")
        create_workspace("Beta")
        with pytest.raises(ValueError, match="already exists"):
            rename_workspace("Alpha", "Beta")


# ---------------------------------------------------------------------------
# delete_workspace
# ---------------------------------------------------------------------------


class TestDeleteWorkspace:
    def test_deletes_workspace(self, isolated_workspace):
        from acemusic.workspace import create_workspace, delete_workspace, list_workspaces

        create_workspace("Extra")  # ensure not last
        create_workspace("Temp")
        delete_workspace("Temp")
        names = [w.name for w in list_workspaces()]
        assert "Temp" not in names

    def test_raises_on_not_found(self, isolated_workspace):
        from acemusic.workspace import delete_workspace

        with pytest.raises(ValueError, match="not found"):
            delete_workspace("NonExistent")

    def test_raises_on_last_workspace(self, isolated_workspace):
        from acemusic.workspace import delete_workspace, ensure_default_workspace

        ensure_default_workspace()
        with pytest.raises(ValueError, match="[Ll]ast"):
            delete_workspace("Default")

    def test_removes_clips_directory(self, isolated_workspace):
        from acemusic.workspace import (
            create_workspace,
            delete_workspace,
            get_workspace_path,
        )

        create_workspace("Extra")
        ws = create_workspace("WithFiles")
        clips_dir = get_workspace_path(ws.id)
        clips_dir.mkdir(parents=True, exist_ok=True)
        (clips_dir / "clip.wav").write_bytes(b"FAKE")
        delete_workspace("WithFiles")
        assert not clips_dir.exists()


# ---------------------------------------------------------------------------
# get_workspace_path
# ---------------------------------------------------------------------------


class TestGetWorkspacePath:
    def test_returns_correct_path(self, isolated_workspace, tmp_path):
        from acemusic.workspace import create_workspace, get_workspace_path

        ws = create_workspace("PathTest")
        path = get_workspace_path(ws.id)
        assert path == tmp_path / ".acemusic" / "workspaces" / ws.id / "clips"


# ---------------------------------------------------------------------------
# get_clip_count
# ---------------------------------------------------------------------------


class TestGetClipCount:
    def test_returns_zero_when_empty(self, isolated_workspace):
        from acemusic.workspace import create_workspace, get_clip_count

        ws = create_workspace("Empty")
        assert get_clip_count(ws.id) == 0

    def test_counts_files(self, isolated_workspace):
        from acemusic.workspace import create_workspace, get_clip_count, get_workspace_path

        ws = create_workspace("Full")
        clips_dir = get_workspace_path(ws.id)
        clips_dir.mkdir(parents=True, exist_ok=True)
        (clips_dir / "clip1.wav").write_bytes(b"FAKE")
        (clips_dir / "clip2.wav").write_bytes(b"FAKE")
        assert get_clip_count(ws.id) == 2


# ---------------------------------------------------------------------------
# CLI: workspace create
# ---------------------------------------------------------------------------


class TestWorkspaceCreateCLI:
    def test_create_workspace(self, isolated_workspace):
        result = runner.invoke(app, ["workspace", "create", "My Album"])
        assert result.exit_code == 0, result.output
        assert "My Album" in result.output

    def test_create_duplicate_name_shows_error(self, isolated_workspace):
        runner.invoke(app, ["workspace", "create", "My Album"])
        result = runner.invoke(app, ["workspace", "create", "My Album"])
        assert result.exit_code != 0 or "already exists" in result.output.lower()


# ---------------------------------------------------------------------------
# CLI: workspace list
# ---------------------------------------------------------------------------


class TestWorkspaceListCLI:
    def test_list_shows_default_workspace(self, isolated_workspace):
        result = runner.invoke(app, ["workspace", "list"])
        assert result.exit_code == 0, result.output
        assert "Default" in result.output

    def test_list_shows_created_workspaces(self, isolated_workspace):
        runner.invoke(app, ["workspace", "create", "My Album"])
        result = runner.invoke(app, ["workspace", "list"])
        assert result.exit_code == 0, result.output
        assert "My Album" in result.output

    def test_list_marks_active_workspace(self, isolated_workspace):
        result = runner.invoke(app, ["workspace", "list"])
        assert result.exit_code == 0, result.output
        assert "\u2713" in result.output  # ✓


# ---------------------------------------------------------------------------
# CLI: workspace switch
# ---------------------------------------------------------------------------


class TestWorkspaceSwitchCLI:
    def test_switch_workspace(self, isolated_workspace):
        runner.invoke(app, ["workspace", "create", "New"])
        result = runner.invoke(app, ["workspace", "switch", "New"])
        assert result.exit_code == 0, result.output
        assert "New" in result.output

    def test_switch_not_found_shows_error(self, isolated_workspace):
        result = runner.invoke(app, ["workspace", "switch", "NonExistent"])
        assert result.exit_code != 0 or "not found" in result.output.lower()


# ---------------------------------------------------------------------------
# CLI: workspace rename
# ---------------------------------------------------------------------------


class TestWorkspaceRenameCLI:
    def test_rename_workspace(self, isolated_workspace):
        runner.invoke(app, ["workspace", "create", "Old"])
        result = runner.invoke(app, ["workspace", "rename", "Old", "New"])
        assert result.exit_code == 0, result.output
        assert "New" in result.output


# ---------------------------------------------------------------------------
# CLI: workspace delete
# ---------------------------------------------------------------------------


class TestWorkspaceDeleteCLI:
    def test_delete_with_force_flag(self, isolated_workspace):
        runner.invoke(app, ["workspace", "create", "Temp"])
        runner.invoke(app, ["workspace", "create", "Another"])
        result = runner.invoke(app, ["workspace", "delete", "Temp", "--force"])
        assert result.exit_code == 0, result.output

    def test_delete_prompts_when_clips_exist(self, isolated_workspace):
        from acemusic.workspace import create_workspace, get_workspace_path

        ws = create_workspace("FilledWS")
        create_workspace("Extra")
        clips_dir = get_workspace_path(ws.id)
        clips_dir.mkdir(parents=True, exist_ok=True)
        (clips_dir / "clip.wav").write_bytes(b"FAKE")
        result = runner.invoke(app, ["workspace", "delete", "FilledWS"], input="y\n")
        assert result.exit_code == 0, result.output

    def test_delete_aborts_on_no(self, isolated_workspace):
        from acemusic.workspace import create_workspace, get_workspace_path, list_workspaces

        ws = create_workspace("FilledWS2")
        create_workspace("Extra2")
        clips_dir = get_workspace_path(ws.id)
        clips_dir.mkdir(parents=True, exist_ok=True)
        (clips_dir / "clip.wav").write_bytes(b"FAKE")
        runner.invoke(app, ["workspace", "delete", "FilledWS2"], input="n\n")
        names = [w.name for w in list_workspaces()]
        assert "FilledWS2" in names

    def test_delete_last_workspace_shows_error(self, isolated_workspace):
        result = runner.invoke(app, ["workspace", "delete", "Default", "--force"])
        assert result.exit_code != 0 or "last" in result.output.lower()
