"""銘柄 × 営業日の行動スナップショットを全市場ぶん組み立てる。

順序が大事:

1. 銘柄ごとに **生の比** まで作る（吸収の分位はまだ出せない）
2. その日の横断面で分位を取る
3. 分位を吸収スコアに直し、状態と点数を決める

2 を挟まずに絶対閾値で吸収を決めると、日本株で検証していない米国由来の
数字を持ち込むことになる。「この日の全銘柄の中でどのくらいか」なら、
少なくとも意味の分かる基準になる。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from app.services.radar.adjustment import adjust_series

from . import events as ev
from . import factors as fac
from . import scoring, states
from .institutions import INSTITUTION_VERSION, InstitutionResolver

#: スナップショット全体の版。どれか 1 つでも変わったら作り直す対象になる。
SNAPSHOT_VERSION = "+".join((
    INSTITUTION_VERSION, ev.EVENT_VERSION, fac.FACTOR_VERSION,
    states.STATE_VERSION, scoring.SCORE_VERSION,
))

LOOKBACK_TRADING_DAYS = 20
SHORT_WINDOW = 5
LONG_WINDOW = 20


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _returns(closes: Sequence[float], window: int) -> float | None:
    if len(closes) <= window:
        return None
    start, end = closes[-window - 1], closes[-1]
    if start is None or end is None or start <= 0.0:
        return None
    return end / start - 1.0


@dataclass
class StockInputs:
    canonical_code: str
    bars: list[dict[str, Any]]
    events: list[dict[str, Any]] = field(default_factory=list)
    sector33_code: str | None = None
    margin: Mapping[str, Any] | None = None
    regulation_severity: int = 0
    trading_days_to_earnings: int | None = None
    news_count_5d: int = 0
    breakout_confirmed: bool = False
    turnover_confirmed: bool = False


@dataclass
class MarketInputs:
    as_of_date: str
    trading_days: list[str]              # 昇順、as_of を含む
    topix_closes: Mapping[str, float]    # trade_date → 終値
    has_news_feed: bool = True


def _window_date(trading_days: Sequence[str], back: int) -> str | None:
    """`back` 営業日前の日付。足りなければ None。"""

    if len(trading_days) <= back:
        return None
    return trading_days[-1 - back]


def _visible_at(events: Sequence[Mapping[str, Any]], cutoff: str) -> dict[str, Any]:
    return ev.visible_totals(ev.last_known_as_of(events, published_cutoff=cutoff))


def _count_events(
    events: Iterable[Mapping[str, Any]], *, since: str
) -> dict[str, int]:
    counts = {
        "entry": 0, "reentry": 0, "reduction": 0, "threshold_exit": 0,
        "increase": 0, "closed": 0, "correction": 0,
    }
    for event in events:
        # 効力日（公開後の最初の営業日）で数える。仓位日で数えると未来の情報を
        # 過去の窓に入れてしまう。
        if str(event.get("effective_trade_date") or "") < since:
            continue
        kind = event.get("event_type")
        if kind == ev.EVENT_NEW:
            counts["entry"] += 1
        elif kind == ev.EVENT_REENTRY:
            counts["reentry"] += 1
        elif kind == ev.EVENT_DECREASED:
            counts["reduction"] += 1
        elif kind == ev.EVENT_BELOW_THRESHOLD:
            counts["threshold_exit"] += 1
        elif kind == ev.EVENT_INCREASED:
            counts["increase"] += 1
        elif kind == ev.EVENT_CLOSED:
            counts["closed"] += 1
        if event.get("correction_status") == ev.CORRECTION_REVISED:
            counts["correction"] += 1
    return counts


def _price_context(bars: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """調整後の価格文脈。分割を跨いだ「50% 暴落」を作らない。"""

    if not bars:
        return {"known": False}
    adjusted = adjust_series(bars)
    closes = [_num(bar.get("close")) for bar in adjusted]
    closes = [value for value in closes if value is not None and value > 0.0]
    if len(closes) < 25:
        return {"known": False, "bars_available": len(closes)}

    highs = [_num(bar.get("high")) or _num(bar.get("close")) for bar in adjusted]
    lows = [_num(bar.get("low")) or _num(bar.get("close")) for bar in adjusted]
    volumes = [_num(bar.get("volume")) for bar in adjusted]
    values = [_num(bar.get("turnover_value")) for bar in adjusted]

    window_252 = closes[-252:]
    highs_252 = [h for h in highs[-252:] if h is not None]
    lows_60 = [l for l in lows[-60:] if l is not None]
    recent_volumes = [v for v in volumes[-20:] if v is not None]
    recent_values = [v for v in values[-20:] if v is not None]

    close = closes[-1]
    ma200 = sum(closes[-200:]) / len(closes[-200:]) if len(closes) >= 200 else None
    # 「安値を更新中か」= 直近 5 営業日の安値が、その前の 60 日の最安を割ったか
    prior_low = min(lows_60[:-5]) if len(lows_60) > 10 else None
    recent_low = min(lows_60[-5:]) if len(lows_60) >= 5 else None
    made_new_low = bool(prior_low and recent_low and recent_low < prior_low)
    # 長期支持割れ = 200 日線を 3% 以上下回った状態
    broke_support = bool(ma200 and close < ma200 * 0.97)

    return {
        "known": True,
        "bars_available": len(closes),
        "close": close,
        "closes_252": window_252,
        "high_52w": max(highs_252) if highs_252 else None,
        "ma200": ma200,
        "adv20_shares": (sum(recent_volumes) / len(recent_volumes)) if recent_volumes else None,
        "adv20_value": (sum(recent_values) / len(recent_values)) if recent_values else None,
        "return_5d": _returns(closes, SHORT_WINDOW),
        "return_20d": _returns(closes, LONG_WINDOW),
        "made_new_low": made_new_low,
        "broke_long_support": broke_support,
    }


def _benchmark_returns(topix_closes: Mapping[str, float], trading_days: Sequence[str]) -> dict[str, float | None]:
    series = [_num(topix_closes.get(day)) for day in trading_days]
    series = [value for value in series if value is not None and value > 0.0]
    return {
        "topix_5d": _returns(series, SHORT_WINDOW),
        "topix_20d": _returns(series, LONG_WINDOW),
    }


def build_raw_rows(
    stocks: Sequence[StockInputs], market: MarketInputs
) -> list[dict[str, Any]]:
    """第 1 段: 銘柄ごとの生の素材。吸収スコアはまだ入らない。"""

    benchmarks = _benchmark_returns(market.topix_closes, market.trading_days)
    cutoff_5 = _window_date(market.trading_days, SHORT_WINDOW)
    cutoff_20 = _window_date(market.trading_days, LONG_WINDOW)
    since_20 = cutoff_20 or market.trading_days[0]

    rows: list[dict[str, Any]] = []
    for stock in stocks:
        price = _price_context(stock.bars)
        if not price.get("known"):
            continue

        now = _visible_at(stock.events, market.as_of_date)
        prev_5 = _visible_at(stock.events, cutoff_5) if cutoff_5 else None
        prev_20 = _visible_at(stock.events, cutoff_20) if cutoff_20 else None
        counts = _count_events(stock.events, since=since_20)

        rows.append({
            "canonical_code": stock.canonical_code,
            "sector33_code": stock.sector33_code,
            "price": price,
            "now": now,
            "prev_5": prev_5,
            "prev_20": prev_20,
            "counts": counts,
            "stock": stock,
            "benchmarks": benchmarks,
        })
    return rows


def _delta(now: Mapping[str, Any] | None, before: Mapping[str, Any] | None, key: str) -> float | None:
    if not now or not before:
        return None
    a, b = _num(now.get(key)), _num(before.get(key))
    if a is None or b is None:
        return None
    return a - b


def _sector_medians(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, float]:
    """業種ごとの中位リターン。業種指数ではなく **構成銘柄の中位** を使う
    （既存の相対強度と同じ定義に揃える）。"""

    buckets: dict[str, list[float]] = {}
    for row in rows:
        sector = row.get("sector33_code")
        value = _num((row.get("price") or {}).get(key))
        if sector and value is not None:
            buckets.setdefault(sector, []).append(value)
    medians: dict[str, float] = {}
    for sector, values in buckets.items():
        if len(values) < 3:
            continue
        values.sort()
        middle = len(values) // 2
        medians[sector] = (
            values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2.0
        )
    return medians


def build_snapshots(
    stocks: Sequence[StockInputs], market: MarketInputs
) -> list[dict[str, Any]]:
    """全市場のスナップショット行。横断面の分位はこの中で取る。"""

    raw = build_raw_rows(stocks, market)
    if not raw:
        return []

    median_20 = _sector_medians(raw, "return_20d")
    median_5 = _sector_medians(raw, "return_5d")

    # -- 第 1 段: 生の比まで ------------------------------------------------
    prepared: list[dict[str, Any]] = []
    for row in raw:
        price = row["price"]
        stock: StockInputs = row["stock"]
        adv_shares = price.get("adv20_shares")

        rel_topix_20 = _rel(price.get("return_20d"), row["benchmarks"].get("topix_20d"))
        rel_topix_5 = _rel(price.get("return_5d"), row["benchmarks"].get("topix_5d"))
        rel_sector_20 = _rel(price.get("return_20d"), median_20.get(row.get("sector33_code") or ""))
        rel_sector_5 = _rel(price.get("return_5d"), median_5.get(row.get("sector33_code") or ""))

        shares_delta_5 = _delta(row["now"], row["prev_5"], "visible_short_shares")
        shares_delta_20 = _delta(row["now"], row["prev_20"], "visible_short_shares")
        ratio_delta_5 = _delta(row["now"], row["prev_5"], "visible_short_ratio")
        ratio_delta_20 = _delta(row["now"], row["prev_20"], "visible_short_ratio")

        pressure_5 = fac.short_pressure(
            shares_change=shares_delta_5, adv20_shares=adv_shares,
            entries=row["counts"]["entry"], reentries=row["counts"]["reentry"],
        )
        pressure_20 = fac.short_pressure(
            shares_change=shares_delta_20, adv20_shares=adv_shares,
            entries=row["counts"]["entry"], reentries=row["counts"]["reentry"],
        )
        damage_5 = fac.DamageInput(
            pressure_adv20=pressure_5.get("pressure_adv20"),
            rel_topix=rel_topix_5, rel_sector=rel_sector_5,
        ).raw_damage()
        damage_20 = fac.DamageInput(
            pressure_adv20=pressure_20.get("pressure_adv20"),
            rel_topix=rel_topix_20, rel_sector=rel_sector_20,
        ).raw_damage()

        prepared.append({
            **row,
            "rel_topix_20d": rel_topix_20, "rel_topix_5d": rel_topix_5,
            "rel_sector_20d": rel_sector_20, "rel_sector_5d": rel_sector_5,
            "shares_delta_5": shares_delta_5, "shares_delta_20": shares_delta_20,
            "ratio_delta_5": ratio_delta_5, "ratio_delta_20": ratio_delta_20,
            "pressure_5": pressure_5, "pressure_20": pressure_20,
            "damage_5": damage_5, "damage_20": damage_20,
        })

    # -- 第 2 段: その日の横断面で分位 -------------------------------------
    damage_population = [row["damage_20"] for row in prepared if row["damage_20"] is not None]

    # -- 第 3 段: 吸収・状態・点数 -----------------------------------------
    out: list[dict[str, Any]] = []
    for row in prepared:
        out.append(_finalize(row, market, damage_population))
    return out


def _rel(value: float | None, benchmark: float | None) -> float | None:
    a, b = _num(value), _num(benchmark)
    if a is None or b is None:
        return None
    return a - b


def _finalize(
    row: Mapping[str, Any], market: MarketInputs, damage_population: Sequence[float]
) -> dict[str, Any]:
    price = row["price"]
    stock: StockInputs = row["stock"]
    now = row["now"]
    counts = row["counts"]
    adv_shares = price.get("adv20_shares")

    percentile = (
        fac.percentile_rank(damage_population, row["damage_20"])
        if row["damage_20"] is not None else None
    )
    consistent = (
        row["damage_5"] is not None and row["damage_20"] is not None
        and (row["damage_5"] >= 0) == (row["damage_20"] >= 0)
    )
    absorption = fac.absorption_from_percentile(
        percentile, made_new_low=bool(price.get("made_new_low")), consistent=consistent,
    )

    low = fac.low_position(
        close=price.get("close"), high_52w=price.get("high_52w"),
        closes_252=price.get("closes_252") or [], ma200=price.get("ma200"),
    )
    cover = fac.covering(
        shares_change=row["shares_delta_20"], adv20_shares=adv_shares,
        reducing_institutions=counts["reduction"], threshold_exits=counts["threshold_exit"],
        rel_topix=row["rel_topix_20d"],
        concentrated=bool((now.get("concentration") or 0.0) >= 0.6),
    )
    rot = fac.rotation(
        entries=counts["entry"], reentries=counts["reentry"],
        exits=counts["threshold_exit"] + counts["closed"], reductions=counts["reduction"],
        concentration=now.get("concentration"),
    )
    margin = fac.margin_environment(
        margin_long=(stock.margin or {}).get("long_total"),
        margin_short=(stock.margin or {}).get("short_total"),
        margin_long_change=(stock.margin or {}).get("long_change"),
        adv20_shares=adv_shares,
        regulation_severity=stock.regulation_severity,
    )
    cat = fac.catalyst(
        trading_days_to_earnings=stock.trading_days_to_earnings,
        news_count_5d=stock.news_count_5d, has_news_feed=market.has_news_feed,
    )
    days_to_cover = fac.visible_days_to_cover(now.get("visible_short_shares"), adv_shares)

    last_report = _last_report_age(stock.events, market.trading_days)
    confidence = fac.data_confidence(
        mapping_confidence=_min_mapping_confidence(stock.events),
        visible_institution_count=int(now.get("visible_institution_count") or 0),
        days_since_last_report=last_report,
        bars_available=int(price.get("bars_available") or 0),
        below_threshold_count=int(now.get("below_threshold_count") or 0),
        has_correction=counts["correction"] > 0,
        adv20_value=price.get("adv20_value"),
    )

    evidence = {
        "pressure_adv20_20d": row["pressure_20"].get("pressure_adv20"),
        "pressure_adv20_5d": row["pressure_5"].get("pressure_adv20"),
        "absorption_score": absorption.get("absorption_score"),
        "covering_score": cover.get("score"),
        "low_position_score": low.get("score"),
        "rotation_score": rot.get("score"),
        "visible_days_to_cover": days_to_cover,
        "rel_topix_20d": row["rel_topix_20d"],
        "rel_sector_20d": row["rel_sector_20d"],
        "breakout_confirmed": stock.breakout_confirmed,
        "turnover_confirmed": stock.turnover_confirmed,
        "made_new_low": price.get("made_new_low"),
        "broke_long_support": price.get("broke_long_support"),
        "data_confidence": confidence["confidence"],
        "visible_institution_count": now.get("visible_institution_count"),
        "below_threshold_count": now.get("below_threshold_count"),
        "hedge_institution_count": now.get("hedge_institution_count"),
        "concentration": now.get("concentration"),
        "entry_count_20d": counts["entry"],
        "reentry_count_20d": counts["reentry"],
        "reduction_count_20d": counts["reduction"],
        "threshold_exit_count_20d": counts["threshold_exit"],
        "crowded_long": margin.get("crowded_long"),
        "regulation_severity": margin.get("regulation_severity"),
        "earnings_near": bool(
            stock.trading_days_to_earnings is not None and stock.trading_days_to_earnings <= 5
        ),
        "news_catalyst": stock.news_count_5d > 0,
        "thin_liquidity": "thin_liquidity" in confidence["reasons"],
        "days_since_last_report": last_report,
    }
    verdict = states.classify(evidence)
    score = scoring.behavior_score({
        "absorption": absorption.get("absorption_score"),
        "covering": cover.get("score"),
        "low_position": low.get("score"),
        "short_pressure": row["pressure_20"].get("score"),
        "rotation": rot.get("score"),
        "catalyst": cat.get("score"),
        "risk": margin.get("score"),
    })

    components = {
        "low_position": low, "pressure_5d": row["pressure_5"], "pressure_20d": row["pressure_20"],
        "absorption": absorption, "covering": cover, "rotation": rot,
        "margin": margin, "catalyst": cat, "confidence": confidence, "score": score,
        "damage_percentile_20d": percentile, "windows_consistent": consistent,
    }

    return {
        "canonical_code": row["canonical_code"],
        "as_of_date": market.as_of_date,
        "close": price.get("close"),
        "adv20_shares": adv_shares,
        "adv20_value": price.get("adv20_value"),
        "drawdown_52w": low.get("drawdown_52w"),
        "price_percentile_252": low.get("price_percentile_252"),
        "rel_topix_20d": row["rel_topix_20d"],
        "rel_sector_20d": row["rel_sector_20d"],
        "visible_short_shares": now.get("visible_short_shares"),
        "visible_short_ratio": now.get("visible_short_ratio"),
        "visible_institution_count": int(now.get("visible_institution_count") or 0),
        "below_threshold_count": int(now.get("below_threshold_count") or 0),
        "largest_institution_ratio": now.get("largest_institution_ratio"),
        "concentration": now.get("concentration"),
        "ratio_change_1d": None,
        "ratio_change_5d": row["ratio_delta_5"],
        "ratio_change_20d": row["ratio_delta_20"],
        "shares_change_5d": row["shares_delta_5"],
        "shares_change_20d": row["shares_delta_20"],
        "pressure_adv20_5d": row["pressure_5"].get("pressure_adv20"),
        "pressure_adv20_20d": row["pressure_20"].get("pressure_adv20"),
        "visible_days_to_cover": days_to_cover,
        "entry_count_20d": counts["entry"],
        "reentry_count_20d": counts["reentry"],
        "reduction_count_20d": counts["reduction"],
        "threshold_exit_count_20d": counts["threshold_exit"],
        "low_position_score": low.get("score"),
        "short_pressure_score": row["pressure_20"].get("score"),
        "price_damage_score": absorption.get("price_damage_score"),
        "absorption_score": absorption.get("absorption_score"),
        "covering_score": cover.get("score"),
        "rotation_score": rot.get("score"),
        "catalyst_score": cat.get("score"),
        "risk_score": margin.get("score"),
        "data_confidence": confidence["confidence"],
        "behavior_score": score.get("score"),
        "monitor_priority": scoring.monitor_priority(score.get("score"), confidence["confidence"]),
        "primary_state": verdict["primary_state"],
        "flags_json": json.dumps(verdict["flags"], ensure_ascii=False),
        "components_json": json.dumps(components, ensure_ascii=False, default=str),
        "algorithm_version": SNAPSHOT_VERSION,
    }


def _min_mapping_confidence(events: Sequence[Mapping[str, Any]]) -> float | None:
    values = [_num(e.get("mapping_confidence")) for e in events]
    usable = [v for v in values if v is not None]
    return min(usable) if usable else None


def _last_report_age(events: Sequence[Mapping[str, Any]], trading_days: Sequence[str]) -> int | None:
    """最後の公開から何営業日経ったか。暦日で数えると連休で 3 日ずれる。"""

    published = [str(e.get("effective_trade_date") or "") for e in events]
    published = [p for p in published if p]
    if not published or not trading_days:
        return None
    last = max(published)
    try:
        return len(trading_days) - 1 - trading_days.index(last)
    except ValueError:
        # 効力日がカレンダーに無い（休場明けの丸めが未来に出た等）
        return sum(1 for day in trading_days if day > last)


def signal_id_for(code: str, signal_date: str, state: str) -> str:
    return hashlib.sha1(f"{code}|{signal_date}|{state}".encode("utf-8")).hexdigest()[:24]


def build_signals(
    snapshots: Sequence[Mapping[str, Any]],
    previous_states: Mapping[str, str],
    *, source_cutoff: str,
) -> list[dict[str, Any]]:
    """状態が変わった銘柄だけ信号として残す（検証の対象になる行）。"""

    out: list[dict[str, Any]] = []
    for snapshot in snapshots:
        state = str(snapshot.get("primary_state") or states.STATE_NO_SIGNAL)
        code = str(snapshot["canonical_code"])
        previous = previous_states.get(code)
        if previous == state or state == states.STATE_NO_SIGNAL:
            continue
        out.append({
            "signal_id": signal_id_for(code, str(snapshot["as_of_date"]), state),
            "canonical_code": code,
            "signal_date": snapshot["as_of_date"],
            "primary_state": state,
            "previous_state": previous,
            "behavior_score": snapshot.get("behavior_score"),
            "components_json": snapshot.get("components_json") or "{}",
            "evidence_json": json.dumps({
                "pressure_adv20_20d": snapshot.get("pressure_adv20_20d"),
                "visible_short_ratio": snapshot.get("visible_short_ratio"),
                "visible_institution_count": snapshot.get("visible_institution_count"),
                "rel_topix_20d": snapshot.get("rel_topix_20d"),
                "rel_sector_20d": snapshot.get("rel_sector_20d"),
                "flags": json.loads(snapshot.get("flags_json") or "[]"),
                "data_confidence": snapshot.get("data_confidence"),
            }, ensure_ascii=False),
            # 「この信号が使ってよい情報の締切」。検証はここより後の値動きだけを見る。
            "source_cutoff": source_cutoff,
            "algorithm_version": snapshot.get("algorithm_version") or SNAPSHOT_VERSION,
        })
    return out


__all__ = [
    "LOOKBACK_TRADING_DAYS",
    "MarketInputs",
    "SNAPSHOT_VERSION",
    "StockInputs",
    "build_raw_rows",
    "build_signals",
    "build_snapshots",
    "signal_id_for",
]
