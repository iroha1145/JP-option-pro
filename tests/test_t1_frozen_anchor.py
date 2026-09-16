"""F1: T1 resistance is a dedicated first-publish anchor, not live structure."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.personal_config import RadarConfig
from app.services.radar import lifecycle as lc
from app.services.radar.engine import RadarEngine, _first_publish_t1_anchor
from app.services.radar.t1_close import evaluate_t1_from_local_bars
from app.services.radar.t1_priority import (
    T1_MET,
    T1_NOT_APPLICABLE,
    T1_UNMET,
    attach_t1_features,
    t1_resistance_high,
)
from tests.support.a0_t1_fixtures import (
    SESSION,
    SESSION_ISO,
    history_plus_session,
    init_repo,
    insert_radar_event,
    insert_security,
    jst,
    prior_weekdays,
    t1_bar,
)
from tests.test_radar_engine import _seed_market


def _calendar(repo):
    return (
        repo.is_trading_day,
        lambda session, count: repo.prior_trading_sessions(session.isoformat(), count),
    )


def test_live_structure_change_does_not_flip_frozen_anchor(tmp_path):
    repo = init_repo(tmp_path / "jp-core.db")
    insert_security(repo, "72030")
    repo.upsert_daily_bars(history_plus_session("72030"))
    insert_radar_event(repo, event_id="evt-anchor", code="72030", resistance_high=100)
    first = evaluate_t1_from_local_bars(repo, scan_date=SESSION_ISO, as_of=jst(18, 0))
    assert first["written"] >= 1
    before = repo.overlay_t1_evaluations(repo.applicable_t1_events())[0]
    assert before["t1_priority"]["status"] == T1_MET
    first_known = before["t1_priority"]["first_known_at"]

    features = dict(before["features"])
    features["structure"] = {"base": {"resistance_high": 106, "pivot_id": "new-platform"}}
    before["features"] = features
    before["alert_priority"] = 11
    repo.upsert_radar_events([before])
    repo.save_t1_anchors([before])

    evaluate_t1_from_local_bars(repo, scan_date=SESSION_ISO, as_of=jst(18, 0))
    after = repo.overlay_t1_evaluations(repo.applicable_t1_events())[0]
    assert t1_resistance_high(after) == 100
    assert after["features"]["structure"]["base"]["resistance_high"] == 106
    assert after["t1_priority"]["status"] == T1_MET
    assert after["t1_priority"]["first_known_at"] == first_known


def test_unevidenced_legacy_is_not_applicable_even_with_live_structure(tmp_path):
    repo = init_repo(tmp_path / "jp-core.db")
    insert_security(repo, "72030")
    repo.upsert_daily_bars(history_plus_session("72030"))
    insert_radar_event(
        repo, event_id="evt-legacy", code="72030", resistance_high=100, freeze_anchor=False,
    )
    evaluate_t1_from_local_bars(repo, scan_date=SESSION_ISO, as_of=jst(18, 0))
    event = repo.overlay_t1_evaluations(repo.applicable_t1_events())[0]
    assert event["t1_priority"]["status"] == T1_NOT_APPLICABLE
    assert event["t1_priority"]["reason"] == "missing_frozen_platform"


def test_evidenced_pivot_recovery_uses_frozen_pivot_not_live_structure():
    event = {
        "event_id": "evt-rec",
        "signal_type": "base_breakout",
        "discovered_date": SESSION_ISO,
        "pivot_price": 100,
        "features": {
            "structure": {"base": {"resistance_high": 106}},
            "t1_anchor_recovery": {
                "pivot_was_resistance_high": True,
                "data_convention": "jp_adj_ohlcv_v1",
            },
        },
    }
    assert t1_resistance_high(event) == 100
    attached = attach_t1_features(
        event,
        history_plus_session("72030"),
        as_of=jst(18, 0),
        is_trading_day=lambda _v: True,
        prior_trading_sessions=lambda session, count: [
            day.isoformat() for day in prior_weekdays(session, count)
        ],
    )
    assert attached["t1_priority"]["status"] == T1_MET


def test_bare_pivot_without_proof_is_not_resistance():
    event = {
        "event_id": "evt-mid",
        "signal_type": "base_breakout",
        "discovered_date": SESSION_ISO,
        "pivot_price": 100,
        "features": {"structure": {"base": {"resistance_high": 100, "pivot_price": 99.5}}},
    }
    assert t1_resistance_high(event) is None


def test_bar_revision_before_event_day_creates_new_eval_version(tmp_path):
    repo = init_repo(tmp_path / "jp-core.db")
    insert_security(repo, "72030")
    repo.upsert_daily_bars(history_plus_session("72030"))
    insert_radar_event(repo, event_id="evt-rev", code="72030")
    evaluate_t1_from_local_bars(repo, scan_date=SESSION_ISO, as_of=jst(18, 0))
    first = repo.overlay_t1_evaluations([{"event_id": "evt-rev"}])[0]["t1_priority"]
    assert first["status"] == T1_MET
    revised = history_plus_session(
        "72030",
        session_bar=t1_bar("72030", SESSION, open_=100, high=106, low=99, close=105.8, volume=100_000),
    )
    repo.upsert_daily_bars(revised)
    evaluate_t1_from_local_bars(repo, scan_date=SESSION_ISO, as_of=jst(18, 0))
    later = repo.overlay_t1_evaluations([{"event_id": "evt-rev"}])[0]["t1_priority"]
    assert later["status"] == T1_UNMET
    assert later["eval_version"] == first["eval_version"] + 1
    assert later["first_known_at"] == first["first_known_at"] or first["known_at"]


def test_t_plus_one_new_platform_does_not_change_anchor_or_first_known(tmp_path):
    repo = init_repo(tmp_path / "jp-core.db")
    insert_security(repo, "72030")
    repo.upsert_daily_bars(history_plus_session("72030"))
    insert_radar_event(repo, event_id="evt-t1p", code="72030", resistance_high=100)
    evaluate_t1_from_local_bars(repo, scan_date=SESSION_ISO, as_of=jst(18, 0))
    first = repo.overlay_t1_evaluations(repo.applicable_t1_events())[0]
    first_known = first["t1_priority"]["first_known_at"]
    next_day = (SESSION + timedelta(days=1)).isoformat()
    features = dict(first["features"])
    features["structure"] = {"base": {"resistance_high": 112, "pivot_id": "tplus1"}}
    features["t1_anchor"] = dict(features["t1_anchor"])
    first["features"] = features
    first["last_scanned_date"] = next_day
    repo.upsert_radar_events([first])
    repo.save_t1_anchors([first])
    evaluate_t1_from_local_bars(repo, as_of=jst(18, 0, SESSION + timedelta(days=1)))
    later = repo.overlay_t1_evaluations([{"event_id": "evt-t1p"}])[0]
    assert t1_resistance_high(later) == 100
    assert later["t1_priority"]["first_known_at"] == first_known
    assert later["t1_anchor"]["resistance_high"] == 100


def test_engine_preserves_anchor_when_structure_is_rewritten(tmp_path):
    up = [100.0 + i * 0.1 for i in range(84)] + [112.0]
    repo, dates = _seed_market(tmp_path, {"70130": up})
    config = RadarConfig(min_avg_turnover_jpy=0.0, min_listed_days=30)
    engine = RadarEngine(repo, config)
    engine.scan(dates[-1], lookback_start=dates[0])
    events = repo.open_radar_events(terminal_states=sorted(lc.TERMINAL_STATES))
    assert events
    event = events[0]
    event["signal_type"] = "base_breakout"
    event["features"] = dict(event.get("features") or {})
    event["features"]["t1_anchor"] = _first_publish_t1_anchor(
        event["event_id"], event["discovered_date"], {"base": {"resistance_high": 100, "pivot_id": "frozen"}}
    )
    repo.upsert_radar_events([event])
    repo.save_t1_anchors([event])
    later = dates[-1]
    engine.scan(later, lookback_start=dates[0])
    refreshed = repo.radar_event(event["event_id"])
    overlaid = repo.overlay_t1_evaluations([refreshed])[0]
    assert t1_resistance_high(overlaid) == 100
    assert overlaid["features"]["t1_anchor"]["resistance_high"] == 100


def test_split_adjust_revises_identity_but_keeps_anchor(tmp_path):
    repo = init_repo(tmp_path / "jp-core.db")
    insert_security(repo, "72030")
    bars = history_plus_session("72030")
    repo.upsert_daily_bars(bars)
    insert_radar_event(repo, event_id="evt-split", code="72030")
    evaluate_t1_from_local_bars(repo, scan_date=SESSION_ISO, as_of=jst(18, 0))
    first = repo.overlay_t1_evaluations([{"event_id": "evt-split"}])[0]["t1_priority"]
    assert first["status"] == T1_MET
    assert first["breakout_distance_atr"] == pytest.approx(2.5777777777777766, rel=1e-6)
    first_known = first["first_known_at"] or first["known_at"]
    adjusted = []
    for bar in bars:
        item = dict(bar)
        item["adj_open"] = bar["open"] * 0.5
        item["adj_high"] = bar["high"] * 0.5
        item["adj_low"] = bar["low"] * 0.5
        item["adj_close"] = bar["close"] * 0.5
        item["adj_volume"] = bar["volume"] * 2
        adjusted.append(item)
    repo.upsert_daily_bars(adjusted)
    evaluate_t1_from_local_bars(repo, scan_date=SESSION_ISO, as_of=jst(18, 0))
    later = repo.overlay_t1_evaluations([{"event_id": "evt-split"}])[0]
    payload = later["t1_priority"]
    assert t1_resistance_high(later) == 100
    assert later["t1_anchor"]["resistance_high"] == 100
    assert payload["status"] == T1_MET
    assert payload["clv"] == pytest.approx(first["clv"], rel=1e-9)
    assert payload["rvol_daily_20med"] == pytest.approx(first["rvol_daily_20med"], rel=1e-9)
    assert payload["upper_shadow_ratio"] == pytest.approx(first["upper_shadow_ratio"], rel=1e-9)
    assert payload["breakout_distance_atr"] == pytest.approx(first["breakout_distance_atr"], rel=1e-6)
    assert payload["first_known_at"] == first_known
    assert payload["eval_version"] == first["eval_version"]
    assert payload["identity_hash"] == first["identity_hash"]
