"""日本市場オーバービュー: 指数・騰落・業種・売買代金・空売り比率。

すべて日足粒度。レスポンスには必ず data_through（データの基準日）を含め、
「本日」を装わない。
"""

from __future__ import annotations

from typing import Any

from app.domain.constants import HOME_INDEX_CODES, INDEX_CODES, SECTOR33, TOPIX_INDEX_CODE
from app.domain.symbols import display_code
from app.repositories.core import CoreRepository


def _median_sorted(sorted_values: list[float]) -> float | None:
    """True median of an already-sorted list (averages the two central values
    for even lengths instead of taking the upper-middle element)."""

    if not sorted_values:
        return None
    mid = len(sorted_values) // 2
    if len(sorted_values) % 2:
        return sorted_values[mid]
    return (sorted_values[mid - 1] + sorted_values[mid]) / 2.0

MARKET_OVERVIEW_VERSION = "jp-market-v1"
SECTOR_MEMBERS_VERSION = "jp-sector-members-v1"

# 「人気（最も注目されている）」の並び順は許可制。ユーザー文字列は SQL に触れない。
SECTOR_MEMBER_SORTS: dict[str, str] = {
    "turnover": "turnover_value DESC",       # 売買代金（絶対額）
    "heat": "turnover_ratio DESC",           # 出来高倍率（20日平均比＝注目度の急変）
    "change": "return_1d DESC",              # 当日騰落率
}
SECTOR_MEMBERS_DEFAULT_LIMIT = 12


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
            # 業種内の値上がり銘柄比率: 中央値だけでは「全面高」と「数銘柄が
            # 牽引しただけ」が同じ顔になる。ヒートタイル下端の細バーに使う。
            advancers_share = (
                sum(1 for value in r1_values if value > 0.0005) / len(r1_values)
                if r1_values
                else None
            )
            sectors.append(
                {
                    "sector33_code": sector_code,
                    "sector33_name": SECTOR33.get(sector_code, sector_code),
                    "member_count": len(members),
                    "median_return_1d": _median_sorted(r1_values),
                    "median_return_20d": _median_sorted(r20_values),
                    "advancers_share": advancers_share,
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


def sector_members(
    repository: CoreRepository,
    *,
    sector33_code: str,
    sort: str = "turnover",
    limit: int = SECTOR_MEMBERS_DEFAULT_LIMIT,
) -> dict[str, Any] | None:
    """業種の「人気銘柄」断面。未知の業種コードは None（API が 404 にする）。

    オーバービューに 33 業種 × N 銘柄を積むとペイロードが数倍になるため、
    選択された業種だけをオンデマンドで返す（米版 IV ランキングと同じ形）。
    """

    if sector33_code not in SECTOR33:
        return None
    order_sql = SECTOR_MEMBER_SORTS.get(sort) or SECTOR_MEMBER_SORTS["turnover"]
    trade_date = repository.screener_trade_date()
    if trade_date is None:
        return {
            "version": SECTOR_MEMBERS_VERSION,
            "sector33_code": sector33_code,
            "sector33_name": SECTOR33[sector33_code],
            "trade_date": None,
            "sort": sort,
            "member_count": 0,
            "sector_turnover_value": None,
            "rows": [],
        }
    # where_sql は固定文字列 + バインド変数のみ（ユーザー入力は結合しない）。
    rows, total = repository.screener_query(
        where_sql="sector33_code = ?",
        params=[sector33_code],
        order_sql=f"{order_sql}, canonical_code ASC",
        limit=max(1, min(50, int(limit))),
        offset=0,
    )
    sector_turnover = _sector_turnover_total(repository, sector33_code)
    items = []
    for row in rows:
        metrics = row.get("metrics") or {}
        turnover = row.get("turnover_value")
        items.append(
            {
                "canonical_code": row["canonical_code"],
                "display_code": display_code(row["canonical_code"]),
                "name_ja": metrics.get("name_ja"),
                "market_name": metrics.get("market_name"),
                "radar_state": metrics.get("radar_state"),
                "close": row.get("close"),
                "return_1d": row.get("return_1d"),
                "return_20d": row.get("return_20d"),
                "turnover_value": turnover,
                "turnover_ratio": row.get("turnover_ratio"),
                "avg_turnover_20d": row.get("avg_turnover_20d"),
                "pct_from_high_252": row.get("pct_from_high_252"),
                "rs_sector_63d": row.get("rs_sector_63d"),
                # 業種売買代金に占めるシェア（「その業種で今日どれだけ注目されたか」）
                "turnover_share": (
                    (turnover / sector_turnover) if turnover and sector_turnover else None
                ),
            }
        )
    return {
        "version": SECTOR_MEMBERS_VERSION,
        "sector33_code": sector33_code,
        "sector33_name": SECTOR33[sector33_code],
        "trade_date": trade_date,
        "sort": sort,
        "member_count": total,
        "sector_turnover_value": sector_turnover,
        "rows": items,
    }


def _sector_turnover_total(repository: CoreRepository, sector33_code: str) -> float | None:
    rows, _total = repository.screener_query(
        where_sql="sector33_code = ?",
        params=[sector33_code],
        order_sql="canonical_code ASC",
        limit=10000,
        offset=0,
    )
    total = sum(float(row["turnover_value"]) for row in rows if row.get("turnover_value"))
    return total or None


__all__ = [
    "MARKET_OVERVIEW_VERSION",
    "SECTOR_MEMBERS_VERSION",
    "SECTOR_MEMBER_SORTS",
    "market_overview",
    "sector_members",
]
