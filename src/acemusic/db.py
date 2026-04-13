"""SQLite database management for acemusic metadata (US-4.1, US-4.2)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from acemusic.models import Clip

DB_DIR: Path = Path.home() / ".acemusic"


def get_db() -> sqlite3.Connection:
    """Return an open SQLite connection to the acemusic metadata database.

    Creates the database file and schema on first call. The caller is
    responsible for closing the connection.
    """
    db_path = DB_DIR / "metadata.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    _init_schema(conn)
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS workspaces (
            id         TEXT PRIMARY KEY,
            name       TEXT UNIQUE NOT NULL,
            is_active  INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS clips (
            id               INTEGER PRIMARY KEY,
            title            TEXT,
            workspace_id     TEXT NOT NULL,
            file_path        TEXT NOT NULL,
            format           TEXT,
            duration         REAL,
            bpm              INTEGER,
            key              TEXT,
            style_tags       TEXT,
            lyrics           TEXT,
            vocal_language   TEXT,
            model            TEXT,
            seed             INTEGER,
            inference_steps  INTEGER,
            parent_clip_id   INTEGER REFERENCES clips(id),
            generation_mode  TEXT,
            created_at       TEXT NOT NULL
        )
        """)
    conn.commit()


# ---------------------------------------------------------------------------
# Clip CRUD
# ---------------------------------------------------------------------------


def _row_to_clip(row: sqlite3.Row) -> "Clip":
    from acemusic.models import Clip

    return Clip(
        id=row["id"],
        title=row["title"],
        workspace_id=row["workspace_id"],
        file_path=row["file_path"],
        format=row["format"],
        duration=row["duration"],
        bpm=row["bpm"],
        key=row["key"],
        style_tags=row["style_tags"],
        lyrics=row["lyrics"],
        vocal_language=row["vocal_language"],
        model=row["model"],
        seed=row["seed"],
        inference_steps=row["inference_steps"],
        parent_clip_id=row["parent_clip_id"],
        generation_mode=row["generation_mode"],
        created_at=row["created_at"],
    )


def create_clip(clip: "Clip") -> int:
    """Insert a clip record and return the new row id."""
    conn = get_db()
    try:
        cur = conn.execute(
            """INSERT INTO clips
               (title, workspace_id, file_path, format, duration, bpm, key,
                style_tags, lyrics, vocal_language, model, seed, inference_steps,
                parent_clip_id, generation_mode, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                clip.title,
                clip.workspace_id,
                clip.file_path,
                clip.format,
                clip.duration,
                clip.bpm,
                clip.key,
                clip.style_tags,
                clip.lyrics,
                clip.vocal_language,
                clip.model,
                clip.seed,
                clip.inference_steps,
                clip.parent_clip_id,
                clip.generation_mode,
                clip.created_at,
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_clip(clip_id: int) -> Optional["Clip"]:
    """Return the clip with the given id, or None if not found."""
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
        return _row_to_clip(row) if row else None
    finally:
        conn.close()


def list_clips(workspace_id: str) -> list["Clip"]:
    """Return all clips for a workspace, newest first."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM clips WHERE workspace_id = ? ORDER BY created_at DESC",
            (workspace_id,),
        ).fetchall()
        return [_row_to_clip(r) for r in rows]
    finally:
        conn.close()


def update_clip_title(clip_id: int, title: str) -> bool:
    """Rename a clip. Returns True if the record existed, False otherwise."""
    conn = get_db()
    try:
        cur = conn.execute("UPDATE clips SET title = ? WHERE id = ?", (title, clip_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_clip(clip_id: int) -> Optional[str]:
    """Delete a clip record and return its file_path, or None if not found."""
    conn = get_db()
    try:
        row = conn.execute("SELECT file_path FROM clips WHERE id = ?", (clip_id,)).fetchone()
        if row is None:
            return None
        file_path = row["file_path"]
        conn.execute("DELETE FROM clips WHERE id = ?", (clip_id,))
        conn.commit()
        return file_path
    finally:
        conn.close()


def search_clips(
    workspace_id: str,
    style: Optional[str] = None,
    bpm_min: Optional[int] = None,
    bpm_max: Optional[int] = None,
    key: Optional[str] = None,
    model: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> list["Clip"]:
    """Return clips matching the given filters, newest first."""
    conditions = ["workspace_id = ?"]
    params: list = [workspace_id]

    if style is not None:
        conditions.append("style_tags LIKE ?")
        params.append(f"%{style}%")
    if bpm_min is not None:
        conditions.append("bpm >= ?")
        params.append(bpm_min)
    if bpm_max is not None:
        conditions.append("bpm <= ?")
        params.append(bpm_max)
    if key is not None:
        conditions.append("key = ?")
        params.append(key)
    if model is not None:
        conditions.append("model = ?")
        params.append(model)
    if date_from is not None:
        conditions.append("DATE(created_at) >= ?")
        params.append(date_from)
    if date_to is not None:
        conditions.append("DATE(created_at) <= ?")
        params.append(date_to)

    where = " AND ".join(conditions)
    conn = get_db()
    try:
        rows = conn.execute(
            f"SELECT * FROM clips WHERE {where} ORDER BY created_at DESC",
            params,
        ).fetchall()
        return [_row_to_clip(r) for r in rows]
    finally:
        conn.close()
