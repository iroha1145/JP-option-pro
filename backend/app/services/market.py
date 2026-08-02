"""日本市場オーバービュー: 指数・騰落・業種・売買代金・空売り比率。

すべて日足粒度。レスポンスには必ず data_through（データの基準日）を含め、
「本日」を装わない。
"""

from __future__ import annotations

from typing import Any

from app.domain.constants import HOME_INDEX_CODES, INDEX_CODES, SECTOR33, TOPIX_INDEX_CODE
from app.repositories.core import CoreRepository

MARKET_OVERVIEW_VERSION = "jp-market-v1"


def _index_summary(repository: CoreRepository, index_code: str) -> dict[str, Any] | None:
    series = repository.index_series(index_code, limit=260)
    if not series:
        return None
    last = series[-1]
    prev_close = series[-2]["close"] if len(series) >= 2 else None
    close = last.get("close")
    change_pct = None
    if close is not None and prev_close:
        change_pct = close / prev_close - 1.0
    closes = [row["close"] for row in series if row.get("close") is not None]
    return {
        "index_code": index_code,
        "name": INDEX_CODES.get(index_code, index_code),
        "trade_date": last.get("trade_date"),
        "close": close,
        "change_pct": change_pct,
        "return_20d": (closes[-1] / closes[-21] - 1.0) if len(closes) >= 21 else None,
        "return_63d": (closes[-1] / closes[-64] - 1.0) if len(closes) >= 64 else None,
        "sparkline": closes[-40:],
    }


def market_overview(repository: CoreRepository) -> dict[str, Any]:
    trade_date = repository.screener_trade_date()
    bars_date = repository.latest_bar_date()

    indices = [
        summary
        for code in HOME_INDEX_CODES
        if (summary := _index_summary(repository, code)) is not None
    ]

    breadth: dict[str, Any] = {
        "advancers": None, "decliners": None, "unchanged": None,
        "new_highs_252": None, "new_lows_pct": None, "total_turnover_value": None,
    }
    sectors: list[dict[str, Any]] = []
    if trade_date:
        rows, _total = repository.screener_query(
            where_sql="1=1", params=[], order_sql="canonical_code ASC", limit=10000, offset=0,
        )
        advancers = decliners = unchanged = new_highs = 0
        turnover_sum = 0.0
        by_sector: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            r1 = row.get("return_1d")
            if r1 is not None:
                if r1 > 0.0005:
                    advancers += 1
                elif r1 < -0.0005:
                    decliners += 1
                else:
                    unchanged += 1
            near_high = row.get("pct_from_high_252")
            if near_high is not None and near_high >= -0.001:
                new_highs += 1
            if row.get("turnover_value"):
                turnover_sum += float(row["turnover_value"])
            sector = row.get("sector33_code")
            if sector:
                by_sector.setdefault(sector, []).append(row)
        breadth = {
            "advancers": advancers,
            "decliners": decliners,
            "unchanged": unchanged,
            "new_highs_252": new_highs,
            "total_turnover_value": turnover_sum or None,
        }
        for sector_code, members in sorted(by_sector.items()):
            r1_values = sorted(
                row["return_1d"] for row in members if row.get("return_1d") is not None
            )
            r20_values = sorted(
                row["return_20d"] for row in members if row.get("return_20d") is not None
            )
            leaders = sorted(
                (row for row in members if row.get("return_1d") is not None),
                key=lambda row: row["return_1d"],
                reverse=True,
            )[:3]
            sectors.append(
                {
                    "sector33_code": sector_code,
                    "sector33_name": SECTOR33.get(sector_code, sector_code),
                    "member_count": len(members),
                    "median_return_1d": r1_values[len(r1_values) // 2] if r1_values else None,
                    "median_return_20d": r20_values[len(r20_values) // 2] if r20_values else None,
                    "leaders": [
                        {
                            "canonical_code": row["canonical_code"],
                            "name_ja": (row.get("metrics") or {}).get("name_ja"),
                            "return_1d": row.get("return_1d"),
                        }
                        for row in leaders
                    ],
                }
            )
        sectors.sort(key=lambda item: (item["median_return_1d"] is None, -(item["median_return_1d"] or 0.0)))

    short_ratio = None
    short_date = repository.latest_short_ratio_date()
    if short_date:
        ratios = repository.short_ratios_for_date(short_date)
        total_regular = sum(row.get("selling_ex_short_value") or 0.0 for row in ratios)
        total_short = sum(
            (row.get("short_with_restriction_value") or 0.0)
            + (row.get("short_without_restriction_value") or 0.0)
            for row in ratios
        )
        denominator = total_regular + total_short
        if denominator > 0:
            short_ratio = {
                "trade_date": short_date,
                "market_short_ratio": total_short / denominator,
            }

    return {
        "version": MARKET_OVERVIEW_VERSION,
        "data_through": trade_date or bars_date,
        "topix_code": TOPIX_INDEX_CODE,
        "indices": indices,
        "breadth": breadth,
        "sectors": sectors,
        "short_selling": short_ratio,
    }


__all__ = ["MARKET_OVERVIEW_VERSION", "market_overview"]
