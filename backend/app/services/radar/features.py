"""Per-security daily-bar features for radar and screener.

Point-in-time discipline: the caller passes bars whose last element is the
completed target session; every rolling window that describes "the level
being broken" excludes that final bar. Missing values stay ``None`` — they
are never imputed, and malformed bars (high < low, close outside range)
are dropped, never repaired.

Prices use the adjusted series (split-consistent history); turnover value
(JPY) is used for participation — raw share volume is not comparable
across price levels.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

FEATURE_VERSION = "jp-features-v2"  # v2: +return_126d/+return_252d（強度スキャン長期族）

MIN_BARS_FOR_FEATURES = 30

from .adjustment import cumulative_factors
from .turnover_quality import turnover_stability as compute_turnover_stability


def _pick_price(
    bar: Mapping[str, Any], adj_key: str, raw_key: str, factor: float = 1.0
) -> float | None:
    """調整後の値。取り込み済みの adj_* があれば優先、無ければ生値 × 累積係数。

    一括配信 CSV には adj_* 列が無く AdjFactor しか来ないため、ここで作らないと
    分割が前日比 −50% の暴落として指標に入る（本番 10 年で 1,959 銘柄が該当）。
    """

    value = bar.get(adj_key)
    if value is not None:
        number = float(value)
        if math.isfinite(number) and number > 0.0:
            return number
    value = bar.get(raw_key)
    if value is None:
        return None
    number = float(value) * factor
    if not math.isfinite(number) or number <= 0.0:
        return None
    return number


def clean_series(bars: Sequence[Mapping[str, Any]]) -> dict[str, list] | None:
    dates: list[str] = []
    closes: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    opens: list[float] = []
    turnover: list[float | None] = []
    upper_limit: list[bool] = []
    # そのバーより後に起きた調整の累積。窓の最終バーは必ず 1.0 なので、
    # 直近の値は生値のまま（画面の現在値と約定可能価格の意味を変えない）。
    factors = cumulative_factors(bars)
    for bar, factor in zip(bars, factors):
        close = _pick_price(bar, "adj_close", "close", factor)
        high = _pick_price(bar, "adj_high", "high", factor)
        low = _pick_price(bar, "adj_low", "low", factor)
        open_ = _pick_price(bar, "adj_open", "open", factor)
        if close is None:
            continue  # 取引成立なし日はスキップ（穴は補間しない）
        if high is None or low is None:
            high = high or close
            low = low or close
        if high < low or close > high * 1.0001 or close < low * 0.9999:
            continue  # 壊れたバーは修復せず捨てる
        raw_turnover = bar.get("turnover_value")
        dates.append(str(bar.get("trade_date")))
        closes.append(close)
        highs.append(high)
        lows.append(low)
        opens.append(open_ or close)
        turnover.append(float(raw_turnover) if raw_turnover is not None else None)
        upper_limit.append(str(bar.get("upper_limit") or "0") in ("1", "1.0", "True", "true"))
    if len(closes) < MIN_BARS_FOR_FEATURES:
        return None
    return {
        "dates": dates,
        "closes": closes,
        "highs": highs,
        "lows": lows,
        "opens": opens,
        "turnover": turnover,
        "upper_limit": upper_limit,
    }


def _sma(values: Sequence[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def _pct_return(closes: Sequence[float], days: int) -> float | None:
    if len(closes) <= days:
        return None
    past = closes[-1 - days]
    if past <= 0.0:
        return None
    return closes[-1] / past - 1.0


def _atr(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], window: int = 14) -> float | None:
    n = len(closes)
    if n < window + 1:
        return None
    trs: list[float] = []
    for i in range(n - window, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    return sum(trs) / len(trs)


def _median(values: Sequence[float]) -> float | None:
    items = sorted(values)
    if not items:
        return None
    mid = len(items) // 2
    if len(items) % 2:
        return items[mid]
    return (items[mid - 1] + items[mid]) / 2.0


def _prior_high(highs: Sequence[float], window: int) -> float | None:
    # Exclude the final (target) bar — the bar being evaluated must never
    # contribute to the level it is breaking.
    if len(highs) < window + 1:
        return None
    return max(highs[-1 - window:-1])


def compute_security_features(bars: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    series = clean_series(bars)
    if series is None:
        return None
    return compute_features_from_series(series)


def compute_features_from_series(series: dict[str, list] | None) -> dict[str, Any] | None:
    # `compute_features_from_series(clean_series(bars))` と繋げて書くのが
    # 自然なので、欠測をそのまま受けて None を返す（例外にしない）。
    if series is None:
        return None
    closes = series["closes"]
    highs = series["highs"]
    lows = series["lows"]
    turnover = series["turnover"]
    dates = series["dates"]

    close = closes[-1]
    high = highs[-1]
    low = lows[-1]
    data_days = len(closes)

    ma25 = _sma(closes, 25)
    ma75 = _sma(closes, 75)
    ma200 = _sma(closes, 200)
    atr14 = _atr(highs, lows, closes)

    turnover_today = turnover[-1]
    prior_turnover = [value for value in turnover[-21:-1] if value is not None and value > 0.0]
    turnover_median_20 = _median(prior_turnover) if len(prior_turnover) >= 10 else None
    avg_turnover_20 = (
        sum(prior_turnover) / len(prior_turnover) if len(prior_turnover) >= 10 else None
    )
    turnover_ratio = (
        turnover_today / turnover_median_20
        if turnover_today is not None and turnover_median_20
        else None
    )
    # 「毎日ちゃんと商いがあるか」は 60 日で測る（20 日だと 1 回の突発が
    # 窓の 5% を占めてしまい、突発と常態の区別が付かない）。
    turnover_stability_60 = compute_turnover_stability(turnover[-60:])
    recent5 = [value for value in turnover[-5:] if value is not None]
    turnover_trend = (
        (sum(recent5) / len(recent5)) / avg_turnover_20
        if recent5 and avg_turnover_20
        else None
    )

    prior_high_20 = _prior_high(highs, 20)
    prior_high_60 = _prior_high(highs, 60)
    prior_high_120 = _prior_high(highs, 120)
    prior_high_252 = _prior_high(highs, 252)

    high_252_incl = max(highs[-252:]) if len(highs) >= 60 else max(highs)
    pct_from_high_252 = close / high_252_incl - 1.0 if high_252_incl > 0 else None

    day_range = high - low
    close_location = (close - low) / day_range if day_range > 0 else None

    return_1d = _pct_return(closes, 1)
    return_5d = _pct_return(closes, 5)
    return_20d = _pct_return(closes, 20)
    return_63d = _pct_return(closes, 63)
    return_126d = _pct_return(closes, 126)
    return_252d = _pct_return(closes, 252)

    # Volatility contraction: recent 10-bar ATR vs the 30→10 bar window.
    atr_recent = _atr(highs[-11:], lows[-11:], closes[-11:], 10) if len(closes) >= 12 else None
    atr_earlier = (
        _atr(highs[-31:-10], lows[-31:-10], closes[-31:-10], 20) if len(closes) >= 32 else None
    )
    volatility_contraction = (
        1.0 - (atr_recent / atr_earlier) if atr_recent and atr_earlier and atr_earlier > 0 else None
    )

    peak_63 = max(closes[-63:]) if len(closes) >= 5 else None
    drawdown_63d = close / peak_63 - 1.0 if peak_63 else None

    ma_alignment = None
    if ma25 is not None and ma75 is not None:
        aligned = close > ma25 > ma75
        if ma200 is not None:
            aligned = aligned and ma75 > ma200
        ma_alignment = bool(aligned)

    trend_persistence = None
    if len(closes) >= 65 and ma25 is not None:
        # Rolling SMA25 via prefix sums — one pass instead of 40 recomputes.
        prefix = [0.0]
        for value in closes:
            prefix.append(prefix[-1] + value)
        above = 0
        for offset in range(40):
            idx = len(closes) - 40 + offset
            sma = (prefix[idx + 1] - prefix[idx + 1 - 25]) / 25.0
            if closes[idx] > sma:
                above += 1
        trend_persistence = above / 40.0

    overheat_atr_multiple = None
    if atr14 and atr14 > 0 and ma25 is not None:
        overheat_atr_multiple = (close - ma25) / atr14

    return {
        "feature_version": FEATURE_VERSION,
        "trade_date": dates[-1],
        "close": close,
        "high": high,
        "low": low,
        "data_days": data_days,
        "ma25": ma25,
        "ma75": ma75,
        "ma200": ma200,
        "ma25_gap_pct": (close / ma25 - 1.0) if ma25 else None,
        "ma75_gap_pct": (close / ma75 - 1.0) if ma75 else None,
        "ma200_gap_pct": (close / ma200 - 1.0) if ma200 else None,
        "ma_alignment": ma_alignment,
        "trend_persistence": trend_persistence,
        "atr14": atr14,
        "turnover_today": turnover_today,
        "avg_turnover_20d": avg_turnover_20,
        "turnover_ratio": turnover_ratio,
        "turnover_trend": turnover_trend,
        "turnover_stability": turnover_stability_60,
        "prior_high_20": prior_high_20,
        "prior_high_60": prior_high_60,
        "prior_high_120": prior_high_120,
        "prior_high_252": prior_high_252,
        "pct_from_high_252": pct_from_high_252,
        "close_location": close_location,
        "return_1d": return_1d,
        "return_5d": return_5d,
        "return_20d": return_20d,
        "return_63d": return_63d,
        "return_126d": return_126d,
        "return_252d": return_252d,
        "volatility_contraction": volatility_contraction,
        "drawdown_63d": drawdown_63d,
        "overheat_atr_multiple": overheat_atr_multiple,
        "upper_limit_today": series["upper_limit"][-1],
    }


def index_return(series: Sequence[Mapping[str, Any]], days: int) -> float | None:
    closes = [float(row["close"]) for row in series if row.get("close") is not None]
    if len(closes) <= days or closes[-1 - days] <= 0.0:
        return None
    return closes[-1] / closes[-1 - days] - 1.0


def series_excluding_last(series: dict[str, list]) -> dict[str, list] | None:
    """評価対象日を除いた列（ベース検出用 — 当日は自分の抵抗帯に不参加）。"""

    if len(series.get("closes") or []) < 2:
        return None
    return {key: list(values[:-1]) for key, values in series.items()}


__all__ = [
    "FEATURE_VERSION",
    "MIN_BARS_FOR_FEATURES",
    "clean_series",
    "compute_features_from_series",
    "compute_security_features",
    "index_return",
    "series_excluding_last",
]
