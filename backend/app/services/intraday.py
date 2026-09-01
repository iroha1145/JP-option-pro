"""分足の取得・リサンプリング・チャート提供。

- 取得はワーカー経由（オーナーの手動アクション intraday_fetch）。API プロセスは
  jp-intraday.db を読むだけで、プロバイダに触れない（全站規約）。
- 未契約（403）は AVAILABILITY_PLAN_NOT_INCLUDED として保存し、チャート API は
  「アドオン未契約」を正直に返す。空配列で「データなし」を装わない。
- リサンプリング: 1分 → 5分/60分。バケットは壁時計切り捨て
  （5分: HH:M0〜、60分: HH:00〜）。欠けた分は埋めない。
"""

from __future__ import annotations

import csv
from typing import Any, Iterable, Mapping

from app.providers.jquants.client import JQuantsClient
from app.providers.jquants.errors import JQuantsError, JQuantsPlanError
from app.providers.jquants.mapping import map_minute_bar, map_trade_tick
from app.repositories.core import CoreRepository
from app.repositories.intraday_store import (
    AVAILABILITY_AVAILABLE,
    AVAILABILITY_PLAN_NOT_INCLUDED,
    DATASET_TICK,
    IntradayStore,
)

INTRADAY_INTERVALS = ("1m", "5m", "60m")
CHART_INTERVALS = ("1d", *INTRADAY_INTERVALS)
FETCH_TRADING_DAYS = 5
RETENTION_TRADING_DAYS = 30

# ティック: 1 銘柄 1 日で数万〜数十万行になり得る。取得は直近取引日のみ、
# 行数に硬い上限を置き（超過は truncated として正直に記録）、チャート用には
# サーバ側で秒バケットへ間引いた ≤ TICK_CHART_MAX_POINTS 点だけを返す。
TICK_FETCH_MAX_ROWS = 200_000
TICK_RETENTION_TRADING_DAYS = 7
TICK_CHART_MAX_POINTS = 1_200
TICK_TAPE_ROWS = 60
# 公式仕様: ティックは CSV 一括配信のみ。REST エンドポイントは存在しない。
TICK_BULK_ENDPOINT = "equities/trades"


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
    fetched = store.fetched_days_for(canonical_code)
    if not minute_rows:
        if fetched:
            return {
                "available": False,
                "reason": "empty",
                "availability": state["availability"],
                "note_ja": "この銘柄の分足は取得済みですが、表示できるバーがありません。",
                "days": sorted(fetched.keys()),
                "bars": [],
            }
        return {
            "available": False,
            "reason": "not_fetched",
            "availability": state["availability"],
            "note_ja": "この銘柄の分足はまだ取得されていません。",
            "bars": [],
        }
    bars = resample_minutes(minute_rows, interval)
    return {
        "available": True,
        "availability": state["availability"],
        "interval": interval,
        "days": sorted(fetched.keys()),
        "bars": bars,
    }


# ---------------------------------------------------------------------------
# ティック（/equities/trades アドオン）
# ---------------------------------------------------------------------------


def fetch_latest_ticks(
    *,
    client: JQuantsClient,
    store: IntradayStore,
    core: CoreRepository,
    canonical_code: str,
    extra_codes: Iterable[str] | None = None,
) -> dict[str, Any]:
    """直近取引日のティックを取得して丸ごと置換キャッシュする。

    配信形態は CSV 一括のみ（公式仕様: 「本データはCSV形式でのみ提供しており、
    API経由での取得はできません」）。REST を叩くと存在しないパスとして 403 が
    返り、未契約と見分けが付かない —— このゲートウェイは未知パスにも 403 を返す。

    完了日は不変なので、既にキャッシュ済み（非 truncated）ならスキップ。
    extra_codes を渡すと同じダウンロード 1 パスでまとめて抽出する。
    """

    latest = core.latest_bar_date() or core.latest_trading_day("2099-12-31")
    if latest is None:
        return {"status": "error", "error_code": "trading_calendar_empty"}
    cached = store.tick_days_for(canonical_code).get(latest)
    if cached and cached["tick_count"] > 0 and not cached["truncated"]:
        # 「完了日は不変」だが、こちらのマッパーが壊れていた時期に取り込んだ行は
        # 不変ではなく単に間違っている（実例: 数量列を取り違えて volume が全 NULL）。
        # 数量が 1 件も入っていない日はキャッシュとして信用せず取り直す。
        if store.tick_day_has_volume(canonical_code, latest):
            return {
                "status": "ok", "trade_date": latest,
                "ticks": cached["tick_count"], "cached": True,
            }

    # ティックは REST では取れない（公式仕様: CSV 一括配信のみ）。日次ファイルは
    # 全市場 600 万行・50〜70MB gz なので、1 銘柄のために毎回落とすのは高い。
    # 同じ 1 パスで「今欲しい銘柄＋自選＋レーダー中」をまとめて抽出して償却する。
    wanted = {str(canonical_code)} | {str(code) for code in (extra_codes or ())}
    try:
        key = _tick_file_key(client, latest)
    except JQuantsPlanError:
        # bulk/list 自体が弾かれる = アドオン未契約。正直に記録する。
        store.record_availability(
            AVAILABILITY_PLAN_NOT_INCLUDED,
            error_code="jquants_plan_not_included",
            dataset=DATASET_TICK,
        )
        return {"status": "plan_not_included", "trade_date": latest}
    except JQuantsError as exc:
        return {"status": "error", "error_code": exc.code, "trade_date": latest}
    if key is None:
        # 営業日なのにファイルが無い = まだ publish されていない（当日は引け後）。
        # 0 件の tick_day を残さないとビューが not_fetched のまま自動再投入が回る。
        store.replace_ticks(str(canonical_code), latest, [], truncated=False)
        store.record_availability(AVAILABILITY_AVAILABLE, dataset=DATASET_TICK)
        return {"status": "not_published", "trade_date": latest}

    collected: dict[str, list[dict[str, Any]]] = {code: [] for code in wanted}
    truncated: set[str] = set()
    try:
        stream = client.bulk_download_csv(key)
        for raw in csv.DictReader(stream):
            code = (raw.get("Code") or "").strip()
            if code not in collected:
                continue
            if len(collected[code]) >= TICK_FETCH_MAX_ROWS:
                truncated.add(code)
                continue
            mapped = map_trade_tick(raw)
            if mapped is not None:
                collected[code].append(mapped)
    except JQuantsPlanError:
        store.record_availability(
            AVAILABILITY_PLAN_NOT_INCLUDED,
            error_code="jquants_plan_not_included",
            dataset=DATASET_TICK,
        )
        return {"status": "plan_not_included", "trade_date": latest}
    except JQuantsError as exc:
        return {"status": "error", "error_code": exc.code, "trade_date": latest}

    stored_by_code = {}
    for code, rows in collected.items():
        stored_by_code[code] = store.replace_ticks(
            code, latest, rows, truncated=code in truncated
        )
    store.record_availability(AVAILABILITY_AVAILABLE, dataset=DATASET_TICK)
    return {
        "status": "ok",
        "trade_date": latest,
        "ticks": stored_by_code.get(str(canonical_code), 0),
        "truncated": str(canonical_code) in truncated,
        "codes_stored": len(stored_by_code),
        "file": key,
    }


def _tick_file_key(client: JQuantsClient, trade_date: str) -> str | None:
    """その営業日のティック CSV のキー。まだ publish されていなければ None。"""

    compact = trade_date.replace("-", "")
    for entry in client.bulk_list(endpoint=TICK_BULK_ENDPOINT, date_from=trade_date, date_to=trade_date):
        key = entry.get("Key") or entry.get("key") or ""
        if compact in key:
            return key
    return None


def _tick_seconds(tick_time: str) -> int:
    """'HH:MM[:SS[.ffff]]' → 当日通算秒。秒欠落は :00 扱い。"""

    parts = tick_time.split(":")
    hours = int(parts[0])
    minutes = int(parts[1]) if len(parts) > 1 else 0
    seconds = int(float(parts[2])) if len(parts) > 2 else 0
    return hours * 3600 + minutes * 60 + seconds


def downsample_ticks(
    rows: list[dict[str, Any]], *, max_points: int = TICK_CHART_MAX_POINTS
) -> tuple[list[dict[str, Any]], int]:
    """秒バケットで間引く: (points, bucket_seconds)。

    各バケットは {t, price(=last), high, low, volume(=sum)}。
    昼休みなど取引の無い区間はバケット自体が生まれない（埋めない）。
    """

    if not rows:
        return [], 1
    first = _tick_seconds(rows[0]["tick_time"])
    last = _tick_seconds(rows[-1]["tick_time"])
    span = max(1, last - first)
    bucket_seconds = max(1, -(-span // max(1, int(max_points))))
    points: list[dict[str, Any]] = []
    current_key: int | None = None
    for row in rows:
        price = row.get("price")
        if price is None:
            continue
        key = _tick_seconds(row["tick_time"]) // bucket_seconds
        volume = row.get("volume") or 0.0
        if key != current_key:
            seconds = key * bucket_seconds
            points.append(
                {
                    "t": f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}",
                    "price": price,
                    "high": price,
                    "low": price,
                    "volume": volume,
                }
            )
            current_key = key
            continue
        point = points[-1]
        point["price"] = price
        if price > point["high"]:
            point["high"] = price
        if price < point["low"]:
            point["low"] = price
        point["volume"] += volume
    return points, bucket_seconds


def tick_tape(rows: list[dict[str, Any]], *, limit: int = TICK_TAPE_ROWS) -> list[dict[str, Any]]:
    """歩み値: 直近 limit 件（新しい順）に前値比方向を付ける。"""

    tape: list[dict[str, Any]] = []
    start = max(0, len(rows) - int(limit) - 1)
    window = rows[start:]
    for index in range(1 if start > 0 or len(window) > int(limit) else 0, len(window)):
        row = window[index]
        prev = window[index - 1] if index > 0 else None
        price = row.get("price")
        prev_price = prev.get("price") if prev else None
        direction = "flat"
        if price is not None and prev_price is not None:
            direction = "up" if price > prev_price else "down" if price < prev_price else "flat"
        tape.append(
            {
                "time": row["tick_time"],
                "price": price,
                "volume": row.get("volume"),
                "direction": direction,
            }
        )
    tape.reverse()
    return tape[: int(limit)]


def tick_view(
    store: IntradayStore,
    canonical_code: str,
    *,
    max_points: int = TICK_CHART_MAX_POINTS,
    tape_rows: int = TICK_TAPE_ROWS,
) -> dict[str, Any]:
    """ティックチャート＋歩み値ビュー。可用性を必ず宣言する。"""

    empty = {"points": [], "tape": [], "trade_date": None, "tick_count": 0}
    if not store.exists():
        return {"available": False, "reason": "not_fetched", "availability": "unknown", **empty}
    state = store.availability(DATASET_TICK)
    if state["availability"] == AVAILABILITY_PLAN_NOT_INCLUDED:
        return {
            "available": False,
            "reason": "plan_not_included",
            "availability": state["availability"],
            "note_ja": "ティックは J-Quants の Tick アドオン契約が必要です（CSV 一括配信）。",
            **empty,
        }
    days = store.tick_days_for(canonical_code)
    if not days:
        return {
            "available": False,
            "reason": "not_fetched",
            "availability": state["availability"],
            "note_ja": "この銘柄のティックはまだ取得されていません。取得は日次 CSV（全市場 50MB 超）からの抽出になるため、必要な時だけ実行します。",
            **empty,
        }
    trade_date = max(days.keys())
    meta = days[trade_date]
    if int(meta["tick_count"] or 0) == 0:
        return {
            "available": False,
            "reason": "empty",
            "availability": state["availability"],
            "note_ja": "ティックは取得済みですが、この銘柄の約定が無い、または日次ファイルが未配信です。",
            "trade_date": trade_date,
            "tick_count": 0,
            "points": [],
            "tape": [],
        }
    rows = store.ticks_for(canonical_code, trade_date)
    points, bucket_seconds = downsample_ticks(rows, max_points=max_points)
    from app.services.tick_analytics import analyse

    return {
        "analytics": analyse(rows),
        "available": True,
        "availability": state["availability"],
        "trade_date": trade_date,
        "tick_count": meta["tick_count"],
        "truncated": bool(meta["truncated"]),
        "fetched_at": meta["fetched_at"],
        "bucket_seconds": bucket_seconds,
        "points": points,
        "tape": tick_tape(rows, limit=tape_rows),
    }


__all__ = [
    "CHART_INTERVALS",
    "FETCH_TRADING_DAYS",
    "INTRADAY_INTERVALS",
    "RETENTION_TRADING_DAYS",
    "TICK_CHART_MAX_POINTS",
    "TICK_FETCH_MAX_ROWS",
    "TICK_RETENTION_TRADING_DAYS",
    "TICK_BULK_ENDPOINT",
    "TICK_TAPE_ROWS",
    "downsample_ticks",
    "fetch_latest_ticks",
    "fetch_recent_minutes",
    "intraday_chart",
    "resample_minutes",
    "tick_tape",
    "tick_view",
]
