"""T1 frozen math: volume RVOL, ATR SMA20, thresholds, no turnover_ratio."""

from __future__ import annotations

from datetime import timedelta

from app.services.radar.daily_confirmation import (
    T1_SETTINGS,
    compute_atr,
    daily_bar_location,
    rvol_daily_20med,
    t1_checks,
)
from app.services.radar.t1_priority import (
    T1_MET,
    T1_NOT_APPLICABLE,
    T1_PENDING,
    T1_UNMET,
    evaluate_t1_from_daily,
    t1_input_identity,
    t1_setup_applicable,
)
from tests.support.a0_t1_fixtures import SESSION, history_plus_session, jst, met_session_bar, prior_weekdays, t1_bar


def _priors(volume=1_000_000):
    return [volume] * 20


def _is_trading_day(value: str) -> bool:
    return True


def _prior_sessions(session, count):
    return [day.isoformat() for day in prior_weekdays(session, count)]


def test_settings_and_atr_need_twenty_one_bars():
    assert T1_SETTINGS["clv_min"] == 0.70
    assert T1_SETTINGS["rvol_min"] == 1.5
    assert T1_SETTINGS["upper_shadow_max"] == 0.15
    assert T1_SETTINGS["distance_atr_min"] == 0.20
    assert T1_SETTINGS["atr_period"] == 20
    bars = [{"high": 101, "low": 99, "close": 100} for _ in range(20)]
    assert compute_atr(bars, period=20) is None
    bars.append({"high": 102, "low": 98, "close": 101})
    value = compute_atr(bars, period=20)
    assert value is not None
    assert round(value, 8) == value


def test_rvol_excludes_t_and_requires_exactly_twenty_priors():
    result = rvol_daily_20med(2_000_000, _priors())
    assert result["status"] == "active"
    assert result["rvol_daily_20med"] == 2.0
    assert result["lookback_used"] == 20
    short = rvol_daily_20med(2_000_000, _priors()[:19])
    assert short["status"] == "unavailable"
    assert short["reason"] == "insufficient_prior_volume"


def test_volume_zero_is_unmet_not_missing():
    daily = history_plus_session("72030", session_bar=t1_bar("72030", SESSION, open_=100, high=106, low=99, close=105.8, volume=0))
    result = evaluate_t1_from_daily(
        daily,
        session_date=SESSION,
        resistance_high=100,
        as_of=jst(18, 0),
        event_id="evt-zero",
        is_trading_day=_is_trading_day,
        prior_trading_sessions=_prior_sessions,
    )
    assert result["status"] == T1_UNMET
    assert result["identity_complete"] is True
    assert result["rvol_daily_20med"] == 0.0


def test_high_turnover_low_volume_is_not_rvol():
    session = t1_bar(
        "72030",
        SESSION,
        open_=100,
        high=106,
        low=99,
        close=105.8,
        volume=100_000,
        turnover_value=50_000_000_000,
    )
    daily = history_plus_session("72030", session_bar=session, prior_volume=1_000_000)
    result = evaluate_t1_from_daily(
        daily,
        session_date=SESSION,
        resistance_high=100,
        as_of=jst(18, 0),
        event_id="evt-va",
        is_trading_day=_is_trading_day,
        prior_trading_sessions=_prior_sessions,
    )
    assert result["rvol_daily_20med"] == 0.1
    assert result["status"] == T1_UNMET
    assert result["checks"]["rvol"] is False


def test_threshold_boundaries_use_inclusive_equals():
    location = daily_bar_location(100, 110, 90, 104)
    assert abs(location["clv"] - 0.70) < 1e-9
    checks = t1_checks(clv=0.70, rvol=1.5, upper_shadow=0.15, distance_atr=0.20)
    assert checks["satisfied"] is True
    below = t1_checks(clv=0.699999, rvol=1.5, upper_shadow=0.15, distance_atr=0.20)
    assert below["satisfied"] is False


def test_h_equals_l_and_invalid_ohlc_are_unavailable():
    daily = history_plus_session(
        "72030",
        session_bar=t1_bar("72030", SESSION, open_=100, high=100, low=100, close=100, volume=2_000_000),
    )
    result = evaluate_t1_from_daily(
        daily,
        session_date=SESSION,
        resistance_high=100,
        as_of=jst(18, 0),
        is_trading_day=_is_trading_day,
        prior_trading_sessions=_prior_sessions,
    )
    assert result["status"] == "unavailable"
    assert result["reason"] == "invalid_ohlc"


def test_before_close_is_pending_and_other_signals_are_not_applicable():
    daily = history_plus_session("72030")
    pending = evaluate_t1_from_daily(
        daily,
        session_date=SESSION,
        resistance_high=100,
        as_of=jst(15, 0),
        is_trading_day=_is_trading_day,
        prior_trading_sessions=_prior_sessions,
    )
    assert pending["status"] == T1_PENDING
    assert t1_setup_applicable({"signal_type": "base_breakout"}) is True
    assert t1_setup_applicable({"signal_type": "high_break_252"}) is False
    assert t1_setup_applicable({"signal_type": "volume_surge_break"}) is False
    assert T1_NOT_APPLICABLE == "not_applicable"


def test_identity_includes_prior_ohlc_not_just_final_metrics():
    prior = [
        {
            "session_date": day.isoformat(),
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1_000_000,
        }
        for day in prior_weekdays(SESSION, 20)
    ]
    session_bar = {"open": 100.0, "high": 106.0, "low": 99.0, "close": 105.8, "volume": 2_000_000}
    first = t1_input_identity(
        event_id="E",
        session_date=SESSION,
        resistance_high=105,
        session_bar=session_bar,
        prior_bars=prior,
    )
    changed = [dict(item) for item in prior]
    changed[0]["high"] = 115.0
    second = t1_input_identity(
        event_id="E",
        session_date=SESSION,
        resistance_high=105,
        session_bar=session_bar,
        prior_bars=changed,
    )
    assert first != second


def test_t_plus_one_bar_does_not_change_t_identity():
    daily = history_plus_session("72030")
    later = daily + [met_session_bar("72030", SESSION + timedelta(days=1))]
    first = evaluate_t1_from_daily(
        daily,
        session_date=SESSION,
        resistance_high=100,
        as_of=jst(18, 0),
        event_id="evt-t",
        is_trading_day=_is_trading_day,
        prior_trading_sessions=_prior_sessions,
    )
    second = evaluate_t1_from_daily(
        later,
        session_date=SESSION,
        resistance_high=100,
        as_of=jst(18, 0) + timedelta(days=1),
        previous=first,
        event_id="evt-t",
        is_trading_day=_is_trading_day,
        prior_trading_sessions=_prior_sessions,
    )
    assert first["status"] == T1_MET
    assert second["identity_hash"] == first["identity_hash"]
    assert second["reused"] is True
    assert second["known_at"] == first["known_at"]
