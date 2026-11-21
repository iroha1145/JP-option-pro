"""レーダー連動: 触ってよいのは `alert_priority` だけ —— そして
**今は何も動かさない**。

v4 で状態由来の加減点（挤空确认 +8 など）と、その仮の値
`hypothetical_priority_shift` は廃止した。残るのは拥挤度の「只減不加」だけで、
スイッチは切ったまま。仮の値は `hypothetical_crowding_shift` として表示だけする。
"""

import pytest

from app.services.short_monitor import radar_link, states


def _snapshot(state, *, confidence=0.9, flags=(), count=3):
    return {
        "primary_state": state, "data_confidence": confidence,
        "flags": list(flags),
        "visible_short_ratio": 0.02, "visible_institution_count": count,
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


# -- スイッチが切れている間の正式な振る舞い -----------------------------------

def test_link_is_disabled_and_the_crowding_status_says_not_applied():
    assert radar_link.PRIORITY_LINK_ENABLED is False
    assert radar_link.CROWDING_LINK_ENABLED is False, "叠加が有効になっている"
    assert radar_link.CROWDING_VALIDATION["status"] == "not_applied"
    assert "gate" not in radar_link.CROWDING_VALIDATION
    # 状態由来の加減点は存在しない
    for gone in ("STATE_SHIFT", "CROWDED_MARGIN_SHIFT", "hypothetical_priority_shift"):
        assert not hasattr(radar_link, gone)


def test_priority_shift_is_zero_while_the_switch_is_off():
    """どの状態でも、機関が何社いても、適用される調整量は 0。"""

    for state in states.ORDERED_STATES:
        for count in (0, 1, 4, 9):
            assert radar_link.priority_shift(_snapshot(state, confidence=1.0, count=count)) == 0.0


def test_alert_priority_is_untouched_while_the_switch_is_off():
    before = _event()
    after = radar_link.overlay([before], {"10000": _snapshot(states.STATE_BUILDING, count=5)})[0]
    assert after["alert_priority"] == pytest.approx(60.0), (
        "スイッチが切れているのに正式な優先度を書き換えている"
    )
    assert after["alert_priority_base"] == pytest.approx(60.0)
    assert after["scores"] == before["scores"], "技術品質に書き込んでいる"


def test_overlay_keeps_the_technical_order_while_the_switch_is_off():
    """最も混んだ銘柄でも、並び順は技術系の優先度のまま。"""

    events = [_event("10000", 60.0), _event("10001", 62.0)]
    snapshots = {"10000": _snapshot(states.STATE_BUILDING, count=9)}
    ordered = radar_link.overlay(events, snapshots)
    assert [e["canonical_code"] for e in ordered] == ["10001", "10000"], (
        "空売りがレーダーを並べ替えている"
    )


# -- 仮の調整量（表示専用）は引き続き計算する -----------------------------------

def test_the_crowding_shift_is_reported_but_not_applied():
    after = radar_link.overlay([_event()], {"10000": _snapshot(states.STATE_BUILDING, count=5)})[0]
    behavior = after["short_behavior"]
    assert behavior["crowding_link_enabled"] is False
    assert behavior["priority_shift"] == 0.0
    assert behavior["hypothetical_crowding_shift"] < 0.0


def test_the_hypothetical_shift_is_bounded():
    for count in range(0, 40):
        shift = radar_link.hypothetical_crowding_shift(
            _snapshot(states.STATE_BUILDING, confidence=1.0, count=count)
        )
        assert -radar_link.MAX_PRIORITY_SHIFT <= shift <= 0.0


def test_low_confidence_shrinks_the_hypothetical_shift():
    strong = radar_link.hypothetical_crowding_shift(_snapshot(states.STATE_BUILDING, confidence=1.0, count=4))
    weak = radar_link.hypothetical_crowding_shift(_snapshot(states.STATE_BUILDING, confidence=0.2, count=4))
    assert strong < weak < 0


def test_the_state_does_not_move_the_hypothetical_shift():
    """状態は価格とも結果とも結びつけない。同じ機関数・信頼度なら同じ調整量。"""

    shifts = {
        radar_link.hypothetical_crowding_shift(_snapshot(state, confidence=1.0, count=4))
        for state in states.ORDERED_STATES
    }
    assert shifts == {-4.0}


# -- 表示・絞り込みは連動とは独立に動く -----------------------------------------

def test_stocks_without_a_snapshot_are_untouched():
    after = radar_link.overlay([_event()], {})[0]
    assert after["alert_priority"] == pytest.approx(60.0)
    assert after["short_behavior"] is None


def test_filters_do_not_pass_stocks_with_no_data():
    """条件を付けたのにデータが無い銘柄を「条件を満たした」と扱わない。"""

    assert radar_link.matches(None, states=[states.STATE_BUILDING]) is False
    assert radar_link.matches(None) is True   # 条件なしなら素通し


def test_filters_by_state_flag_and_confidence():
    snapshot = _snapshot(states.STATE_BUILDING, confidence=0.7, flags=[states.FLAG_REENTRY])
    assert radar_link.matches(snapshot, states=[states.STATE_BUILDING])
    assert not radar_link.matches(snapshot, states=[states.STATE_COVERING])
    assert radar_link.matches(snapshot, flags=[states.FLAG_REENTRY])
    assert not radar_link.matches(snapshot, flags=[states.FLAG_NEW_ENTRY])
    assert radar_link.matches(snapshot, min_confidence=0.6)
    assert not radar_link.matches(snapshot, min_confidence=0.8)


def test_exclude_flag_filters_out_crowded_margin():
    crowded = _snapshot(states.STATE_COVERING, flags=[states.FLAG_CROWDED_MARGIN])
    assert not radar_link.matches(crowded, exclude_flags=[states.FLAG_CROWDED_MARGIN])
    assert radar_link.matches(_snapshot(states.STATE_COVERING),
                              exclude_flags=[states.FLAG_CROWDED_MARGIN])


def test_the_overlay_carries_no_scores_only_facts_and_the_crowding_level():
    """合成点数は無い。名前を変えて（shadow_score など）残すこともしない。"""

    snapshot = _snapshot(states.STATE_BUILDING, count=4)
    after = radar_link.overlay([_event()], {"10000": snapshot})[0]
    behavior = after["short_behavior"]
    for gone in ("shadow_score", "behavior_score", "hypothetical_priority_shift", "priority_link_enabled"):
        assert gone not in behavior
    assert behavior["crowding_level"] == states.CROWDING_HIGH
    assert behavior["state"] == states.STATE_BUILDING


# -- 第十四轮: 拥挤度の「只減不加」叠加 ------------------------------------------

def test_crowding_shift_is_never_positive_and_zero_while_ungated():
    snapshot = _snapshot(states.STATE_BUILDING, confidence=1.0)
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

    snapshot = _snapshot(states.STATE_BUILDING, confidence=1.0)
    snapshot["visible_institution_count"] = 5
    snapshot["components_json"] = json.dumps({"informed": {"institution_count": 0}})
    assert radar_link.informed_institution_count(snapshot) == 0
    assert radar_link.hypothetical_crowding_shift(snapshot) == 0.0
    snapshot["components_json"] = json.dumps({"informed": {"institution_count": 2}})
    assert radar_link.hypothetical_crowding_shift(snapshot) == -2.0


def test_crowding_shift_scales_with_confidence_and_is_bounded():
    snapshot = _snapshot(states.STATE_BUILDING, confidence=0.5)
    snapshot["visible_institution_count"] = 4
    assert radar_link.hypothetical_crowding_shift(snapshot) == pytest.approx(-2.0)
    assert radar_link.hypothetical_crowding_shift(snapshot) >= -radar_link.MAX_PRIORITY_SHIFT


def test_overlay_reports_crowding_but_does_not_apply_it_yet():
    before = _event(priority=60.0)
    snapshot = _snapshot(states.STATE_BUILDING, confidence=1.0)
    snapshot["visible_institution_count"] = 4
    after = radar_link.overlay([before], {"10000": snapshot})[0]
    assert after["alert_priority"] == pytest.approx(60.0)
    assert after["short_behavior"]["hypothetical_crowding_shift"] == -4.0
    assert after["short_behavior"]["crowding_link_enabled"] is False
