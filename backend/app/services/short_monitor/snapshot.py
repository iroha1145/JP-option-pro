"""銘柄 × 営業日のスナップショットを全市場ぶん組み立てる。

載せるのは事実量（公開持仓・窓内の純変化・出来高比・価格の位置・信用環境）と、
そこから固定の規則で決まる 2 つの分類（近 20 日の動向・拥挤度）だけ。点数の
合成はしない（`states.py` の冒頭を参照）。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from app.services.radar.adjustment import adjust_series

from . import events as ev
from . import factors as fac
from . import reporters
from . import states
from .institutions import INSTITUTION_VERSION, InstitutionResolver

#: スナップショット全体の版。どれか 1 つでも変わったら作り直す対象になる。
SNAPSHOT_VERSION = "+".join((
    INSTITUTION_VERSION, ev.EVENT_VERSION, reporters.REPORTER_VERSION, fac.FACTOR_VERSION,
    states.STATE_VERSION,
))

LOOKBACK_TRADING_DAYS = 20
SHORT_WINDOW = 5
#: 回補が「価格が上がる前」か「上がってから」かを見る窓（主動 / 被動の判別）。
MID_WINDOW = 10
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
    regulation_known: bool = True
    trading_days_to_earnings: int | None = None
    breakout_confirmed: bool = False
    turnover_confirmed: bool = False


@dataclass
class MarketInputs:
    as_of_date: str
    trading_days: list[str]              # 昇順、as_of を含む
    topix_closes: Mapping[str, float]    # trade_date → 終値
    # 業種中位リターンの外部注入（再生用）。本番は渡さない —— 全市場を渡して
    # いるので構成銘柄から計算した値と同じ。再生は評価対象を「直近に公開
    # イベントがある銘柄」に絞るため、その部分集合から中位を取ると本番と
    # 別の業種基準になる（audit 指摘）。全市場から事前計算した値を渡す。
    sector_median_20d: Mapping[str, float] | None = None


def _window_date(trading_days: Sequence[str], back: int) -> str | None:
    """`back` 営業日前の日付。足りなければ None。"""

    if len(trading_days) <= back:
        return None
    return trading_days[-1 - back]


def _visible_at(
    events: Sequence[Mapping[str, Any]], cutoff: str, trading_days: Sequence[str]
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """その締切時点の（機関別状態, 可視合計）。営業日列で「古すぎる報告」を弾く。"""

    past = [day for day in trading_days if day <= cutoff]
    known = ev.last_known_as_of(events, published_cutoff=cutoff, trading_days=past)
    return known, ev.visible_totals(known)


def _count_events(
    events: Iterable[Mapping[str, Any]], *, since: str
) -> dict[str, int]:
    """行動イベントの窓内件数。

    訂正はデータの改訂であって新しい行動ではない —— `correction` として
    数えるだけで、增仓/减仓/再参入には入れない（入れると同じ行動が 2 回
    起きたことになる）。比率の読めない行（unknown）も行動としては数えない。
    """

    counts = {
        "entry": 0, "reentry": 0, "reduction": 0, "threshold_exit": 0,
        "increase": 0, "closed": 0, "correction": 0, "unknown": 0,
    }
    for event in events:
        # 効力日（公開の翌営業日）で数える。仓位日で数えると未来の情報を
        # 過去の窓に入れてしまう。
        if str(event.get("effective_trade_date") or "") < since:
            continue
        if event.get("correction_status") == ev.CORRECTION_REVISED:
            counts["correction"] += 1
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
        elif kind == ev.EVENT_UNKNOWN:
            counts["unknown"] += 1
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
        "return_10d": _returns(closes, MID_WINDOW),
        "return_20d": _returns(closes, LONG_WINDOW),
        "made_new_low": made_new_low,
        "broke_long_support": broke_support,
    }


def _benchmark_returns(topix_closes: Mapping[str, float], trading_days: Sequence[str]) -> dict[str, float | None]:
    series = [_num(topix_closes.get(day)) for day in trading_days]
    series = [value for value in series if value is not None and value > 0.0]
    return {
        "topix_5d": _returns(series, SHORT_WINDOW),
        "topix_10d": _returns(series, MID_WINDOW),
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
    since_5 = cutoff_5 or market.trading_days[0]

    rows: list[dict[str, Any]] = []
    for stock in stocks:
        price = _price_context(stock.bars)
        if not price.get("known"):
            continue

        known_now, now = _visible_at(stock.events, market.as_of_date, market.trading_days)
        # 窓内の変化は **可視合計の差ではなく** 同一連鎖の報告差の積み上げ。
        # 合計の差だと閾値割れ 1 件が「全株数の減少」に化ける（audit P0-4）。
        changes_5 = (
            ev.window_changes(stock.events, from_cutoff=cutoff_5, to_cutoff=market.as_of_date)
            if cutoff_5 else None
        )
        changes_20 = (
            ev.window_changes(stock.events, from_cutoff=cutoff_20, to_cutoff=market.as_of_date)
            if cutoff_20 else None
        )
        counts_20 = _count_events(stock.events, since=since_20)
        counts_5 = _count_events(stock.events, since=since_5)

        # informed 口径: 国内証券・集合名義を除いた報告主体だけの鎖。全鎖口径と
        # **並べて** 持つ（どちらか一方を正とはしない —— 検証で別々に測る）。
        classes = reporters.classify_events(stock.events)
        informed_events = [
            event for event in stock.events
            if reporters.is_informed(classes.get(str(event.get("legal_id") or "")))
        ]
        informed_known = {
            legal_id: state for legal_id, state in known_now.items()
            if reporters.is_informed(classes.get(legal_id))
        }
        informed_now = ev.visible_totals(informed_known)
        informed_changes_5 = (
            ev.window_changes(informed_events, from_cutoff=cutoff_5, to_cutoff=market.as_of_date)
            if (cutoff_5 and informed_events) else None
        )
        informed_changes_20 = (
            ev.window_changes(informed_events, from_cutoff=cutoff_20, to_cutoff=market.as_of_date)
            if (cutoff_20 and informed_events) else None
        )

        rows.append({
            "canonical_code": stock.canonical_code,
            "sector33_code": stock.sector33_code,
            "price": price,
            "known_now": known_now,
            "now": now,
            "changes_5": changes_5,
            "changes_20": changes_20,
            "counts": counts_20,
            "counts_5": counts_5,
            "stock": stock,
            "benchmarks": benchmarks,
            "classes": classes,
            "informed_now": informed_now,
            "informed_changes_5": informed_changes_5,
            "informed_changes_20": informed_changes_20,
            "informed_counts": _count_events(informed_events, since=since_20),
            "informed_counts_5": _count_events(informed_events, since=since_5),
            "parked_below_count": fac.parked_below_count(known_now),
        })
    return rows


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
    """全市場のスナップショット行。"""

    raw = build_raw_rows(stocks, market)
    if not raw:
        return []

    median_20 = market.sector_median_20d or _sector_medians(raw, "return_20d")
    return [_finalize(row, market, median_20) for row in raw]


def _rel(value: float | None, benchmark: float | None) -> float | None:
    a, b = _num(value), _num(benchmark)
    if a is None or b is None:
        return None
    return a - b


def _pressure(changes: Mapping[str, Any] | None, counts: Mapping[str, int], adv_shares: Any) -> dict[str, Any]:
    if not changes:
        return {"pressure_adv20": None, "known": False}
    return fac.short_pressure(
        shares_change=changes.get("shares_change"), adv20_shares=adv_shares,
        entries=counts["entry"], reentries=counts["reentry"],
    )


def _finalize(
    row: Mapping[str, Any], market: MarketInputs, sector_median_20d: Mapping[str, float]
) -> dict[str, Any]:
    price = row["price"]
    stock: StockInputs = row["stock"]
    now = row["now"]
    counts = row["counts"]
    adv_shares = price.get("adv20_shares")

    rel_topix_20 = _rel(price.get("return_20d"), row["benchmarks"].get("topix_20d"))
    rel_topix_10 = _rel(price.get("return_10d"), row["benchmarks"].get("topix_10d"))
    rel_sector_20 = _rel(price.get("return_20d"), sector_median_20d.get(row.get("sector33_code") or ""))

    changes_5 = row["changes_5"] or {}
    changes_20 = row["changes_20"] or {}
    # 5 日の変化に 20 日の参入件数を混ぜない（15 日前の再参入が 5 日分に化ける）。
    pressure_5 = _pressure(row["changes_5"], row["counts_5"], adv_shares)
    pressure_20 = _pressure(row["changes_20"], counts, adv_shares)
    # informed 口径（集合名義を除く）。鎖が 1 本も無ければ None（0 ではない）。
    pressure_informed_5 = _pressure(row.get("informed_changes_5"), row["informed_counts_5"], adv_shares)
    pressure_informed_20 = _pressure(row.get("informed_changes_20"), row["informed_counts"], adv_shares)

    low = fac.low_position(
        close=price.get("close"), high_52w=price.get("high_52w"),
        closes_252=price.get("closes_252") or [], ma200=price.get("ma200"),
    )
    margin = fac.margin_environment(
        margin_long=(stock.margin or {}).get("long_total"),
        margin_short=(stock.margin or {}).get("short_total"),
        adv20_shares=adv_shares,
        regulation_severity=stock.regulation_severity,
    )
    days_to_cover = fac.visible_days_to_cover(now.get("visible_short_shares"), adv_shares)
    combined_days_to_cover = fac.combined_visible_days_to_cover(
        now.get("visible_short_shares"), (stock.margin or {}).get("short_total"), adv_shares,
    )
    informed_now = row.get("informed_now") or {}
    informed_count = int(informed_now.get("visible_institution_count") or 0)
    classes = row.get("classes") or {}
    visible_count = int(now.get("visible_institution_count") or 0)

    last_report = _last_report_age(stock.events, market.trading_days)
    confidence = fac.data_confidence(
        # 全歴史の最小値ではなく「今の判定に効く範囲」の最小値。
        mapping_confidence=_current_mapping_confidence(
            row.get("known_now") or {}, stock.events,
            since=_window_date(market.trading_days, LONG_WINDOW) or market.trading_days[0],
        ),
        visible_institution_count=visible_count,
        days_since_last_report=last_report,
        bars_available=int(price.get("bars_available") or 0),
        below_threshold_count=int(now.get("below_threshold_count") or 0),
        has_correction=counts["correction"] > 0,
        adv20_value=price.get("adv20_value"),
        unknown_records=int(now.get("unknown_count") or 0) + int(counts.get("unknown") or 0),
        regulation_unknown=not stock.regulation_known,
    )

    verdict = states.classify({
        "ratio_change_20d": changes_20.get("ratio_change"),
        "ratio_change_5d": changes_5.get("ratio_change"),
        "visible_institution_count": visible_count,
        "visible_short_ratio": now.get("visible_short_ratio"),
        "informed_institution_count": informed_count,
        "parked_below_count": int(row.get("parked_below_count") or 0),
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
        "thin_liquidity": "thin_liquidity" in confidence["reasons"],
        "days_since_last_report": last_report,
    })

    components = {
        "crowding_level": verdict["crowding_level"],
        "days_since_last_report": last_report,
        "low_position": low, "pressure_5d": pressure_5, "pressure_20d": pressure_20,
        "margin": margin, "confidence": confidence,
        # 逐連鎖の報告差の内訳（純増減のほかに粗い増分・減分も残す）
        "window_changes_5d": row.get("changes_5"),
        "window_changes_20d": row.get("changes_20"),
        # informed 口径（集合名義を除いた報告主体）。全鎖口径と並べて持つ。
        # DB 列は増やさず components に載せる。
        "informed": {
            "reporter_version": reporters.REPORTER_VERSION,
            "institution_count": informed_count,
            "visible_short_ratio": informed_now.get("visible_short_ratio"),
            "visible_short_shares": informed_now.get("visible_short_shares"),
            "pressure_5d": pressure_informed_5,
            "pressure_20d": pressure_informed_20,
            "window_changes_5d": row.get("informed_changes_5"),
            "window_changes_20d": row.get("informed_changes_20"),
            "entry_count_20d": row["informed_counts"]["entry"],
            "reentry_count_20d": row["informed_counts"]["reentry"],
            "reduction_count_20d": row["informed_counts"]["reduction"],
        },
        "reporter_classes": reporters.class_counts(classes, (row.get("known_now") or {}).keys()),
        "parked_below_count": int(row.get("parked_below_count") or 0),
        "combined_visible_days_to_cover": combined_days_to_cover,
        "rel_topix_10d": rel_topix_10,
        # 突破・出来高の確認はレーダーが決める事実。ここでは読みを付けずに残す。
        "breakout_confirmed": bool(stock.breakout_confirmed),
        "turnover_confirmed": bool(stock.turnover_confirmed),
        "trading_days_to_earnings": stock.trading_days_to_earnings,
    }

    return {
        "canonical_code": row["canonical_code"],
        "as_of_date": market.as_of_date,
        "close": price.get("close"),
        "adv20_shares": adv_shares,
        "adv20_value": price.get("adv20_value"),
        "drawdown_52w": low.get("drawdown_52w"),
        "price_percentile_252": low.get("price_percentile_252"),
        "rel_topix_20d": rel_topix_20,
        "rel_sector_20d": rel_sector_20,
        "visible_short_shares": now.get("visible_short_shares"),
        "visible_short_ratio": now.get("visible_short_ratio"),
        # 公式ルール上「まだ報告義務中」の全機関の和（125 日の新鮮さ条件なし）。
        # 新鮮な部分集合（visible_*）とは別口径で、両方とも常に出す。
        "reported_in_scope_ratio": now.get("reported_in_scope_ratio"),
        "reported_in_scope_shares": now.get("reported_in_scope_shares"),
        "unknown_institution_count": int(now.get("unknown_count") or 0),
        "visible_institution_count": visible_count,
        "below_threshold_count": int(now.get("below_threshold_count") or 0),
        # 報告義務中の表示のまま古くなったもの。合計には入れないが、
        # 「閾値を割った」とは別の事象なので列を分ける。
        "stale_reporting_count": int(now.get("stale_reporting_count") or 0),
        "largest_institution_ratio": now.get("largest_institution_ratio"),
        "concentration": now.get("concentration"),
        "ratio_change_1d": None,
        "ratio_change_5d": changes_5.get("ratio_change"),
        "ratio_change_20d": changes_20.get("ratio_change"),
        "shares_change_5d": changes_5.get("shares_change"),
        "shares_change_20d": changes_20.get("shares_change"),
        "pressure_adv20_5d": pressure_5.get("pressure_adv20"),
        "pressure_adv20_20d": pressure_20.get("pressure_adv20"),
        "visible_days_to_cover": days_to_cover,
        "entry_count_20d": counts["entry"],
        "reentry_count_20d": counts["reentry"],
        "reduction_count_20d": counts["reduction"],
        "threshold_exit_count_20d": counts["threshold_exit"],
        # 点数の列は v4（sbs-v4 / sbf-v3）で廃止。列は残るが常に NULL。
        "low_position_score": None,
        "short_pressure_score": None,
        "price_damage_score": None,
        "absorption_score": None,
        "covering_score": None,
        "rotation_score": None,
        "catalyst_score": None,
        "risk_score": None,
        "behavior_score": None,
        "monitor_priority": None,
        "data_confidence": confidence["confidence"],
        "primary_state": verdict["primary_state"],
        "flags_json": json.dumps(verdict["flags"], ensure_ascii=False),
        "components_json": json.dumps(components, ensure_ascii=False, default=str),
        "algorithm_version": SNAPSHOT_VERSION,
    }


def _current_mapping_confidence(
    known: Mapping[str, Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
    *,
    since: str,
) -> float | None:
    """今の判定に効く範囲の対応づけ信頼度。

    現在の機関別状態と、窓内（効力日 >= since）の行動イベントだけを見る。
    全歴史の最小値を取ると、大昔の 1 件の曖昧表記が現在を永久に汚す。
    """

    values: list[float] = []
    for state in known.values():
        value = _num(state.get("mapping_confidence"))
        if value is not None:
            values.append(value)
    for event in events:
        if str(event.get("effective_trade_date") or "") < since:
            continue
        value = _num(event.get("mapping_confidence"))
        if value is not None:
            values.append(value)
    return min(values) if values else None


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
            "behavior_score": None,
            "components_json": snapshot.get("components_json") or "{}",
            "evidence_json": json.dumps({
                "ratio_change_20d": snapshot.get("ratio_change_20d"),
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
    "MID_WINDOW",
    "MarketInputs",
    "SNAPSHOT_VERSION",
    "StockInputs",
    "build_raw_rows",
    "build_signals",
    "build_snapshots",
    "signal_id_for",
]
