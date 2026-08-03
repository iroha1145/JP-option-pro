"""市場状態の門: 迟滞が本当に効くか、欠損を中立に丸めないか。

移植の狙いは「状態が日替わりしないこと」なので、そこを主に突く。
"""

from __future__ import annotations

from app.services import market_shape_jp as ms


def _regime(**overrides) -> dict:
    base = {
        "index_trend": 75.0, "momentum": 60.0, "breadth": 60.0,
        "risk_on_spread": 55.0, "score": 65.0,
    }
    base.update(overrides)
    return base


def _series(states: list[dict], start_day: int = 1) -> list[tuple[str, dict]]:
    return [
        (f"2026-03-{start_day + index:02d}", regime)
        for index, regime in enumerate(states)
    ]


# ---------------------------------------------------------------------------
# 1. 生の分類
# ---------------------------------------------------------------------------


def test_classifies_the_six_states():
    cases = {
        ms.STATE_BULL_TREND: _regime(),
        ms.STATE_BEAR_TREND: _regime(index_trend=25.0, momentum=30.0, score=35.0, breadth=40.0),
        ms.STATE_BULL_PULLBACK: _regime(index_trend=62.0, momentum=42.0, score=55.0),
        ms.STATE_CAPITULATION_RECOVERY: _regime(
            index_trend=45.0, momentum=60.0, breadth=30.0, score=48.0
        ),
        ms.STATE_RANGE_ACCUMULATION: _regime(
            index_trend=52.0, momentum=52.0, breadth=52.0, score=55.0
        ),
    }
    for expected, regime in cases.items():
        state, missing = ms.classify_state(regime)
        assert state == expected, f"{expected} を {state} と判定した"
        assert missing == []


def test_missing_inputs_produce_none_not_a_neutral_state():
    """材料が無い日を「レンジ」に丸めない（分からないと言う）。"""

    state, missing = ms.classify_state({"index_trend": None, "momentum": 50.0})
    assert state is None
    assert "index_trend" in missing and "breadth" in missing


# ---------------------------------------------------------------------------
# 2. 迟滞 —— これが移植の主目的
# ---------------------------------------------------------------------------


def test_a_single_off_day_does_not_flip_the_state():
    """1 日のブレで判定基準が入れ替わらないこと。

    状態が確認要求を左右する以上、状態が揺れると基準そのものが日替わりになる。
    """

    bear = _regime(index_trend=25.0, momentum=30.0, score=35.0, breadth=40.0)
    days = _series([_regime(), _regime(), _regime(), bear, _regime(), _regime()])

    result = ms.replay_shape(days)
    assert result.state == ms.STATE_BULL_TREND, "1 日の外れ値で状態が変わった"
    assert result.raw_state == ms.STATE_BULL_TREND


def test_a_sustained_change_does_flip_the_state():
    """本物の転換は通す（迟滞は変化を止める仕組みではない）。"""

    bear = _regime(index_trend=25.0, momentum=30.0, score=35.0, breadth=40.0)
    days = _series([_regime()] * 4 + [bear] * 6)

    result = ms.replay_shape(days)
    assert result.state == ms.STATE_BEAR_TREND


def test_minimum_dwell_blocks_an_immediate_second_flip():
    """採用直後にまた変わろうとしても、最短滞在日数までは動かない。"""

    bear = _regime(index_trend=25.0, momentum=30.0, score=35.0, breadth=40.0)
    # 弱気に転換 → すぐに強気の日が来る
    days = _series([_regime()] * 4 + [bear] * 5 + [_regime()] * 2)

    result = ms.replay_shape(days, hysteresis=ms.Hysteresis(min_dwell_days=5))
    assert result.state == ms.STATE_BEAR_TREND, "最短滞在を無視して戻った"


def test_missing_days_neither_advance_nor_reset_the_state():
    broken = {"index_trend": None, "momentum": None, "breadth": None, "score": None}
    days = _series([_regime()] * 4 + [broken] * 3 + [_regime()] * 2)

    result = ms.replay_shape(days)
    assert result.state == ms.STATE_BULL_TREND
    assert result.missing == []      # 最後の日は取れている


def test_empty_history_yields_no_state():
    result = ms.replay_shape([])
    assert result.state is None
    assert result.gate() == ms.Gate()   # 既定の門（何も変えない）


# ---------------------------------------------------------------------------
# 3. 門は確認要求を変え、スコアは変えない
# ---------------------------------------------------------------------------


def test_weak_regimes_demand_more_confirmation():
    """doc §七: 震荡・転換局面では初日突破の重みを下げ、保ちと出来高を要求する。"""

    base_days, base_ratio = 2, 2.5

    bull_days, bull_ratio = ms.apply_gate(
        gate=ms.STATE_GATES[ms.STATE_BULL_TREND],
        confirm_hold_days=base_days, strong_turnover_ratio=base_ratio,
    )
    bear_days, bear_ratio = ms.apply_gate(
        gate=ms.STATE_GATES[ms.STATE_BEAR_TREND],
        confirm_hold_days=base_days, strong_turnover_ratio=base_ratio,
    )
    dist_days, dist_ratio = ms.apply_gate(
        gate=ms.STATE_GATES[ms.STATE_RANGE_DISTRIBUTION],
        confirm_hold_days=base_days, strong_turnover_ratio=base_ratio,
    )

    assert bull_days == base_days and bull_ratio == base_ratio
    assert bear_days > dist_days > bull_days, "下降局面ほど厳しくなっていない"
    assert bear_ratio > dist_ratio > bull_ratio


def test_single_day_confirmation_is_disallowed_in_weak_states():
    for state in (ms.STATE_RANGE_DISTRIBUTION, ms.STATE_BEAR_TREND,
                  ms.STATE_CAPITULATION_RECOVERY):
        days, _ratio = ms.apply_gate(
            gate=ms.STATE_GATES[state], confirm_hold_days=1, strong_turnover_ratio=2.5
        )
        assert days >= 2, f"{state} で初日突破がそのまま通る"


def test_bear_and_recovery_damp_pure_momentum():
    assert ms.STATE_GATES[ms.STATE_BEAR_TREND].damp_momentum is True
    assert ms.STATE_GATES[ms.STATE_CAPITULATION_RECOVERY].damp_momentum is True
    assert ms.STATE_GATES[ms.STATE_BULL_TREND].damp_momentum is False


def test_gates_are_declared_unvalidated():
    """歴史検証を通るまで「日本株の最適パラメータ」と称さない（doc §十五）。"""

    assert ms.GATES_VALIDATED is False
    payload = ms.replay_shape(_series([_regime()] * 3)).as_dict()
    assert payload["gates_validated"] is False


def test_every_state_has_a_gate():
    for state in ms.ALL_STATES:
        assert state in ms.STATE_GATES, f"{state} に門が無い"
        assert state in ms.STATE_LABELS
