"""A0 math through the production ranking module, not a copied helper."""

from __future__ import annotations

import math

import pytest

from app.services.a0_ranking import a0_family_score, a0_request_can_score, apply_a0_mid_long
from app.services.algorithm_modes import (
    A0_ALGORITHM,
    A0_SCORE_BASIS,
    A0_VERSION,
    ConflictingAlgorithmError,
    UnknownAlgorithmError,
    resolve_screener_algorithm,
)


def test_a0_is_exact_half_mid_half_long():
    assert a0_family_score({"score_mid": 80, "score_long": 60}) == 70.0
    assert a0_family_score({"score_mid": 0, "score_long": 0}) == 0.0


def test_a0_zero_is_legal_and_ranks_before_missing():
    rows = apply_a0_mid_long(
        [
            {"canonical_code": "B0000", "score_mid": 0, "score_long": 0},
            {"canonical_code": "A0000", "score_mid": None, "score_long": 90},
        ]
    )
    assert rows[0]["canonical_code"] == "B0000"
    assert rows[0]["a0_score"] == 0.0
    assert rows[0]["a0_available"] is True
    assert rows[1]["a0_available"] is False
    assert rows[1]["sort_score"] is None


@pytest.mark.parametrize("mid,long", [(None, 50), (50, None), (math.nan, 50), (50, math.inf)])
def test_a0_does_not_fill_none_nan_inf(mid, long):
    assert a0_family_score({"score_mid": mid, "score_long": long}) is None


def test_a0_all_missing_is_unavailable_but_still_a0_sorted():
    rows = [
        {"canonical_code": "Z9990", "score_mid": None, "score_long": None},
        {"canonical_code": "A1110", "score_mid": math.nan, "score_long": 10},
    ]
    assert a0_request_can_score(rows) is False
    ranked = apply_a0_mid_long(rows)
    assert [item["sort_algorithm"] for item in ranked] == [A0_ALGORITHM, A0_ALGORITHM]
    assert all(item["sort_basis"] == A0_SCORE_BASIS for item in ranked)
    assert all(item["sort_algorithm_version"] == A0_VERSION for item in ranked)
    assert [item["canonical_code"] for item in ranked] == ["Z9990", "A1110"]


def test_a0_tie_break_is_score_then_code_desc():
    ranked = apply_a0_mid_long(
        [
            {"canonical_code": "11110", "score_mid": 80, "score_long": 80},
            {"canonical_code": "99990", "score_mid": 80, "score_long": 80},
            {"canonical_code": "55550", "score_mid": 90, "score_long": 90},
        ]
    )
    assert [item["canonical_code"] for item in ranked] == ["55550", "99990", "11110"]
    assert [item["selected_view_rank"] for item in ranked] == [1, 2, 3]


def test_explicit_a0_on_unsupported_view_errors():
    with pytest.raises(ConflictingAlgorithmError):
        resolve_screener_algorithm(
            requested=A0_ALGORITHM,
            timeframe="mid",
            profile="balanced",
            explicit_request=True,
        )
    with pytest.raises(UnknownAlgorithmError):
        resolve_screener_algorithm(requested="us-a0-mid-long-v1")


def test_implicit_a0_falls_back_on_unsupported_view():
    resolution = resolve_screener_algorithm(
        user_choice=A0_ALGORITHM,
        timeframe="short",
        profile="aggressive",
    )
    assert resolution.effective == "production"
    assert resolution.fallback_reason == "incompatible_view"
