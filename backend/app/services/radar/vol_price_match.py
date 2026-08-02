"""量価一致（Wyckoff 努力対結果）分析 — 米国版 vol_price_match の移植。

米国版のドル建て成交額の代わりに **売買代金（円）** を使う。株価水準の
異なる銘柄間で生の出来高は比較できない、という原則は同じ。

出力は突破品質への調整量（±）と假突破リスクとして評分側に入る。
"""

from __future__ import annotations

import math
from statistics import median
from typing import Any, Sequence

VOL_PRICE_VERSION = "jp-vol-price-v1"


def _safe(value: Any, ndigits: int = 4) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, ndigits)


def _slope(values: Sequence[float]) -> float | None:
    size = len(values)
    if size < 3:
        return None
    x_mean = (size - 1) / 2
    y_mean = sum(values) / size
    denom = sum((idx - x_mean) ** 2 for idx in range(size))
    if denom <= 0:
        return None
    numer = sum((idx - x_mean) * (value - y_mean) for idx, value in enumerate(values))
    return numer / denom


def _empty(status: str, tag: str) -> dict[str, Any]:
    return {
        "version": VOL_PRICE_VERSION,
        "status": status, "setup_type": status, "setup_label": tag,
        "range_compression": None, "turnover_compression": None,
        "turnover_range_ratio": None, "clv_mean": None,
        "up_down_turnover_ratio": None, "obv_slope": None,
        "effort": None, "result": None, "effort_result_ratio": None,
        "breakout_quality_adjustment": 0.0,
        "false_breakout_risk": 0.0,
        "tags": [tag],
    }


def compute_vol_price_match(
    series: dict[str, list],
    *,
    recent_window: int = 10,
    baseline_window: int = 60,
    compression_threshold: float = 0.65,
    absorption_ratio_threshold: float = 1.25,
    vacuum_ratio_threshold: float = 0.70,
) -> dict[str, Any]:
    closes_all = list(series.get("closes") or [])
    opens_all = list(series.get("opens") or [])
    highs_all = list(series.get("highs") or [])
    lows_all = list(series.get("lows") or [])
    turnover_all = list(series.get("turnover") or [])

    # 欠測売買代金は「観測なし」— 0 埋めせず行ごと除外（vacuum 誤判定防止）。
    rows = [
        (o, h, l, c, t)
        for o, h, l, c, t in zip(opens_all, highs_all, lows_all, closes_all, turnover_all)
        if t is not None and t >= 0
    ]
    if len(rows) < baseline_window + 2:
        return _empty("not_enough_data", "量价样本不足")
    opens = [row[0] for row in rows]
    highs = [row[1] for row in rows]
    lows = [row[2] for row in rows]
    closes = [row[3] for row in rows]
    turnover = [row[4] for row in rows]

    tr_pct: list[float] = []
    for i in range(1, len(closes)):
        if closes[i] <= 0:
            continue
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        tr_pct.append(tr / closes[i])
    if len(tr_pct) < baseline_window:
        return _empty("not_enough_data", "量价样本不足")

    recent_tr = median(tr_pct[-recent_window:])
    baseline_tr = median(tr_pct[-baseline_window:])
    recent_turnover = median(turnover[-recent_window:])
    baseline_turnover = median(turnover[-baseline_window:])
    if baseline_tr <= 0 or baseline_turnover <= 0:
        return _empty("invalid_baseline", "量价基准异常")

    range_compression = recent_tr / baseline_tr
    turnover_compression = recent_turnover / baseline_turnover
    turnover_range_ratio = turnover_compression / max(range_compression, 1e-9)

    clv_values: list[float] = []
    for i in range(len(closes)):
        day_range = highs[i] - lows[i]
        if day_range > 0:
            clv_values.append((2 * closes[i] - highs[i] - lows[i]) / day_range)
    clv_mean = sum(clv_values[-recent_window:]) / max(1, len(clv_values[-recent_window:]))

    up_turnover = sum(
        turnover[i] for i in range(len(closes) - recent_window, len(closes)) if closes[i] > opens[i]
    )
    down_turnover = sum(
        turnover[i] for i in range(len(closes) - recent_window, len(closes)) if closes[i] < opens[i]
    )
    up_down_turnover_ratio = up_turnover / max(down_turnover, 1e-9)

    obv = 0.0
    obv_series: list[float] = []
    for i in range(len(closes)):
        if i > 0:
            if closes[i] > closes[i - 1]:
                obv += turnover[i]
            elif closes[i] < closes[i - 1]:
                obv -= turnover[i]
        obv_series.append(obv)
    obv_slope_raw = _slope(obv_series[-recent_window:])
    obv_scale = max(median(turnover[-recent_window:]), 1.0)
    normalized_obv_slope = (obv_slope_raw / obv_scale) if obv_slope_raw is not None else 0.0

    base_close = closes[-recent_window] if closes[-recent_window] else None
    recent_abs_return = abs(closes[-1] / base_close - 1) if base_close else 0.0
    effort = recent_turnover / max(baseline_turnover, 1e-9)
    result = recent_abs_return / max(baseline_tr, 1e-9)
    effort_result_ratio = effort / max(result, 1e-9)

    tags: list[str] = []
    breakout_adjustment = 0.0
    false_breakout_risk = 0.0

    if range_compression > compression_threshold:
        setup_type = "no_compression"
        setup_label = "未收缩"
        tags.append("未明显收缩")
        if effort <= 0.8 and result > 1.25:
            tags.append("真空上涨")
            false_breakout_risk += 6
    elif turnover_range_ratio >= absorption_ratio_threshold:
        tags.append("吸收型收缩")
        bullish = clv_mean > 0.15 and up_down_turnover_ratio > 1.2 and normalized_obv_slope > 0
        bearish = clv_mean < -0.15 and up_down_turnover_ratio < 0.8 and normalized_obv_slope < 0
        if bullish:
            setup_type = "absorption_bullish"
            setup_label = "多头吸收"
            tags.append("多头吸收")
            breakout_adjustment = 12.0
            false_breakout_risk = -3.0
        elif bearish:
            setup_type = "absorption_bearish"
            setup_label = "空头吸收"
            tags.append("空头吸收")
            breakout_adjustment = -8.0
            false_breakout_risk = 10.0
        else:
            setup_type = "absorption_neutral"
            setup_label = "吸收未确认"
            tags.append("方向未确认")
            breakout_adjustment = 3.0
            false_breakout_risk = 3.0
    elif turnover_range_ratio <= vacuum_ratio_threshold:
        setup_type = "vacuum"
        setup_label = "真空型收缩"
        tags.extend(["真空型收缩", "假突破风险高"])
        breakout_adjustment = -10.0
        false_breakout_risk = 12.0
    else:
        setup_type = "balanced_compression"
        setup_label = "平衡收缩"
        tags.append("平衡收缩")
        breakout_adjustment = 2.0

    if effort > 1.3 and result > 1.0:
        tags.append("高努力高结果")
    elif effort > 1.3 and result <= 1.0:
        tags.append("高换手吸收")
    elif effort <= 0.8 and result > 1.0:
        tags.append("低量真空移动")
        false_breakout_risk += 4

    return {
        "version": VOL_PRICE_VERSION,
        "status": "active",
        "setup_type": setup_type,
        "setup_label": setup_label,
        "range_compression": _safe(range_compression),
        "turnover_compression": _safe(turnover_compression),
        "turnover_range_ratio": _safe(turnover_range_ratio),
        "clv_mean": _safe(clv_mean),
        "up_down_turnover_ratio": _safe(up_down_turnover_ratio),
        "obv_slope": _safe(normalized_obv_slope),
        "effort": _safe(effort),
        "result": _safe(result),
        "effort_result_ratio": _safe(effort_result_ratio),
        "breakout_quality_adjustment": round(breakout_adjustment, 1),
        "false_breakout_risk": round(false_breakout_risk, 1),
        "tags": list(dict.fromkeys(tags))[:5],
    }


__all__ = ["VOL_PRICE_VERSION", "compute_vol_price_match"]
