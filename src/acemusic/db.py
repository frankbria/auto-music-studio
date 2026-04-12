"""SQLite database management for acemusic metadata (US-4.1)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS workspaces (
            id         TEXT PRIMARY KEY,
            name       TEXT UNIQUE NOT NULL,
            is_active  INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
