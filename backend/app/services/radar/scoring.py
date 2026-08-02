"""Missing-aware weighted scoring (ported kernel, Japan-calibrated weights).

The kernel never substitutes a neutral 50 for missing data: absent
components leave the weight pool, remaining weights renormalize, and the
result carries its own confidence (= active weight share). Below the
minimum active weight the score is honestly ``None`` with
``insufficient_data`` status.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

SCORE_VERSION = "jp-radar-score-v1"
MIN_ACTIVE_WEIGHT = 0.25


@dataclass(frozen=True)
class WeightedScore:
    score: float | None
    confidence: float
    status: str
    effective_weights: dict[str, float] = field(default_factory=dict)
    contributions: dict[str, float] = field(default_factory=dict)
    missing: tuple[str, ...] = ()


def weighted_score(components: Mapping[str, float | None], weights: Mapping[str, float]) -> WeightedScore:
    configured = sum(weights.values())
    if configured <= 0.0:
        return WeightedScore(None, 0.0, "no_weights")
    active: dict[str, float] = {}
    missing: list[str] = []
    for name, weight in weights.items():
        value = components.get(name)
        if value is None:
            missing.append(name)
            continue
        active[name] = float(weight)
    active_weight = sum(active.values())
    confidence = active_weight / configured
    if not active or confidence < MIN_ACTIVE_WEIGHT:
        return WeightedScore(None, round(confidence, 4), "insufficient_data", missing=tuple(missing))
    effective = {name: weight / active_weight for name, weight in active.items()}
    contributions = {
        name: round(effective[name] * float(components[name]), 4) for name in effective
    }
    score = sum(contributions.values())
    return WeightedScore(
        score=round(min(100.0, max(0.0, score)), 2),
        confidence=round(confidence, 4),
        status="ok",
        effective_weights={k: round(v, 4) for k, v in effective.items()},
        contributions=contributions,
        missing=tuple(missing),
    )


def clamp_score(value: float | None) -> float | None:
    if value is None:
        return None
    return round(min(100.0, max(0.0, float(value))), 2)


def linear_score(value: float | None, low: float, high: float) -> float | None:
    """Map value linearly onto 0..100 between low→0 and high→100."""

    if value is None or high == low:
        return None
    position = (float(value) - low) / (high - low)
    return clamp_score(position * 100.0)


# ---------------------------------------------------------------------------
# Dimension weights — Japan calibration
# ---------------------------------------------------------------------------

TREND_WEIGHTS = {
    "ma_alignment": 0.30,
    "above_ma75": 0.20,
    "return_63d_score": 0.30,
    "trend_persistence": 0.20,
}

BASE_WEIGHTS = {
    "tightness": 0.35,
    "duration": 0.20,
    "contraction": 0.25,
    "position_in_base": 0.20,
}

CONFIRMATION_WEIGHTS = {
    "close_location": 0.25,
    "turnover_surge": 0.30,
    "breakout_margin": 0.25,
    "hold_days": 0.20,
}

RELATIVE_STRENGTH_WEIGHTS = {
    "rs_topix": 0.60,
    "rs_sector": 0.40,
}

PARTICIPATION_WEIGHTS = {
    "turnover_ratio_score": 0.60,
    "turnover_trend": 0.40,
}

LIQUIDITY_WEIGHTS = {
    "avg_turnover_score": 0.70,
    "turnover_stability": 0.30,
}

PRIORITY_WEIGHTS = {
    "breakout_quality": 0.34,
    "relative_strength": 0.22,
    "market_fit": 0.12,
    "sector_fit": 0.10,
    "participation": 0.12,
    "data_confidence": 0.10,
}

# Penalties are bounded so a single risk dimension cannot zero out an event.
CHASE_PENALTY_RATE = 0.25   # per point of chase risk above 50
CROWDING_PENALTY_RATE = 0.15


def alert_priority(
    *,
    breakout_quality: float | None,
    relative_strength: float | None,
    market_fit: float | None,
    sector_fit: float | None,
    participation: float | None,
    data_confidence: float | None,
    chase_risk: float | None,
    crowding_risk: float | None,
) -> WeightedScore:
    base = weighted_score(
        {
            "breakout_quality": breakout_quality,
            "relative_strength": relative_strength,
            "market_fit": market_fit,
            "sector_fit": sector_fit,
            "participation": participation,
            "data_confidence": data_confidence,
        },
        PRIORITY_WEIGHTS,
    )
    if base.score is None:
        return base
    penalty = 0.0
    if chase_risk is not None and chase_risk > 50.0:
        penalty += CHASE_PENALTY_RATE * (chase_risk - 50.0)
    if crowding_risk is not None and crowding_risk > 50.0:
        penalty += CROWDING_PENALTY_RATE * (crowding_risk - 50.0)
    return WeightedScore(
        score=clamp_score(base.score - penalty),
        confidence=base.confidence,
        status=base.status,
        effective_weights=base.effective_weights,
        contributions={**base.contributions, "penalty": round(-penalty, 4)},
        missing=base.missing,
    )


__all__ = [
    "BASE_WEIGHTS",
    "CONFIRMATION_WEIGHTS",
    "LIQUIDITY_WEIGHTS",
    "MIN_ACTIVE_WEIGHT",
    "PARTICIPATION_WEIGHTS",
    "PRIORITY_WEIGHTS",
    "RELATIVE_STRENGTH_WEIGHTS",
    "SCORE_VERSION",
    "TREND_WEIGHTS",
    "WeightedScore",
    "alert_priority",
    "clamp_score",
    "linear_score",
    "weighted_score",
]
