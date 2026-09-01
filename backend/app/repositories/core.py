"""Repository over jp-core.db — worker-only writer, API reads read-only.

All writes are idempotent upserts inside single transactions; re-running a
sync for the same date set must be a no-op apart from ``ingested_at``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from app.domain.constants import EQUITY_TRADING_DIVISIONS
from app.domain.symbols import display_code

from .base import SQLiteRepository, utc_now_iso
from .core_schema import CORE_DDL, CORE_MIGRATIONS, CORE_SCHEMA_VERSION


def _upsert_sql(table: str, columns: Sequence[str], conflict: Sequence[str]) -> str:
    updates = [c for c in columns if c not in conflict]
    placeholders = ", ".join("?" for _ in columns)
    set_clause = ", ".join(f"{c} = excluded.{c}" for c in updates)
    return (
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT ({', '.join(conflict)}) DO UPDATE SET {set_clause}"
    )


class CoreRepository(SQLiteRepository):
    SCHEMA_NAME = "jp_core"
    SCHEMA_VERSION = CORE_SCHEMA_VERSION
    DDL = CORE_DDL
    MIGRATIONS = CORE_MIGRATIONS

    def __init__(self, db_path: Path, *, read_only: bool = False) -> None:
        super().__init__(db_path, read_only=read_only)

    # ------------------------------------------------------------------
    # securities master
    # ------------------------------------------------------------------

    _SECURITY_COLUMNS = (
        "canonical_code", "display_code", "name_ja", "name_en",
        "sector17_code", "sector17_name", "sector33_code", "sector33_name",
        "scale_category", "market_code", "market_name", "margin_code",
        "margin_name", "product_category", "as_of_date", "first_seen_date",
        "delisted_date", "active", "updated_at",
    )

    def replace_security_master(self, rows: Iterable[Mapping[str, Any]], *, as_of_date: str) -> dict[str, int]:
        """Apply a full master snapshot: upsert every row, deactivate missing codes."""

        now = utc_now_iso()
        prepared: list[tuple[Any, ...]] = []
        seen: set[str] = set()
        for row in rows:
            code = row.get("canonical_code")
            if not code or code in seen:
                continue
            seen.add(code)
            prepared.append(
                (
                    code, display_code(code), row.get("name_ja"), row.get("name_en"),
                    row.get("sector17_code"), row.get("sector17_name"),
                    row.get("sector33_code"), row.get("sector33_name"),
                    row.get("scale_category"), row.get("market_code"), row.get("market_name"),
                    row.get("margin_code"), row.get("margin_name"), row.get("product_category"),
                    row.get("as_of_date") or as_of_date,
                    as_of_date,  # first_seen_date default; existing rows keep theirs
                    None, 1, now,
                )
            )
        if not prepared:
            return {"upserted": 0, "deactivated": 0}
        sql = (
            f"INSERT INTO securities ({', '.join(self._SECURITY_COLUMNS)}) "
            f"VALUES ({', '.join('?' for _ in self._SECURITY_COLUMNS)}) "
            "ON CONFLICT (canonical_code) DO UPDATE SET "
            "display_code=excluded.display_code, name_ja=excluded.name_ja, name_en=excluded.name_en, "
            "sector17_code=excluded.sector17_code, sector17_name=excluded.sector17_name, "
            "sector33_code=excluded.sector33_code, sector33_name=excluded.sector33_name, "
            "scale_category=excluded.scale_category, market_code=excluded.market_code, "
            "market_name=excluded.market_name, margin_code=excluded.margin_code, "
            "margin_name=excluded.margin_name, product_category=excluded.product_category, "
            "as_of_date=excluded.as_of_date, delisted_date=NULL, active=1, updated_at=excluded.updated_at"
        )
        with self.write() as connection:
            connection.executemany(sql, prepared)
            placeholders = ", ".join("?" for _ in seen)
            cursor = connection.execute(
                f"UPDATE securities SET active = 0, delisted_date = ?, updated_at = ? "
                f"WHERE active = 1 AND canonical_code NOT IN ({placeholders})",
                (as_of_date, now, *sorted(seen)),
            )
            deactivated = cursor.rowcount if cursor.rowcount is not None else 0
        return {"upserted": len(prepared), "deactivated": deactivated}

    def list_securities(
        self,
        *,
        active_only: bool = True,
        market_codes: Sequence[str] | None = None,
        sector33_codes: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if active_only:
            clauses.append("active = 1")
        if market_codes:
            clauses.append(f"market_code IN ({', '.join('?' for _ in market_codes)})")
            params.extend(market_codes)
        if sector33_codes:
            clauses.append(f"sector33_code IN ({', '.join('?' for _ in sector33_codes)})")
            params.extend(sector33_codes)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.read() as connection:
            rows = connection.execute(
                f"SELECT * FROM securities {where} ORDER BY canonical_code", params
            ).fetchall()
        return [dict(row) for row in rows]

    def get_security(self, canonical_code: str) -> dict[str, Any] | None:
        with self.read() as connection:
            row = connection.execute(
                "SELECT * FROM securities WHERE canonical_code = ?", (canonical_code,)
            ).fetchone()
        return dict(row) if row else None

    def search_securities(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        text = (query or "").strip()
        if not text:
            return []
        like = f"%{text}%"
        prefix = f"{text.upper()}%"
        with self.read() as connection:
            rows = connection.execute(
                """
                SELECT *,
                    CASE
                        WHEN display_code = ? THEN 0
                        WHEN display_code LIKE ? THEN 1
                        WHEN name_ja LIKE ? THEN 2
                        WHEN name_en LIKE ? THEN 3
                        ELSE 4
                    END AS match_rank
                FROM securities
                WHERE active = 1 AND (
                    display_code LIKE ? OR canonical_code LIKE ?
                    OR name_ja LIKE ? OR name_en LIKE ?
                )
                ORDER BY match_rank, display_code
                LIMIT ?
                """,
                (text.upper(), prefix, like, like, prefix, prefix, like, like, int(limit)),
            ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item.pop("match_rank", None)
            results.append(item)
        return results

    # ------------------------------------------------------------------
    # trading calendar
    # ------------------------------------------------------------------

    def upsert_trading_days(self, rows: Iterable[Mapping[str, Any]]) -> int:
        prepared = [
            (row["calendar_date"], row["holiday_division"])
            for row in rows
            if row.get("calendar_date") and row.get("holiday_division") is not None
        ]
        if not prepared:
            return 0
        with self.write() as connection:
            connection.executemany(
                "INSERT INTO trading_calendar (calendar_date, holiday_division) VALUES (?, ?) "
                "ON CONFLICT (calendar_date) DO UPDATE SET holiday_division = excluded.holiday_division",
                prepared,
            )
        return len(prepared)

    def trading_days_between(self, start_date: str, end_date: str) -> list[str]:
        divisions = tuple(sorted(EQUITY_TRADING_DIVISIONS))
        with self.read() as connection:
            rows = connection.execute(
                f"""
                SELECT calendar_date FROM trading_calendar
                WHERE calendar_date >= ? AND calendar_date <= ?
                  AND holiday_division IN ({', '.join('?' for _ in divisions)})
                ORDER BY calendar_date
                """,
                (start_date, end_date, *divisions),
            ).fetchall()
        return [row[0] for row in rows]

    def latest_trading_day(self, on_or_before: str) -> str | None:
        divisions = tuple(sorted(EQUITY_TRADING_DIVISIONS))
        with self.read() as connection:
            row = connection.execute(
                f"""
                SELECT calendar_date FROM trading_calendar
                WHERE calendar_date <= ?
                  AND holiday_division IN ({', '.join('?' for _ in divisions)})
                ORDER BY calendar_date DESC LIMIT 1
                """,
                (on_or_before, *divisions),
            ).fetchone()
        return row[0] if row else None

    def next_trading_day(self, after: str) -> str | None:
        divisions = tuple(sorted(EQUITY_TRADING_DIVISIONS))
        with self.read() as connection:
            row = connection.execute(
                f"""
                SELECT calendar_date FROM trading_calendar
                WHERE calendar_date > ?
                  AND holiday_division IN ({', '.join('?' for _ in divisions)})
                ORDER BY calendar_date LIMIT 1
                """,
                (after, *divisions),
            ).fetchone()
        return row[0] if row else None

    def is_trading_day(self, date: str) -> bool | None:
        with self.read() as connection:
            row = connection.execute(
                "SELECT holiday_division FROM trading_calendar WHERE calendar_date = ?", (date,)
            ).fetchone()
        if row is None:
            return None
        return row[0] in EQUITY_TRADING_DIVISIONS

    # ------------------------------------------------------------------
    # daily bars
    # ------------------------------------------------------------------

    _BAR_COLUMNS = (
        "canonical_code", "trade_date", "open", "high", "low", "close",
        "upper_limit", "lower_limit", "volume", "turnover_value",
        "adjustment_factor", "adj_open", "adj_high", "adj_low", "adj_close",
        "adj_volume", "ingested_at",
    )

    def upsert_daily_bars(self, rows: Iterable[Mapping[str, Any]]) -> int:
        now = utc_now_iso()
        prepared = [
            tuple(row.get(column) for column in self._BAR_COLUMNS[:-1]) + (now,)
            for row in rows
            if row.get("canonical_code") and row.get("trade_date")
        ]
        if not prepared:
            return 0
        sql = _upsert_sql("daily_bars", self._BAR_COLUMNS, ("canonical_code", "trade_date"))
        with self.write() as connection:
            connection.executemany(sql, prepared)
        return len(prepared)

    def bars_for_code(
        self, canonical_code: str, *, start_date: str | None = None, end_date: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["canonical_code = ?"]
        params: list[Any] = [canonical_code]
        if start_date:
            clauses.append("trade_date >= ?")
            params.append(start_date)
        if end_date:
            clauses.append("trade_date <= ?")
            params.append(end_date)
        sql = f"SELECT * FROM daily_bars WHERE {' AND '.join(clauses)} ORDER BY trade_date"
        if limit is not None:
            sql = (
                f"SELECT * FROM (SELECT * FROM daily_bars WHERE {' AND '.join(clauses)} "
                f"ORDER BY trade_date DESC LIMIT {int(limit)}) ORDER BY trade_date"
            )
        with self.read() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def bars_matrix_since(self, start_date: str) -> dict[str, list[dict[str, Any]]]:
        """Per-code bar lists for the radar/screener full-market scan."""

        with self.read() as connection:
            rows = connection.execute(
                """
                SELECT canonical_code, trade_date, close, adj_close, adj_open, adj_high, adj_low,
                       turnover_value, volume, adj_volume, upper_limit
                FROM daily_bars WHERE trade_date >= ?
                ORDER BY canonical_code, trade_date
                """,
                (start_date,),
            ).fetchall()
        result: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            result.setdefault(row["canonical_code"], []).append(dict(row))
        return result

    def cross_section_on(self, trade_date: str) -> list[dict[str, Any]]:
        with self.read() as connection:
            rows = connection.execute(
                "SELECT * FROM daily_bars WHERE trade_date = ?", (trade_date,)
            ).fetchall()
        return [dict(row) for row in rows]

    def latest_quote_map(self) -> dict[str, dict[str, Any]]:
        """最新営業日の終値・前日比（全市場、2クエリ・3列のみ）。"""

        with self.read() as connection:
            latest = connection.execute("SELECT MAX(trade_date) FROM daily_bars").fetchone()[0]
            if not latest:
                return {}
            prior = connection.execute(
                "SELECT MAX(trade_date) FROM daily_bars WHERE trade_date < ?", (latest,)
            ).fetchone()[0]
            rows = connection.execute(
                "SELECT canonical_code, trade_date, close, adj_close FROM daily_bars "
                "WHERE trade_date IN (?, ?)",
                (latest, prior or latest),
            ).fetchall()
        prior_adj: dict[str, float] = {}
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            if row["trade_date"] == latest:
                result[row["canonical_code"]] = {
                    "close": row["close"], "adj_close": row["adj_close"], "change_pct": None,
                }
            else:
                if row["adj_close"] is not None:
                    prior_adj[row["canonical_code"]] = row["adj_close"]
        for code, quote in result.items():
            adj = quote.pop("adj_close", None)
            prev = prior_adj.get(code)
            if adj and prev:
                quote["change_pct"] = round((adj / prev - 1.0) * 100.0, 2)
        return result

    def latest_bar_date(self) -> str | None:
        with self.read() as connection:
            row = connection.execute("SELECT MAX(trade_date) FROM daily_bars").fetchone()
        return row[0] if row and row[0] else None

    def bar_dates_present(self, start_date: str, end_date: str) -> set[str]:
        with self.read() as connection:
            rows = connection.execute(
                "SELECT DISTINCT trade_date FROM daily_bars WHERE trade_date >= ? AND trade_date <= ?",
                (start_date, end_date),
            ).fetchall()
        return {row[0] for row in rows}

    # ------------------------------------------------------------------
    # index bars
    # ------------------------------------------------------------------

    def upsert_index_bars(self, rows: Iterable[Mapping[str, Any]]) -> int:
        now = utc_now_iso()
        prepared = [
            (row["index_code"], row["trade_date"], row.get("open"), row.get("high"),
             row.get("low"), row.get("close"), now)
            for row in rows
            if row.get("index_code") and row.get("trade_date")
        ]
        if not prepared:
            return 0
        with self.write() as connection:
            connection.executemany(
                "INSERT INTO index_bars (index_code, trade_date, open, high, low, close, ingested_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (index_code, trade_date) DO UPDATE SET open=excluded.open, "
                "high=excluded.high, low=excluded.low, close=excluded.close, ingested_at=excluded.ingested_at",
                prepared,
            )
        return len(prepared)

    def index_series(
        self, index_code: str, *, start_date: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        params: list[Any] = [index_code]
        clause = ""
        if start_date:
            clause = "AND trade_date >= ?"
            params.append(start_date)
        sql = f"SELECT * FROM index_bars WHERE index_code = ? {clause} ORDER BY trade_date"
        if limit is not None:
            sql = (
                f"SELECT * FROM (SELECT * FROM index_bars WHERE index_code = ? {clause} "
                f"ORDER BY trade_date DESC LIMIT {int(limit)}) ORDER BY trade_date"
            )
        with self.read() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def latest_index_date(self) -> str | None:
        with self.read() as connection:
            row = connection.execute("SELECT MAX(trade_date) FROM index_bars").fetchone()
        return row[0] if row and row[0] else None

    # ------------------------------------------------------------------
    # financial summaries
    # ------------------------------------------------------------------

    _FIN_COLUMNS = (
        "canonical_code", "disclosed_date", "disclosure_number", "disclosed_time",
        "type_of_document", "period_type", "period_start", "period_end",
        "fiscal_year_start", "fiscal_year_end", "next_fiscal_year_start", "next_fiscal_year_end",
        "sales", "operating_profit", "ordinary_profit", "net_profit", "eps",
        "total_assets", "equity", "equity_ratio", "bps",
        "forecast_sales_2q", "forecast_operating_profit_2q", "forecast_ordinary_profit_2q",
        "forecast_net_profit_2q", "forecast_eps_2q",
        "forecast_sales", "forecast_operating_profit", "forecast_ordinary_profit",
        "forecast_net_profit", "forecast_eps",
        "next_forecast_sales", "next_forecast_operating_profit", "next_forecast_ordinary_profit",
        "next_forecast_net_profit", "next_forecast_eps",
        "dividend_annual", "forecast_dividend_annual", "next_forecast_dividend_annual",
        "payout_ratio_annual",
        "material_change_subsidiaries", "change_by_accounting_standard",
        "change_other_than_accounting_standard", "change_accounting_estimate",
        "retrospective_restatement",
        "shares_outstanding_fy", "treasury_shares_fy", "average_shares",
        "nc_sales", "nc_operating_profit", "nc_ordinary_profit", "nc_net_profit", "nc_eps",
        "ingested_at",
    )

    def upsert_financial_summaries(self, rows: Iterable[Mapping[str, Any]]) -> int:
        now = utc_now_iso()
        prepared = []
        for row in rows:
            if not row.get("canonical_code") or not row.get("disclosed_date"):
                continue
            values = {column: row.get(column) for column in self._FIN_COLUMNS}
            values["disclosure_number"] = values.get("disclosure_number") or ""
            values["ingested_at"] = now
            prepared.append(tuple(values[column] for column in self._FIN_COLUMNS))
        if not prepared:
            return 0
        sql = _upsert_sql(
            "financial_summaries", self._FIN_COLUMNS,
            ("canonical_code", "disclosed_date", "disclosure_number"),
        )
        with self.write() as connection:
            connection.executemany(sql, prepared)
        return len(prepared)

    def summaries_for_code(self, canonical_code: str, *, limit: int = 40) -> list[dict[str, Any]]:
        with self.read() as connection:
            rows = connection.execute(
                "SELECT * FROM financial_summaries WHERE canonical_code = ? "
                "ORDER BY disclosed_date DESC, disclosure_number DESC LIMIT ?",
                (canonical_code, int(limit)),
            ).fetchall()
        return [dict(row) for row in rows]

    def summaries_disclosed_between(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        with self.read() as connection:
            rows = connection.execute(
                "SELECT * FROM financial_summaries WHERE disclosed_date >= ? AND disclosed_date <= ? "
                "ORDER BY disclosed_date DESC",
                (start_date, end_date),
            ).fetchall()
        return [dict(row) for row in rows]

    def latest_summary_map(self) -> dict[str, dict[str, Any]]:
        """Latest disclosure per security (by disclosed_date, disclosure_number).

        disclosure_number is ranked numerically: a string MAX on
        ``disclosed_date || '#' || disclosure_number`` picks "#99" over "#100"
        (lexicographic), which would select an older disclosure as "latest".
        """

        with self.read() as connection:
            rows = connection.execute(
                """
                SELECT * FROM (
                    SELECT fs.*, ROW_NUMBER() OVER (
                        PARTITION BY canonical_code
                        ORDER BY disclosed_date DESC, CAST(disclosure_number AS INTEGER) DESC
                    ) AS _rn
                    FROM financial_summaries fs
                ) WHERE _rn = 1
                """
            ).fetchall()
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            record = dict(row)
            record.pop("_rn", None)
            result[record["canonical_code"]] = record
        return result

    # ------------------------------------------------------------------
    # earnings announcements
    # ------------------------------------------------------------------

    def replace_earnings_announcements(self, rows: Iterable[Mapping[str, Any]]) -> int:
        now = utc_now_iso()
        prepared = [
            (
                row["canonical_code"], row.get("fiscal_year_end") or "", row.get("fiscal_quarter") or "",
                row.get("announcement_date") or "", row.get("company_name"), row.get("sector_name"),
                row.get("section"), now,
            )
            for row in rows
            if row.get("canonical_code")
        ]
        with self.write() as connection:
            connection.execute("DELETE FROM earnings_announcements")
            if prepared:
                connection.executemany(
                    "INSERT INTO earnings_announcements (canonical_code, fiscal_year_end, fiscal_quarter, "
                    "announcement_date, company_name, sector_name, section, synced_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT (canonical_code, fiscal_year_end, fiscal_quarter) DO UPDATE SET "
                    "announcement_date=excluded.announcement_date, company_name=excluded.company_name, "
                    "sector_name=excluded.sector_name, section=excluded.section, synced_at=excluded.synced_at",
                    prepared,
                )
        return len(prepared)

    def earnings_between(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        # 未定（announcement_date=''）は日付レンジに関係なく常に返す —
        # 「予定があるが日付未定」を範囲フィルタで黙って消さない。
        with self.read() as connection:
            rows = connection.execute(
                "SELECT * FROM earnings_announcements "
                "WHERE (announcement_date >= ? AND announcement_date <= ?) "
                "   OR announcement_date = '' "
                "ORDER BY announcement_date = '', announcement_date, canonical_code",
                (start_date, end_date),
            ).fetchall()
        return [dict(row) for row in rows]

    def earnings_for_code(self, canonical_code: str) -> list[dict[str, Any]]:
        with self.read() as connection:
            rows = connection.execute(
                "SELECT * FROM earnings_announcements WHERE canonical_code = ? "
                "ORDER BY announcement_date",
                (canonical_code,),
            ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # margin / short data
    # ------------------------------------------------------------------

    _MARGIN_COLUMNS = (
        "canonical_code", "application_date", "short_total", "long_total",
        "short_negotiable", "long_negotiable", "short_standardized", "long_standardized",
        "issue_type", "ingested_at",
    )

    def upsert_margin_interest(self, rows: Iterable[Mapping[str, Any]]) -> int:
        now = utc_now_iso()
        prepared = [
            tuple(row.get(column) for column in self._MARGIN_COLUMNS[:-1]) + (now,)
            for row in rows
            if row.get("canonical_code") and row.get("application_date")
        ]
        if not prepared:
            return 0
        sql = _upsert_sql("margin_interest", self._MARGIN_COLUMNS, ("canonical_code", "application_date"))
        with self.write() as connection:
            connection.executemany(sql, prepared)
        return len(prepared)

    def margin_interest_for_code(self, canonical_code: str, *, limit: int = 60) -> list[dict[str, Any]]:
        with self.read() as connection:
            rows = connection.execute(
                "SELECT * FROM (SELECT * FROM margin_interest WHERE canonical_code = ? "
                "ORDER BY application_date DESC LIMIT ?) ORDER BY application_date",
                (canonical_code, int(limit)),
            ).fetchall()
        return [dict(row) for row in rows]

    def latest_margin_map(self) -> dict[str, dict[str, Any]]:
        with self.read() as connection:
            rows = connection.execute(
                """
                SELECT mi.* FROM margin_interest mi
                JOIN (
                    SELECT canonical_code, MAX(application_date) AS latest_date
                    FROM margin_interest GROUP BY canonical_code
                ) latest ON latest.canonical_code = mi.canonical_code
                    AND mi.application_date = latest.latest_date
                """
            ).fetchall()
        return {row["canonical_code"]: dict(row) for row in rows}

    _MARGIN_ALERT_COLUMNS = (
        "canonical_code", "published_date", "application_date",
        "short_outstanding", "long_outstanding", "short_long_ratio",
        "short_outstanding_change", "long_outstanding_change",
        "short_outstanding_listed_ratio", "long_outstanding_listed_ratio",
        "short_negotiable", "short_standardized", "long_negotiable", "long_standardized",
        "tse_regulation_class", "publish_reason", "ingested_at",
    )

    def upsert_margin_alerts(self, rows: Iterable[Mapping[str, Any]]) -> int:
        now = utc_now_iso()
        prepared = []
        for row in rows:
            if not row.get("canonical_code"):
                continue
            values = {column: row.get(column) for column in self._MARGIN_ALERT_COLUMNS}
            values["published_date"] = values.get("published_date") or ""
            values["application_date"] = values.get("application_date") or ""
            values["ingested_at"] = now
            prepared.append(tuple(values[column] for column in self._MARGIN_ALERT_COLUMNS))
        if not prepared:
            return 0
        sql = _upsert_sql(
            "margin_alerts", self._MARGIN_ALERT_COLUMNS,
            ("canonical_code", "published_date", "application_date"),
        )
        with self.write() as connection:
            connection.executemany(sql, prepared)
        return len(prepared)

    def margin_alerts_for_code(self, canonical_code: str, *, limit: int = 30) -> list[dict[str, Any]]:
        with self.read() as connection:
            rows = connection.execute(
                "SELECT * FROM (SELECT * FROM margin_alerts WHERE canonical_code = ? "
                "ORDER BY application_date DESC, published_date DESC LIMIT ?) "
                "ORDER BY application_date",
                (canonical_code, int(limit)),
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_short_ratios(self, rows: Iterable[Mapping[str, Any]]) -> int:
        now = utc_now_iso()
        prepared = [
            (
                row["sector33_code"], row["trade_date"], row.get("selling_ex_short_value"),
                row.get("short_with_restriction_value"), row.get("short_without_restriction_value"), now,
            )
            for row in rows
            if row.get("sector33_code") and row.get("trade_date")
        ]
        if not prepared:
            return 0
        with self.write() as connection:
            connection.executemany(
                "INSERT INTO short_sale_ratios (sector33_code, trade_date, selling_ex_short_value, "
                "short_with_restriction_value, short_without_restriction_value, ingested_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (sector33_code, trade_date) DO UPDATE SET "
                "selling_ex_short_value=excluded.selling_ex_short_value, "
                "short_with_restriction_value=excluded.short_with_restriction_value, "
                "short_without_restriction_value=excluded.short_without_restriction_value, "
                "ingested_at=excluded.ingested_at",
                prepared,
            )
        return len(prepared)

    def short_ratios_for_date(self, trade_date: str) -> list[dict[str, Any]]:
        with self.read() as connection:
            rows = connection.execute(
                "SELECT * FROM short_sale_ratios WHERE trade_date = ? ORDER BY sector33_code",
                (trade_date,),
            ).fetchall()
        return [dict(row) for row in rows]

    def short_ratio_series(self, sector33_code: str, *, limit: int = 120) -> list[dict[str, Any]]:
        with self.read() as connection:
            rows = connection.execute(
                "SELECT * FROM (SELECT * FROM short_sale_ratios WHERE sector33_code = ? "
                "ORDER BY trade_date DESC LIMIT ?) ORDER BY trade_date",
                (sector33_code, int(limit)),
            ).fetchall()
        return [dict(row) for row in rows]

    def latest_short_ratio_date(self) -> str | None:
        with self.read() as connection:
            row = connection.execute("SELECT MAX(trade_date) FROM short_sale_ratios").fetchone()
        return row[0] if row and row[0] else None

    _SHORT_POSITION_COLUMNS = (
        "canonical_code", "disclosed_date", "calculated_date", "holder_name",
        "investment_fund_name", "short_position_ratio", "short_position_shares",
        "short_position_units", "previous_report_date", "previous_ratio", "notes",
        "ingested_at",
    )

    def upsert_short_positions(self, rows: Iterable[Mapping[str, Any]]) -> int:
        now = utc_now_iso()
        prepared = []
        for row in rows:
            if not row.get("canonical_code") or not row.get("disclosed_date"):
                continue
            values = {column: row.get(column) for column in self._SHORT_POSITION_COLUMNS}
            values["holder_name"] = values.get("holder_name") or ""
            values["calculated_date"] = values.get("calculated_date") or ""
            values["ingested_at"] = now
            prepared.append(tuple(values[column] for column in self._SHORT_POSITION_COLUMNS))
        if not prepared:
            return 0
        sql = _upsert_sql(
            "short_positions", self._SHORT_POSITION_COLUMNS,
            ("canonical_code", "disclosed_date", "calculated_date", "holder_name"),
        )
        with self.write() as connection:
            connection.executemany(sql, prepared)
        return len(prepared)

    def short_positions_for_code(self, canonical_code: str, *, limit: int = 50) -> list[dict[str, Any]]:
        with self.read() as connection:
            rows = connection.execute(
                "SELECT * FROM short_positions WHERE canonical_code = ? "
                "ORDER BY calculated_date DESC, disclosed_date DESC LIMIT ?",
                (canonical_code, int(limit)),
            ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # radar events
    # ------------------------------------------------------------------

    _RADAR_COLUMNS = (
        "event_id", "canonical_code", "signal_type", "state", "discovered_date",
        "pivot_price", "trigger_price", "state_changed_date", "last_scanned_date",
        "alert_priority", "scores_json", "features_json", "transitions_json",
        "created_at", "updated_at",
    )

    def upsert_radar_events(self, events: Iterable[Mapping[str, Any]]) -> int:
        now = utc_now_iso()
        prepared = []
        for event in events:
            if not event.get("event_id"):
                continue
            prepared.append(
                (
                    event["event_id"], event["canonical_code"], event["signal_type"], event["state"],
                    event["discovered_date"], event.get("pivot_price"), event.get("trigger_price"),
                    event["state_changed_date"], event["last_scanned_date"], event.get("alert_priority"),
                    json.dumps(event.get("scores") or {}, ensure_ascii=False, sort_keys=True),
                    json.dumps(event.get("features") or {}, ensure_ascii=False, sort_keys=True),
                    json.dumps(event.get("transitions") or [], ensure_ascii=False),
                    event.get("created_at") or now, now,
                )
            )
        if not prepared:
            return 0
        sql = (
            f"INSERT INTO radar_events ({', '.join(self._RADAR_COLUMNS)}) "
            f"VALUES ({', '.join('?' for _ in self._RADAR_COLUMNS)}) "
            "ON CONFLICT (event_id) DO UPDATE SET state=excluded.state, "
            "pivot_price=excluded.pivot_price, trigger_price=excluded.trigger_price, "
            "state_changed_date=excluded.state_changed_date, last_scanned_date=excluded.last_scanned_date, "
            "alert_priority=excluded.alert_priority, scores_json=excluded.scores_json, "
            "features_json=excluded.features_json, transitions_json=excluded.transitions_json, "
            "updated_at=excluded.updated_at"
        )
        with self.write() as connection:
            connection.executemany(sql, prepared)
        return len(prepared)

    def open_radar_events(self, *, terminal_states: Sequence[str]) -> list[dict[str, Any]]:
        placeholders = ", ".join("?" for _ in terminal_states)
        with self.read() as connection:
            rows = connection.execute(
                f"SELECT * FROM radar_events WHERE state NOT IN ({placeholders})",
                tuple(terminal_states),
            ).fetchall()
        return [self._radar_row(row) for row in rows]

    def radar_events_scanned_on(
        self, trade_date: str, *, states: Sequence[str] | None = None,
        signal_types: Sequence[str] | None = None, min_priority: float | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        clauses = ["last_scanned_date = ?"]
        params: list[Any] = [trade_date]
        if states:
            clauses.append(f"state IN ({', '.join('?' for _ in states)})")
            params.extend(states)
        if signal_types:
            clauses.append(f"signal_type IN ({', '.join('?' for _ in signal_types)})")
            params.extend(signal_types)
        if min_priority is not None:
            clauses.append("alert_priority >= ?")
            params.append(float(min_priority))
        params.append(int(limit))
        with self.read() as connection:
            rows = connection.execute(
                f"SELECT * FROM radar_events WHERE {' AND '.join(clauses)} "
                "ORDER BY alert_priority IS NULL, alert_priority DESC, event_id LIMIT ?",
                params,
            ).fetchall()
        return [self._radar_row(row) for row in rows]

    def radar_event(self, event_id: str) -> dict[str, Any] | None:
        with self.read() as connection:
            row = connection.execute(
                "SELECT * FROM radar_events WHERE event_id = ?", (event_id,)
            ).fetchone()
        return self._radar_row(row) if row else None

    def radar_events_for_code(self, canonical_code: str, *, limit: int = 50) -> list[dict[str, Any]]:
        with self.read() as connection:
            rows = connection.execute(
                "SELECT * FROM radar_events WHERE canonical_code = ? "
                "ORDER BY discovered_date DESC LIMIT ?",
                (canonical_code, int(limit)),
            ).fetchall()
        return [self._radar_row(row) for row in rows]

    @staticmethod
    def _radar_row(row: Any) -> dict[str, Any]:
        item = dict(row)
        for key, target in (("scores_json", "scores"), ("features_json", "features"), ("transitions_json", "transitions")):
            raw = item.pop(key, None)
            try:
                item[target] = json.loads(raw) if raw else ({} if target != "transitions" else [])
            except ValueError:
                item[target] = {} if target != "transitions" else []
        return item

    # ------------------------------------------------------------------
    # screener rows
    # ------------------------------------------------------------------

    _SCREENER_COLUMNS = (
        "canonical_code", "trade_date", "market_code", "sector33_code", "close",
        "turnover_value", "avg_turnover_20d", "turnover_ratio", "return_1d", "return_5d",
        "return_20d", "return_63d", "pct_from_high_252", "ma25_gap_pct",
        "ma75_gap_pct", "ma200_gap_pct", "ma_alignment", "rs_topix_63d",
        "rs_sector_63d", "volatility_contraction", "drawdown_63d",
        "overheat_atr_multiple", "listed_days", "data_days",
        "margin_long_short_ratio", "metrics_json", "updated_at",
    )

    def replace_screener_rows(self, rows: Iterable[Mapping[str, Any]]) -> int:
        now = utc_now_iso()
        prepared = []
        for row in rows:
            if not row.get("canonical_code"):
                continue
            values = {column: row.get(column) for column in self._SCREENER_COLUMNS}
            values["metrics_json"] = json.dumps(row.get("metrics") or {}, ensure_ascii=False, sort_keys=True)
            values["updated_at"] = now
            prepared.append(tuple(values[column] for column in self._SCREENER_COLUMNS))
        if not prepared:
            # Don't wipe the last good snapshot on an empty rebuild (same
            # "empty never overwrites" contract as the earnings/master syncs).
            return 0
        with self.write() as connection:
            connection.execute("DELETE FROM screener_rows")
            connection.executemany(
                # OR IGNORE: a spurious duplicate canonical_code must not abort the
                # whole rebuild (rows are DELETE-d first, so no cross-run conflict).
                f"INSERT OR IGNORE INTO screener_rows ({', '.join(self._SCREENER_COLUMNS)}) "
                f"VALUES ({', '.join('?' for _ in self._SCREENER_COLUMNS)})",
                prepared,
            )
        return len(prepared)

    def screener_query(
        self, *, where_sql: str, params: Sequence[Any], order_sql: str, limit: int, offset: int
    ) -> tuple[list[dict[str, Any]], int]:
        """Execute an allowlisted screener filter. ``where_sql``/``order_sql``
        must be built exclusively by the screener service's filter compiler."""

        with self.read() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) FROM screener_rows WHERE {where_sql}", tuple(params)
            ).fetchone()[0]
            rows = connection.execute(
                f"SELECT * FROM screener_rows WHERE {where_sql} ORDER BY {order_sql} "
                f"LIMIT {int(limit)} OFFSET {int(offset)}",
                tuple(params),
            ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            raw = item.pop("metrics_json", None)
            try:
                item["metrics"] = json.loads(raw) if raw else {}
            except ValueError:
                item["metrics"] = {}
            results.append(item)
        return results, int(total)

    def screener_trade_date(self) -> str | None:
        with self.read() as connection:
            row = connection.execute("SELECT MAX(trade_date) FROM screener_rows").fetchone()
        return row[0] if row and row[0] else None

    # ------------------------------------------------------------------
    # strength scan (nightly intrinsic cross-section)
    # ------------------------------------------------------------------

    _STRENGTH_COLUMNS = (
        "canonical_code", "trade_date", "intrinsic_score", "confidence",
        "score_short", "score_mid", "score_long", "trend_score",
        "breakout_quality_score", "price_action_score",
        "global_rank_percentile", "sector_rank_percentile",
        "close", "change_pct", "atr_pct", "avg_turnover_20d",
        "turnover_ratio", "ath_proximity", "drawdown_63d_pct",
        "ma_alignment_pct", "rs_topix_63d", "market_code", "sector33_code",
        "details_json", "built_at",
    )

    def replace_strength_rows(
        self,
        rows: Iterable[Mapping[str, Any]],
        *,
        trade_date: str,
        regime: Mapping[str, Any],
    ) -> int:
        now = utc_now_iso()
        prepared = []
        for row in rows:
            if not row.get("canonical_code"):
                continue
            values = {column: row.get(column) for column in self._STRENGTH_COLUMNS}
            values["details_json"] = json.dumps(
                row.get("details") or {}, ensure_ascii=False, sort_keys=True
            )
            values["built_at"] = now
            prepared.append(tuple(values[column] for column in self._STRENGTH_COLUMNS))
        if not prepared:
            # Don't wipe the last good snapshot (rows + meta) on an empty rebuild.
            return 0
        with self.write() as connection:
            connection.execute("DELETE FROM strength_rows")
            connection.executemany(
                f"INSERT OR IGNORE INTO strength_rows ({', '.join(self._STRENGTH_COLUMNS)}) "
                f"VALUES ({', '.join('?' for _ in self._STRENGTH_COLUMNS)})",
                prepared,
            )
            connection.execute(
                "INSERT INTO strength_meta (id, trade_date, regime_json, universe_count, built_at) "
                "VALUES (1, ?, ?, ?, ?) ON CONFLICT (id) DO UPDATE SET trade_date=excluded.trade_date, "
                "regime_json=excluded.regime_json, universe_count=excluded.universe_count, "
                "built_at=excluded.built_at",
                (
                    trade_date,
                    json.dumps(dict(regime), ensure_ascii=False, sort_keys=True),
                    len(prepared),
                    now,
                ),
            )
        return len(prepared)

    def strength_rows_all(self) -> list[dict[str, Any]]:
        with self.read() as connection:
            rows = connection.execute("SELECT * FROM strength_rows").fetchall()
        results = []
        for row in rows:
            item = dict(row)
            raw = item.pop("details_json", None)
            try:
                item["details"] = json.loads(raw) if raw else {}
            except ValueError:
                item["details"] = {}
            results.append(item)
        return results

    def strength_meta(self) -> dict[str, Any] | None:
        with self.read() as connection:
            row = connection.execute(
                "SELECT trade_date, regime_json, universe_count, built_at FROM strength_meta WHERE id=1"
            ).fetchone()
        if row is None:
            return None
        try:
            regime = json.loads(row["regime_json"]) if row["regime_json"] else {}
        except ValueError:
            regime = {}
        return {
            "trade_date": row["trade_date"],
            "regime": regime,
            "universe_count": int(row["universe_count"] or 0),
            "built_at": row["built_at"],
        }

    # ------------------------------------------------------------------
    # sync state
    # ------------------------------------------------------------------

    def record_sync_attempt(self, dataset: str) -> None:
        now = utc_now_iso()
        with self.write() as connection:
            connection.execute(
                "INSERT INTO sync_state (dataset, last_attempt_at) VALUES (?, ?) "
                "ON CONFLICT (dataset) DO UPDATE SET last_attempt_at = excluded.last_attempt_at",
                (dataset, now),
            )

    def record_sync_success(
        self, dataset: str, *, checkpoint: Mapping[str, Any] | None = None,
        rows_total: int | None = None, data_through: str | None = None,
    ) -> None:
        now = utc_now_iso()
        with self.write() as connection:
            existing = connection.execute(
                "SELECT checkpoint_json FROM sync_state WHERE dataset = ?", (dataset,)
            ).fetchone()
            merged: dict[str, Any] = {}
            if existing and existing[0]:
                try:
                    merged = json.loads(existing[0])
                except ValueError:
                    merged = {}
            if checkpoint:
                merged.update(checkpoint)
            connection.execute(
                "INSERT INTO sync_state (dataset, last_success_at, last_attempt_at, checkpoint_json, "
                "rows_total, data_through, last_error_code) VALUES (?, ?, ?, ?, ?, ?, NULL) "
                "ON CONFLICT (dataset) DO UPDATE SET last_success_at = excluded.last_success_at, "
                "checkpoint_json = excluded.checkpoint_json, "
                "rows_total = COALESCE(excluded.rows_total, sync_state.rows_total), "
                "data_through = COALESCE(excluded.data_through, sync_state.data_through), "
                "last_error_code = NULL",
                (
                    dataset, now, now, json.dumps(merged, ensure_ascii=False, sort_keys=True),
                    rows_total, data_through,
                ),
            )

    def record_sync_error(self, dataset: str, error_code: str) -> None:
        now = utc_now_iso()
        with self.write() as connection:
            connection.execute(
                "INSERT INTO sync_state (dataset, last_attempt_at, last_error_code, last_error_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT (dataset) DO UPDATE SET last_attempt_at = excluded.last_attempt_at, "
                "last_error_code = excluded.last_error_code, last_error_at = excluded.last_error_at",
                (dataset, now, error_code[:120], now),
            )

    def sync_state(self, dataset: str) -> dict[str, Any] | None:
        with self.read() as connection:
            row = connection.execute(
                "SELECT * FROM sync_state WHERE dataset = ?", (dataset,)
            ).fetchone()
        return self._sync_row(row) if row else None

    def all_sync_states(self) -> list[dict[str, Any]]:
        with self.read() as connection:
            rows = connection.execute("SELECT * FROM sync_state ORDER BY dataset").fetchall()
        return [self._sync_row(row) for row in rows]

    @staticmethod
    def _sync_row(row: Any) -> dict[str, Any]:
        item = dict(row)
        raw = item.pop("checkpoint_json", None)
        try:
            item["checkpoint"] = json.loads(raw) if raw else {}
        except ValueError:
            item["checkpoint"] = {}
        return item


__all__ = ["CoreRepository"]
