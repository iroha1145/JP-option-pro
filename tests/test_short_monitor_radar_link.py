"""レーダー連動: 触ってよいのは `alert_priority` だけ。"""

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


def test_only_alert_priority_moves():
    """正式な技術品質を書き換えない。"""

    before = _event()
    after = radar_link.overlay([before], {"10000": _snapshot(states.STATE_SQUEEZE_CONFIRMED)})[0]
    assert after["scores"] == before["scores"], "技術品質に書き込んでいる"
    assert after["alert_priority"] != before["alert_priority"]
    assert after["alert_priority_base"] == pytest.approx(60.0)


def test_the_shift_is_bounded():
    """どんな状態でも優先度は限られた幅しか動かない。"""

    for state in states.ORDERED_STATES:
        shift = radar_link.priority_shift(_snapshot(state, confidence=1.0))
        assert abs(shift) <= radar_link.MAX_PRIORITY_SHIFT


def test_low_confidence_shrinks_the_shift():
    strong = radar_link.priority_shift(_snapshot(states.STATE_ABSORPTION, confidence=1.0))
    weak = radar_link.priority_shift(_snapshot(states.STATE_ABSORPTION, confidence=0.2))
    assert 0 < weak < strong


def test_divergence_failed_lowers_priority():
    shift = radar_link.priority_shift(_snapshot(states.STATE_DIVERGENCE_FAILED))
    assert shift < 0


def test_crowded_margin_pulls_priority_back():
    """踏み上げ期待の裏で玉の構造が危ういことがある。上げっぱなしにしない。"""

    plain = radar_link.priority_shift(_snapshot(states.STATE_SQUEEZE_CONFIRMED))
    crowded = radar_link.priority_shift(
        _snapshot(states.STATE_SQUEEZE_CONFIRMED, flags=[states.FLAG_CROWDED_MARGIN])
    )
    assert crowded < plain


def test_stocks_without_a_snapshot_are_untouched():
    after = radar_link.overlay([_event()], {})[0]
    assert after["alert_priority"] == pytest.approx(60.0)
    assert after["short_behavior"] is None


def test_overlay_reorders_by_the_adjusted_priority():
    events = [_event("10000", 60.0), _event("10001", 62.0)]
    snapshots = {"10000": _snapshot(states.STATE_SQUEEZE_CONFIRMED)}
    ordered = radar_link.overlay(events, snapshots)
    assert [e["canonical_code"] for e in ordered] == ["10000", "10001"]


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
