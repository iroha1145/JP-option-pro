"""T1 applies only to base_breakout and boosts met events inside one day."""

from __future__ import annotations

from app.services.radar.engine import SIGNAL_BASE_BREAK
from app.services.radar.t1_priority import (
    T1_MET,
    T1_NOT_APPLICABLE,
    apply_t1_stable_boost,
    attach_t1_features,
)
from tests.support.a0_t1_fixtures import SESSION, jst


def _event(event_id, signal, day, priority, status=None):
    item = {
        "event_id": event_id,
        "canonical_code": event_id[-5:] + "0",
        "signal_type": signal,
        "discovered_date": day,
        "alert_priority": priority,
        "state": "triggered",
    }
    if status:
        item["t1_priority"] = {"status": status}
    return item


def test_only_base_breakout_is_applicable():
    as_of = jst(18, 0)
    applicable = attach_t1_features(
        {"event_id": "a", "signal_type": SIGNAL_BASE_BREAK, "discovered_date": SESSION.isoformat(),
         "features": {"t1_anchor": {"resistance_high": 100, "data_convention": "jp_adj_ohlcv_v1"}}},
        None,
        as_of=as_of,
        is_trading_day=lambda _v: True,
        prior_trading_sessions=lambda *_a: None,
    )
    other = attach_t1_features(
        {"event_id": "b", "signal_type": "high_break_252", "discovered_date": SESSION.isoformat()},
        None,
        as_of=as_of,
    )
    surge = attach_t1_features(
        {"event_id": "c", "signal_type": "volume_surge_break", "discovered_date": SESSION.isoformat()},
        None,
        as_of=as_of,
    )
    assert applicable["t1_priority"]["status"] != T1_NOT_APPLICABLE or applicable["t1_priority"]["reason"] != "setup_not_in_t1_universe"
    assert other["t1_priority"]["status"] == T1_NOT_APPLICABLE
    assert surge["t1_priority"]["status"] == T1_NOT_APPLICABLE


def test_same_day_met_moves_ahead_without_deleting_or_reordering_days():
    day_a = "2026-03-16"
    day_b = "2026-03-13"
    incoming = [
        _event("b-high", "high_break_252", day_b, 99, "not_applicable"),
        _event("b-base", SIGNAL_BASE_BREAK, day_b, 50, T1_MET),
        _event("a-low", SIGNAL_BASE_BREAK, day_a, 40, "unmet"),
        _event("a-met", SIGNAL_BASE_BREAK, day_a, 30, T1_MET),
        _event("a-other", "high_break_60", day_a, 95, "not_applicable"),
    ]
    boosted = apply_t1_stable_boost(incoming)
    ids = [item["event_id"] for item in boosted]
    # Same-day met rows move to the front of their discovered-date group.
    # Cross-day order stays as received (day_b then day_a).
    assert ids[:2] == ["b-base", "b-high"]
    assert ids[2] == "a-met"
    assert "a-low" in ids and "a-other" in ids
    assert set(ids) == {item["event_id"] for item in incoming}
    assert ids.index("a-met") < ids.index("a-low")
    assert ids.index("a-met") < ids.index("a-other")


def test_zero_boostable_events_preserve_production_order_item_for_item():
    incoming = [
        _event("A", SIGNAL_BASE_BREAK, "2026-03-16", 90, "unmet"),
        _event("B", SIGNAL_BASE_BREAK, "2026-03-13", 80, "unmet"),
        _event("C", SIGNAL_BASE_BREAK, "2026-03-16", 70, "pending_close"),
    ]
    boosted = apply_t1_stable_boost(incoming)
    assert [item["event_id"] for item in boosted] == ["A", "B", "C"]


def test_interleaved_dates_keep_original_slots_when_boosting():
    incoming = [
        _event("A", SIGNAL_BASE_BREAK, "2026-03-16", 90, T1_MET),
        _event("B", SIGNAL_BASE_BREAK, "2026-03-13", 80, "unmet"),
        _event("C", SIGNAL_BASE_BREAK, "2026-03-16", 70, "unmet"),
    ]
    boosted = apply_t1_stable_boost(incoming)
    assert [item["event_id"] for item in boosted] == ["A", "B", "C"]


def test_live_structure_without_anchor_is_not_applicable():
    as_of = jst(18, 0)
    attached = attach_t1_features(
        {"event_id": "legacy", "signal_type": SIGNAL_BASE_BREAK, "discovered_date": SESSION.isoformat(),
         "features": {"structure": {"base": {"resistance_high": 100}}}},
        None,
        as_of=as_of,
        is_trading_day=lambda _v: True,
        prior_trading_sessions=lambda *_a: None,
    )
    assert attached["t1_priority"]["status"] == T1_NOT_APPLICABLE
    assert attached["t1_priority"]["reason"] == "missing_frozen_platform"
