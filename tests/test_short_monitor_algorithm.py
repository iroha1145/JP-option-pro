"""因子・状態機・評分。指令書 §十七「算法」の各項目に対応する。"""

import pytest

from app.services.short_monitor import factors as f
from app.services.short_monitor import scoring, states


# -- 圧力の正規化 -----------------------------------------------------------

def test_pressure_is_measured_against_liquidity_not_ratio_alone():
    """同じ比率変化でも、日常の出来高に対する大きさが違えば意味が違う。"""

    liquid = f.short_pressure(shares_change=100_000, adv20_shares=5_000_000)
    thin = f.short_pressure(shares_change=100_000, adv20_shares=200_000)
    assert thin["pressure_adv20"] > liquid["pressure_adv20"]
    assert thin["score"] > liquid["score"]


def test_pressure_is_unknown_without_liquidity():
    assert f.short_pressure(shares_change=100_000, adv20_shares=None)["score"] is None
    assert f.short_pressure(shares_change=100_000, adv20_shares=0)["known"] is False


def test_pressure_saturates_instead_of_exploding():
    """1 社の巨大報告がスケール全体を支配しないこと。"""

    big = f.short_pressure(shares_change=50_000_000, adv20_shares=100_000)
    assert big["score"] <= 100.0
    assert abs(big["pressure_adv20"]) <= f.WINSOR_LIMIT


# -- 吸収 -------------------------------------------------------------------

def test_no_absorption_verdict_below_the_minimum_pressure():
    """圧力が小さいときに「吸収された」と言わない（小さい分母で割らない）。"""

    tiny = f.DamageInput(pressure_adv20=0.005, rel_topix=0.02, rel_sector=0.02)
    assert tiny.raw_damage() is None


def test_damage_uses_the_weaker_of_market_and_sector():
    """都合のいいほうを選ばない。"""

    both = f.DamageInput(pressure_adv20=0.5, rel_topix=0.05, rel_sector=-0.05)
    assert both.raw_damage() > 0


def test_shorting_plus_underperformance_reads_as_effective_pressure():
    hurt = f.DamageInput(pressure_adv20=0.5, rel_topix=-0.10, rel_sector=-0.08)
    held = f.DamageInput(pressure_adv20=0.5, rel_topix=0.01, rel_sector=0.01)
    assert hurt.raw_damage() > held.raw_damage()


def test_absorption_is_discounted_while_the_stock_still_makes_new_lows():
    """安値を更新している間は「吸収」と呼ばない。"""

    holding = f.absorption_from_percentile(0.1, made_new_low=False, consistent=True)
    falling = f.absorption_from_percentile(0.1, made_new_low=True, consistent=True)
    assert falling["absorption_score"] < holding["absorption_score"]


def test_absorption_is_discounted_when_windows_disagree():
    consistent = f.absorption_from_percentile(0.1, made_new_low=False, consistent=True)
    noisy = f.absorption_from_percentile(0.1, made_new_low=False, consistent=False)
    assert noisy["absorption_score"] < consistent["absorption_score"]


# -- 回補 -------------------------------------------------------------------

def test_covering_counts_only_reported_reductions():
    result = f.covering(shares_change=-500_000, adv20_shares=1_000_000, reducing_institutions=3)
    assert result["visible_covering_adv20"] == pytest.approx(0.5)
    assert result["score"] > 0


def test_increasing_shorts_produce_no_covering():
    result = f.covering(shares_change=+500_000, adv20_shares=1_000_000)
    assert result["visible_covering_adv20"] == 0.0


def test_covering_concentrated_in_one_institution_scores_lower():
    spread = f.covering(shares_change=-500_000, adv20_shares=1_000_000, reducing_institutions=4)
    single = f.covering(
        shares_change=-500_000, adv20_shares=1_000_000, reducing_institutions=1, concentrated=True,
    )
    assert single["score"] < spread["score"]


def test_visible_days_to_cover_is_named_and_bounded():
    assert f.visible_days_to_cover(2_000_000, 1_000_000) == pytest.approx(2.0)
    assert f.visible_days_to_cover(None, 1_000_000) is None
    assert f.visible_days_to_cover(1_000_000, 0) is None


# -- 機関の入れ替わり -------------------------------------------------------

def test_rotation_requires_both_sides_moving():
    both = f.rotation(entries=2, reentries=1, exits=3, reductions=3, concentration=0.3)
    one_sided = f.rotation(entries=3, reentries=0, exits=0, reductions=0, concentration=0.3)
    assert both["score"] > one_sided["score"]
    assert both["balanced"] is True
    assert one_sided["balanced"] is False


# -- 信用環境 ---------------------------------------------------------------

def test_crowded_retail_margin_raises_risk():
    """機関空頭が多く、かつ信用買いも極端に混雑 = 単純な踏み上げ候補ではない。"""

    calm = f.margin_environment(
        margin_long=1_000_000, margin_short=500_000, margin_long_change=0,
        adv20_shares=2_000_000,
    )
    crowded = f.margin_environment(
        margin_long=20_000_000, margin_short=500_000, margin_long_change=3_000_000,
        adv20_shares=2_000_000,
    )
    assert crowded["score"] > calm["score"]
    assert crowded["crowded_long"] is True


def test_regulation_adds_risk():
    plain = f.margin_environment(
        margin_long=1_000_000, margin_short=500_000, margin_long_change=0, adv20_shares=2_000_000,
    )
    regulated = f.margin_environment(
        margin_long=1_000_000, margin_short=500_000, margin_long_change=0,
        adv20_shares=2_000_000, regulation_severity=4,
    )
    assert regulated["score"] > plain["score"]


# -- 信頼度 -----------------------------------------------------------------

def test_confidence_falls_with_staleness_and_thinness():
    fresh = f.data_confidence(
        mapping_confidence=1.0, visible_institution_count=4,
        days_since_last_report=3, bars_available=500, adv20_value=5_000_000_000,
    )
    stale = f.data_confidence(
        mapping_confidence=0.75, visible_institution_count=1,
        days_since_last_report=90, bars_available=40, adv20_value=10_000_000,
    )
    assert fresh["confidence"] > stale["confidence"]
    assert "stale_over_60_trading_days" in stale["reasons"]
    assert "thin_liquidity" in stale["reasons"]


def test_no_visible_institution_is_not_treated_as_safe():
    result = f.data_confidence(
        mapping_confidence=1.0, visible_institution_count=0,
        days_since_last_report=5, bars_available=500,
    )
    assert result["confidence"] < 0.5
    assert "no_visible_institution" in result["reasons"]


# -- 催化剂 -----------------------------------------------------------------

def test_missing_catalyst_is_absent_not_neutral():
    """ニュースが無いことを「中立の催化剂」として点にしない。"""

    none = f.catalyst(trading_days_to_earnings=None, news_count_5d=0)
    assert none["score"] is None
    near = f.catalyst(trading_days_to_earnings=2, news_count_5d=1)
    assert near["score"] > 0


# -- 状態機 -----------------------------------------------------------------

def _evidence(**overrides):
    base = {
        "pressure_adv20_20d": 0.0, "pressure_adv20_5d": 0.0,
        "absorption_score": None, "covering_score": None, "low_position_score": 20.0,
        "rotation_score": 0.0, "visible_days_to_cover": None,
        "rel_topix_20d": 0.0, "rel_sector_20d": 0.0,
        "breakout_confirmed": False, "turnover_confirmed": False,
        "made_new_low": False, "broke_long_support": False,
        "data_confidence": 0.9, "visible_institution_count": 3,
    }
    base.update(overrides)
    return base


def test_shorting_into_a_falling_stock_is_normal_shorting():
    result = states.classify(_evidence(
        pressure_adv20_20d=0.30, pressure_adv20_5d=0.20,
        rel_topix_20d=-0.09, rel_sector_20d=-0.08, absorption_score=20.0,
    ))
    assert result["primary_state"] == states.STATE_NORMAL_SHORTING


def test_shorting_that_does_not_move_the_price_is_absorption():
    result = states.classify(_evidence(
        pressure_adv20_20d=0.30, pressure_adv20_5d=0.20,
        rel_topix_20d=0.01, rel_sector_20d=0.01, absorption_score=78.0,
    ))
    assert result["primary_state"] == states.STATE_ABSORPTION


def test_absorption_is_not_claimed_while_making_new_lows():
    result = states.classify(_evidence(
        pressure_adv20_20d=0.30, pressure_adv20_5d=0.20,
        rel_topix_20d=-0.02, rel_sector_20d=-0.02, absorption_score=78.0,
        made_new_low=True,
    ))
    assert result["primary_state"] != states.STATE_ABSORPTION


def test_covering_while_the_price_still_falls_is_not_covering_start():
    """减空但股价继续下跌 —— 回補確認とは呼べない。"""

    result = states.classify(_evidence(
        pressure_adv20_20d=-0.30, pressure_adv20_5d=-0.20,
        covering_score=70.0, rel_topix_20d=-0.06, rel_sector_20d=-0.05,
    ))
    assert result["primary_state"] not in (
        states.STATE_COVERING_START, states.STATE_SQUEEZE_CONFIRMED,
    )


def test_covering_with_strength_is_covering_start_without_requiring_a_breakout():
    result = states.classify(_evidence(
        pressure_adv20_20d=-0.30, pressure_adv20_5d=-0.20,
        covering_score=70.0, rel_topix_20d=0.04, rel_sector_20d=0.03,
    ))
    assert result["primary_state"] == states.STATE_COVERING_START


def test_squeeze_requires_every_condition_at_once():
    strict = dict(
        pressure_adv20_20d=-0.40, pressure_adv20_5d=-0.30, covering_score=80.0,
        visible_days_to_cover=2.5, breakout_confirmed=True, turnover_confirmed=True,
        rel_topix_20d=0.06, rel_sector_20d=0.05,
    )
    assert states.classify(_evidence(**strict))["primary_state"] == states.STATE_SQUEEZE_CONFIRMED

    for missing in ("breakout_confirmed", "turnover_confirmed"):
        weakened = dict(strict)
        weakened[missing] = False
        assert states.classify(_evidence(**weakened))["primary_state"] != states.STATE_SQUEEZE_CONFIRMED

    thin = dict(strict)
    thin["visible_days_to_cover"] = 0.2
    assert states.classify(_evidence(**thin))["primary_state"] != states.STATE_SQUEEZE_CONFIRMED


def test_shorting_into_a_breakdown_is_divergence_failed():
    result = states.classify(_evidence(
        pressure_adv20_20d=0.30, pressure_adv20_5d=0.25,
        broke_long_support=True, rel_topix_20d=-0.12, rel_sector_20d=-0.10,
    ))
    assert result["primary_state"] == states.STATE_DIVERGENCE_FAILED


def test_deep_low_without_short_activity_produces_no_signal():
    """深度低位だが空頭に動きが無い → 機関空売りの信号は出さない。"""

    result = states.classify(_evidence(
        low_position_score=85.0, pressure_adv20_20d=0.0, pressure_adv20_5d=0.0,
        entry_count_20d=0, reentry_count_20d=0,
    ))
    assert result["primary_state"] == states.STATE_NO_SIGNAL


def test_deep_low_with_new_entries_is_low_conflict():
    result = states.classify(_evidence(
        low_position_score=85.0, pressure_adv20_20d=0.01, pressure_adv20_5d=0.01,
        entry_count_20d=1, reentry_count_20d=1,
    ))
    assert result["primary_state"] == states.STATE_LOW_CONFLICT


def test_tiny_short_changes_do_not_trigger_a_state():
    result = states.classify(_evidence(pressure_adv20_20d=0.005, pressure_adv20_5d=0.004))
    assert result["primary_state"] == states.STATE_NO_SIGNAL


def test_low_confidence_downgrades_strong_claims_but_keeps_the_labels():
    result = states.classify(_evidence(
        pressure_adv20_20d=-0.40, pressure_adv20_5d=-0.30, covering_score=80.0,
        visible_days_to_cover=2.5, breakout_confirmed=True, turnover_confirmed=True,
        rel_topix_20d=0.06, rel_sector_20d=0.05, data_confidence=0.2,
        threshold_exit_count_20d=2,
    ))
    assert result["primary_state"] != states.STATE_SQUEEZE_CONFIRMED
    assert states.FLAG_BELOW_THRESHOLD in result["flags"]
    assert states.FLAG_STALE_DATA in result["flags"]


def test_rotation_is_a_label_not_a_state():
    result = states.classify(_evidence(
        pressure_adv20_20d=0.30, pressure_adv20_5d=0.20, absorption_score=78.0,
        rel_topix_20d=0.01, rotation_score=70.0, entry_count_20d=2,
    ))
    assert result["primary_state"] == states.STATE_ABSORPTION
    assert states.FLAG_ROTATION in result["flags"]
    assert states.FLAG_NEW_ENTRY in result["flags"]


def test_gates_are_marked_unvalidated():
    assert states.GATES_VALIDATED is False
    assert scoring.SCORE_VALIDATED is False


# -- 評分 -------------------------------------------------------------------

def test_missing_components_are_dropped_not_zeroed():
    """欠測を 0 で埋めると「データが無い」が「悪い」に化ける。"""

    partial = scoring.behavior_score({"absorption": 80.0, "low_position": 70.0})
    zeroed = scoring.behavior_score({
        "absorption": 80.0, "low_position": 70.0, "covering": 0.0,
        "short_pressure": 0.0, "rotation": 0.0, "catalyst": 0.0,
    })
    assert partial["raw_score"] > zeroed["raw_score"]
    assert partial["coverage"] < 1.0


def test_risk_penalty_moves_the_final_score():
    """減点が順位に効くこと（表示だけの飾りにしない）。"""

    clean = scoring.behavior_score({"absorption": 80.0, "covering": 70.0, "risk": 0.0})
    risky = scoring.behavior_score({"absorption": 80.0, "covering": 70.0, "risk": 100.0})
    assert risky["score"] < clean["score"]
    assert risky["raw_score"] == clean["raw_score"]
    assert risky["risk_penalty"] == pytest.approx(scoring.MAX_RISK_PENALTY)


def test_priority_discounts_low_confidence():
    trusted = scoring.monitor_priority(80.0, 1.0)
    doubtful = scoring.monitor_priority(80.0, 0.2)
    assert doubtful < trusted
    assert doubtful > 0.0, "存在は見えるが上には来ない、という扱いにする"


def test_score_is_none_when_nothing_is_known():
    assert scoring.behavior_score({})["score"] is None
