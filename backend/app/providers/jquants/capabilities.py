"""Data capability declaration for the current J-Quants subscription.

The product renders capability states honestly: a dataset the plan does not
include is ``unavailable`` (never an empty array pretending to be "no data"),
and a dataset we have not wired yet is ``planned``.
"""

from __future__ import annotations

from dataclasses import dataclass


SUBSCRIPTION_PLAN = "standard"


@dataclass(frozen=True)
class DataCapability:
    key: str
    endpoint: str
    status: str  # enabled | planned | unavailable
    cadence: str  # daily | weekly | irregular | static
    history_years: int | None
    note_ja: str = ""


CAPABILITIES: tuple[DataCapability, ...] = (
    DataCapability("listed_master", "/equities/master", "enabled", "daily", 10),
    DataCapability("daily_prices", "/equities/bars/daily", "enabled", "daily", 10),
    DataCapability("financial_summary", "/fins/summary", "enabled", "irregular", 10),
    DataCapability(
        "earnings_calendar",
        "/equities/earnings-calendar",
        "enabled",
        "daily",
        None,
        "直近分のみ・3月期/9月期決算会社のみ・REIT除外（J-Quants仕様）",
    ),
    DataCapability("trading_calendar", "/markets/calendar", "enabled", "static", 10),
    DataCapability("index_prices", "/indices/bars/daily", "enabled", "daily", 10),
    DataCapability("topix_prices", "/indices/bars/daily/topix", "enabled", "daily", 10),
    DataCapability("margin_interest", "/markets/margin-interest", "enabled", "weekly", 10),
    DataCapability("margin_alerts", "/markets/margin-alert", "enabled", "daily", 10),
    DataCapability("short_sale_ratio", "/markets/short-ratio", "enabled", "daily", 10),
    DataCapability("reported_short_positions", "/markets/short-sale-report", "enabled", "daily", 10),
    # Standard プランに含まれるが v1 では未接続。
    DataCapability("investor_types", "/equities/investor-types", "planned", "weekly", 10, "週次・投資部門別売買状況"),
    DataCapability("major_shareholders", "/edinet/major-shareholders", "planned", "irregular", 10),
    DataCapability("cross_shareholdings", "/edinet/cross-shareholdings", "planned", "irregular", 10),
    DataCapability("large_volume_reports", "/edinet/large-volume-shareholders", "planned", "irregular", 10),
    # Standard プランに含まれない。
    DataCapability("financial_details", "/fins/details", "unavailable", "irregular", None, "Premium 限定"),
    DataCapability("dividend_details", "/fins/dividend", "unavailable", "irregular", None, "Premium 限定"),
    DataCapability("trading_breakdown", "/markets/breakdown", "unavailable", "daily", None, "Premium 限定"),
    DataCapability("morning_session_prices", "/equities/bars/daily/am", "unavailable", "daily", None, "Premium 限定"),
    # アドオン契約済み（2026-08: OHLC-Min + Tick 加購）。銘柄別オンデマンド取得。
    DataCapability("intraday_prices", "/equities/bars/minute", "enabled", "intraday", None, "分足アドオン契約済み・銘柄別オンデマンド"),
    DataCapability("tick_trades", "bulk:equities/trades", "enabled", "daily", 2, "Tick アドオン契約済み。CSV 一括配信のみ（REST 不可）・過去2年・東証銘柄限定"),
)


def capability_map() -> dict[str, DataCapability]:
    return {capability.key: capability for capability in CAPABILITIES}


def enabled_keys() -> tuple[str, ...]:
    return tuple(c.key for c in CAPABILITIES if c.status == "enabled")


__all__ = ["CAPABILITIES", "DataCapability", "SUBSCRIPTION_PLAN", "capability_map", "enabled_keys"]
