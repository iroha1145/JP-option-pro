"""T1 persist/overlay through the real CoreRepository and temporary SQLite."""

from __future__ import annotations

from datetime import timedelta

from app.services.radar.t1_priority import (
    T1_MET,
    T1_UNAVAILABLE,
    T1_UNMET,
    attach_t1_features,
    evaluate_t1_from_daily,
    t1_identity_complete,
)
from tests.support.a0_t1_fixtures import (
    SESSION,
    history_plus_session,
    init_repo,
    insert_radar_event,
    insert_security,
    jst,
    met_session_bar,
    prior_weekdays,
    t1_bar,
)


def _eval(daily=None, **kwargs):
    return evaluate_t1_from_daily(
        daily if daily is not None else history_plus_session("72030"),
        session_date=SESSION,
        resistance_high=kwargs.pop("resistance_high", 100),
        as_of=kwargs.pop("as_of", jst(18, 0)),
        is_trading_day=lambda _value: True,
        prior_trading_sessions=lambda session, count: [
            day.isoformat() for day in prior_weekdays(session, count)
        ],
        event_id=kwargs.pop("event_id", "evt-1"),
        **kwargs,
    )


def test_store_keeps_settled_when_later_input_is_incomplete(tmp_path):
    repo = init_repo(tmp_path / "jp-core.db")
    first = _eval()
    assert first["status"] == T1_MET
    repo.persist_t1_evaluations([{"event_id": "evt-1", "t1_priority": first}])
    incomplete = {
        "status": T1_UNAVAILABLE,
        "reason": "missing_event_volume",
        "identity_hash": "forged-complete-hash",
        "identity_complete": True,
        "computed_at": "2026-03-17T09:00:00Z",
        "known_at": None,
    }
    repo.persist_t1_evaluations([{"event_id": "evt-1", "t1_priority": incomplete}])
    kept = repo.overlay_t1_evaluations([{"event_id": "evt-1"}])[0]["t1_priority"]
    assert kept["status"] == T1_MET
    assert kept["known_at"] == first["known_at"]
    assert kept["latest_attempt"]["reason"] == "missing_event_volume"
    assert t1_identity_complete(incomplete) is False


def test_forged_complete_unmet_without_metrics_cannot_overwrite(tmp_path):
    repo = init_repo(tmp_path / "jp-core.db")
    first = _eval()
    repo.persist_t1_evaluations([{"event_id": "evt-1", "t1_priority": first}])
    forged = {
        "status": T1_UNMET,
        "reason": "conditions_not_met",
        "identity_hash": "forged",
        "identity_complete": True,
        "computed_at": "2026-03-17T09:00:00Z",
        "known_at": "2026-03-17T09:00:00Z",
    }
    repo.persist_t1_evaluations([{"event_id": "evt-1", "t1_priority": forged}])
    kept = repo.overlay_t1_evaluations([{"event_id": "evt-1"}])[0]["t1_priority"]
    assert kept["status"] == T1_MET
    assert kept["first_known_at"] == first["first_known_at"] or first["known_at"]


def test_official_revision_can_flip_met_to_unmet(tmp_path):
    repo = init_repo(tmp_path / "jp-core.db")
    met = _eval(event_id="evt-rev")
    repo.persist_t1_evaluations([{"event_id": "evt-rev", "t1_priority": met}])
    revised_daily = history_plus_session(
        "72030",
        session_bar=t1_bar("72030", SESSION, open_=100, high=106, low=99, close=105.8, volume=100_000),
    )
    revised = _eval(revised_daily, previous=met, event_id="evt-rev")
    assert revised["status"] == T1_UNMET
    assert revised["eval_version"] == met["eval_version"] + 1
    repo.persist_t1_evaluations([{"event_id": "evt-rev", "t1_priority": revised}])
    kept = repo.overlay_t1_evaluations([{"event_id": "evt-rev"}])[0]["t1_priority"]
    assert kept["status"] == T1_UNMET
    assert kept["first_known_at"] == met["known_at"]
    assert kept["revisions"]


def test_t_plus_two_new_bars_do_not_change_t(tmp_path):
    repo = init_repo(tmp_path / "jp-core.db")
    first = _eval(event_id="evt-t2")
    repo.persist_t1_evaluations([{"event_id": "evt-t2", "t1_priority": first}])
    extra = history_plus_session("72030") + [
        met_session_bar("72030", SESSION + timedelta(days=1)),
        met_session_bar("72030", SESSION + timedelta(days=2)),
    ]
    later = _eval(extra, previous=first, event_id="evt-t2", as_of=jst(18, 0, SESSION + timedelta(days=2)))
    repo.persist_t1_evaluations([{"event_id": "evt-t2", "t1_priority": later}])
    kept = repo.overlay_t1_evaluations([{"event_id": "evt-t2"}])[0]["t1_priority"]
    assert kept["status"] == T1_MET
    assert kept["identity_hash"] == first["identity_hash"]
    assert kept["eval_version"] == first["eval_version"]


def test_carryover_and_api_overlay_share_repository_rules(tmp_path, monkeypatch):
    from tests.support.a0_t1_fixtures import api_client

    repo = init_repo(tmp_path / "jp-core.db")
    insert_security(repo, "72030")
    insert_radar_event(repo, event_id="evt-api", code="72030", priority=90)
    first = _eval(event_id="evt-api")
    repo.persist_t1_evaluations([{"event_id": "evt-api", "t1_priority": first}])
    client = api_client(tmp_path, monkeypatch)
    body = client.get("/api/radar/current", params={"sort_algorithm": "production"}).json()
    event = next(item for item in body["events"] if item["event_id"] == "evt-api")
    assert event["t1_priority"]["status"] == T1_MET
    attached = attach_t1_features(
        {"event_id": "evt-api", "signal_type": "base_breakout", "discovered_date": SESSION.isoformat(),
         "features": {"t1_anchor": {"resistance_high": 100, "data_convention": "jp_adj_ohlcv_v1"}}},
        None,
        as_of=jst(18, 0),
        previous=first,
        is_trading_day=lambda _v: True,
        prior_trading_sessions=lambda session, count: [
            day.isoformat() for day in prior_weekdays(session, count)
        ],
    )
    repo.persist_t1_evaluations([attached])
    kept = repo.overlay_t1_evaluations([{"event_id": "evt-api"}])[0]["t1_priority"]
    assert kept["status"] == T1_MET
    assert kept["latest_attempt"]["reason"] in {"daily_unavailable", "missing_event_bar"}
