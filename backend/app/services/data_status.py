"""データ状態ページ: 各データセットの鮮度・チェックポイント・能力宣言。

接続済みデータの実際の取得日時と保存日付を返す。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.domain.constants import TOPIX_INDEX_CODE
from app.domain.timeutil import add_days
from app.providers.jquants.capabilities import CAPABILITIES, SUBSCRIPTION_PLAN
from app.repositories.core import CoreRepository

DATA_STATUS_VERSION = "jp-data-status-v1"

# データセット毎の「この時間を超えて成功が無ければ stale」しきい値（時間）。
_STALE_HOURS = {
    "trading_calendar": 7 * 24,
    "security_master": 36,
    "daily_prices": 30,
    "index_prices": 30,
    "topix_prices": 30,
    "financial_summary": 30,
    "earnings_calendar": 36,
    "margin_interest": 40,
    "margin_alerts": 40,
    "short_sale_ratio": 40,
    "reported_short_positions": 4 * 24,
}


def _hours_since(iso_timestamp: str | None) -> float | None:
    if not iso_timestamp:
        return None
    try:
        moment = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    delta = datetime.now(timezone.utc) - moment
    return delta.total_seconds() / 3600.0


def data_status(repository: CoreRepository, *, jquants_configured: bool) -> dict[str, Any]:
    states = {state["dataset"]: state for state in repository.all_sync_states()}
    market_date = repository.latest_bar_date()
    intraday = intraday_addon_status(market_date)
    topix_actual = repository.index_bar_summary(TOPIX_INDEX_CODE)
    margin_actual = repository.margin_interest_summary()
    expected_margin_date = (
        repository.latest_trading_day(add_days(market_date, -1))
        if market_date and market_date >= "2026-09-28" else None
    )
    datasets = []
    for capability in CAPABILITIES:
        state = states.get(_dataset_key(capability.key))
        if capability.key == "topix_prices":
            # TOPIX is included in the daily shared index task. Older imports
            # can still have a dedicated state, used only when no shared one exists.
            state = states.get("index_prices") or state
        entry: dict[str, Any] = {
            "key": capability.key,
            "endpoint": capability.endpoint,
            "status": capability.status,
            "cadence": capability.cadence,
            "history_years": capability.history_years,
            "note_ja": capability.note_ja or None,
            "last_success_at": None,
            "last_error_code": None,
            "data_through": None,
            "rows_total": None,
            "freshness": None,
            "backfill_pending": None,
        }
        addon_key = {"intraday_prices": "minute", "tick_trades": "tick"}.get(capability.key)
        if addon_key:
            addon = intraday[addon_key]
            entry.update({key: addon.get(key) for key in (
                "last_success_at", "last_error_code", "data_through", "rows_total", "freshness",
            )})
        elif capability.status == "enabled" and state is not None:
            age_hours = _hours_since(state.get("last_success_at"))
            threshold = _STALE_HOURS.get(_dataset_key(capability.key))
            freshness = "unknown"
            if age_hours is not None:
                freshness = "fresh" if threshold is None or age_hours <= threshold else "stale"
            elif state.get("last_error_code"):
                freshness = "error"
            checkpoint = state.get("checkpoint") or {}
            pending = checkpoint.get("bulk_pending")
            entry.update(
                {
                    "last_success_at": state.get("last_success_at"),
                    "last_error_code": state.get("last_error_code"),
                    "data_through": state.get("data_through"),
                    "rows_total": state.get("rows_total"),
                    "freshness": freshness,
                    "backfill_pending": len(pending) if isinstance(pending, list) else None,
                }
            )
        elif capability.status == "enabled":
            entry["freshness"] = "never_synced"
        if capability.key == "topix_prices":
            entry.update(topix_actual)
            if not entry["data_through"]:
                entry["freshness"] = "never_synced"
            elif state is None:
                entry["freshness"] = "unknown"
        if capability.key in {"topix_prices", "margin_alerts", "short_sale_ratio"}:
            if entry["last_error_code"]:
                entry["freshness"] = "error"
            elif entry["data_through"] and market_date:
                # Non-trading days do not age data that already covers the
                # latest completed market date. Real missing dates still do.
                entry["freshness"] = "stale" if entry["data_through"] < market_date else "fresh"
        if capability.key == "margin_interest":
            entry.update(margin_actual)
            if entry["last_error_code"]:
                entry["freshness"] = "error"
            elif not entry["data_through"]:
                entry["freshness"] = "never_synced"
            elif expected_margin_date:
                # Daily balances are published on the next business day; the
                # latest Friday quote does not require Friday balances on Sunday.
                entry["freshness"] = "stale" if entry["data_through"] < expected_margin_date else "fresh"
            else:
                age = _hours_since(entry["last_success_at"])
                threshold = 9 * 24 if entry["data_through"] < "2026-09-25" else _STALE_HOURS["margin_interest"]
                entry["freshness"] = "unknown" if age is None else "stale" if age > threshold else "fresh"
        datasets.append(entry)

    return {
        "version": DATA_STATUS_VERSION,
        "provider": "J-Quants API V2",
        "plan": SUBSCRIPTION_PLAN,
        "api_key_configured": jquants_configured,
        "market_timezone": "Asia/Tokyo",
        "datasets": datasets,
        "intraday": intraday,
    }


def intraday_addon_status(target_date: str | None = None) -> dict[str, Any]:
    """分足・ティックのアドオン実況: 能力宣言（契約状態）＋実データ可用性。

    以前は data_status() が enabled=False を直書きしており、CAPABILITIES で
    intraday_prices / tick_trades を enabled と宣言し実装も存在するのと矛盾していた。
    """

    from app.data_paths import get_data_paths
    from app.providers.jquants.capabilities import capability_map
    from app.repositories.intraday_store import (
        DATASET_MINUTE,
        DATASET_TICK,
        IntradayStore,
    )

    caps = capability_map()
    minute_cap = caps.get("intraday_prices")
    tick_cap = caps.get("tick_trades")
    enabled = bool(
        (minute_cap is not None and minute_cap.status == "enabled")
        or (tick_cap is not None and tick_cap.status == "enabled")
    )
    note = (
        "分足・ティックはアドオン契約済み。銘柄別オンデマンド取得（全市場の常時取得ではない）。"
        if enabled
        else "現プランは日足まで。分足・リアルタイムは将来の拡張ポイント（IntradayProvider）で追加予定。"
    )
    store = IntradayStore(get_data_paths().intraday_db, read_only=True)
    def summary(dataset: str) -> dict:
        if not store.exists():
            return {"availability": "unknown", "freshness": "never_synced", "rows_total": 0}
        actual = store.dataset_summary(dataset)
        checked = actual.get("checked_through") or actual.get("data_through")
        if actual.get("last_error_code"):
            freshness = "error"
        elif checked:
            freshness = "stale" if target_date and checked < target_date else "fresh"
        else:
            freshness = "never_synced"
        return {**actual, "freshness": freshness}
    return {
        "enabled": enabled,
        "note_ja": note,
        "minute": summary(DATASET_MINUTE),
        "tick": summary(DATASET_TICK),
    }


def _dataset_key(capability_key: str) -> str:
    aliases = {
        "listed_master": "security_master",
        "daily_prices": "daily_prices",
        "topix_prices": "topix_prices",
        "index_prices": "index_prices",
        "financial_summary": "financial_summary",
        "earnings_calendar": "earnings_calendar",
        "trading_calendar": "trading_calendar",
        "margin_interest": "margin_interest",
        "margin_alerts": "margin_alerts",
        "short_sale_ratio": "short_sale_ratio",
        "reported_short_positions": "reported_short_positions",
    }
    return aliases.get(capability_key, capability_key)


__all__ = ["DATA_STATUS_VERSION", "data_status", "intraday_addon_status"]
