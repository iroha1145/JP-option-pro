"""レーダー連動: 触ってよいのは `alert_priority` だけ —— そして
**検証を通るまでそれすら動かさない**。

初回の走步検証は否定（全状態が TOPIX を下回り、強気/弱気の実測順位が逆）。
方向が逆だと自分のデータで分かっているモデルに本番の並び順を動かさせない。
仮の調整量は hypothetical_priority_shift として表示だけする。
"""

import pytest

from app.services.short_monitor import radar_link, states


def _snapshot(state, *, confidence=0.9, flags=(), score=70.0):
    return {
        "primary_state": state, "data_confidence": confidence,
        "flags": list(flags), "behavior_score": score,
        "visible_short_ratio": 0.02, "visible_institution_count": 3,
    }


def _event(code="10000", priority=60.0, **extra):
    return {
        "canonical_code": code, "alert_priority": priority,
        "scores": {
            "base_quality": {"score": 70.0},
            "breakout_confirmation": {"score": 65.0},
            "intrinsic_strength": {"score": 55.0},
        },
        **extra,
    }


# -- 検証を通るまでの正式な振る舞い -------------------------------------------

def test_link_is_disabled_until_validation_passes():
    """SCORE_VALIDATED も GATES_VALIDATED も False の間、連動は無効。"""

    from app.services.short_monitor.scoring import SCORE_VALIDATED
    from app.services.short_monitor.states import GATES_VALIDATED

    assert radar_link.PRIORITY_LINK_ENABLED == (SCORE_VALIDATED and GATES_VALIDATED)
    assert radar_link.PRIORITY_LINK_ENABLED is False, (
        "検証が通っていないのに連動が有効になっている。検証を通してから"
        "このテストを更新すること。"
    )


def test_priority_shift_is_zero_while_unvalidated():
    """初回検証が否定だったモデルに、本番の並び順を動かさせない。"""

    for state in states.ORDERED_STATES:
        assert radar_link.priority_shift(_snapshot(state, confidence=1.0)) == 0.0


def test_alert_priority_is_untouched_while_unvalidated():
    before = _event()
    after = radar_link.overlay([before], {"10000": _snapshot(states.STATE_SQUEEZE_CONFIRMED)})[0]
    assert after["alert_priority"] == pytest.approx(60.0), (
        "検証前なのに正式な優先度を書き換えている"
    )
    assert after["alert_priority_base"] == pytest.approx(60.0)
    assert after["scores"] == before["scores"], "技術品質に書き込んでいる"


def test_overlay_keeps_the_technical_order_while_unvalidated():
    """挤空確認が付いても、並び順は技術系の優先度のまま。"""

    events = [_event("10000", 60.0), _event("10001", 62.0)]
    snapshots = {"10000": _snapshot(states.STATE_SQUEEZE_CONFIRMED)}
    ordered = radar_link.overlay(events, snapshots)
    assert [e["canonical_code"] for e in ordered] == ["10001", "10000"], (
        "検証に落ちたモデルがレーダーを並べ替えている"
    )


# -- 仮の調整量（表示専用）は引き続き計算する -----------------------------------

def test_hypothetical_shift_is_reported_but_not_applied():
    after = radar_link.overlay([_event()], {"10000": _snapshot(states.STATE_SQUEEZE_CONFIRMED)})[0]
    behavior = after["short_behavior"]
    assert behavior["priority_link_enabled"] is False
    assert behavior["priority_shift"] == 0.0
    assert behavior["hypothetical_priority_shift"] > 0.0


def test_the_hypothetical_shift_is_bounded():
    for state in states.ORDERED_STATES:
        shift = radar_link.hypothetical_priority_shift(_snapshot(state, confidence=1.0))
        assert abs(shift) <= radar_link.MAX_PRIORITY_SHIFT


def test_low_confidence_shrinks_the_hypothetical_shift():
    strong = radar_link.hypothetical_priority_shift(_snapshot(states.STATE_ABSORPTION, confidence=1.0))
    weak = radar_link.hypothetical_priority_shift(_snapshot(states.STATE_ABSORPTION, confidence=0.2))
    assert 0 < weak < strong


def test_divergence_failed_would_lower_priority():
    assert radar_link.hypothetical_priority_shift(_snapshot(states.STATE_DIVERGENCE_FAILED)) < 0


def test_crowded_margin_would_pull_priority_back():
    plain = radar_link.hypothetical_priority_shift(_snapshot(states.STATE_SQUEEZE_CONFIRMED))
    crowded = radar_link.hypothetical_priority_shift(
        _snapshot(states.STATE_SQUEEZE_CONFIRMED, flags=[states.FLAG_CROWDED_MARGIN])
    )
    assert crowded < plain


# -- 表示・絞り込みは連動とは独立に動く -----------------------------------------

def test_stocks_without_a_snapshot_are_untouched():
    after = radar_link.overlay([_event()], {})[0]
    assert after["alert_priority"] == pytest.approx(60.0)
    assert after["short_behavior"] is None


def test_filters_do_not_pass_stocks_with_no_data():
    """条件を付けたのにデータが無い銘柄を「条件を満たした」と扱わない。"""

    assert radar_link.matches(None, states=[states.STATE_ABSORPTION]) is False
    assert radar_link.matches(None) is True   # 条件なしなら素通し


def test_filters_by_state_flag_and_confidence():
    snapshot = _snapshot(states.STATE_ABSORPTION, confidence=0.7, flags=[states.FLAG_REENTRY])
    assert radar_link.matches(snapshot, states=[states.STATE_ABSORPTION])
    assert not radar_link.matches(snapshot, states=[states.STATE_SQUEEZE_CONFIRMED])
    assert radar_link.matches(snapshot, flags=[states.FLAG_REENTRY])
    assert not radar_link.matches(snapshot, flags=[states.FLAG_ROTATION])
    assert radar_link.matches(snapshot, min_confidence=0.6)
    assert not radar_link.matches(snapshot, min_confidence=0.8)


def test_exclude_flag_filters_out_crowded_margin():
    crowded = _snapshot(states.STATE_COVERING_START, flags=[states.FLAG_CROWDED_MARGIN])
    assert not radar_link.matches(crowded, exclude_flags=[states.FLAG_CROWDED_MARGIN])
    assert radar_link.matches(_snapshot(states.STATE_COVERING_START),
                              exclude_flags=[states.FLAG_CROWDED_MARGIN])


def test_shadow_score_is_labelled_as_shadow():
    after = radar_link.overlay([_event()], {"10000": _snapshot(states.STATE_ABSORPTION)})[0]
    assert "shadow_score" in after["short_behavior"]
    assert "behavior_score" not in after["short_behavior"], (
        "正式スコアと同じ名前で出すと、そのうち本物として使われる"
    )


# -- 第十四轮: 拥挤度の「只減不加」叠加 ------------------------------------------

def test_crowding_shift_is_never_positive_and_zero_while_ungated():
    snapshot = _snapshot(states.STATE_NORMAL_SHORTING, confidence=1.0)
    snapshot["visible_institution_count"] = 5
    assert radar_link.CROWDING_LINK_ENABLED is False, "窓別検証を通す前に叠加が有効になっている"
    assert radar_link.crowding_shift(snapshot) == 0.0
    assert radar_link.hypothetical_crowding_shift(snapshot) == -4.0
    for count in (0, 1, 2, 3, 4, 9):
        snapshot["visible_institution_count"] = count
        assert radar_link.hypothetical_crowding_shift(snapshot) <= 0.0


def test_crowding_shift_prefers_informed_count_from_components():
    """国内証券だけが 5 社いても informed 口径 0 社なら引き下げない。"""

    import json

    snapshot = _snapshot(states.STATE_NORMAL_SHORTING, confidence=1.0)
    snapshot["visible_institution_count"] = 5
    snapshot["components_json"] = json.dumps({"informed": {"institution_count": 0}})
    assert radar_link.informed_institution_count(snapshot) == 0
    assert radar_link.hypothetical_crowding_shift(snapshot) == 0.0
    snapshot["components_json"] = json.dumps({"informed": {"institution_count": 2}})
    assert radar_link.hypothetical_crowding_shift(snapshot) == -2.0


def test_crowding_shift_scales_with_confidence_and_is_bounded():
    snapshot = _snapshot(states.STATE_NORMAL_SHORTING, confidence=0.5)
    snapshot["visible_institution_count"] = 4
    assert radar_link.hypothetical_crowding_shift(snapshot) == pytest.approx(-2.0)
    assert radar_link.hypothetical_crowding_shift(snapshot) >= -radar_link.MAX_PRIORITY_SHIFT


def test_overlay_reports_crowding_but_does_not_apply_it_yet():
    before = _event(priority=60.0)
    snapshot = _snapshot(states.STATE_NORMAL_SHORTING, confidence=1.0)
    snapshot["visible_institution_count"] = 4
    after = radar_link.overlay([before], {"10000": snapshot})[0]
    assert after["alert_priority"] == pytest.approx(60.0)
    assert after["short_behavior"]["hypothetical_crowding_shift"] == -4.0
    assert after["short_behavior"]["crowding_link_enabled"] is False
