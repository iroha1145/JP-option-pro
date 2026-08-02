"""個別銘柄リサーチ: 基本情報・日足・財務・信用・空売り・レーダー履歴。

会社予想は「会社予想」として返す。アナリストコンセンサスのデータ源は
存在しないため、市場予想と呼ばれるフィールドはこのサービスに無い。
"""

from __future__ import annotations

from typing import Any

from app.domain.symbols import display_code, normalize_input_code
from app.repositories.core import CoreRepository
from app.services.radar.base_detector import detect_base
from app.services.radar.features import clean_series, series_excluding_last
from app.services.radar.price_action import compute_price_action
from app.services.radar.technicals import compute_technicals
from app.services.radar.vol_price_match import compute_vol_price_match

STOCK_RESEARCH_VERSION = "jp-stock-v1"

_CHART_RANGES = {"3m": 66, "6m": 132, "1y": 250, "3y": 750, "5y": 1250, "10y": 2500}


def resolve_code(repository: CoreRepository, raw: str) -> dict[str, Any] | None:
    canonical = normalize_input_code(raw)
    if canonical is None:
        return None
    security = repository.get_security(canonical)
    if security is not None:
        return security
    # 4桁入力で末尾0以外の銘柄（例: 285A）を display_code で解決する。
    matches = repository.search_securities(raw, limit=1)
    return matches[0] if matches else None


def stock_chart(repository: CoreRepository, canonical_code: str, *, range_key: str = "1y") -> dict[str, Any]:
    limit = _CHART_RANGES.get(range_key, 250)
    bars = repository.bars_for_code(canonical_code, limit=limit)
    return {
        "canonical_code": canonical_code,
        "display_code": display_code(canonical_code),
        "range": range_key,
        "data_through": bars[-1]["trade_date"] if bars else None,
        "bars": [
            {
                "trade_date": bar["trade_date"],
                "open": bar.get("open"),
                "high": bar.get("high"),
                "low": bar.get("low"),
                "close": bar.get("close"),
                "adj_open": bar.get("adj_open"),
                "adj_high": bar.get("adj_high"),
                "adj_low": bar.get("adj_low"),
                "adj_close": bar.get("adj_close"),
                "volume": bar.get("volume"),
                "turnover_value": bar.get("turnover_value"),
                "adjustment_factor": bar.get("adjustment_factor"),
            }
            for bar in bars
        ],
    }


def _financial_view(row: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "disclosed_date", "disclosed_time", "disclosure_number", "type_of_document",
        "period_type", "period_start", "period_end", "fiscal_year_start", "fiscal_year_end",
        "sales", "operating_profit", "ordinary_profit", "net_profit", "eps",
        "total_assets", "equity", "equity_ratio", "bps",
        "forecast_sales", "forecast_operating_profit", "forecast_ordinary_profit",
        "forecast_net_profit", "forecast_eps",
        "next_forecast_sales", "next_forecast_operating_profit",
        "next_forecast_ordinary_profit", "next_forecast_net_profit", "next_forecast_eps",
        "dividend_annual", "forecast_dividend_annual", "payout_ratio_annual",
        "nc_sales", "nc_operating_profit", "nc_ordinary_profit", "nc_net_profit", "nc_eps",
        "retrospective_restatement", "change_accounting_estimate",
    )
    view = {key: row.get(key) for key in keys}
    view["is_consolidated"] = row.get("sales") is not None or row.get("operating_profit") is not None
    view["forecast_label"] = "会社予想"
    return view


def derive_quarter_values(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """累計値から単四半期値を導出（同一会計年度内の直前累計との差分）。

    通期(FY)行は Q4 単期 = FY累計 − 3Q累計。導出不能な期は None のまま。
    """

    by_fy: dict[str, dict[str, dict[str, Any]]] = {}
    for row in summaries:
        fy = row.get("fiscal_year_end") or ""
        period = (row.get("period_type") or "").upper()
        if fy and period:
            # 同一期に複数開示（訂正）がある場合は開示日の新しい方を採用。
            existing = by_fy.setdefault(fy, {}).get(period)
            if existing is None or (row.get("disclosed_date") or "") >= (existing.get("disclosed_date") or ""):
                by_fy[fy][period] = row
    order = ["1Q", "2Q", "3Q", "FY"]
    results: list[dict[str, Any]] = []
    for fy, periods in sorted(by_fy.items()):
        previous_cumulative: dict[str, float | None] = {}
        for period in order:
            row = periods.get(period)
            if row is None:
                previous_cumulative = {}
                continue
            single: dict[str, Any] = {
                "fiscal_year_end": fy,
                "period_type": period,
                "disclosed_date": row.get("disclosed_date"),
            }
            for field in ("sales", "operating_profit", "ordinary_profit", "net_profit"):
                cumulative = row.get(field)
                if cumulative is None:
                    single[field] = None
                elif period == "1Q" or not previous_cumulative:
                    single[field] = cumulative if period == "1Q" else None
                else:
                    prior = previous_cumulative.get(field)
                    single[field] = cumulative - prior if prior is not None else None
            previous_cumulative = {
                field: row.get(field)
                for field in ("sales", "operating_profit", "ordinary_profit", "net_profit")
            }
            results.append(single)
    return results


def technical_structure(bars: list[dict[str, Any]]) -> dict[str, Any] | None:
    """K線構造分析（米国版アルゴリズム移植: ベース/価格行動/量価/指標）。"""

    series = clean_series(bars)
    if series is None:
        return None
    prior = series_excluding_last(series)
    base = detect_base(prior) if prior else None
    price_action = compute_price_action(series)
    vol_price = compute_vol_price_match(series)
    technicals = compute_technicals(series)
    overlays: dict[str, Any] = {
        "swing_highs": price_action.get("swing_highs") or [],
        "swing_lows": price_action.get("swing_lows") or [],
    }
    if base:
        overlays["resistance_high"] = base.get("resistance_high")
        overlays["resistance_low"] = base.get("resistance_low")
        overlays["support_low"] = base.get("support_low")
        overlays["invalidation_price"] = base.get("invalidation_price")
        overlays["base_start"] = base.get("base_start")
        overlays["base_end"] = base.get("base_end")
    return {
        "base": base,
        "price_action": price_action,
        "vol_price": vol_price,
        "technicals": technicals,
        "chart_overlays": overlays,
    }


def stock_overview(repository: CoreRepository, canonical_code: str) -> dict[str, Any] | None:
    security = repository.get_security(canonical_code)
    if security is None:
        return None
    bars = repository.bars_for_code(canonical_code, limit=300)
    last_bar = bars[-1] if bars else None
    prev_bar = bars[-2] if len(bars) >= 2 else None
    change_pct = None
    if last_bar and prev_bar and last_bar.get("adj_close") and prev_bar.get("adj_close"):
        change_pct = last_bar["adj_close"] / prev_bar["adj_close"] - 1.0

    summaries = repository.summaries_for_code(canonical_code, limit=24)
    quarters = derive_quarter_values(list(reversed(summaries)))

    return {
        "version": STOCK_RESEARCH_VERSION,
        "security": {
            "canonical_code": canonical_code,
            "display_code": display_code(canonical_code),
            "name_ja": security.get("name_ja"),
            "name_en": security.get("name_en"),
            "market_code": security.get("market_code"),
            "market_name": security.get("market_name"),
            "sector17_name": security.get("sector17_name"),
            "sector33_code": security.get("sector33_code"),
            "sector33_name": security.get("sector33_name"),
            "scale_category": security.get("scale_category"),
            "margin_name": security.get("margin_name"),
            "active": security.get("active"),
            "delisted_date": security.get("delisted_date"),
        },
        "quote": {
            "trade_date": last_bar.get("trade_date") if last_bar else None,
            "close": last_bar.get("close") if last_bar else None,
            "adj_close": last_bar.get("adj_close") if last_bar else None,
            "change_pct": change_pct,
            "turnover_value": last_bar.get("turnover_value") if last_bar else None,
            "volume": last_bar.get("volume") if last_bar else None,
        },
        "financials": {
            "summaries": [_financial_view(row) for row in summaries],
            "single_quarters": quarters,
        },
        "earnings": repository.earnings_for_code(canonical_code),
        "margin_interest": repository.margin_interest_for_code(canonical_code, limit=26),
        "margin_alerts": repository.margin_alerts_for_code(canonical_code, limit=20),
        "short_positions": repository.short_positions_for_code(canonical_code, limit=30),
        "radar_events": repository.radar_events_for_code(canonical_code, limit=20),
        "technical": technical_structure(bars),
    }


__all__ = [
    "STOCK_RESEARCH_VERSION",
    "derive_quarter_values",
    "resolve_code",
    "stock_chart",
    "stock_overview",
]
