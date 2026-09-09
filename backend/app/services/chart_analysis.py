"""Japan-site ChartAnalysisBundle assembler.

Ported from option-pro technical/chart_analysis.py without pandas, New York
session logic, US-index relative strength, VWAP, or opening-range overlays.
Indicator series reuse the same pure-Python formulas; relative strength is
TOPIX (0000).
"""

from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from app.services.radar.base_detector import DETECTOR_VERSION as BASE_VERSION
from app.services.radar.base_detector import detect_base
from app.services.radar.features import clean_series, series_excluding_last
from app.services.radar.price_action import PRICE_ACTION_VERSION, compute_price_action
from app.services.radar.technicals import TECHNICALS_VERSION, compute_technicals
from app.services.radar.vol_price_match import compute_vol_price_match

BUNDLE_VERSION = "jp-chart-analysis-v1"
LAYER_REGISTRY_VERSION = "jp-layer-registry-v1"
FINGERPRINT_ALGORITHM = "sha256-bar-ohlcv-v1"
TOPIX_INDEX_CODE = "0000"

MACD_WARMUP = 26 + 9


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _safe(value: Any, ndigits: int = 4) -> float | None:
    number = _finite_number(value)
    if number is None:
        return None
    return round(number, ndigits)


def _fmt6(value: Any) -> str:
    scaled = int(float(value) * 1_000_000 + (0.5 if float(value) >= 0 else -0.5))
    return f"{scaled / 1_000_000:.6f}"


def _date_epoch(day: str) -> int:
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp())


def _ema_series(values: Sequence[float], period: int) -> list[float]:
    alpha = 2.0 / (period + 1.0)
    result: list[float] = []
    ema = values[0]
    for value in values:
        ema = value * alpha + ema * (1.0 - alpha)
        result.append(ema)
    return result


def sma_series(closes: Sequence[float], window: int) -> list[float | None]:
    n = len(closes)
    out: list[float | None] = [None] * n
    if window < 1 or n < window:
        return out
    acc = 0.0
    for i, value in enumerate(closes):
        acc += value
        if i >= window:
            acc -= closes[i - window]
        if i >= window - 1:
            out[i] = _safe(acc / window)
    return out


def rsi_series(closes: Sequence[float], period: int = 14) -> list[float | None]:
    n = len(closes)
    out: list[float | None] = [None] * n
    if n < period + 1:
        return out
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        delta = closes[i] - closes[i - 1]
        if delta > 0:
            gains += delta
        else:
            losses -= delta
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss <= 0:
        out[period] = 100.0 if avg_gain > 0 else 50.0
    else:
        out[period] = _safe(100.0 - 100.0 / (1.0 + avg_gain / avg_loss), 2)
    for i in range(period + 1, n):
        delta = closes[i] - closes[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(delta, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-delta, 0.0)) / period
        if avg_loss <= 0:
            out[i] = 100.0 if avg_gain > 0 else 50.0
        else:
            out[i] = _safe(100.0 - 100.0 / (1.0 + avg_gain / avg_loss), 2)
    return out


def macd_series(closes: Sequence[float]) -> dict[str, list[float | None]]:
    n = len(closes)
    empty = [None] * n
    if n < 40:
        return {"macd": empty, "signal": empty[:], "histogram": empty[:]}
    fast = _ema_series(closes, 12)
    slow = _ema_series(closes, 26)
    macd_line = [f - s for f, s in zip(fast, slow)]
    signal = _ema_series(macd_line, 9)
    histogram = [m - s for m, s in zip(macd_line, signal)]

    def masked(values: Sequence[float]) -> list[float | None]:
        return [None if i < MACD_WARMUP else _safe(value) for i, value in enumerate(values)]

    return {
        "macd": masked(macd_line),
        "signal": masked(signal),
        "histogram": masked(histogram),
    }


def range_position_series(
    closes: Sequence[float], highs: Sequence[float], lows: Sequence[float], window: int = 60
) -> list[float | None]:
    n = len(closes)
    out: list[float | None] = [None] * n
    if n < window:
        return out
    for i in range(window - 1, n):
        window_high = max(highs[i - window + 1 : i + 1])
        window_low = min(lows[i - window + 1 : i + 1])
        span = window_high - window_low
        out[i] = _safe((closes[i] - window_low) / span if span > 0 else 0.5)
    return out


def compute_display_priority(
    shape_quality: float,
    volume_confirmation: float,
    trend_alignment: float,
    recency: float,
    consensus: float,
) -> float:
    value = (
        0.55 * _clamp01(shape_quality)
        + 0.15 * _clamp01(volume_confirmation)
        + 0.15 * _clamp01(trend_alignment)
        + 0.10 * _clamp01(recency)
        + 0.05 * _clamp01(consensus)
    )
    return round(_clamp01(value), 4)


def volume_confirmation_from_vol_price(vol_price: Mapping[str, Any] | None) -> float:
    if not vol_price:
        return 0.5
    parts: list[float] = []
    setup = f"{vol_price.get('setup_type') or ''} {vol_price.get('setup_label') or ''}".lower()
    if "absor" in setup or "吸收" in setup:
        parts.append(0.85)
    elif "vacuum" in setup or "真空" in setup:
        parts.append(0.25)
    obv = _finite_number(vol_price.get("obv_slope"))
    if obv is not None:
        parts.append(_clamp01(0.5 + max(-0.5, min(0.5, obv * 40.0))))
    clv = _finite_number(vol_price.get("clv_mean"))
    if clv is not None:
        parts.append(_clamp01((clv + 1.0) / 2.0))
    bqa = _finite_number(vol_price.get("breakout_quality_adjustment"))
    if bqa is not None:
        if abs(bqa) <= 1:
            parts.append(_clamp01(0.5 + bqa / 2.0))
        else:
            parts.append(_clamp01(0.5 + max(-0.5, min(0.5, bqa / 20.0))))
    fbr = _finite_number(vol_price.get("false_breakout_risk"))
    if fbr is not None:
        risk = fbr / 100.0 if fbr > 1.0 else fbr
        parts.append(_clamp01(1.0 - risk))
    if not parts:
        return 0.5
    return round(sum(parts) / len(parts), 4)


def trend_alignment_from_technicals(technicals: Mapping[str, Any] | None) -> float:
    technicals = technicals or {}
    parts: list[float] = []
    slope = _finite_number(technicals.get("ma50_slope_pct_21d"))
    if slope is not None:
        parts.append(_clamp01(0.5 + max(-0.5, min(0.5, slope / 10.0))))
    macd = technicals.get("macd") if isinstance(technicals.get("macd"), Mapping) else {}
    hist = _finite_number((macd or {}).get("histogram") or (macd or {}).get("direction_pct"))
    if hist is not None:
        parts.append(_clamp01(0.5 + max(-0.5, min(0.5, hist / 100.0 if abs(hist) > 1 else hist))))
    te = _finite_number(technicals.get("trend_efficiency_63d"))
    if te is not None:
        parts.append(_clamp01(te if te <= 1 else te / 100.0))
    if not parts:
        return 0.5
    return round(sum(parts) / len(parts), 4)


def canonical_bar_payload(series: Mapping[str, list]) -> str:
    closes = list(series.get("closes") or [])
    n = len(closes)
    times = list(series.get("times") or [0] * n)
    opens = list(series.get("opens") or closes)
    highs = list(series.get("highs") or closes)
    lows = list(series.get("lows") or closes)
    volumes = list(series.get("volumes") or [0.0] * n)
    lines: list[str] = []
    for i in range(n):
        lines.append(
            f"{int(times[i] if i < len(times) else 0)}|"
            f"{_fmt6(opens[i] if i < len(opens) else closes[i])}|"
            f"{_fmt6(highs[i] if i < len(highs) else closes[i])}|"
            f"{_fmt6(lows[i] if i < len(lows) else closes[i])}|"
            f"{_fmt6(closes[i])}|"
            f"{_fmt6(volumes[i] if i < len(volumes) else 0.0)}|"
            f"0|0"
        )
    return "\n".join(lines)


def bar_fingerprint(series: Mapping[str, list]) -> str:
    return hashlib.sha256(canonical_bar_payload(series).encode("utf-8")).hexdigest()


def fingerprint_meta(series: Mapping[str, list]) -> dict[str, Any]:
    dates = list(series.get("dates") or [])
    return {
        "fingerprintAlgorithm": FINGERPRINT_ALGORITHM,
        "barFingerprint": bar_fingerprint(series),
        "barCount": len(series.get("closes") or []),
        "firstBarDate": dates[0] if dates else None,
        "lastBarDate": dates[-1] if dates else None,
    }


def _overlay(
    *,
    overlay_id: str,
    source_id: str,
    algorithm_version: str,
    group: str,
    kind: str,
    geometry: Mapping[str, Any],
    status: str,
    direction: str,
    shape_quality: float,
    display_priority: float,
    evidence: Mapping[str, Any],
    formation_start: str,
    formation_end: str,
    data_through: str,
    label: str,
    detail: str,
) -> dict[str, Any]:
    return {
        "id": overlay_id,
        "sourceId": source_id,
        "algorithmVersion": algorithm_version,
        "group": group,
        "kind": kind,
        "geometry": dict(geometry),
        "status": status,
        "direction": direction,
        "shapeQuality": round(float(shape_quality), 4),
        "displayPriority": round(float(display_priority), 4),
        "evidence": dict(evidence),
        "formationStart": formation_start,
        "formationEnd": formation_end,
        "dataThrough": data_through,
        "label": label,
        "detail": detail,
    }


def consecutive_swing_labels(points: Sequence[Mapping[str, Any]], *, role: str) -> list[str]:
    indexed = list(enumerate(points))
    indexed.sort(key=lambda item: (str(item[1].get("trade_date") or ""), float(item[1].get("price") or 0), item[0]))
    labels = [""] * len(points)
    prev: float | None = None
    for original_index, point in indexed:
        try:
            price = float(point.get("price"))
        except (TypeError, ValueError):
            labels[original_index] = "H" if role == "high" else "L"
            continue
        if prev is None:
            labels[original_index] = "H" if role == "high" else "L"
        elif role == "high":
            labels[original_index] = "HH" if price >= prev else "LH"
        else:
            labels[original_index] = "HL" if price >= prev else "LL"
        prev = price
    return labels


def _warmup_len(values: Sequence[float | None]) -> int:
    count = 0
    for value in values:
        if value is not None:
            break
        count += 1
    return count


def _offset_series(values: Sequence[float | None]) -> tuple[int, list[float | None]]:
    start = _warmup_len(values)
    if start >= len(values):
        return 0, []
    return start, list(values[start:])


def _pane(pane_id: str, label: str, kind: str, values: Mapping[str, Sequence[float | None]]) -> dict[str, Any]:
    arrays = {key: list(series) for key, series in values.items()}
    length = max((len(series) for series in arrays.values()), default=0)
    start = min((_warmup_len(series) for series in arrays.values()), default=0)
    if start >= length:
        start = 0
    return {
        "id": pane_id,
        "label": label,
        "kind": kind,
        "startIndex": start,
        "values": {key: series[start:] for key, series in arrays.items()},
    }


def _volume_series(series: Mapping[str, list]) -> dict[str, list[float | None]]:
    closes = list(series.get("closes") or [])
    highs = list(series.get("highs") or [])
    lows = list(series.get("lows") or [])
    volumes = list(series.get("volumes") or [0.0] * len(closes))
    n = len(closes)
    obv: list[float | None] = [None] * n
    clv: list[float | None] = [None] * n
    running = 0.0
    for i in range(n):
        vol = float(volumes[i] if i < len(volumes) else 0.0)
        if i > 0:
            if closes[i] > closes[i - 1]:
                running += vol
            elif closes[i] < closes[i - 1]:
                running -= vol
        obv[i] = round(running, 4)
        span = highs[i] - lows[i] if i < len(highs) and i < len(lows) else 0.0
        if span > 0:
            clv[i] = round((2 * closes[i] - highs[i] - lows[i]) / span, 4)
    return {"obv": obv, "clv": clv}


def _align_index_closes(
    dates: Sequence[str],
    index_closes: Sequence[float | None] | Mapping[str, float] | None,
) -> list[float | None] | None:
    if index_closes is None:
        return None
    if isinstance(index_closes, Mapping):
        out: list[float | None] = []
        for day in dates:
            try:
                number = float(index_closes[day]) if day in index_closes and index_closes[day] is not None else None
            except (TypeError, ValueError, KeyError):
                number = None
            out.append(number if number is not None and number > 0 else None)
        return out
    values = list(index_closes)
    if len(values) != len(dates):
        return None
    aligned: list[float | None] = []
    for value in values:
        try:
            number = float(value) if value is not None else None
        except (TypeError, ValueError):
            number = None
        aligned.append(number if number is not None and number > 0 else None)
    return aligned


def _indicator_panes(
    series: Mapping[str, list],
    *,
    topix_closes: Sequence[float | None] | Mapping[str, float] | None,
    dates: Sequence[str],
) -> list[dict[str, Any]]:
    closes = list(series.get("closes") or [])
    highs = list(series.get("highs") or [])
    lows = list(series.get("lows") or [])
    vol = _volume_series(series)
    macd = macd_series(closes)
    aligned = _align_index_closes(dates, topix_closes)
    rs: list[float | None] = [None] * len(closes)
    if aligned is not None:
        base_stock: float | None = None
        base_index: float | None = None
        for i, (price, index) in enumerate(zip(closes, aligned)):
            if price is None or index is None or price <= 0 or index <= 0:
                continue
            if base_stock is None or base_index is None:
                base_stock = float(price)
                base_index = float(index)
                rs[i] = 100.0
                continue
            rs[i] = round(100.0 * (float(price) / base_stock) / (float(index) / base_index), 6)
    panes = [
        _pane("rsi", "RSI", "rsi", {"rsi": rsi_series(closes)}),
        _pane("macd", "MACD", "macd", macd),
        _pane("obv", "OBV", "obv", {"obv": vol["obv"]}),
        _pane("clv", "CLV", "clv", {"clv": vol["clv"]}),
        _pane(
            "range_persistence",
            "60日区间位置",
            "range",
            {"position": range_position_series(closes, highs, lows)},
        ),
    ]
    if any(value is not None for value in rs):
        panes.append(_pane("topix_rs", "TOPIX 相对强度", "rs", {"rs": rs}))
    return panes


def _ma_overlays(series: Mapping[str, list], data_through: str) -> list[dict[str, Any]]:
    closes = list(series.get("closes") or [])
    dates = list(series.get("dates") or [])
    overlays = []
    for window, layer_id in ((20, "ma20"), (50, "ma50"), (200, "ma200")):
        start, values = _offset_series(sma_series(closes, window))
        overlays.append(
            _overlay(
                overlay_id=layer_id,
                source_id="indicators",
                algorithm_version=TECHNICALS_VERSION,
                group="price",
                kind="ma",
                geometry={
                    "type": "series",
                    "window": window,
                    "values": values,
                    "startIndex": start,
                    "styleHint": "auto-pale",
                },
                status="forming",
                direction="neutral",
                shape_quality=1.0,
                display_priority=0.2,
                evidence={
                    "sources": ["indicators"],
                    "shapeQuality": 1.0,
                    "volumeConfirmation": 0.5,
                    "trendAlignment": 0.5,
                    "recency": 1.0,
                    "consensus": 1.0,
                },
                formation_start=dates[0] if dates else data_through,
                formation_end=data_through,
                data_through=data_through,
                label=f"MA{window}",
                detail="same-series moving average",
            )
        )
    return overlays


def _base_state_from_close(base: Mapping[str, Any] | None, close: float | None) -> dict[str, Any] | None:
    if not base or close is None:
        return None
    resistance_high = _finite_number(base.get("resistance_high"))
    resistance_low = _finite_number(base.get("resistance_low"))
    support_low = _finite_number(base.get("support_low"))
    buffer = _finite_number(base.get("break_buffer")) or 0.0
    if resistance_high is not None and close > resistance_high + buffer:
        status = "breakout"
    elif support_low is not None and close < support_low:
        status = "below_support"
    elif resistance_low is not None and close >= resistance_low:
        status = "at_resistance"
    else:
        status = "in_base"
    return {"status": status}


def _base_overlays(
    base: Mapping[str, Any] | None,
    base_state: Mapping[str, Any] | None,
    data_through: str,
    *,
    volume_confirmation: float,
    trend_alignment: float,
) -> list[dict[str, Any]]:
    if not base:
        return []
    start = str(base.get("base_start") or data_through)
    end = str(base.get("base_end") or data_through)
    status_map = {
        "breakout": "broken_up",
        "failed": "broken_down",
        "at_resistance": "testing",
        "below_support": "testing",
        "in_base": "forming",
    }
    live = (base_state or {}).get("status") or "in_base"
    status = status_map.get(str(live), "forming")
    quality = float(base.get("quality") or 0.0)
    evidence = {
        "shapeQuality": quality,
        "volumeConfirmation": round(float(volume_confirmation), 4),
        "trendAlignment": round(float(trend_alignment), 4),
        "recency": 0.6,
        "consensus": 1.0,
        "sources": ["base_structure"],
    }
    geometry = {
        "type": "band",
        "resistanceHigh": base.get("resistance_high"),
        "resistanceLow": base.get("resistance_low"),
        "supportLow": base.get("support_low"),
        "supportHigh": base.get("support_high"),
        "pivot": base.get("pivot_price"),
        "invalidation": base.get("invalidation_price"),
        "breakBuffer": base.get("break_buffer"),
        "styleHint": "auto-pale",
    }
    return [
        _overlay(
            overlay_id=f"base:{base.get('pivot_id') or start}",
            source_id="base_structure",
            algorithm_version=str(base.get("detector_version") or BASE_VERSION),
            group="price",
            kind="box",
            geometry=geometry,
            status=status,
            direction="neutral",
            shape_quality=quality,
            display_priority=compute_display_priority(quality, volume_confirmation, trend_alignment, 0.6, 1.0),
            evidence=evidence,
            formation_start=start,
            formation_end=end,
            data_through=data_through,
            label="整理区",
            detail="box overlays come only from base_structure",
        ),
        _overlay(
            overlay_id=f"pivot:{base.get('pivot_id') or start}",
            source_id="base_structure",
            algorithm_version=str(base.get("detector_version") or BASE_VERSION),
            group="price",
            kind="pivot",
            geometry={
                "type": "levels",
                "pivot": base.get("pivot_price"),
                "invalidation": base.get("invalidation_price"),
                "styleHint": "auto-pale",
            },
            status=status,
            direction="neutral",
            shape_quality=quality,
            display_priority=compute_display_priority(quality, volume_confirmation, trend_alignment, 0.6, 1.0),
            evidence=evidence,
            formation_start=start,
            formation_end=end,
            data_through=data_through,
            label="pivot/invalidation",
            detail="not a probability",
        ),
    ]


def _price_action_overlays(
    price_action: Mapping[str, Any],
    series: Mapping[str, list],
    data_through: str,
) -> list[dict[str, Any]]:
    overlays: list[dict[str, Any]] = []
    dates: list[str] = list(series.get("dates") or [])
    highs = list(price_action.get("swing_highs") or [])
    lows = list(price_action.get("swing_lows") or [])
    high_labels = consecutive_swing_labels(highs, role="high")
    low_labels = consecutive_swing_labels(lows, role="low")
    for point, label in zip(highs, high_labels):
        day = point.get("trade_date") or data_through
        overlays.append(
            _overlay(
                overlay_id=f"swing-h:{day}:{point.get('price')}",
                source_id="price_action",
                algorithm_version=PRICE_ACTION_VERSION,
                group="price",
                kind="swing",
                geometry={
                    "type": "point",
                    "anchors": [{"time": f"{day}T00:00:00+00:00", "barKey": day, "price": point.get("price")}],
                    "role": "high",
                    "styleHint": "auto-pale",
                },
                status="forming",
                direction="bearish",
                shape_quality=0.6,
                display_priority=0.4,
                evidence={"sources": ["price_action"], "shapeQuality": 0.6, "volumeConfirmation": 0.5, "trendAlignment": 0.5, "recency": 0.7, "consensus": 1.0},
                formation_start=day,
                formation_end=day,
                data_through=data_through,
                label=label,
                detail="confirmed fractal swing",
            )
        )
    for point, label in zip(lows, low_labels):
        day = point.get("trade_date") or data_through
        overlays.append(
            _overlay(
                overlay_id=f"swing-l:{day}:{point.get('price')}",
                source_id="price_action",
                algorithm_version=PRICE_ACTION_VERSION,
                group="price",
                kind="swing",
                geometry={
                    "type": "point",
                    "anchors": [{"time": f"{day}T00:00:00+00:00", "barKey": day, "price": point.get("price")}],
                    "role": "low",
                    "styleHint": "auto-pale",
                },
                status="forming",
                direction="bullish",
                shape_quality=0.6,
                display_priority=0.4,
                evidence={"sources": ["price_action"], "shapeQuality": 0.6, "volumeConfirmation": 0.5, "trendAlignment": 0.5, "recency": 0.7, "consensus": 1.0},
                formation_start=day,
                formation_end=day,
                data_through=data_through,
                label=label,
                detail="confirmed fractal swing",
            )
        )
    if price_action.get("resistance") is not None:
        overlays.append(
            _overlay(
                overlay_id="sr:resistance",
                source_id="price_action",
                algorithm_version=PRICE_ACTION_VERSION,
                group="price",
                kind="level",
                geometry={"type": "level", "price": price_action.get("resistance"), "role": "resistance", "styleHint": "auto-pale"},
                status="forming",
                direction="bearish",
                shape_quality=0.55,
                display_priority=0.35,
                evidence={"sources": ["price_action"], "shapeQuality": 0.55, "volumeConfirmation": 0.5, "trendAlignment": 0.5, "recency": 0.6, "consensus": 1.0},
                formation_start=data_through,
                formation_end=data_through,
                data_through=data_through,
                label="最近阻力",
                detail="nearest confirmed swing high",
            )
        )
    if price_action.get("support") is not None:
        overlays.append(
            _overlay(
                overlay_id="sr:support",
                source_id="price_action",
                algorithm_version=PRICE_ACTION_VERSION,
                group="price",
                kind="level",
                geometry={"type": "level", "price": price_action.get("support"), "role": "support", "styleHint": "auto-pale"},
                status="forming",
                direction="bullish",
                shape_quality=0.55,
                display_priority=0.35,
                evidence={"sources": ["price_action"], "shapeQuality": 0.55, "volumeConfirmation": 0.5, "trendAlignment": 0.5, "recency": 0.6, "consensus": 1.0},
                formation_start=data_through,
                formation_end=data_through,
                data_through=data_through,
                label="最近支撑",
                detail="nearest confirmed swing low",
            )
        )
    for name in price_action.get("patterns") or []:
        if not name:
            continue
        day = dates[-1] if dates else data_through
        price = series.get("closes", [None])[-1] if series.get("closes") else None
        if price is None:
            continue
        overlays.append(
            _overlay(
                overlay_id=f"candle:{name}:{day}",
                source_id="price_action",
                algorithm_version=PRICE_ACTION_VERSION,
                group="event",
                kind="candle",
                geometry={
                    "type": "point",
                    "anchors": [{"time": f"{day}T00:00:00+00:00", "barKey": day, "price": round(float(price), 4)}],
                    "pattern": name,
                    "barKey": day,
                    "styleHint": "event",
                },
                status="forming",
                direction="bullish" if "bull" in str(name) or name == "hammer" else ("bearish" if "bear" in str(name) or name == "shooting_star" else "neutral"),
                shape_quality=0.5,
                display_priority=0.45,
                evidence={"sources": ["price_action"], "shapeQuality": 0.5, "volumeConfirmation": 0.5, "trendAlignment": 0.5, "recency": 0.9, "consensus": 1.0},
                formation_start=day,
                formation_end=day,
                data_through=data_through,
                label=str(name),
                detail="exact barKey event",
            )
        )
    return overlays


def _vol_price_overlays(vol_price: Mapping[str, Any], data_through: str) -> list[dict[str, Any]]:
    if not vol_price or vol_price.get("status") != "active":
        return []
    setup = str(vol_price.get("setup_type") or "unknown")
    label = str(vol_price.get("setup_label") or setup)
    return [
        _overlay(
            overlay_id=f"volprice:{setup}:{data_through}",
            source_id="vol_price_match",
            algorithm_version="vol-price-match",
            group="event",
            kind="volume_setup",
            geometry={"type": "summary", "window": 10, "styleHint": "summary"},
            status="forming",
            direction="bullish" if "bull" in setup or "吸收" in label else ("bearish" if "bear" in setup or setup == "vacuum" or "真空" in label else "neutral"),
            shape_quality=0.55,
            display_priority=0.4,
            evidence={
                "shapeQuality": 0.55,
                "volumeConfirmation": 0.7,
                "trendAlignment": 0.5,
                "recency": 1.0,
                "consensus": 1.0,
                "sources": ["vol_price_match"],
                "effort": vol_price.get("effort"),
                "result": vol_price.get("result"),
                "obvSlope": vol_price.get("obv_slope"),
                "clvMean": vol_price.get("clv_mean"),
            },
            formation_start=data_through,
            formation_end=data_through,
            data_through=data_through,
            label=label,
            detail="last 10-day volume/price window; not a win rate",
        )
    ]


def _breakout_overlays(
    base: Mapping[str, Any] | None,
    base_state: Mapping[str, Any] | None,
    data_through: str,
    *,
    volume_confirmation: float,
    trend_alignment: float,
) -> list[dict[str, Any]]:
    if not base or not base_state:
        return []
    live = str(base_state.get("status") or "")
    status_map = {
        "breakout": "triggered",
        "failed": "failed",
        "at_resistance": "testing",
        "in_base": "forming",
        "below_support": "failed",
    }
    status = status_map.get(live, "forming")
    return [
        _overlay(
            overlay_id=f"breakout:{base.get('pivot_id') or data_through}",
            source_id="breakouts",
            algorithm_version="daily-base-breakout",
            group="event",
            kind="breakout",
            geometry={
                "type": "levels",
                "pivot": base.get("pivot_price"),
                "breakBuffer": base.get("break_buffer"),
                "invalidation": base.get("invalidation_price"),
                "styleHint": "emphasis" if status in {"triggered", "confirmed"} else "auto-pale",
            },
            status=status,
            direction="bullish" if status in {"triggered", "confirmed", "retest"} else ("bearish" if status == "failed" else "neutral"),
            shape_quality=float(base.get("quality") or 0.5),
            display_priority=compute_display_priority(
                float(base.get("quality") or 0.5),
                volume_confirmation,
                trend_alignment,
                0.7,
                1.0,
            ),
            evidence={
                "shapeQuality": float(base.get("quality") or 0.5),
                "volumeConfirmation": round(float(volume_confirmation), 4),
                "trendAlignment": round(float(trend_alignment), 4),
                "recency": 0.7,
                "consensus": 1.0,
                "sources": ["base_structure"],
            },
            formation_start=str(base.get("base_start") or data_through),
            formation_end=data_through,
            data_through=data_through,
            label=f"breakout:{status}",
            detail="daily pivot trigger / buffer / failed",
        )
    ]


def series_from_jp_bars(bars: Sequence[Mapping[str, Any]], *, min_bars: int = 30) -> dict[str, list] | None:
    series = clean_series(bars, min_bars=min_bars)
    if series is None:
        return None
    by_date = {str(bar.get("trade_date")): bar for bar in bars}
    volumes: list[float] = []
    times: list[int] = []
    for day in series["dates"]:
        bar = by_date.get(str(day), {})
        volume = bar.get("volume")
        if volume is None:
            volume = bar.get("turnover_value") or 0.0
        try:
            volumes.append(max(0.0, float(volume)))
        except (TypeError, ValueError):
            volumes.append(0.0)
        times.append(_date_epoch(str(day)))
    series["volumes"] = volumes
    series["times"] = times
    return series


def assemble_chart_analysis(
    *,
    series: Mapping[str, list],
    data_through: str,
    ticker: str = "",
    chart_range: str = "1d",
    adjustment: str = "adjusted",
    price_action: Mapping[str, Any] | None = None,
    vol_price: Mapping[str, Any] | None = None,
    base: Mapping[str, Any] | None = None,
    base_state: Mapping[str, Any] | None = None,
    technicals: Mapping[str, Any] | None = None,
    topix_closes: Sequence[float | None] | Mapping[str, float] | None = None,
) -> dict[str, Any]:
    dates = list(series.get("dates") or [])
    closes = list(series.get("closes") or [])
    price_action = price_action or {}
    vol_price = vol_price or {}
    technicals = technicals or {}
    volume_confirmation = volume_confirmation_from_vol_price(vol_price)
    trend_alignment = trend_alignment_from_technicals(technicals)
    overlays: list[dict[str, Any]] = []
    overlays.extend(_ma_overlays(series, data_through))
    overlays.extend(_price_action_overlays(price_action, series, data_through))
    overlays.extend(
        _base_overlays(
            base,
            base_state,
            data_through,
            volume_confirmation=volume_confirmation,
            trend_alignment=trend_alignment,
        )
    )
    overlays.extend(_vol_price_overlays(vol_price, data_through))
    overlays.extend(
        _breakout_overlays(
            base,
            base_state,
            data_through,
            volume_confirmation=volume_confirmation,
            trend_alignment=trend_alignment,
        )
    )
    return {
        "version": BUNDLE_VERSION,
        "registryVersion": LAYER_REGISTRY_VERSION,
        "ticker": ticker,
        "range": chart_range,
        "adjustment": adjustment,
        "dataThrough": data_through,
        **fingerprint_meta(series),
        "lastClose": round(float(closes[-1]), 6) if closes else None,
        "seriesBreakAt": None,
        "dates": dates,
        "overlays": overlays,
        "indicatorPanes": _indicator_panes(series, topix_closes=topix_closes, dates=dates),
        "strengthContext": None,
    }


def chart_analysis_for_bars(
    bars: Sequence[Mapping[str, Any]],
    *,
    ticker: str = "",
    topix_closes: Mapping[str, float] | None = None,
    min_bars: int = 30,
) -> dict[str, Any] | None:
    """Assemble a bundle from Japan daily bars. Failures stay None so the chart still loads."""

    try:
        series = series_from_jp_bars(bars, min_bars=min_bars)
        if series is None:
            return None
        prior = series_excluding_last(series)
        base = detect_base(prior) if prior else None
        price_action = compute_price_action(series)
        vol_price = compute_vol_price_match(series)
        technicals = compute_technicals(series)
        close = series["closes"][-1] if series.get("closes") else None
        return assemble_chart_analysis(
            series=series,
            data_through=series["dates"][-1],
            ticker=ticker,
            chart_range="1d",
            adjustment="adjusted",
            price_action=price_action,
            vol_price=vol_price,
            base=base,
            base_state=_base_state_from_close(base, close),
            technicals=technicals,
            topix_closes=topix_closes,
        )
    except (TypeError, ValueError, KeyError, OverflowError):
        return None


def topix_close_map(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in rows:
        day = str(row.get("trade_date") or "")
        close = _finite_number(row.get("close"))
        if day and close is not None and close > 0:
            out[day] = close
    return out


__all__ = [
    "BUNDLE_VERSION",
    "FINGERPRINT_ALGORITHM",
    "LAYER_REGISTRY_VERSION",
    "TOPIX_INDEX_CODE",
    "assemble_chart_analysis",
    "bar_fingerprint",
    "canonical_bar_payload",
    "chart_analysis_for_bars",
    "consecutive_swing_labels",
    "fingerprint_meta",
    "macd_series",
    "rsi_series",
    "series_from_jp_bars",
    "sma_series",
    "topix_close_map",
]
