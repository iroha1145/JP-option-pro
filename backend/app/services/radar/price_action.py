"""純粋な価格行動（K線行为）分析 — OHLC のみ、出来高不使用。米国版の移植。

- スイング検出（フラクタル枢軸、確定足のみ = 先読みなし）
- 市場構造: HH/HL vs LH/LL
- ローソク足パターン: 吞没・ハンマー・流れ星・はらみ足
- 構造トラップ: Spring（假跌破回收）/ Upthrust（假突破）

表示ラベルは簡体中文（本製品の分析表示言語）。
"""

from __future__ import annotations

import math
from typing import Any, Sequence

PRICE_ACTION_VERSION = "jp-price-action-v1"

_STRUCTURE_SCORES = {
    "uptrend": 82.0,
    "uptrend_weak": 66.0,
    "hl_base": 62.0,
    "range": 50.0,
    "lh_pressure": 38.0,
    "downtrend": 24.0,
}

_STRUCTURE_LABELS = {
    "uptrend": "HH+HL 上升结构",
    "uptrend_weak": "高点抬升待确认",
    "hl_base": "低点抬升筑底",
    "range": "区间震荡",
    "lh_pressure": "高点压低",
    "downtrend": "LH+LL 下降结构",
}

_PATTERN_LABELS = {
    "bullish_engulfing": "看涨吞没",
    "bearish_engulfing": "看跌吞没",
    "hammer": "锤子线",
    "shooting_star": "射击之星",
    "inside_bar": "内包线",
}

_PATTERN_ADJUST = {
    "bullish_engulfing": 6.0,
    "bearish_engulfing": -6.0,
    "hammer": 6.0,
    "shooting_star": -6.0,
    "inside_bar": 0.0,
}


def _safe(value: Any, ndigits: int = 4) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, ndigits)


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _empty(status: str, label: str) -> dict[str, Any]:
    # データ不足時の score は None — 50 を「本物の中性」と混同させない。
    return {
        "version": PRICE_ACTION_VERSION,
        "status": status, "score": None,
        "structure": status, "structure_label": label,
        "swing_highs": [], "swing_lows": [],
        "resistance": None, "support": None,
        "resistance_dist_pct": None, "support_dist_pct": None,
        "patterns": [], "pattern_labels": [],
        "spring": False, "upthrust": False, "tags": [label],
    }


def find_swings(
    highs: Sequence[float], lows: Sequence[float], span: int = 3
) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """フラクタル枢軸。左側は厳密比較・右側はタイ許容（同値高値の連続で
    枢軸が全滅しないための Wilder 流）。末尾 span 本は未確定なので出ない。"""

    swing_highs: list[tuple[int, float]] = []
    swing_lows: list[tuple[int, float]] = []
    n = len(highs)
    for i in range(span, n - span):
        if highs[i] > max(highs[i - span:i]) and highs[i] >= max(highs[i + 1:i + span + 1]):
            swing_highs.append((i, highs[i]))
        if lows[i] < min(lows[i - span:i]) and lows[i] <= min(lows[i + 1:i + span + 1]):
            swing_lows.append((i, lows[i]))
    return swing_highs, swing_lows


def _structure_state(
    swing_highs: list[tuple[int, float]], swing_lows: list[tuple[int, float]]
) -> str:
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return "range"
    hh = swing_highs[-1][1] > swing_highs[-2][1]
    hl = swing_lows[-1][1] > swing_lows[-2][1]
    lh = swing_highs[-1][1] < swing_highs[-2][1]
    ll = swing_lows[-1][1] < swing_lows[-2][1]
    if hh and hl:
        return "uptrend"
    if lh and ll:
        return "downtrend"
    if hh:
        return "uptrend_weak"
    if hl:
        return "hl_base"
    if lh:
        return "lh_pressure"
    return "range"


def _detect_patterns(
    opens: Sequence[float], highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
    check_last: int = 3, extreme_window: int = 10,
) -> list[str]:
    n = len(closes)
    found: list[str] = []
    for i in range(max(1, n - check_last), n):
        o, h, l, c = opens[i], highs[i], lows[i], closes[i]
        po, pc = opens[i - 1], closes[i - 1]
        rng = h - l
        if rng <= 0:
            continue
        body = abs(c - o)
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l
        prev_body = abs(pc - po)

        if pc < po and c > o and c >= po and o <= pc and body > prev_body * 1.05:
            found.append("bullish_engulfing")
        elif pc > po and c < o and c <= po and o >= pc and body > prev_body * 1.05:
            found.append("bearish_engulfing")

        window_lo = min(lows[max(0, i - extreme_window):i + 1])
        window_hi = max(highs[max(0, i - extreme_window):i + 1])
        if body > 0 and lower_wick >= body * 2 and upper_wick <= body * 0.6 and l <= window_lo * 1.01:
            found.append("hammer")
        elif body > 0 and upper_wick >= body * 2 and lower_wick <= body * 0.6 and h >= window_hi * 0.99:
            found.append("shooting_star")

        if h < highs[i - 1] and l > lows[i - 1]:
            found.append("inside_bar")
    return list(dict.fromkeys(found))


def _detect_traps(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
    swing_highs: list[tuple[int, float]], swing_lows: list[tuple[int, float]],
    recent: int = 8,
) -> tuple[bool, bool]:
    n = len(closes)
    start = max(0, n - recent)
    spring = False
    upthrust = False
    for i in range(start, n):
        prior_lows = [price for idx, price in swing_lows if idx < i - 1]
        if prior_lows and not spring:
            level = prior_lows[-1]
            if lows[i] < level * 0.998 and closes[i] > level:
                spring = True
        prior_highs = [price for idx, price in swing_highs if idx < i - 1]
        if prior_highs and not upthrust:
            level = prior_highs[-1]
            if highs[i] > level * 1.002 and closes[i] < level:
                upthrust = True
    return spring, upthrust


def compute_price_action(
    series: dict[str, list], *, swing_span: int = 3, lookback: int = 120
) -> dict[str, Any]:
    """``series`` は features.clean_series 形式（当日を含む列で良い —
    スイングは末尾 span 本が構造的に未確定なので先読みは起きない）。"""

    closes = list(series.get("closes") or [])[-lookback:]
    if len(closes) < 40:
        return _empty("not_enough_data", "K线样本不足")
    opens = list(series["opens"])[-lookback:]
    highs = list(series["highs"])[-lookback:]
    lows = list(series["lows"])[-lookback:]
    last_close = closes[-1]
    if not last_close or last_close <= 0:
        return _empty("invalid_price", "价格异常")

    swing_highs, swing_lows = find_swings(highs, lows, swing_span)
    structure = _structure_state(swing_highs, swing_lows)
    structure_label = _STRUCTURE_LABELS[structure]
    score = _STRUCTURE_SCORES[structure]
    tags: list[str] = [structure_label] if structure != "range" else []

    patterns = _detect_patterns(opens, highs, lows, closes)
    pattern_adjust = 0.0
    for pattern in patterns:
        pattern_adjust += _PATTERN_ADJUST.get(pattern, 0.0)
        label = _PATTERN_LABELS.get(pattern)
        if label and pattern != "inside_bar":
            tags.append(label)
    if "inside_bar" in patterns:
        tags.append("内包线收缩")
    pattern_adjust = max(-10.0, min(10.0, pattern_adjust))

    spring, upthrust = _detect_traps(highs, lows, closes, swing_highs, swing_lows)
    trap_adjust = 0.0
    if spring:
        trap_adjust += 8.0
        tags.append("Spring 假跌破回收")
    if upthrust:
        trap_adjust -= 8.0
        tags.append("Upthrust 假突破")

    score = _clamp(score + pattern_adjust + trap_adjust)
    resistance = swing_highs[-1][1] if swing_highs else None
    support = swing_lows[-1][1] if swing_lows else None
    dates = list(series["dates"])[-lookback:]

    return {
        "version": PRICE_ACTION_VERSION,
        "status": "active",
        "score": round(score, 1),
        "structure": structure,
        "structure_label": structure_label,
        "swing_highs": [
            {"trade_date": dates[idx], "price": _safe(price)} for idx, price in swing_highs[-4:]
        ],
        "swing_lows": [
            {"trade_date": dates[idx], "price": _safe(price)} for idx, price in swing_lows[-4:]
        ],
        "resistance": _safe(resistance),
        "support": _safe(support),
        "resistance_dist_pct": _safe((resistance / last_close - 1) * 100, 2) if resistance else None,
        "support_dist_pct": _safe((support / last_close - 1) * 100, 2) if support else None,
        "patterns": patterns,
        "pattern_labels": [_PATTERN_LABELS[p] for p in patterns if p in _PATTERN_LABELS],
        "spring": spring,
        "upthrust": upthrust,
        "tags": list(dict.fromkeys(tags))[:4],
    }


__all__ = ["PRICE_ACTION_VERSION", "compute_price_action", "find_swings"]
