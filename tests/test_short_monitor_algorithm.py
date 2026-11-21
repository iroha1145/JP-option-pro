"""因子・状態機。指令書 §十七「算法」のうち、v4（sbf-v3 / sbs-v4）でも残る項目。

v4 で合成分数（吸収・回補・轮換・催化・行動分・監視優先度）と旧 6 状態の閘門は
廃止した。ここにはそれらのテストは無い。残るのは事実の列（出来高比の圧力・
回補日数・信用環境）、データ信頼度、5 状態の分類と補助ラベル。
"""

import pytest

from app.services.short_monitor import factors as f
from app.services.short_monitor import states


# -- 圧力の正規化 -----------------------------------------------------------

def test_pressure_is_measured_against_liquidity_not_ratio_alone():
    """同じ比率変化でも、日常の出来高に対する大きさが違えば意味が違う。"""

    liquid = f.short_pressure(shares_change=100_000, adv20_shares=5_000_000)
    thin = f.short_pressure(shares_change=100_000, adv20_shares=200_000)
    assert thin["pressure_adv20"] > liquid["pressure_adv20"]
    assert "score" not in thin, "v4 は合成点数を返さない"


def test_pressure_is_unknown_without_liquidity():
    assert f.short_pressure(shares_change=100_000, adv20_shares=None)["pressure_adv20"] is None
    assert f.short_pressure(shares_change=100_000, adv20_shares=0)["known"] is False


def test_pressure_saturates_instead_of_exploding():
    """1 社の巨大報告がスケール全体を支配しないこと。"""

    big = f.short_pressure(shares_change=50_000_000, adv20_shares=100_000)
    assert abs(big["pressure_adv20"]) <= f.WINSOR_LIMIT


def test_visible_days_to_cover_is_named_and_bounded():
    assert f.visible_days_to_cover(2_000_000, 1_000_000) == pytest.approx(2.0)
    assert f.visible_days_to_cover(None, 1_000_000) is None
    assert f.visible_days_to_cover(1_000_000, 0) is None


# -- 信用環境 ---------------------------------------------------------------

def test_crowded_retail_margin_is_reported_as_a_fact():
    """機関空頭が多く、かつ信用買いも極端に混雑 = 単純な踏み上げ候補ではない。
    v4 は点数にせず、`crowded_long` という事実の印だけを返す。"""

    calm = f.margin_environment(
        margin_long=1_000_000, margin_short=500_000, adv20_shares=2_000_000,
    )
    crowded = f.margin_environment(
        margin_long=20_000_000, margin_short=500_000, adv20_shares=2_000_000,
    )
    assert crowded["long_crowding_adv20"] > calm["long_crowding_adv20"]
    assert crowded["crowded_long"] is True
    assert calm["crowded_long"] is False
    assert "score" not in crowded


def test_regulation_is_carried_as_a_fact_and_labelled():
    plain = f.margin_environment(
        margin_long=1_000_000, margin_short=500_000, adv20_shares=2_000_000,
    )
    regulated = f.margin_environment(
        margin_long=1_000_000, margin_short=500_000, adv20_shares=2_000_000,
        regulation_severity=4,
    )
    assert plain["regulation_severity"] == 0
    assert regulated["regulation_severity"] == 4
    assert states.FLAG_REGULATED in states.classify({"regulation_severity": 4})["flags"]
    assert states.FLAG_REGULATED not in states.classify({"regulation_severity": 0})["flags"]


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


# -- 状態と補助ラベル -------------------------------------------------------

def _evidence(**overrides):
    base = {
        "ratio_change_20d": 0.0, "ratio_change_5d": 0.0,
        "visible_institution_count": 3, "visible_short_ratio": 0.012,
    }
    base.update(overrides)
    return base


def test_deep_low_without_short_activity_is_steady_not_a_signal():
    """価格が深い安値でも、空頭に動きが無ければ状態は動かない（価格は状態に入らない）。"""

    result = states.classify(_evidence(drawdown_52w=-0.45, price_percentile_252=0.02))
    assert result["primary_state"] == states.STATE_STEADY


def test_tiny_short_changes_do_not_trigger_a_state():
    result = states.classify(_evidence(ratio_change_20d=0.0004, ratio_change_5d=0.0003))
    assert result["primary_state"] == states.STATE_STEADY


def test_labels_survive_whatever_the_state_is():
    """低信頼・古い報告・閾値割れは、状態とは別に補助ラベルで残る。"""

    result = states.classify(_evidence(
        ratio_change_20d=0.0030, visible_institution_count=2,
        threshold_exit_count_20d=2, days_since_last_report=30, data_confidence=0.2,
    ))
    assert result["primary_state"] == states.STATE_BUILDING
    assert states.FLAG_BELOW_THRESHOLD in result["flags"]
    assert states.FLAG_STALE_DATA in result["flags"]


def test_stale_data_needs_a_visible_institution():
    """見えている機関が無いのに「報告が古い」とは言わない（v4 の修正）。"""

    nobody = states.classify(_evidence(visible_institution_count=0, days_since_last_report=90))
    assert states.FLAG_STALE_DATA not in nobody["flags"]
    assert states.FLAG_NOT_VISIBLE in nobody["flags"]


def test_concentrated_needs_at_least_two_visible_institutions():
    """1 社だけなら集中度は定義上 1.0。それは single_institution が言う（v4 の修正）。"""

    single = states.classify(_evidence(visible_institution_count=1, concentration=1.0))
    assert states.FLAG_CONCENTRATED not in single["flags"]
    assert states.FLAG_SINGLE_INSTITUTION in single["flags"]
    pair = states.classify(_evidence(visible_institution_count=2, concentration=0.8))
    assert states.FLAG_CONCENTRATED in pair["flags"]


def test_removed_labels_are_gone():
    """轮換・催化・自発/強制回補は解釈であって事実ではないので、ラベルごと無くした。"""

    for name in ("FLAG_ROTATION", "FLAG_NEWS_CATALYST", "FLAG_VOLUNTARY_COVERING", "FLAG_FORCED_COVERING"):
        assert not hasattr(states, name)


# -- 第十四轮: 潜伏空頭 / 回補の広がり / informed 口径 -----------------------------

def test_parked_below_counts_recent_holders_just_under_the_line():
    states_by_holder = {
        "a": {"visibility_status": "below_public_threshold", "last_reported_ratio": 0.0047, "state_age_trading_days": 10},
        "b": {"visibility_status": "below_public_threshold", "last_reported_ratio": 0.0020, "state_age_trading_days": 10},
        "c": {"visibility_status": "below_public_threshold", "last_reported_ratio": 0.0048, "state_age_trading_days": 200},
        "d": {"visibility_status": "reporting", "last_reported_ratio": 0.0090, "state_age_trading_days": 1},
        "e": {"visibility_status": "closed", "last_reported_ratio": 0.0, "state_age_trading_days": 1},
    }
    assert f.parked_below_count(states_by_holder) == 1
    assert f.parked_below_count(states_by_holder, max_age_trading_days=300) == 2


def test_combined_days_to_cover_requires_both_legs():
    assert f.combined_visible_days_to_cover(1_000_000, 500_000, 1_000_000) == 1.5
    assert f.combined_visible_days_to_cover(1_000_000, None, 1_000_000) is None
    assert f.combined_visible_days_to_cover(None, 500_000, 1_000_000) is None


def test_informed_label_marks_domestic_only_reporters():
    """国内証券・集合名義だけの報告（informed 口径が 0 社）には印が付く。
    旧版はこれを回補開始の閘門にしていたが、v4 は閘門を持たない —— 印だけが残る。"""

    all_chains = states.classify(_evidence(ratio_change_20d=-0.0030))
    assert states.FLAG_NO_INFORMED_REPORTER not in all_chains["flags"]   # キー無し = 判定しない

    domestic_only = states.classify(_evidence(ratio_change_20d=-0.0030, informed_institution_count=0))
    assert states.FLAG_NO_INFORMED_REPORTER in domestic_only["flags"]
    assert domestic_only["primary_state"] == states.STATE_COVERING        # 状態は変えない

    informed = states.classify(_evidence(ratio_change_20d=-0.0030, informed_institution_count=1))
    assert states.FLAG_NO_INFORMED_REPORTER not in informed["flags"]


def test_parked_below_is_a_label():
    verdict = states.classify({"parked_below_count": 2})
    assert states.FLAG_PARKED_BELOW in verdict["flags"]
    assert verdict["primary_state"] == states.STATE_NO_SIGNAL
