"""RVOL uses share volume. turnover_ratio / turnover_value cannot stand in."""

from __future__ import annotations

from app.services.radar.t1_priority import T1_UNMET, evaluate_t1_from_daily
from tests.support.a0_t1_fixtures import SESSION, history_plus_session, jst, prior_weekdays, t1_bar


def test_turnover_ratio_cannot_replace_volume_rvol():
    session = t1_bar(
        "72030",
        SESSION,
        open_=100,
        high=106,
        low=99,
        close=105.8,
        volume=100_000,
        turnover_value=80_000_000_000,
    )
    session["turnover_ratio"] = 12.0
    daily = history_plus_session("72030", session_bar=session, prior_volume=1_000_000)
    result = evaluate_t1_from_daily(
        daily,
        session_date=SESSION,
        resistance_high=100,
        as_of=jst(18, 0),
        event_id="evt-turnover",
        is_trading_day=lambda _value: True,
        prior_trading_sessions=lambda session_date, count: [
            day.isoformat() for day in prior_weekdays(session_date, count)
        ],
    )
    assert result["rvol_daily_20med"] == 0.1
    assert result["status"] == T1_UNMET
    assert result["checks"]["rvol"] is False
