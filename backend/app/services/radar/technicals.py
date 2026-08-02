"""古典テクニカル指標 — 米国版 strength/scanner・scoring から日足対応分を移植。

RSI(Wilder)・MACD 方向・Kaufman 型トレンド効率・MA スロープ・トレンド
安定度・レンジポジション/持続。全て純 Python、欠損は None のまま。
"""

from __future__ import annotations

import math
from typing import Any, Sequence

TECHNICALS_VERSION = "jp-technicals-v1"


def _safe(value: Any, ndigits: int = 4) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, ndigits)


def rsi14(closes: Sequence[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
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
    for i in range(period + 1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss <= 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def rsi_score(value: float | None) -> float | None:
    """米国版の折れ線ノットマップ: RSI 68 付近が最良、極端は減点。"""

    if value is None:
        return None
    knots = ((0.0, 15.0), (30.0, 35.0), (45.0, 60.0), (55.0, 75.0), (68.0, 88.0), (80.0, 70.0), (100.0, 33.0))
    for (x0, y0), (x1, y1) in zip(knots, knots[1:]):
        if x0 <= value <= x1:
            if x1 == x0:
                return y0
            ratio = (value - x0) / (x1 - x0)
            return y0 + (y1 - y0) * ratio
    return 33.0


def _ema_series(values: Sequence[float], period: int) -> list[float]:
    alpha = 2.0 / (period + 1.0)
    result: list[float] = []
    ema = values[0]
    for value in values:
        ema = value * alpha + ema * (1.0 - alpha)
        result.append(ema)
    return result


def macd_direction(closes: Sequence[float]) -> dict[str, float | None]:
    """MACD(12/26/9) ヒストグラムの直近3本変化を終値比 % で返す。"""

    if len(closes) < 40:
        return {"histogram": None, "direction_pct": None}
    fast = _ema_series(closes, 12)
    slow = _ema_series(closes, 26)
    macd_line = [f - s for f, s in zip(fast, slow)]
    signal = _ema_series(macd_line, 9)
    histogram = [m - s for m, s in zip(macd_line, signal)]
    last_close = closes[-1]
    if last_close <= 0 or len(histogram) < 4:
        return {"histogram": _safe(histogram[-1]), "direction_pct": None}
    delta = histogram[-1] - histogram[-4]
    return {
        "histogram": _safe(histogram[-1]),
        "direction_pct": _safe(delta / last_close * 100.0),
    }


def trend_efficiency(closes: Sequence[float], window: int = 63) -> float | None:
    """Kaufman 効率比: |純移動| / 経路長。1 に近いほど一方向。"""

    if len(closes) < window + 1:
        return None
    tail = closes[-window - 1:]
    net = abs(tail[-1] - tail[0])
    path = sum(abs(tail[i] - tail[i - 1]) for i in range(1, len(tail)))
    if path <= 0:
        return None
    return net / path


def ma_slope(closes: Sequence[float], ma_window: int = 50, change_bars: int = 21) -> float | None:
    """50日SMA の 21 本変化率（%）。"""

    need = ma_window + change_bars
    if len(closes) < need:
        return None
    def sma_at(end_index: int) -> float:
        return sum(closes[end_index - ma_window:end_index]) / ma_window
    now = sma_at(len(closes))
    before = sma_at(len(closes) - change_bars)
    if before <= 0:
        return None
    return (now / before - 1.0) * 100.0


def trend_stability(closes: Sequence[float], window: int = 20) -> float | None:
    """日次リターンの標準偏差（小さいほど安定）。"""

    if len(closes) < window + 1:
        return None
    returns = [
        closes[i] / closes[i - 1] - 1.0
        for i in range(len(closes) - window, len(closes))
        if closes[i - 1] > 0
    ]
    if len(returns) < 3:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / len(returns)
    return math.sqrt(variance)


def range_position(
    closes: Sequence[float], highs: Sequence[float], lows: Sequence[float], window: int = 60
) -> dict[str, float | None]:
    """N日レンジ内の終値位置(0-1)と、その 5/20 日 EMA（レンジ持続の簡易版）。"""

    n = len(closes)
    if n < window + 5:
        return {"position": None, "persistence_fast": None, "persistence_slow": None}
    positions: list[float] = []
    for i in range(window, n):
        window_high = max(highs[i - window + 1:i + 1])
        window_low = min(lows[i - window + 1:i + 1])
        span = window_high - window_low
        positions.append((closes[i] - window_low) / span if span > 0 else 0.5)
    fast = _ema_series(positions, 5)[-1] if positions else None
    slow = _ema_series(positions, 20)[-1] if len(positions) >= 5 else None
    return {
        "position": _safe(positions[-1]) if positions else None,
        "persistence_fast": _safe(fast),
        "persistence_slow": _safe(slow),
    }


def compute_technicals(series: dict[str, list]) -> dict[str, Any]:
    closes = list(series.get("closes") or [])
    highs = list(series.get("highs") or [])
    lows = list(series.get("lows") or [])
    rsi_value = rsi14(closes)
    rp = range_position(closes, highs, lows)
    return {
        "version": TECHNICALS_VERSION,
        "rsi14": _safe(rsi_value, 2),
        "rsi_score": _safe(rsi_score(rsi_value), 1),
        "macd": macd_direction(closes),
        "trend_efficiency_63d": _safe(trend_efficiency(closes)),
        "ma50_slope_pct_21d": _safe(ma_slope(closes), 2),
        "return_stability_20d": _safe(trend_stability(closes), 5),
        "range_position_60d": rp["position"],
        "range_persistence_fast": rp["persistence_fast"],
        "range_persistence_slow": rp["persistence_slow"],
    }


__all__ = [
    "TECHNICALS_VERSION",
    "compute_technicals",
    "ma_slope",
    "macd_direction",
    "range_position",
    "rsi14",
    "rsi_score",
    "trend_efficiency",
    "trend_stability",
]
