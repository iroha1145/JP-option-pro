"""分足の取得・リサンプリング・チャート提供。

- 取得はワーカー経由（オーナーの手動アクション intraday_fetch）。API プロセスは
  jp-intraday.db を読むだけで、プロバイダに触れない（全站規約）。
- 未契約（403）は AVAILABILITY_PLAN_NOT_INCLUDED として保存し、チャート API は
  「アドオン未契約」を正直に返す。空配列で「データなし」を装わない。
- リサンプリング: 1分 → 5分/60分。バケットは壁時計切り捨て
  （5分: HH:M0〜、60分: HH:00〜）。欠けた分は埋めない。
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from app.providers.jquants.client import JQuantsClient
from app.providers.jquants.errors import JQuantsError, JQuantsPlanError
from app.providers.jquants.mapping import map_minute_bar
from app.repositories.core import CoreRepository
from app.repositories.intraday_store import (
    AVAILABILITY_AVAILABLE,
    AVAILABILITY_PLAN_NOT_INCLUDED,
    IntradayStore,
)

INTRADAY_INTERVALS = ("1m", "5m", "60m")
CHART_INTERVALS = ("1d", *INTRADAY_INTERVALS)
FETCH_TRADING_DAYS = 5
RETENTION_TRADING_DAYS = 30


def fetch_recent_minutes(
    *,
    client: JQuantsClient,
    store: IntradayStore,
    core: CoreRepository,
    canonical_code: str,
    days: int = FETCH_TRADING_DAYS,
) -> dict[str, Any]:
    """直近 N 取引日の分足を取得してキャッシュ（完了日は再取得しない）。"""

    latest = core.latest_bar_date() or core.latest_trading_day("2099-12-31")
    if latest is None:
        return {"status": "error", "error_code": "trading_calendar_empty"}
    from app.domain.timeutil import add_days

    window = core.trading_days_between(add_days(latest, -30), latest)
    trading_days = list(reversed(window[-max(1, int(days)):]))
    already = store.fetched_days_for(canonical_code)
    fetched = 0
    bars_total = 0
    for day in trading_days:
        if day in already and already[day]["bar_count"] > 0 and day != latest:
            continue  # 完了日のキャッシュは不変
        try:
            rows = [
                mapped
                for row in client.fetch_rows(
                    "/equities/bars/minute", {"code": canonical_code, "date": day}
                )
                if (mapped := map_minute_bar(row))
            ]
        except JQuantsPlanError:
            store.record_availability(
                AVAILABILITY_PLAN_NOT_INCLUDED, error_code="jquants_plan_not_included"
            )
            return {"status": "plan_not_included", "fetched_days": fetched}
        except JQuantsError as exc:
            return {"status": "error", "error_code": exc.code, "fetched_days": fetched}
        store.upsert_minute_bars(rows)
        store.record_fetched_day(canonical_code, day, len(rows))
        fetched += 1
        bars_total += len(rows)
    store.record_availability(AVAILABILITY_AVAILABLE)
    return {"status": "ok", "fetched_days": fetched, "bars": bars_total, "days": trading_days}


def _bucket_key(bar_time: str, interval: str) -> str:
    hours, minutes = int(bar_time[:2]), int(bar_time[3:5])
    if interval == "5m":
        minutes = (minutes // 5) * 5
    elif interval == "60m":
        minutes = 0
    return f"{hours:02d}:{minutes:02d}"


def resample_minutes(
    rows: Iterable[Mapping[str, Any]], interval: str
) -> list[dict[str, Any]]:
    """1分足 → 指定間隔。入力は (trade_date, bar_time) 昇順であること。"""

    if interval == "1m":
        return [dict(row) for row in rows]
    buckets: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for row in rows:
        key = (row["trade_date"], _bucket_key(row["bar_time"], interval))
        if current is None or (current["trade_date"], current["bar_time"]) != key:
            if current is not None:
                buckets.append(current)
            current = {
                "trade_date": row["trade_date"],
                "bar_time": key[1],
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "close": row.get("close"),
                "volume": row.get("volume") or 0.0,
                "turnover_value": row.get("turnover_value") or 0.0,
            }
            continue
        high = row.get("high")
        low = row.get("low")
        if high is not None and (current["high"] is None or high > current["high"]):
            current["high"] = high
        if low is not None and (current["low"] is None or low < current["low"]):
            current["low"] = low
        if row.get("close") is not None:
            current["close"] = row["close"]
        if current["open"] is None and row.get("open") is not None:
            current["open"] = row["open"]
        current["volume"] = (current["volume"] or 0.0) + (row.get("volume") or 0.0)
        current["turnover_value"] = (current["turnover_value"] or 0.0) + (
            row.get("turnover_value") or 0.0
        )
    if current is not None:
        buckets.append(current)
    return buckets


def intraday_chart(
    store: IntradayStore, canonical_code: str, *, interval: str
) -> dict[str, Any]:
    """チャート API 用の分足ビュー。可用性を必ず宣言する。"""

    if interval not in INTRADAY_INTERVALS:
        raise ValueError(f"unsupported intraday interval: {interval}")
    if not store.exists():
        return {
            "available": False,
            "reason": "not_fetched",
            "availability": "unknown",
            "bars": [],
        }
    state = store.availability()
    if state["availability"] == AVAILABILITY_PLAN_NOT_INCLUDED:
        return {
            "available": False,
            "reason": "plan_not_included",
            "availability": state["availability"],
            "note_ja": "分足は J-Quants のオプション（アドオン）契約が必要です。現在の契約では取得できません。",
            "bars": [],
        }
    minute_rows = store.minute_bars(canonical_code)
    if not minute_rows:
        return {
            "available": False,
            "reason": "not_fetched",
            "availability": state["availability"],
            "note_ja": "この銘柄の分足はまだ取得されていません。",
            "bars": [],
        }
    bars = resample_minutes(minute_rows, interval)
    fetched = store.fetched_days_for(canonical_code)
    return {
        "available": True,
        "availability": state["availability"],
        "interval": interval,
        "days": sorted(fetched.keys()),
        "bars": bars,
    }


__all__ = [
    "CHART_INTERVALS",
    "FETCH_TRADING_DAYS",
    "INTRADAY_INTERVALS",
    "RETENTION_TRADING_DAYS",
    "fetch_recent_minutes",
    "intraday_chart",
    "resample_minutes",
]
