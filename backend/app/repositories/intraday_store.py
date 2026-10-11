"""jp-intraday.db — 分足・ティックキャッシュ（worker 専用ライタ）。

J-Quants 分足（OHLC-Min）とティック（Tick）はアドオン契約。未契約なら 403 が
返るので、その事実を addon_state に **データセット別** に保存し、UI が
「未契約 / 未有効化」を正直に表示できるようにする。完了した取引日の分足・
ティックは不変データとしてキャッシュされ、再取得しない。

v3: 日別に配信待ちと取得完了を区別し、未配信を後ほど再取得する。
旧 intraday_state（単一行）は
addon_state('minute') へ移行して廃止。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .base import SQLiteRepository, utc_now_iso

INTRADAY_SCHEMA_VERSION = "jp-intraday-v3"

_ADDON_STATE_DDL = """
    CREATE TABLE IF NOT EXISTS addon_state (
        dataset TEXT PRIMARY KEY,
        availability TEXT NOT NULL DEFAULT 'unknown',
        last_checked_at TEXT,
        last_error_code TEXT
    ) WITHOUT ROWID
    """

_TICKS_DDL = """
    CREATE TABLE IF NOT EXISTS ticks (
        canonical_code TEXT NOT NULL,
        trade_date TEXT NOT NULL,
        seq INTEGER NOT NULL,
        tick_time TEXT NOT NULL,
        price REAL,
        volume REAL,
        PRIMARY KEY (canonical_code, trade_date, seq)
    ) WITHOUT ROWID
    """

_TICK_DAYS_DDL = """
    CREATE TABLE IF NOT EXISTS tick_days (
        canonical_code TEXT NOT NULL,
        trade_date TEXT NOT NULL,
        fetched_at TEXT NOT NULL,
        tick_count INTEGER NOT NULL,
        truncated INTEGER NOT NULL DEFAULT 0,
        fetch_status TEXT NOT NULL DEFAULT 'complete',
        PRIMARY KEY (canonical_code, trade_date)
    ) WITHOUT ROWID
    """

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
    CREATE TABLE IF NOT EXISTS fetched_days (
        canonical_code TEXT NOT NULL,
        trade_date TEXT NOT NULL,
        fetched_at TEXT NOT NULL,
        bar_count INTEGER NOT NULL,
        fetch_status TEXT NOT NULL DEFAULT 'complete',
        PRIMARY KEY (canonical_code, trade_date)
    ) WITHOUT ROWID
    """,
    _ADDON_STATE_DDL,
    _TICKS_DDL,
    _TICK_DAYS_DDL,
)

INTRADAY_MIGRATIONS: dict[str, tuple[tuple[str, ...], str]] = {
    "jp-intraday-v1": (
        (
            _ADDON_STATE_DDL,
            _TICKS_DDL,
            _TICK_DAYS_DDL,
            "INSERT INTO addon_state (dataset, availability, last_checked_at, last_error_code) "
            "SELECT 'minute', availability, last_checked_at, last_error_code "
            "FROM intraday_state WHERE id = 1",
            "DROP TABLE intraday_state",
        ),
        "jp-intraday-v2",
    ),
    "jp-intraday-v2": (
        (
            "ALTER TABLE fetched_days ADD COLUMN fetch_status TEXT NOT NULL DEFAULT 'complete'",
            "ALTER TABLE tick_days ADD COLUMN fetch_status TEXT NOT NULL DEFAULT 'complete'",
            # Old zero-count markers also meant 'file not published yet'. Recheck once.
            "UPDATE fetched_days SET fetch_status = 'not_published' WHERE bar_count = 0",
            "UPDATE tick_days SET fetch_status = 'not_published' WHERE tick_count = 0",
        ),
        INTRADAY_SCHEMA_VERSION,
    ),
}

AVAILABILITY_UNKNOWN = "unknown"
AVAILABILITY_AVAILABLE = "available"
AVAILABILITY_PLAN_NOT_INCLUDED = "plan_not_included"

DATASET_MINUTE = "minute"
DATASET_TICK = "tick"

_TICK_INSERT_CHUNK = 5_000


class IntradayStore(SQLiteRepository):
    SCHEMA_NAME = "jp_intraday"
    SCHEMA_VERSION = INTRADAY_SCHEMA_VERSION
    DDL = INTRADAY_DDL
    MIGRATIONS = INTRADAY_MIGRATIONS

    def __init__(self, db_path: Path, *, read_only: bool = False) -> None:
        super().__init__(db_path, read_only=read_only)

    # ---------------- 可用性（データセット別） ----------------

    def availability(self, dataset: str = DATASET_MINUTE) -> dict[str, Any]:
        with self.read() as connection:
            row = connection.execute(
                "SELECT dataset, availability, last_checked_at, last_error_code "
                "FROM addon_state WHERE dataset = ?",
                (dataset,),
            ).fetchone()
        if row is None:
            return {
                "dataset": dataset,
                "availability": AVAILABILITY_UNKNOWN,
                "last_checked_at": None,
                "last_error_code": None,
            }
        return dict(row)

    def record_availability(
        self, availability: str, *, error_code: str | None = None, dataset: str = DATASET_MINUTE
    ) -> None:
        with self.write() as connection:
            connection.execute(
                "INSERT INTO addon_state (dataset, availability, last_checked_at, last_error_code) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT (dataset) DO UPDATE SET availability = excluded.availability, "
                "last_checked_at = excluded.last_checked_at, last_error_code = excluded.last_error_code",
                (dataset, availability, utc_now_iso(), error_code),
            )

    # ---------------- 分足 ----------------

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

    def record_fetched_day(
        self, canonical_code: str, trade_date: str, bar_count: int, *, fetch_status: str = "complete"
    ) -> None:
        with self.write() as connection:
            connection.execute(
                "INSERT INTO fetched_days (canonical_code, trade_date, fetched_at, bar_count, fetch_status) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT (canonical_code, trade_date) DO UPDATE SET "
                "fetched_at = excluded.fetched_at, bar_count = excluded.bar_count, "
                "fetch_status = excluded.fetch_status",
                (canonical_code, trade_date, utc_now_iso(), int(bar_count), fetch_status),
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

    def prune_older_than(self, cutoff_date: str, *, canonical_code: str | None = None) -> int:
        scope = " AND canonical_code = ?" if canonical_code else ""
        params = (cutoff_date, canonical_code) if canonical_code else (cutoff_date,)
        with self.write() as connection:
            cursor = connection.execute(
                "DELETE FROM minute_bars WHERE trade_date < ?" + scope, params
            )
            connection.execute("DELETE FROM fetched_days WHERE trade_date < ?" + scope, params)
            return cursor.rowcount or 0

    # ---------------- ティック ----------------

    def replace_ticks(
        self,
        canonical_code: str,
        trade_date: str,
        rows: Sequence[Mapping[str, Any]],
        *,
        truncated: bool = False,
        fetch_status: str = "complete",
    ) -> int:
        """当日分を丸ごと置換（部分日→完全日への育ちを単純に保つ）。

        一つの書き込みトランザクション内で DELETE + チャンク insert する:
        原子性が保たれ、読者は常に「無い or 完全なスナップショット」を見る。
        """

        prepared = [
            (canonical_code, trade_date, seq, row["tick_time"], row.get("price"), row.get("volume"))
            for seq, row in enumerate(rows)
            if row.get("tick_time")
        ]
        with self.write() as connection:
            connection.execute(
                "DELETE FROM ticks WHERE canonical_code = ? AND trade_date = ?",
                (canonical_code, trade_date),
            )
            for start in range(0, len(prepared), _TICK_INSERT_CHUNK):
                connection.executemany(
                    "INSERT INTO ticks (canonical_code, trade_date, seq, tick_time, price, volume) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    prepared[start : start + _TICK_INSERT_CHUNK],
                )
            connection.execute(
                "INSERT INTO tick_days (canonical_code, trade_date, fetched_at, tick_count, truncated, fetch_status) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (canonical_code, trade_date) DO UPDATE SET "
                "fetched_at = excluded.fetched_at, tick_count = excluded.tick_count, "
                "truncated = excluded.truncated, fetch_status = excluded.fetch_status",
                (canonical_code, trade_date, utc_now_iso(), len(prepared), 1 if truncated else 0, fetch_status),
            )
        return len(prepared)

    def tick_days_for(self, canonical_code: str) -> dict[str, dict[str, Any]]:
        with self.read() as connection:
            rows = connection.execute(
                "SELECT * FROM tick_days WHERE canonical_code = ?", (canonical_code,)
            ).fetchall()
        return {row["trade_date"]: dict(row) for row in rows}

    def mark_ticks_not_published(self, canonical_code: str, trade_date: str) -> None:
        """Record a retryable missing file without erasing an existing tape."""
        with self.write() as connection:
            connection.execute(
                "INSERT INTO tick_days (canonical_code, trade_date, fetched_at, tick_count, fetch_status) "
                "VALUES (?, ?, ?, 0, 'not_published') ON CONFLICT (canonical_code, trade_date) "
                "DO UPDATE SET fetched_at = excluded.fetched_at, fetch_status = excluded.fetch_status",
                (canonical_code, trade_date, utc_now_iso()),
            )

    def dataset_summary(self, dataset: str) -> dict[str, Any]:
        """Summarize the real cache, independently of the daily sync checkpoints."""
        table, days = ("ticks", "tick_days") if dataset == DATASET_TICK else ("minute_bars", "fetched_days")
        with self.read() as connection:
            row = connection.execute(
                f"SELECT COUNT(*) AS rows_total, MAX(trade_date) AS data_through FROM {table}"
            ).fetchone()
            completed = connection.execute(
                f"SELECT MAX(trade_date) AS checked_through, MAX(fetched_at) AS last_success_at "
                f"FROM {days} WHERE fetch_status = 'complete'"
            ).fetchone()
        return {**self.availability(dataset), **dict(row), **dict(completed)}

    def ticks_for(self, canonical_code: str, trade_date: str) -> list[dict[str, Any]]:
        with self.read() as connection:
            rows = connection.execute(
                "SELECT seq, tick_time, price, volume FROM ticks "
                "WHERE canonical_code = ? AND trade_date = ? ORDER BY seq",
                (canonical_code, trade_date),
            ).fetchall()
        return [dict(row) for row in rows]

    def tick_day_has_volume(self, canonical_code: str, trade_date: str) -> bool:
        """その日のティックに数量が 1 件でも入っているか（壊れた取り込みの検出）。"""

        with self.read() as connection:
            row = connection.execute(
                "SELECT 1 FROM ticks WHERE canonical_code = ? AND trade_date = ? "
                "AND volume IS NOT NULL LIMIT 1",
                (canonical_code, trade_date),
            ).fetchone()
        return row is not None

    def prune_ticks_older_than(self, cutoff_date: str, *, canonical_code: str | None = None) -> int:
        scope = " AND canonical_code = ?" if canonical_code else ""
        params = (cutoff_date, canonical_code) if canonical_code else (cutoff_date,)
        with self.write() as connection:
            cursor = connection.execute("DELETE FROM ticks WHERE trade_date < ?" + scope, params)
            connection.execute("DELETE FROM tick_days WHERE trade_date < ?" + scope, params)
            return cursor.rowcount or 0


__all__ = [
    "AVAILABILITY_AVAILABLE",
    "AVAILABILITY_PLAN_NOT_INCLUDED",
    "AVAILABILITY_UNKNOWN",
    "DATASET_MINUTE",
    "DATASET_TICK",
    "INTRADAY_MIGRATIONS",
    "INTRADAY_SCHEMA_VERSION",
    "IntradayStore",
]
