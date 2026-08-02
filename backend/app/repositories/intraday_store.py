"""jp-intraday.db — 分足キャッシュ（worker 専用ライタ）。

J-Quants 分足はアドオン契約。未契約なら 403 が返るので、その事実を
availability として保存し、UI が「未契約」を正直に表示できるようにする。
完了した取引日の分足は不変データとしてキャッシュされ、再取得しない。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

from .base import SQLiteRepository, utc_now_iso

INTRADAY_SCHEMA_VERSION = "jp-intraday-v1"

INTRADAY_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS minute_bars (
        canonical_code TEXT NOT NULL,
        trade_date TEXT NOT NULL,
        bar_time TEXT NOT NULL,
        open REAL, high REAL, low REAL, close REAL,
        volume REAL, turnover_value REAL,
        PRIMARY KEY (canonical_code, trade_date, bar_time)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE IF NOT EXISTS intraday_state (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        availability TEXT NOT NULL DEFAULT 'unknown',
        last_checked_at TEXT,
        last_error_code TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fetched_days (
        canonical_code TEXT NOT NULL,
        trade_date TEXT NOT NULL,
        fetched_at TEXT NOT NULL,
        bar_count INTEGER NOT NULL,
        PRIMARY KEY (canonical_code, trade_date)
    ) WITHOUT ROWID
    """,
)

AVAILABILITY_UNKNOWN = "unknown"
AVAILABILITY_AVAILABLE = "available"
AVAILABILITY_PLAN_NOT_INCLUDED = "plan_not_included"


class IntradayStore(SQLiteRepository):
    SCHEMA_NAME = "jp_intraday"
    SCHEMA_VERSION = INTRADAY_SCHEMA_VERSION
    DDL = INTRADAY_DDL

    def __init__(self, db_path: Path, *, read_only: bool = False) -> None:
        super().__init__(db_path, read_only=read_only)

    def availability(self) -> dict[str, Any]:
        with self.read() as connection:
            row = connection.execute("SELECT * FROM intraday_state WHERE id = 1").fetchone()
        if row is None:
            return {"availability": AVAILABILITY_UNKNOWN, "last_checked_at": None, "last_error_code": None}
        return dict(row)

    def record_availability(self, availability: str, *, error_code: str | None = None) -> None:
        with self.write() as connection:
            connection.execute(
                "INSERT INTO intraday_state (id, availability, last_checked_at, last_error_code) "
                "VALUES (1, ?, ?, ?) "
                "ON CONFLICT (id) DO UPDATE SET availability = excluded.availability, "
                "last_checked_at = excluded.last_checked_at, last_error_code = excluded.last_error_code",
                (availability, utc_now_iso(), error_code),
            )

    def upsert_minute_bars(self, rows: Iterable[Mapping[str, Any]]) -> int:
        prepared = [
            (
                row["canonical_code"], row["trade_date"], row["bar_time"],
                row.get("open"), row.get("high"), row.get("low"), row.get("close"),
                row.get("volume"), row.get("turnover_value"),
            )
            for row in rows
            if row.get("canonical_code") and row.get("trade_date") and row.get("bar_time")
        ]
        if not prepared:
            return 0
        with self.write() as connection:
            connection.executemany(
                "INSERT INTO minute_bars (canonical_code, trade_date, bar_time, open, high, low, "
                "close, volume, turnover_value) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (canonical_code, trade_date, bar_time) DO UPDATE SET "
                "open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close, "
                "volume=excluded.volume, turnover_value=excluded.turnover_value",
                prepared,
            )
        return len(prepared)

    def record_fetched_day(self, canonical_code: str, trade_date: str, bar_count: int) -> None:
        with self.write() as connection:
            connection.execute(
                "INSERT INTO fetched_days (canonical_code, trade_date, fetched_at, bar_count) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT (canonical_code, trade_date) DO UPDATE SET "
                "fetched_at = excluded.fetched_at, bar_count = excluded.bar_count",
                (canonical_code, trade_date, utc_now_iso(), int(bar_count)),
            )

    def fetched_days_for(self, canonical_code: str) -> dict[str, dict[str, Any]]:
        with self.read() as connection:
            rows = connection.execute(
                "SELECT * FROM fetched_days WHERE canonical_code = ?", (canonical_code,)
            ).fetchall()
        return {row["trade_date"]: dict(row) for row in rows}

    def minute_bars(
        self, canonical_code: str, *, dates: Iterable[str] | None = None
    ) -> list[dict[str, Any]]:
        if dates is not None:
            date_list = sorted(set(dates))
            if not date_list:
                return []
            placeholders = ", ".join("?" for _ in date_list)
            query = (
                "SELECT * FROM minute_bars WHERE canonical_code = ? "
                f"AND trade_date IN ({placeholders}) ORDER BY trade_date, bar_time"
            )
            params: tuple[Any, ...] = (canonical_code, *date_list)
        else:
            query = (
                "SELECT * FROM minute_bars WHERE canonical_code = ? ORDER BY trade_date, bar_time"
            )
            params = (canonical_code,)
        with self.read() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def prune_older_than(self, cutoff_date: str) -> int:
        with self.write() as connection:
            cursor = connection.execute(
                "DELETE FROM minute_bars WHERE trade_date < ?", (cutoff_date,)
            )
            connection.execute("DELETE FROM fetched_days WHERE trade_date < ?", (cutoff_date,))
            return cursor.rowcount or 0


__all__ = [
    "AVAILABILITY_AVAILABLE",
    "AVAILABILITY_PLAN_NOT_INCLUDED",
    "AVAILABILITY_UNKNOWN",
    "INTRADAY_SCHEMA_VERSION",
    "IntradayStore",
]
