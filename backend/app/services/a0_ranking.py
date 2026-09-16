"""Optional A0 ranking over already-computed Japan family scores.

A0 does not recompute RSI, eligibility, family weights, or the original
ranking mix. It is a request-time sort of the saved full pool.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

from app.services.algorithm_modes import A0_ALGORITHM, A0_SCORE_BASIS, A0_VERSION


def _finite_score(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def production_tiebreak_sort_key(score: float | None, canonical_code: str) -> tuple[bool, float, str]:
    """Match ``sort_view_rows`` for timeframe=all: usable first, score desc, code desc."""

    return (score is not None, score if score is not None else -1.0, canonical_code)


def a0_family_score(row: Mapping[str, Any]) -> float | None:
    """Equal-weight mid/long family scores. Missing or non-finite stays missing.

    This is not the mid/long page view key (94% family + 6% ranking_score).
    Zero is a valid score. NaN/Inf/None are not coerced to zero or 50.
    """

    mid = _finite_score(row.get("score_mid"))
    long = _finite_score(row.get("score_long"))
    if mid is None or long is None:
        return None
    return round(0.5 * mid + 0.5 * long, 6)


def annotate_a0_row(row: Mapping[str, Any]) -> dict[str, Any]:
    item = dict(row)
    score = a0_family_score(item)
    item["a0_score"] = score
    item["sort_score"] = score
    item["sort_basis"] = A0_SCORE_BASIS
    item["sort_algorithm"] = A0_ALGORITHM
    item["sort_algorithm_version"] = A0_VERSION
    item["a0_available"] = score is not None
    return item


def annotate_production_row(row: Mapping[str, Any]) -> dict[str, Any]:
    item = dict(row)
    score = _finite_score(item.get("final_ranking_score"))
    if score is None:
        score = _finite_score(item.get("ranking_score"))
    item["sort_score"] = score
    item["sort_basis"] = "final_ranking_score"
    item["sort_algorithm"] = "production"
    item["sort_algorithm_version"] = item.get("score_version") or "jp-strength-v1"
    item["a0_available"] = False
    return item


def apply_a0_mid_long(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Sort the full eligible pool by A0, then assign contiguous ranks.

    Rows that cannot compute A0 stay visible after every scored row. They are
    not filled with ranking_score and are not dropped.
    """

    copies = [annotate_a0_row(row) for row in rows]
    copies.sort(
        key=lambda item: production_tiebreak_sort_key(
            _finite_score(item.get("sort_score")),
            str(item.get("canonical_code") or ""),
        ),
        reverse=True,
    )
    for rank, item in enumerate(copies, start=1):
        item["selected_view_rank"] = rank
    return copies


def a0_request_can_score(rows: list[Mapping[str, Any]]) -> bool:
    return any(a0_family_score(row) is not None for row in rows)
