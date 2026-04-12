"""Workspace repository for acemusic (US-4.1).

Workspaces are named containers for audio clips. Audio files are stored under
~/.acemusic/workspaces/{workspace_id}/clips/. A "Default" workspace is
auto-created on first access.
"""

from __future__ import annotations

import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import acemusic.db as _db


@dataclass
class Workspace:
    id: str
    name: str
    is_active: bool
    created_at: str


def _row_to_workspace(row: sqlite3.Row) -> Workspace:
    return Workspace(
        id=row["id"],
        name=row["name"],
        is_active=bool(row["is_active"]),
        created_at=row["created_at"],
    )


def ensure_default_workspace() -> None:
    """Create the Default workspace if no workspaces exist."""
    conn = _db.get_db()
    try:
        count = conn.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0]
        if count == 0:
            ws_id = str(uuid.uuid4())
            created_at = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO workspaces (id, name, is_active, created_at) VALUES (?, ?, 1, ?)",
                (ws_id, "Default", created_at),
            )
            conn.commit()
    finally:
        conn.close()


def create_workspace(name: str) -> Workspace:
    """Create a new workspace with the given name and return it."""
    conn = _db.get_db()
    try:
        if conn.execute("SELECT id FROM workspaces WHERE name = ?", (name,)).fetchone():
            raise ValueError(f"Workspace {name!r} already exists")
        ws_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO workspaces (id, name, is_active, created_at) VALUES (?, ?, 0, ?)",
            (ws_id, name, created_at),
        )
        conn.commit()
        return Workspace(id=ws_id, name=name, is_active=False, created_at=created_at)
    finally:
        conn.close()


def list_workspaces() -> list[Workspace]:
    """Return all workspaces sorted by creation time."""
    conn = _db.get_db()
    try:
        rows = conn.execute("SELECT * FROM workspaces ORDER BY created_at").fetchall()
        return [_row_to_workspace(r) for r in rows]
    finally:
        conn.close()


def get_workspace_by_name(name: str) -> Workspace:
    """Return the workspace with the given name, or raise ValueError if not found."""
    conn = _db.get_db()
    try:
        row = conn.execute("SELECT * FROM workspaces WHERE name = ?", (name,)).fetchone()
        if row is None:
            raise ValueError(f"Workspace {name!r} not found")
        return _row_to_workspace(row)
    finally:
        conn.close()


def get_active_workspace() -> Workspace:
    """Return the active workspace, auto-creating Default if no workspaces exist."""
    ensure_default_workspace()
    conn = _db.get_db()
    try:
        row = conn.execute("SELECT * FROM workspaces WHERE is_active = 1").fetchone()
        if row is None:
            # Edge case: workspaces exist but none is active — activate the oldest.
            first = conn.execute(
                "SELECT * FROM workspaces ORDER BY created_at LIMIT 1"
            ).fetchone()
            conn.execute("UPDATE workspaces SET is_active = 1 WHERE id = ?", (first["id"],))
            conn.commit()
            row = first
        return Workspace(
            id=row["id"],
            name=row["name"],
            is_active=True,
            created_at=row["created_at"],
        )
    finally:
        conn.close()


def switch_workspace(name: str) -> None:
    """Set the named workspace as active."""
    conn = _db.get_db()
    try:
        row = conn.execute("SELECT id FROM workspaces WHERE name = ?", (name,)).fetchone()
        if row is None:
            raise ValueError(f"Workspace {name!r} not found")
        conn.execute("UPDATE workspaces SET is_active = 0")
        conn.execute("UPDATE workspaces SET is_active = 1 WHERE id = ?", (row["id"],))
        conn.commit()
    finally:
        conn.close()


def rename_workspace(old_name: str, new_name: str) -> None:
    """Rename a workspace from old_name to new_name."""
    conn = _db.get_db()
    try:
        row = conn.execute("SELECT id FROM workspaces WHERE name = ?", (old_name,)).fetchone()
        if row is None:
            raise ValueError(f"Workspace {old_name!r} not found")
        if conn.execute("SELECT id FROM workspaces WHERE name = ?", (new_name,)).fetchone():
            raise ValueError(f"Workspace {new_name!r} already exists")
        conn.execute("UPDATE workspaces SET name = ? WHERE id = ?", (new_name, row["id"]))
        conn.commit()
    finally:
        conn.close()


def delete_workspace(name: str) -> None:
    """Delete a workspace by name and remove its clips directory."""
    conn = _db.get_db()
    try:
        row = conn.execute("SELECT id FROM workspaces WHERE name = ?", (name,)).fetchone()
        if row is None:
            raise ValueError(f"Workspace {name!r} not found")
        count = conn.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0]
        if count <= 1:
            raise ValueError("Cannot delete the last remaining workspace")
        ws_id = row["id"]
        conn.execute("DELETE FROM workspaces WHERE id = ?", (ws_id,))
        conn.commit()
    finally:
        conn.close()

    ws_dir = get_workspace_path(ws_id).parent  # parent of clips/
    if ws_dir.exists():
        shutil.rmtree(ws_dir)


def get_workspace_path(workspace_id: str) -> Path:
    """Return the clips directory for the given workspace."""
    return _db.DB_DIR / "workspaces" / workspace_id / "clips"


def get_clip_count(workspace_id: str) -> int:
    """Count audio files in the workspace's clips directory."""
    clips_dir = get_workspace_path(workspace_id)
    if not clips_dir.exists():
        return 0
    return sum(1 for f in clips_dir.iterdir() if f.is_file())
