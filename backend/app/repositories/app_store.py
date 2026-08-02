"""jp-app.db — the only database the API process writes.

Holds the owner's watchlist and, since v2, per-account watchlists for
signed-in visitors (identity lives in the shared accounts.db; the JP
security codes stay here so the US app's ticker watchlist is untouched).
Kept separate from jp-core.db so the worker can stay that file's single
writer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import SQLiteRepository, utc_now_iso

APP_SCHEMA_VERSION = "jp-app-v2"

_ACCOUNT_WATCHLIST_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS account_watchlist (
        user_id TEXT NOT NULL,
        canonical_code TEXT NOT NULL,
        note TEXT,
        marked_important INTEGER NOT NULL DEFAULT 0 CHECK (marked_important IN (0, 1)),
        added_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (user_id, canonical_code)
    ) WITHOUT ROWID
    """,
    "CREATE INDEX IF NOT EXISTS idx_account_watchlist_user ON account_watchlist(user_id, added_at)",
)

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
    *_ACCOUNT_WATCHLIST_DDL,
)


class AppStore(SQLiteRepository):
    SCHEMA_NAME = "jp_app"
    SCHEMA_VERSION = APP_SCHEMA_VERSION
    DDL = APP_DDL
    MIGRATIONS = {"jp-app-v1": (_ACCOUNT_WATCHLIST_DDL, APP_SCHEMA_VERSION)}

    #: オーナーの自選は従来の watchlist テーブル。この定数は per-account API が
    #: 「オーナー主体」を選ぶ際の目印にだけ使う（accounts.db の own_local と対応）。
    OWNER_PRINCIPAL = "__owner__"

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

    # ------------------------------------------------------------------
    # per-account watchlist（訪客アカウント; user_id は共有 accounts.db の主体）
    # ------------------------------------------------------------------

    ACCOUNT_WATCHLIST_MAX = 50

    def account_watchlist(self, user_id: str) -> list[dict[str, Any]]:
        with self.read() as connection:
            rows = connection.execute(
                "SELECT * FROM account_watchlist WHERE user_id = ? ORDER BY added_at, canonical_code",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def account_add_to_watchlist(self, user_id: str, canonical_code: str) -> bool:
        now = utc_now_iso()
        with self.write() as connection:
            total = connection.execute(
                "SELECT COUNT(*) FROM account_watchlist WHERE user_id = ?", (user_id,)
            ).fetchone()[0]
            exists = connection.execute(
                "SELECT 1 FROM account_watchlist WHERE user_id = ? AND canonical_code = ?",
                (user_id, canonical_code),
            ).fetchone()
            if exists:
                return False
            if int(total) >= self.ACCOUNT_WATCHLIST_MAX:
                raise ValueError("watchlist_full")
            connection.execute(
                "INSERT INTO account_watchlist (user_id, canonical_code, note, marked_important, added_at, updated_at)"
                " VALUES (?, ?, NULL, 0, ?, ?)",
                (user_id, canonical_code, now, now),
            )
            return True

    def account_update_watchlist_item(
        self, user_id: str, canonical_code: str, *, note: str | None = None,
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
        params.extend([user_id, canonical_code])
        with self.write() as connection:
            cursor = connection.execute(
                f"UPDATE account_watchlist SET {', '.join(sets)} WHERE user_id = ? AND canonical_code = ?",
                params,
            )
            return bool(cursor.rowcount)

    def account_remove_from_watchlist(self, user_id: str, canonical_code: str) -> bool:
        with self.write() as connection:
            cursor = connection.execute(
                "DELETE FROM account_watchlist WHERE user_id = ? AND canonical_code = ?",
                (user_id, canonical_code),
            )
            return bool(cursor.rowcount)


__all__ = ["AppStore"]
