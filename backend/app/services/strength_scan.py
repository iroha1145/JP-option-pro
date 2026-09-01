"""強度スキャン — 米国版 Strength Radar（strength/scoring.py v2）の日本株移植。

設計はレーダーと同じ「夜間に重い計算、要求時に軽い重ね掛け」:

- 夜間バッチ: レーダーが計算済みの features / 構造分析（base・price action・
  量価一致・テクニカル）をそのまま消費し、銘柄内在評価（intrinsic）を
  6 因子ファミリで合成して ``strength_rows`` に全量保存する。市場レジーム
  （TOPIX トレンド + 全市場ブレッドス等 6 次元）も同時に確定する。
- API: 保存済み行に profile_fit / market_fit / ranking / リスク減点 /
  分類を重ねる。これらは軽い算術なので要求毎に profile を変えられる。

米国版との対応（重みは同一、入力だけ日本株の口径に置換）:
  米国指数相対 → TOPIX 相対、ドル建て成交額 → 円建て売買代金、
  SMA20/50/200 → MA25/75/200（日本の慣習）、52週高値は 240 本未満なら欠損。
欠損は常に「重み再配分 + confidence 低下」で扱い、中立値 50 で埋めない。
"""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from typing import Any, Mapping

STRENGTH_SCORE_VERSION = "jp-strength-v1"

TIMEFRAMES = ("short", "mid", "long", "all")
PROFILES = ("conservative", "balanced", "aggressive")

#: 分類ラベル（米国版 _classify と同じ閾値、RS だけ TOPIX 比）。
PROFILE_TILT = {
    "conservative": {"risk": 1.22},
    "balanced": {"risk": 1.0},
    "aggressive": {"risk": 0.82},
}

FAMILY_WEIGHTS = {
    "short": 0.16, "mid": 0.24, "long": 0.14,
    "trend": 0.16, "breakout": 0.15, "price_action": 0.15,
}

#: 流動性リスクの基準線: 20日平均売買代金 1 億円。
_LIQUIDITY_BASE_JPY = 100_000_000.0
_MIN_HISTORY_FOR_52W = 240

TIER_FLOORS: tuple[tuple[str, float], ...] = (
    ("S", 90.0), ("A", 80.0), ("B", 70.0), ("C", 60.0),
)


def _median(values: Any) -> float | None:
    """True median (averages the two central values for even lengths)."""

    items = sorted(values)
    if not items:
        return None
    mid = len(items) // 2
    if len(items) % 2:
        return items[mid]
    return (items[mid - 1] + items[mid]) / 2.0


def _finite(value: Any, lo: float | None = None, hi: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    if lo is not None:
        number = max(lo, number)
    if hi is not None:
        number = min(hi, number)
    return number


def _score(value: Any) -> float | None:
    return _finite(value, 0.0, 100.0)


def weighted_available(
    components: Mapping[str, Any],
    weights: Mapping[str, float],
    qualities: Mapping[str, float] | None = None,
    *,
    min_active_weight: float = 0.25,
) -> dict[str, Any]:
    """米国版 weighted_available の忠実移植: 有限値のみ集計し、監査情報を残す。

    confidence = 実際に使えた重みの割合（quality 割引後）。欠損は中立値に
    変換されず、重みごと脱落する。
    """

    configured = {str(k): max(0.0, _finite(w) or 0.0) for k, w in weights.items()}
    quality_map = qualities or {}
    values: dict[str, float] = {}
    active: dict[str, float] = {}
    missing: list[str] = []
    for name, weight in configured.items():
        value = _score(components.get(name))
        quality = _finite(quality_map.get(name, 1.0), 0.0, 1.0)
        if value is None or quality is None or quality <= 0 or weight <= 0:
            missing.append(name)
            continue
        values[name] = value
        active[name] = weight * quality
    configured_total = sum(configured.values())
    active_total = sum(active.values())
    confidence = active_total / configured_total if configured_total > 0 else 0.0
    result: dict[str, Any] = {
        "score": None,
        "status": "insufficient_data",
        "confidence": round(max(0.0, min(1.0, confidence)), 6),
        "effective_weights": {},
        "contributions": {},
        "missing": missing,
    }
    if active_total <= 0 or active_total < max(0.0, float(min_active_weight)):
        return result
    effective = {name: weight / active_total for name, weight in active.items()}
    contributions = {name: values[name] * effective[name] for name in effective}
    result.update(
        score=round(max(0.0, min(100.0, sum(contributions.values()))), 4),
        status="active",
        effective_weights={k: round(v, 6) for k, v in effective.items()},
        contributions={k: round(v, 6) for k, v in contributions.items()},
    )
    return result


def absolute_return_score(value: Any, scale: float) -> float | None:
    number = _finite(value)
    if number is None:
        return None
    return round(max(0.0, min(100.0, 50.0 + number * scale)), 4)


def relative_volume_score(value: Any) -> float | None:
    number = _finite(value, 0.0)
    if number is None:
        return None
    return round(max(0.0, min(100.0, 50.0 + (number - 1.0) * 35.0)), 4)


# ---------------------------------------------------------------------------
# intrinsic（銘柄内在評価: 夜間バッチで確定、市場・profile を含まない）
# ---------------------------------------------------------------------------


def score_intrinsic_jp(
    features: Mapping[str, Any],
    structure: Mapping[str, Any] | None,
    *,
    rs_topix_63d: float | None,
) -> dict[str, Any]:
    structure = structure or {}
    technicals = structure.get("technicals") or {}
    price_action = structure.get("price_action") or {}
    vol_price = structure.get("vol_price") or {}

    data_days = int(features.get("data_days") or 0)
    close = _finite(features.get("close"))
    pct_from_high = _finite(features.get("pct_from_high_252"))
    # 52週高値は一年分の実データがあるときだけ意味を持つ（米国版 v3 と同じ）。
    ath_proximity = (
        round((1.0 + pct_from_high) * 100.0, 2)
        if pct_from_high is not None and data_days >= _MIN_HISTORY_FOR_52W
        else None
    )
    ma_alignment_pct = _ma_alignment_pct(features)
    rsi_component = _score(technicals.get("rsi_score"))
    macd_direction = _finite((technicals.get("macd") or {}).get("direction_pct"))
    pa_score = _score(price_action.get("score"))

    short = weighted_available(
        {
            "return_5d": absolute_return_score(features.get("return_5d"), 500.0),
            "return_20d": absolute_return_score(features.get("return_20d"), 300.0),
            "relative_volume": relative_volume_score(features.get("turnover_ratio")),
            "distance_ma25": absolute_return_score(features.get("ma25_gap_pct"), 400.0),
            "rsi14": rsi_component,
        },
        {"return_5d": 0.20, "return_20d": 0.25, "relative_volume": 0.15,
         "distance_ma25": 0.20, "rsi14": 0.20},
        min_active_weight=0.45,
    )

    mid = weighted_available(
        {
            "return_63d": absolute_return_score(features.get("return_63d"), 180.0),
            "rs_topix_63d": absolute_return_score(rs_topix_63d, 220.0),
            "ma_alignment": ma_alignment_pct,
            "macd_direction": absolute_return_score(macd_direction, 5.0),
            "distance_ma75": absolute_return_score(features.get("ma75_gap_pct"), 320.0),
        },
        {"return_63d": 0.28, "rs_topix_63d": 0.27, "ma_alignment": 0.20,
         "macd_direction": 0.10, "distance_ma75": 0.15},
        min_active_weight=0.45,
    )

    long = weighted_available(
        {
            "return_126d": absolute_return_score(features.get("return_126d"), 130.0),
            "return_252d": absolute_return_score(features.get("return_252d"), 90.0),
            "distance_ma200": absolute_return_score(features.get("ma200_gap_pct"), 260.0),
            "ath_proximity": ath_proximity,
            "ma_alignment": ma_alignment_pct,
        },
        {"return_126d": 0.26, "return_252d": 0.22, "distance_ma200": 0.24,
         "ath_proximity": 0.18, "ma_alignment": 0.10},
        min_active_weight=0.45,
    )

    # トレンド族: 効率比は無符号なので 63 日リターンの符号を与える。
    efficiency = _finite(technicals.get("trend_efficiency_63d"))
    r63 = _finite(features.get("return_63d"))
    signed_efficiency = None
    if efficiency is not None and r63 is not None:
        signed_efficiency = efficiency if r63 >= 0 else -efficiency
    stability = _finite(technicals.get("return_stability_20d"), 0.0)
    trend = weighted_available(
        {
            "medium_term_momentum": absolute_return_score(features.get("return_63d"), 180.0),
            "trend_efficiency": (
                round(max(0.0, min(100.0, 50.0 + signed_efficiency * 50.0)), 4)
                if signed_efficiency is not None else None
            ),
            "moving_average_slope": absolute_return_score(
                (technicals.get("ma50_slope_pct_21d") or 0.0) / 100.0
                if technicals.get("ma50_slope_pct_21d") is not None else None,
                500.0,
            ),
            "trend_stability": (
                round(max(0.0, min(100.0, 100.0 - stability * 2200.0)), 4)
                if stability is not None else None
            ),
        },
        {"medium_term_momentum": 0.50, "trend_efficiency": 0.25,
         "moving_average_slope": 0.20, "trend_stability": 0.05},
        min_active_weight=0.45,
    )

    breakout_base = weighted_available(
        {
            "ath_proximity": ath_proximity,
            "return_20d": absolute_return_score(features.get("return_20d"), 300.0),
            "price_action": pa_score,
        },
        {"ath_proximity": 0.40, "return_20d": 0.40, "price_action": 0.20},
        min_active_weight=0.40,
    )
    breakout_score = breakout_base["score"]
    adjustment = _finite(vol_price.get("breakout_quality_adjustment")) or 0.0
    false_risk = _finite(vol_price.get("false_breakout_risk"), 0.0) or 0.0
    prior_high_60 = _finite(features.get("prior_high_60"))
    turnover_ratio = _finite(features.get("turnover_ratio"), 0.0)
    breakout_confirmed = bool(
        close is not None and prior_high_60 is not None
        and close >= prior_high_60 * 0.995
        and (turnover_ratio or 0.0) >= 1.15
    )
    ma25 = _finite(features.get("ma25"))
    follow_through = bool(
        close is not None and ma25 is not None and close > ma25
        and (_finite(features.get("return_5d")) or 0.0) >= 0.0
    )
    if breakout_score is not None:
        breakout_score = max(0.0, min(100.0, breakout_score + adjustment - false_risk))
        setup_type = str(vol_price.get("setup_type") or "")
        if setup_type == "vacuum" and not follow_through:
            breakout_score = min(breakout_score, 65.0)
        if setup_type == "absorption_bearish" and not breakout_confirmed:
            breakout_score = min(breakout_score, 55.0)
        breakout_score = round(breakout_score, 4)

    families = {
        "short": short["score"],
        "mid": mid["score"],
        "long": long["score"],
        "trend": trend["score"],
        "breakout": breakout_score,
        "price_action": pa_score,
    }
    qualities = {
        "short": short["confidence"],
        "mid": mid["confidence"],
        "long": long["confidence"],
        "trend": trend["confidence"],
        "breakout": breakout_base["confidence"],
        "price_action": 1.0 if pa_score is not None else 0.0,
    }
    composite = weighted_available(families, FAMILY_WEIGHTS, qualities, min_active_weight=0.25)

    return {
        "score": round(composite["score"], 1) if composite["score"] is not None else None,
        "status": composite["status"],
        "confidence": composite["confidence"],
        "score_version": STRENGTH_SCORE_VERSION,
        "families": families,
        "family_details": {
            "short": short, "mid": mid, "long": long,
            "trend": trend, "breakout": breakout_base,
        },
        "effective_weights": composite["effective_weights"],
        "contributions": composite["contributions"],
        "missing_families": composite["missing"],
        "score_short": short["score"],
        "score_mid": mid["score"],
        "score_long": long["score"],
        "trend_score": trend["score"],
        "breakout_quality_score": breakout_score,
        "price_action_score": pa_score,
        "ath_proximity": ath_proximity,
        "ma_alignment_pct": ma_alignment_pct,
        "breakout_confirmed": breakout_confirmed,
        "follow_through": follow_through,
    }


def _ma_alignment_pct(features: Mapping[str, Any]) -> float | None:
    """終値が MA25/75/200 のうち何本の上にあるか（利用可能な本数比、％）。"""

    states = [
        features.get(key) for key in ("ma25_gap_pct", "ma75_gap_pct", "ma200_gap_pct")
        if features.get(key) is not None
    ]
    if not states:
        return None
    above = sum(1 for gap in states if float(gap) > 0)
    return round(above / len(states) * 100.0, 2)


# ---------------------------------------------------------------------------
# 市場レジーム（TOPIX + 全市場ブレッドス、6 次元）
# ---------------------------------------------------------------------------


def compute_market_regime_jp(
    topix_series: list[Mapping[str, Any]],
    features_by_code: Mapping[str, Mapping[str, Any]],
    market_code_by_code: Mapping[str, str],
) -> dict[str, Any]:
    closes = [float(row["close"]) for row in topix_series if row.get("close") is not None]

    index_trend = None
    momentum = None
    warnings: list[str] = []
    if len(closes) >= 80:
        close = closes[-1]
        ma25 = sum(closes[-25:]) / 25.0
        ma75 = sum(closes[-75:]) / 75.0
        ma200 = sum(closes[-200:]) / 200.0 if len(closes) >= 200 else None
        score = 50.0
        score += 16.0 if close > ma25 else -16.0
        score += 16.0 if close > ma75 else -16.0
        if ma200 is not None:
            score += 12.0 if close > ma200 else -12.0
            if close < ma200:
                warnings.append("TOPIX が200日線を下回っている")
        if len(closes) >= 47:
            slope = ma25 / (sum(closes[-46:-21]) / 25.0) - 1.0
            score += max(-14.0, min(14.0, slope * 400.0))
        index_trend = round(max(0.0, min(100.0, score)), 1)
        r20 = closes[-1] / closes[-21] - 1.0 if len(closes) >= 21 else None
        if r20 is not None:
            momentum = round(max(0.0, min(100.0, 50.0 + r20 * 500.0)), 1)

    above_ma200: list[bool] = []
    above_avg_turnover = 0
    turnover_known = 0
    r20_values: list[float] = []
    r20_by_market: dict[str, list[float]] = {}
    for code, features in features_by_code.items():
        gap200 = features.get("ma200_gap_pct")
        if gap200 is not None:
            above_ma200.append(float(gap200) > 0)
        ratio = features.get("turnover_ratio")
        if ratio is not None:
            turnover_known += 1
            if float(ratio) >= 1.0:
                above_avg_turnover += 1
        r20 = features.get("return_20d")
        if r20 is not None:
            r20_values.append(float(r20))
            market = market_code_by_code.get(code)
            if market:
                r20_by_market.setdefault(market, []).append(float(r20))

    breadth = (
        round(sum(above_ma200) / len(above_ma200) * 100.0, 1) if above_ma200 else None
    )
    volume = (
        round(above_avg_turnover / turnover_known * 100.0, 1) if turnover_known else None
    )
    risk_appetite = None
    if r20_values:
        median = _median(r20_values)
        risk_appetite = round(max(0.0, min(100.0, 50.0 + median * 1000.0)), 1)

    # リスクオン価差: グロース市場と プライム市場の 20 日中央値リターン差。
    risk_on_spread = None
    spread_label = None
    growth = sorted(r20_by_market.get("0113") or [])
    prime = sorted(r20_by_market.get("0111") or [])
    if len(growth) >= 30 and len(prime) >= 30:
        spread = _median(growth) - _median(prime)
        risk_on_spread = round(max(0.0, min(100.0, 50.0 + spread * 600.0)), 1)
        # Chinese msgid (front-end runs it through t()); keeps the app-wide
        # "backend emits Chinese, frontend localizes" contract.
        spread_label = "强弱价差 · グロース−プライム"

    dims = {
        "index_trend": index_trend,
        "momentum": momentum,
        "breadth": breadth,
        "volume": volume,
        "risk_appetite": risk_appetite,
        "risk_on_spread": risk_on_spread,
    }
    composite = weighted_available(
        dims,
        {"index_trend": 0.24, "momentum": 0.18, "breadth": 0.22,
         "volume": 0.12, "risk_appetite": 0.12, "risk_on_spread": 0.12},
        min_active_weight=0.40,
    )
    score = composite["score"]
    if breadth is not None and breadth < 30.0:
        warnings.append("200日線超の銘柄が3割未満（ブレッドス弱い）")
    label = None
    if score is not None:
        # Chinese msgids; localized on the front-end via t().
        label = "顺风" if score >= 64 else ("中立" if score >= 45 else "逆风")
    return {
        "score": round(score, 1) if score is not None else None,
        "label": label,
        "confidence": composite["confidence"],
        "status": composite["status"],
        "dims": dims,
        "spread_label": spread_label,
        "warnings": warnings,
        "universe_size": len(features_by_code),
    }


# ---------------------------------------------------------------------------
# 要求時の重ね掛け（profile / market / ranking / リスク / 分類）
# ---------------------------------------------------------------------------


def score_market_fit(regime: Mapping[str, Any]) -> dict[str, Any]:
    raw = _score(regime.get("score"))
    confidence = _finite(regime.get("confidence"), 0.0, 1.0)
    if raw is None or confidence is None or confidence <= 0:
        return {"score": None, "status": "insufficient_data", "confidence": 0.0}
    fitted = 50.0 + (raw - 50.0) * confidence
    return {
        "score": round(fitted, 4),
        "status": "active",
        "confidence": round(confidence, 6),
        "raw_score": raw,
    }


def score_profile_fit(row: Mapping[str, Any], profile: str) -> dict[str, Any]:
    intrinsic = _score(row.get("intrinsic_score"))
    atr_pct = _finite(row.get("atr_pct"), 0.0)
    if atr_pct is None:
        volatility_fit = None
    elif profile == "conservative":
        volatility_fit = max(0.0, min(100.0, 100.0 - atr_pct * 11.0))
    elif profile == "aggressive":
        volatility_fit = max(0.0, min(100.0, 45.0 + atr_pct * 7.0))
    else:
        volatility_fit = max(0.0, min(100.0, 100.0 - abs(atr_pct - 3.0) * 12.0))
    avg_turnover = _finite(row.get("avg_turnover_20d"), 0.0)
    liquidity_fit = None
    if avg_turnover is not None and avg_turnover > 0:
        # 1億円 → 約20、10億円 → 約50、100億円 → 約80（米国版の $1m/10m/100m と同形）。
        liquidity_fit = max(
            0.0, min(100.0, 20.0 + math.log10(avg_turnover / _LIQUIDITY_BASE_JPY) * 30.0)
        )
    trend_fit = _score(row.get("ma_alignment_pct"))
    weights = {"intrinsic": 0.55, "volatility_fit": 0.20, "liquidity_fit": 0.15, "trend_fit": 0.10}
    if profile == "conservative":
        weights = {"intrinsic": 0.45, "volatility_fit": 0.25, "liquidity_fit": 0.20, "trend_fit": 0.10}
    elif profile == "aggressive":
        weights = {"intrinsic": 0.60, "volatility_fit": 0.20, "liquidity_fit": 0.10, "trend_fit": 0.10}
    return weighted_available(
        {"intrinsic": intrinsic, "volatility_fit": volatility_fit,
         "liquidity_fit": liquidity_fit, "trend_fit": trend_fit},
        weights,
        min_active_weight=0.45,
    )


def score_ranking(
    intrinsic_score: float | None,
    intrinsic_confidence: float,
    market_fit: Mapping[str, Any],
    profile_fit: Mapping[str, Any],
) -> dict[str, Any]:
    return weighted_available(
        {
            "intrinsic": intrinsic_score,
            "market_fit": market_fit.get("score"),
            "profile_fit": profile_fit.get("score"),
        },
        {"intrinsic": 0.78, "market_fit": 0.08, "profile_fit": 0.14},
        {
            "intrinsic": intrinsic_confidence,
            "market_fit": float(market_fit.get("confidence") or 0.0),
            "profile_fit": float(profile_fit.get("confidence") or 0.0),
        },
        min_active_weight=0.45,
    )


def risk_penalty(row: Mapping[str, Any], profile: str) -> tuple[float, list[str], list[str]]:
    tilt = PROFILE_TILT.get(profile, PROFILE_TILT["balanced"])
    penalty = 0.0
    flags: list[str] = []
    warnings: list[str] = []
    atr_pct = _finite(row.get("atr_pct"))
    if atr_pct is not None and atr_pct > 7:
        penalty += 12
        flags.append("高波动")
        warnings.append(f"ATR约{atr_pct:.1f}%，波动风险高")
    elif atr_pct is not None and atr_pct > 5:
        penalty += 7
        flags.append("波动偏高")
    details = row.get("details") or {}
    gap200 = (details.get("snapshot") or {}).get("ma200_gap_pct")
    if gap200 is not None and float(gap200) <= 0:
        penalty += 8
        flags.append("低于200日线")
        warnings.append("长期趋势仍未修复")
    avg_turnover = _finite(row.get("avg_turnover_20d"))
    if avg_turnover is not None and avg_turnover < _LIQUIDITY_BASE_JPY * 1.4:
        penalty += 4
        flags.append("流动性边缘")
    drawdown = _finite(row.get("drawdown_63d_pct"))
    if drawdown is not None and drawdown < -22:
        penalty += 7
        flags.append("回撤较深")
    vol_price = details.get("vol_price") or {}
    # vol_price_match never emits `risk_penalty_adjustment`, so the previous read was
    # dead code and vacuum/absorption structures never actually reached the risk tier.
    # Fold the reported false-breakout risk in instead. This penalty feeds the risk
    # tier / classification (not the ranking score — the breakout family already nets
    # out false_breakout_risk), so there is no double count of the score.
    false_risk = _finite(vol_price.get("false_breakout_risk"), 0.0) or 0.0
    if false_risk > 0:
        penalty += min(false_risk, 12.0)
    setup_type = str(vol_price.get("setup_type") or "")
    if setup_type == "vacuum":
        flags.append("真空型")
        warnings.append("真空型收缩，假突破风险偏高")
    elif setup_type == "absorption_bearish":
        flags.append("空头吸收")
        warnings.append("空头吸收结构，向上突破需要更强确认")
    elif setup_type == "absorption_bullish":
        flags.append("多头吸收")
    return round(penalty * tilt["risk"], 1), flags, warnings


def classify(row: Mapping[str, Any], final_score: float | None, penalty: float) -> str:
    if final_score is None:
        return "数据不足"
    ma_alignment = _finite(row.get("ma_alignment_pct"))
    if final_score >= 78 and ma_alignment is not None and ma_alignment >= 66:
        return "质量趋势"
    if (
        final_score >= 70
        and (_finite(row.get("turnover_ratio")) or 0.0) >= 1.5
        and (_finite(row.get("ath_proximity")) or 0.0) >= 88
    ):
        return "放量突破"
    if final_score >= 64 and (_finite(row.get("rs_topix_63d")) or 0.0) > 0:
        return "相对强势"
    details = row.get("details") or {}
    rsi = _finite((details.get("technicals") or {}).get("rsi14"))
    if final_score >= 58 and rsi is not None and rsi < 52:
        return "回暖候选"
    if penalty >= 16:
        return "高风险题材"
    return "观察"


def _pct_rank(pairs: list[tuple[str, float]]) -> dict[str, float]:
    """中位順位法のパーセンタイル（米国版 _pct_rank と同一）。"""

    values = sorted(value for _, value in pairs)
    if len(values) <= 1:
        return {}
    denom = len(values) - 1
    ranks: dict[str, float] = {}
    for code, value in pairs:
        below = bisect_left(values, value)
        tied = bisect_right(values, value) - below
        ranks[code] = round((below + (tied - 1) / 2) / denom * 100, 1)
    return ranks


# ---------------------------------------------------------------------------
# 夜間ビルド
# ---------------------------------------------------------------------------


def build_strength_rows(
    *,
    trade_date: str,
    features_by_code: Mapping[str, Mapping[str, Any]],
    structure_by_code: Mapping[str, Mapping[str, Any]],
    securities: Mapping[str, Mapping[str, Any]],
    topix_return_63d: float | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for code, features in features_by_code.items():
        security = securities.get(code)
        if security is None:
            continue
        rs_topix = None
        if features.get("return_63d") is not None and topix_return_63d is not None:
            rs_topix = features["return_63d"] - topix_return_63d
        structure = structure_by_code.get(code) or {}
        intrinsic = score_intrinsic_jp(features, structure, rs_topix_63d=rs_topix)
        close = _finite(features.get("close"))
        atr = _finite(features.get("atr14"))
        atr_pct = (
            round(atr / close * 100.0, 2) if atr is not None and close and close > 0 else None
        )
        drawdown = _finite(features.get("drawdown_63d"))
        technicals = structure.get("technicals") or {}
        price_action = structure.get("price_action") or {}
        vol_price = structure.get("vol_price") or {}
        rows.append(
            {
                "canonical_code": code,
                "trade_date": trade_date,
                "intrinsic_score": intrinsic["score"],
                "confidence": intrinsic["confidence"],
                "score_short": intrinsic["score_short"],
                "score_mid": intrinsic["score_mid"],
                "score_long": intrinsic["score_long"],
                "trend_score": intrinsic["trend_score"],
                "breakout_quality_score": intrinsic["breakout_quality_score"],
                "price_action_score": intrinsic["price_action_score"],
                "close": close,
                "change_pct": (
                    round(features["return_1d"] * 100.0, 2)
                    if features.get("return_1d") is not None else None
                ),
                "atr_pct": atr_pct,
                "avg_turnover_20d": features.get("avg_turnover_20d"),
                "turnover_ratio": features.get("turnover_ratio"),
                "ath_proximity": intrinsic["ath_proximity"],
                "drawdown_63d_pct": (
                    round(drawdown * 100.0, 2) if drawdown is not None else None
                ),
                "ma_alignment_pct": intrinsic["ma_alignment_pct"],
                "rs_topix_63d": rs_topix,
                "market_code": security.get("market_code"),
                "sector33_code": security.get("sector33_code"),
                "details": {
                    "name_ja": security.get("name_ja"),
                    "name_en": security.get("name_en"),
                    "sector33_name": security.get("sector33_name"),
                    "market_name": security.get("market_name"),
                    "families": intrinsic["families"],
                    "effective_weights": intrinsic["effective_weights"],
                    "contributions": intrinsic["contributions"],
                    "missing_families": intrinsic["missing_families"],
                    "breakout_confirmed": intrinsic["breakout_confirmed"],
                    "follow_through": intrinsic["follow_through"],
                    "snapshot": {
                        "return_5d": features.get("return_5d"),
                        "return_20d": features.get("return_20d"),
                        "return_63d": features.get("return_63d"),
                        "return_126d": features.get("return_126d"),
                        "return_252d": features.get("return_252d"),
                        "ma25_gap_pct": features.get("ma25_gap_pct"),
                        "ma75_gap_pct": features.get("ma75_gap_pct"),
                        "ma200_gap_pct": features.get("ma200_gap_pct"),
                        "volatility_contraction": features.get("volatility_contraction"),
                        "data_days": features.get("data_days"),
                    },
                    "technicals": {
                        "rsi14": technicals.get("rsi14"),
                        "macd_direction_pct": (technicals.get("macd") or {}).get("direction_pct"),
                        "trend_efficiency_63d": technicals.get("trend_efficiency_63d"),
                        "ma50_slope_pct_21d": technicals.get("ma50_slope_pct_21d"),
                    },
                    "price_action": {
                        "structure": price_action.get("structure"),
                        "structure_label": price_action.get("structure_label"),
                        "pattern_labels": price_action.get("pattern_labels") or [],
                        "spring": bool(price_action.get("spring")),
                        "upthrust": bool(price_action.get("upthrust")),
                    },
                    "vol_price": {
                        "setup_type": vol_price.get("setup_type"),
                        "setup_label": vol_price.get("setup_label"),
                        "breakout_quality_adjustment": vol_price.get("breakout_quality_adjustment"),
                        "false_breakout_risk": vol_price.get("false_breakout_risk"),
                        "tags": (vol_price.get("tags") or [])[:3],
                    },
                },
            }
        )

    scored = [
        (row["canonical_code"], float(row["intrinsic_score"]))
        for row in rows
        if row["intrinsic_score"] is not None
    ]
    global_ranks = _pct_rank(scored)
    by_sector: dict[str, list[tuple[str, float]]] = {}
    for row in rows:
        if row["intrinsic_score"] is None:
            continue
        sector = str(row.get("sector33_code") or "")
        if sector:
            by_sector.setdefault(sector, []).append(
                (row["canonical_code"], float(row["intrinsic_score"]))
            )
    sector_ranks: dict[str, float] = {}
    for members in by_sector.values():
        sector_ranks.update(_pct_rank(members))
    for row in rows:
        code = row["canonical_code"]
        row["global_rank_percentile"] = global_ranks.get(code)
        row["sector_rank_percentile"] = sector_ranks.get(code)
    return rows


# ---------------------------------------------------------------------------
# 要求時ビュー（API から呼ばれる）
# ---------------------------------------------------------------------------


def tier_of(score: float) -> str:
    for name, floor in TIER_FLOORS:
        if score >= floor:
            return name
    return "D"


def tier_distribution(rows: list[Mapping[str, Any]], timeframe: str) -> dict[str, int]:
    field = f"score_{timeframe}" if timeframe in {"short", "mid", "long"} else "ranking_score"
    counts: dict[str, int] = {name: 0 for name, _ in TIER_FLOORS}
    counts["D"] = 0
    counts["unscored"] = 0
    for row in rows:
        score = _finite(row.get(field))
        if score is None:
            score = _finite(row.get("ranking_score"))
        if score is None:
            counts["unscored"] += 1
            continue
        counts[tier_of(score)] += 1
    counts["scored"] = len(rows) - counts["unscored"]
    counts["total"] = len(rows)
    return counts


def build_view_rows(
    stored_rows: list[dict[str, Any]],
    regime: Mapping[str, Any],
    *,
    profile: str,
) -> list[dict[str, Any]]:
    """保存済み intrinsic 行に market/profile/ranking/リスク/分類を重ねる。"""

    market_fit = score_market_fit(regime)
    view: list[dict[str, Any]] = []
    for row in stored_rows:
        profile_fit = score_profile_fit(row, profile)
        ranking = score_ranking(
            _score(row.get("intrinsic_score")),
            float(row.get("confidence") or 0.0),
            market_fit,
            profile_fit,
        )
        penalty, flags, warnings = risk_penalty(row, profile)
        ranking_score = _finite(ranking.get("score"))
        merged = dict(row)
        merged.update(
            ranking_score=round(ranking_score, 1) if ranking_score is not None else None,
            market_fit_score=(
                round(market_fit["score"], 1) if market_fit.get("score") is not None else None
            ),
            profile_fit_score=(
                round(profile_fit["score"], 1) if profile_fit.get("score") is not None else None
            ),
            ranking_confidence=float(ranking.get("confidence") or 0.0),
            risk_penalty=penalty,
            classification=classify(row, ranking_score, penalty),
        )
        merged["tags"], merged["reasons"], merged["warnings"] = _annotate(
            merged, flags, warnings, market_fit
        )
        view.append(merged)
    return view


def _annotate(
    row: Mapping[str, Any],
    risk_flags: list[str],
    warnings_in: list[str],
    market_fit: Mapping[str, Any],
) -> tuple[list[str], list[str], list[str]]:
    tags: list[str] = []
    reasons: list[str] = []
    warnings = list(warnings_in)
    details = row.get("details") or {}
    rs = _finite(row.get("rs_topix_63d"))
    if rs is not None and rs > 0:
        tags.append("相对TOPIX强")
        reasons.append("近3个月跑赢TOPIX")
    ath = _finite(row.get("ath_proximity"))
    if ath is not None and ath >= 90:
        tags.append("接近52周高位")
        reasons.append("价格接近一年高点区域")
    ratio = _finite(row.get("turnover_ratio"))
    if ratio is not None and ratio >= 1.5:
        tags.append("放量")
        reasons.append(f"成交额约为20日均额{ratio:.1f}倍")
    vol_price = details.get("vol_price") or {}
    for tag in (vol_price.get("tags") or [])[:2]:
        tags.append(str(tag))
    price_action = details.get("price_action") or {}
    if price_action.get("structure") == "uptrend":
        reasons.append("HH/HL 上升结构完好")
    elif price_action.get("spring"):
        reasons.append("Spring 假跌破后回收，结构偏多")
    elif price_action.get("structure") == "downtrend":
        warnings.append("LH/LL 下降结构未破坏")
    if price_action.get("upthrust"):
        warnings.append("前高假突破（Upthrust），追高需谨慎")
    ma_alignment = _finite(row.get("ma_alignment_pct"))
    if ma_alignment is not None and ma_alignment >= 66:
        tags.append("均线多头")
        reasons.append("价格位于关键均线上方")
    market_score = _finite(market_fit.get("score"))
    if market_score is not None and market_score >= 64:
        tags.append("市场顺风")
    elif market_score is not None and market_score < 40:
        tags.append("弱市降权")
    elif market_score is None:
        warnings.append("市场行情不足，市场维度暂不计入评分")
    tags.extend(risk_flags[:2])
    if not reasons:
        reasons.append(
            "可用价格证据已完成评分"
            if row.get("intrinsic_score") is not None
            else "价格证据不足，暂不生成强势结论"
        )
    seen: dict[str, None] = {}
    for tag in tags:
        seen.setdefault(tag, None)
    return list(seen)[:6], reasons[:4], list(dict.fromkeys(warnings))[:5]


def sort_view_rows(rows: list[dict[str, Any]], timeframe: str) -> None:
    if timeframe in {"short", "mid", "long"}:
        key = f"score_{timeframe}"
        rows.sort(
            key=lambda item: (
                item.get(key) is not None,
                (_finite(item.get(key)) or 0.0) * 0.94
                + (_finite(item.get("ranking_score")) or 0.0) * 0.06,
                item.get("canonical_code") or "",
            ),
            reverse=True,
        )
        return
    rows.sort(
        key=lambda item: (
            item.get("ranking_score") is not None,
            _finite(item.get("ranking_score")) or 0.0,
            item.get("canonical_code") or "",
        ),
        reverse=True,
    )


__all__ = [
    "PROFILES",
    "STRENGTH_SCORE_VERSION",
    "TIMEFRAMES",
    "build_strength_rows",
    "build_view_rows",
    "compute_market_regime_jp",
    "score_intrinsic_jp",
    "sort_view_rows",
    "tier_distribution",
    "tier_of",
    "weighted_available",
]
