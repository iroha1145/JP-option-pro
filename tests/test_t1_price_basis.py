"""T1 event-day price basis: raw / adj / mix, split before and after T, API path."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.services.radar.t1_close import evaluate_t1_from_local_bars
from app.services.radar.t1_priority import T1_MET, T1_UNMET, t1_resistance_high
from tests.support.a0_t1_fixtures import (
    SESSION,
    SESSION_ISO,
    api_client,
    history_plus_session,
    init_repo,
    insert_radar_event,
    insert_security,
    jst,
    t1_bar,
)


def _overlay(repo, event_id="evt-basis"):
    return repo.overlay_t1_evaluations([{"event_id": event_id}])[0]


def _restate_adj(bars, *, scale=0.5):
    out = []
    for bar in bars:
        item = dict(bar)
        item["adj_open"] = bar["open"] * scale
        item["adj_high"] = bar["high"] * scale
        item["adj_low"] = bar["low"] * scale
        item["adj_close"] = bar["close"] * scale
        item["adj_volume"] = bar["volume"] / scale
        out.append(item)
    return out


def _strip_raw(bars):
    out = []
    for bar in bars:
        item = dict(bar)
        item["open"] = None
        item["high"] = None
        item["low"] = None
        item["close"] = None
        item["volume"] = None
        out.append(item)
    return out


def test_raw_only_window_matches_first_eval(tmp_path):
    repo = init_repo(tmp_path / "jp-core.db")
    insert_security(repo, "72030")
    bars = history_plus_session("72030")
    for bar in bars:
        bar["adj_open"] = None
        bar["adj_high"] = None
        bar["adj_low"] = None
        bar["adj_close"] = None
        bar["adj_volume"] = None
    repo.upsert_daily_bars(bars)
    insert_radar_event(repo, event_id="evt-basis", code="72030")
    evaluate_t1_from_local_bars(repo, scan_date=SESSION_ISO, as_of=jst(18, 0))
    first = _overlay(repo)["t1_priority"]
    assert first["status"] == T1_MET
    evaluate_t1_from_local_bars(repo, scan_date=SESSION_ISO, as_of=jst(18, 0))
    later = _overlay(repo)["t1_priority"]
    assert later["status"] == T1_MET
    assert later["identity_hash"] == first["identity_hash"]
    assert later["breakout_distance_atr"] == pytest.approx(first["breakout_distance_atr"])


def test_mixed_raw_and_restated_adj_keeps_normalized_met(tmp_path):
    repo = init_repo(tmp_path / "jp-core.db")
    insert_security(repo, "72030")
    bars = history_plus_session("72030")
    repo.upsert_daily_bars(bars)
    insert_radar_event(repo, event_id="evt-basis", code="72030")
    evaluate_t1_from_local_bars(repo, scan_date=SESSION_ISO, as_of=jst(18, 0))
    first = _overlay(repo)["t1_priority"]
    repo.upsert_daily_bars(_restate_adj(bars))
    evaluate_t1_from_local_bars(repo, scan_date=SESSION_ISO, as_of=jst(18, 0))
    later = _overlay(repo)
    payload = later["t1_priority"]
    assert t1_resistance_high(later) == 100
    assert payload["status"] == T1_MET
    assert payload["breakout_distance_atr"] == pytest.approx(first["breakout_distance_atr"])
    assert payload["clv"] == pytest.approx(first["clv"])
    assert payload["rvol_daily_20med"] == pytest.approx(first["rvol_daily_20med"])
    assert payload["first_known_at"] == first["first_known_at"]
    assert payload["identity_hash"] == first["identity_hash"]


def test_adj_only_post_t_split_converts_back_to_event_day(tmp_path):
    repo = init_repo(tmp_path / "jp-core.db")
    insert_security(repo, "72030")
    bars = history_plus_session("72030")
    repo.upsert_daily_bars(_strip_raw(bars))
    insert_radar_event(repo, event_id="evt-basis", code="72030")
    evaluate_t1_from_local_bars(repo, scan_date=SESSION_ISO, as_of=jst(18, 0))
    first = _overlay(repo)["t1_priority"]
    assert first["status"] == T1_MET
    restated = _strip_raw(_restate_adj(bars))
    next_day = SESSION + timedelta(days=1)
    restated.append(
        t1_bar("72030", next_day, open_=53, high=54, low=52, close=53, volume=2_000_000, adj_factor=0.5)
    )
    restated[-1]["adj_open"] = 53
    restated[-1]["adj_high"] = 54
    restated[-1]["adj_low"] = 52
    restated[-1]["adj_close"] = 53
    restated[-1]["adj_volume"] = 2_000_000
    repo.upsert_daily_bars(restated)
    evaluate_t1_from_local_bars(repo, scan_date=SESSION_ISO, as_of=jst(18, 0))
    later = _overlay(repo)["t1_priority"]
    assert later["status"] == T1_MET
    assert later["breakout_distance_atr"] == pytest.approx(first["breakout_distance_atr"])
    assert later["first_known_at"] == first["first_known_at"]
    assert later["identity_hash"] == first["identity_hash"]


def test_adj_only_restatement_without_factor_keeps_settled(tmp_path):
    repo = init_repo(tmp_path / "jp-core.db")
    insert_security(repo, "72030")
    bars = history_plus_session("72030")
    repo.upsert_daily_bars(_strip_raw(bars))
    insert_radar_event(repo, event_id="evt-basis", code="72030")
    evaluate_t1_from_local_bars(repo, scan_date=SESSION_ISO, as_of=jst(18, 0))
    first = _overlay(repo)["t1_priority"]
    assert first["status"] == T1_MET
    repo.upsert_daily_bars(_strip_raw(_restate_adj(bars)))
    evaluate_t1_from_local_bars(repo, scan_date=SESSION_ISO, as_of=jst(18, 0))
    later = _overlay(repo)["t1_priority"]
    assert later["status"] == T1_MET
    assert later["breakout_distance_atr"] == pytest.approx(first["breakout_distance_atr"])
    assert later["first_known_at"] == first["first_known_at"]
    assert later["identity_hash"] == first["identity_hash"]
    assert later["latest_attempt"]["reason"] == "price_basis_unreliable"
    assert later["latest_attempt"]["identity_complete"] is False


def test_split_before_event_day_stays_internally_consistent(tmp_path):
    repo = init_repo(tmp_path / "jp-core.db")
    insert_security(repo, "72030")
    bars = history_plus_session("72030")
    bars[-2]["adjustment_factor"] = 0.5
    repo.upsert_daily_bars(bars)
    insert_radar_event(repo, event_id="evt-basis", code="72030")
    evaluate_t1_from_local_bars(repo, scan_date=SESSION_ISO, as_of=jst(18, 0))
    first = _overlay(repo)["t1_priority"]
    evaluate_t1_from_local_bars(repo, scan_date=SESSION_ISO, as_of=jst(18, 0))
    later = _overlay(repo)["t1_priority"]
    assert later["status"] == first["status"]
    assert later["identity_hash"] == first["identity_hash"]
    assert later["breakout_distance_atr"] == pytest.approx(first["breakout_distance_atr"])
    assert later["clv"] == pytest.approx(first["clv"])
    assert later["rvol_daily_20med"] == pytest.approx(first["rvol_daily_20med"])
    assert later["first_known_at"] == first["first_known_at"]


def test_real_ohlc_revision_can_change_conclusion(tmp_path):
    repo = init_repo(tmp_path / "jp-core.db")
    insert_security(repo, "72030")
    repo.upsert_daily_bars(history_plus_session("72030"))
    insert_radar_event(repo, event_id="evt-basis", code="72030")
    evaluate_t1_from_local_bars(repo, scan_date=SESSION_ISO, as_of=jst(18, 0))
    first = _overlay(repo)["t1_priority"]
    revised = history_plus_session(
        "72030",
        session_bar=t1_bar("72030", SESSION, open_=100, high=106, low=99, close=100.1, volume=100_000),
    )
    repo.upsert_daily_bars(revised)
    evaluate_t1_from_local_bars(repo, scan_date=SESSION_ISO, as_of=jst(18, 0))
    later = _overlay(repo)["t1_priority"]
    assert later["status"] == T1_UNMET
    assert later["eval_version"] == first["eval_version"] + 1
    assert later["first_known_at"] == first["first_known_at"]
    assert later["identity_hash"] != first["identity_hash"]


def test_adjustment_evaluate_sqlite_api_preserves_event_day_math(tmp_path, monkeypatch):
    repo = init_repo(tmp_path / "jp-core.db")
    insert_security(repo, "72030")
    bars = history_plus_session("72030")
    repo.upsert_daily_bars(bars)
    insert_radar_event(repo, event_id="evt-basis", code="72030")
    evaluate_t1_from_local_bars(repo, scan_date=SESSION_ISO, as_of=jst(18, 0))
    client = api_client(tmp_path, monkeypatch)
    first = client.get("/api/radar/events/evt-basis")
    assert first.status_code == 200
    first_t1 = first.json()["t1_priority"]
    assert first_t1["status"] == T1_MET
    repo.upsert_daily_bars(_restate_adj(bars))
    evaluate_t1_from_local_bars(repo, scan_date=SESSION_ISO, as_of=jst(18, 0))
    later = client.get("/api/radar/events/evt-basis")
    later_t1 = later.json()["t1_priority"]
    assert later.json()["t1_anchor"]["resistance_high"] == 100
    assert later_t1["status"] == T1_MET
    assert later_t1["breakout_distance_atr"] == pytest.approx(first_t1["breakout_distance_atr"])
    assert later_t1["clv"] == pytest.approx(first_t1["clv"])
    assert later_t1["rvol_daily_20med"] == pytest.approx(first_t1["rvol_daily_20med"])
    assert later_t1["first_known_at"] == first_t1["first_known_at"]
    current = client.get("/api/radar/current", params={"sort_algorithm": "t1", "limit": 5})
    assert current.status_code == 200
    match = next(item for item in current.json()["events"] if item["event_id"] == "evt-basis")
    assert match["t1_priority"]["status"] == T1_MET
    assert match["t1_priority"]["breakout_distance_atr"] == pytest.approx(first_t1["breakout_distance_atr"])
