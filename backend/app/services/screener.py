"""Screener: nightly cross-section build + allowlisted SQL filtering.

The build side runs inside the post-close worker batch, reusing the exact
feature dicts the radar computed — one nightly pass, two products. The
query side compiles a validated filter model into SQL against
``screener_rows``; only columns in the allowlist can ever reach the query,
and sorting is restricted the same way. Missing values are excluded by the
specific filter that references them (SQL NULL semantics), never treated
as zero.
"""

from __future__ import annotations

from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field

from app.repositories.core import CoreRepository

SCREENER_VERSION = "jp-screener-v1"

_SORTABLE_COLUMNS = {
    "close", "turnover_value", "avg_turnover_20d", "turnover_ratio",
    "return_1d", "return_5d", "return_20d", "return_63d", "pct_from_high_252",
    "rs_topix_63d", "rs_sector_20d", "rs_sector_63d",
    # 規制は序数の severity だけ並べ替え可（level はテキストなので辞書順に
    # 並べても意味がない）。
    "regulation_severity", "volatility_contraction",
    "drawdown_63d", "overheat_atr_multiple", "margin_long_short_ratio",
    "canonical_code",
}


class ScreenerFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    markets: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)
    watchlist_codes: list[str] = Field(default_factory=list)
    min_price: float | None = Field(default=None, ge=0)
    max_price: float | None = Field(default=None, ge=0)
    min_avg_turnover: float | None = Field(default=None, ge=0)
    min_turnover_ratio: float | None = Field(default=None, ge=0)
    max_pct_from_high_252: float | None = Field(default=None, le=0)
    ma_alignment: bool | None = None
    above_ma25: bool | None = None
    above_ma75: bool | None = None
    above_ma200: bool | None = None
    min_return_20d: float | None = None
    min_rs_topix_63d: float | None = None
    min_rs_sector_20d: float | None = None
    min_rs_sector_63d: float | None = None
    min_volatility_contraction: float | None = None
    max_drawdown_63d: float | None = None
    min_listed_days: int | None = Field(default=None, ge=0)
    max_margin_ratio: float | None = Field(default=None, ge=0)
    sort_by: Literal[
        "turnover_ratio", "return_20d", "return_63d", "rs_topix_63d",
        "rs_sector_20d", "rs_sector_63d", "pct_from_high_252", "avg_turnover_20d",
        "volatility_contraction", "close", "canonical_code",
    ] = "rs_topix_63d"
    sort_dir: Literal["asc", "desc"] = "desc"
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


def compile_filters(filters: ScreenerFilters) -> tuple[str, list[Any], str]:
    clauses: list[str] = ["1=1"]
    params: list[Any] = []
    if filters.markets:
        clauses.append(f"market_code IN ({', '.join('?' for _ in filters.markets)})")
        params.extend(filters.markets)
    if filters.sectors:
        clauses.append(f"sector33_code IN ({', '.join('?' for _ in filters.sectors)})")
        params.extend(filters.sectors)
    if filters.watchlist_codes:
        clauses.append(
            f"canonical_code IN ({', '.join('?' for _ in filters.watchlist_codes)})"
        )
        params.extend(filters.watchlist_codes)
    numeric_rules: tuple[tuple[str, str, float | int | None], ...] = (
        ("close", ">=", filters.min_price),
        ("close", "<=", filters.max_price),
        ("avg_turnover_20d", ">=", filters.min_avg_turnover),
        ("turnover_ratio", ">=", filters.min_turnover_ratio),
        ("pct_from_high_252", ">=", filters.max_pct_from_high_252),
        ("return_20d", ">=", filters.min_return_20d),
        ("rs_topix_63d", ">=", filters.min_rs_topix_63d),
        ("rs_sector_20d", ">=", filters.min_rs_sector_20d),
        ("rs_sector_63d", ">=", filters.min_rs_sector_63d),
        ("volatility_contraction", ">=", filters.min_volatility_contraction),
        ("drawdown_63d", ">=", filters.max_drawdown_63d),
        ("data_days", ">=", filters.min_listed_days),
        ("margin_long_short_ratio", "<=", filters.max_margin_ratio),
    )
    for column, op, value in numeric_rules:
        if value is not None:
            clauses.append(f"{column} {op} ?")
            params.append(value)
    for column, flag in (
        ("ma25_gap_pct", filters.above_ma25),
        ("ma75_gap_pct", filters.above_ma75),
        ("ma200_gap_pct", filters.above_ma200),
    ):
        if flag is True:
            clauses.append(f"{column} > 0")
        elif flag is False:
            clauses.append(f"{column} <= 0")
    if filters.ma_alignment is True:
        clauses.append("ma_alignment = 1")
    elif filters.ma_alignment is False:
        clauses.append("ma_alignment = 0")

    sort_column = filters.sort_by if filters.sort_by in _SORTABLE_COLUMNS else "rs_topix_63d"
    direction = "ASC" if filters.sort_dir == "asc" else "DESC"
    # NULL は常に末尾へ — 欠損を 0 とみなして順位に混ぜない。
    order_sql = f"{sort_column} IS NULL, {sort_column} {direction}, canonical_code ASC"
    return " AND ".join(clauses), params, order_sql


def run_screener(
    repository: CoreRepository, filters: ScreenerFilters
) -> dict[str, Any]:
    where_sql, params, order_sql = compile_filters(filters)
    rows, total = repository.screener_query(
        where_sql=where_sql, params=params, order_sql=order_sql,
        limit=filters.limit, offset=filters.offset,
    )
    return {
        "version": SCREENER_VERSION,
        "trade_date": repository.screener_trade_date(),
        "total": total,
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# nightly build
# ---------------------------------------------------------------------------


def build_screener_rows(
    *,
    trade_date: str,
    features_by_code: Mapping[str, Mapping[str, Any]],
    securities: Mapping[str, Mapping[str, Any]],
    sector_median_returns: Mapping[str, float],
    sector_median_returns_63d: Mapping[str, float] | None = None,
    topix_return_63d: float | None,
    margin_map: Mapping[str, Mapping[str, Any]],
    radar_state_by_code: Mapping[str, str],
    regulation_map: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for code, features in features_by_code.items():
        security = securities.get(code)
        if security is None:
            continue
        sector = security.get("sector33_code")
        rs_topix = None
        if features.get("return_63d") is not None and topix_return_63d is not None:
            rs_topix = features["return_63d"] - topix_return_63d
        # 20 日リターン同士の差は 20 日指標。63 日の名前で保存していたので
        # 画面・API・DB が揃って「63日」と言いながら中身は 20 日だった。
        rs_sector_20d = None
        sector_median = sector_median_returns.get(sector or "")
        if features.get("return_20d") is not None and sector_median is not None:
            rs_sector_20d = features["return_20d"] - sector_median
        rs_sector_63d = None
        sector_median_63 = (sector_median_returns_63d or {}).get(sector or "")
        if features.get("return_63d") is not None and sector_median_63 is not None:
            rs_sector_63d = features["return_63d"] - sector_median_63
        regulation = (regulation_map or {}).get(code)
        margin_row = margin_map.get(code)
        margin_ratio = None
        if margin_row:
            long_total = margin_row.get("long_total")
            short_total = margin_row.get("short_total")
            if long_total is not None and short_total:
                margin_ratio = long_total / short_total
        rows.append(
            {
                "canonical_code": code,
                "trade_date": trade_date,
                "market_code": security.get("market_code"),
                "sector33_code": sector,
                "close": features.get("close"),
                "turnover_value": features.get("turnover_today"),
                "avg_turnover_20d": features.get("avg_turnover_20d"),
                "turnover_ratio": features.get("turnover_ratio"),
                "return_1d": features.get("return_1d"),
                "return_5d": features.get("return_5d"),
                "return_20d": features.get("return_20d"),
                "return_63d": features.get("return_63d"),
                "pct_from_high_252": features.get("pct_from_high_252"),
                "ma25_gap_pct": features.get("ma25_gap_pct"),
                "ma75_gap_pct": features.get("ma75_gap_pct"),
                "ma200_gap_pct": features.get("ma200_gap_pct"),
                "ma_alignment": (
                    None if features.get("ma_alignment") is None
                    else (1 if features.get("ma_alignment") else 0)
                ),
                "rs_topix_63d": rs_topix,
                "rs_sector_20d": rs_sector_20d,
                "rs_sector_63d": rs_sector_63d,
                "regulation_level": getattr(regulation, "level", None),
                "regulation_severity": getattr(regulation, "severity", None),
                "volatility_contraction": features.get("volatility_contraction"),
                "drawdown_63d": features.get("drawdown_63d"),
                "overheat_atr_multiple": features.get("overheat_atr_multiple"),
                "listed_days": features.get("data_days"),
                "data_days": features.get("data_days"),
                "margin_long_short_ratio": margin_ratio,
                "metrics": {
                    "name_ja": security.get("name_ja"),
                    "name_en": security.get("name_en"),
                    "sector33_name": security.get("sector33_name"),
                    "market_name": security.get("market_name"),
                    "radar_state": radar_state_by_code.get(code),
                    "upper_limit_today": features.get("upper_limit_today"),
                },
            }
        )
    return rows


__all__ = [
    "SCREENER_VERSION",
    "ScreenerFilters",
    "build_screener_rows",
    "compile_filters",
    "run_screener",
]
