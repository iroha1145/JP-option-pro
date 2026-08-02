"""jp-app.db — the only database the API process writes.

Holds the owner's watchlist and per-security marks. Kept separate from
jp-core.db so the worker can stay that file's single writer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import SQLiteRepository, utc_now_iso

APP_SCHEMA_VERSION = "jp-app-v1"

APP_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS watchlist (
        canonical_code TEXT PRIMARY KEY,
        note TEXT,
        marked_important INTEGER NOT NULL DEFAULT 0 CHECK (marked_important IN (0, 1)),
        added_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    ) WITHOUT ROWID
    """,
)


class AppStore(SQLiteRepository):
    SCHEMA_NAME = "jp_app"
    SCHEMA_VERSION = APP_SCHEMA_VERSION
    DDL = APP_DDL

    def __init__(self, db_path: Path, *, read_only: bool = False) -> None:
        super().__init__(db_path, read_only=read_only)

    def watchlist(self) -> list[dict[str, Any]]:
        with self.read() as connection:
            rows = connection.execute(
                "SELECT * FROM watchlist ORDER BY added_at, canonical_code"
            ).fetchall()
        return [dict(row) for row in rows]

    def watchlist_codes(self) -> list[str]:
        with self.read() as connection:
            rows = connection.execute(
                "SELECT canonical_code FROM watchlist ORDER BY added_at, canonical_code"
            ).fetchall()
        return [row[0] for row in rows]

    def add_to_watchlist(self, canonical_code: str, *, note: str | None = None) -> bool:
        now = utc_now_iso()
        with self.write() as connection:
            cursor = connection.execute(
                "INSERT INTO watchlist (canonical_code, note, marked_important, added_at, updated_at) "
                "VALUES (?, ?, 0, ?, ?) ON CONFLICT (canonical_code) DO NOTHING",
                (canonical_code, note, now, now),
            )
            return bool(cursor.rowcount)

    def update_watchlist_item(
        self, canonical_code: str, *, note: str | None = None,
        marked_important: bool | None = None,
    ) -> bool:
        sets = ["updated_at = ?"]
        params: list[Any] = [utc_now_iso()]
        if note is not None:
            sets.append("note = ?")
            params.append(note)
        if marked_important is not None:
            sets.append("marked_important = ?")
            params.append(1 if marked_important else 0)
        params.append(canonical_code)
        with self.write() as connection:
            cursor = connection.execute(
                f"UPDATE watchlist SET {', '.join(sets)} WHERE canonical_code = ?", params
            )
            return bool(cursor.rowcount)

    def remove_from_watchlist(self, canonical_code: str) -> bool:
        with self.write() as connection:
            cursor = connection.execute(
                "DELETE FROM watchlist WHERE canonical_code = ?", (canonical_code,)
            )
            return bool(cursor.rowcount)


__all__ = ["AppStore"]
