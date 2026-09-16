"""Japan calendar, vendor publish gate, and publication identity stay distinct."""

from __future__ import annotations

from datetime import date, timedelta

from app.services.publication import evaluate_freshness, expected_trade_date
from app.services.radar.t1_priority import (
    evaluate_t1_from_daily,
    session_daily_complete,
    vendor_publish_ready,
)
from tests.support.a0_t1_fixtures import SESSION, history_plus_session, init_repo, jst, prior_weekdays


def test_session_complete_is_1530_but_vendor_gate_is_later():
    assert session_daily_complete(SESSION, as_of=jst(15, 29)) is False
    assert session_daily_complete(SESSION, as_of=jst(15, 30)) is True
    assert vendor_publish_ready(SESSION, as_of=jst(15, 30)) is False
    assert vendor_publish_ready(SESSION, as_of=jst(16, 59)) is False
    assert vendor_publish_ready(SESSION, as_of=jst(17, 0)) is True


def test_lunch_and_holiday_are_not_us_half_days():
    lunch = jst(12, 0)
    assert session_daily_complete(SESSION, as_of=lunch) is False
    holiday = date(2026, 1, 1)
    assert session_daily_complete(holiday, as_of=jst(13, 0, holiday)) is False
    assert vendor_publish_ready(holiday, as_of=jst(18, 0, holiday)) is True


def test_missing_calendar_is_unavailable_not_assumed_trading(tmp_path):
    repo = init_repo(tmp_path / "jp-core.db")

    def unknown(_value: str):
        return None

    result = evaluate_t1_from_daily(
        history_plus_session("72030"),
        session_date=SESSION,
        resistance_high=100,
        as_of=jst(18, 0),
        is_trading_day=unknown,
        prior_trading_sessions=lambda *_a: None,
    )
    assert result["status"] == "unavailable"
    assert result["reason"] == "calendar_unknown"
    assert repo.prior_trading_sessions("1990-01-02", 20) is None


def test_publication_fields_stay_separate_from_query_time(tmp_path, monkeypatch):
    from tests.support.a0_t1_fixtures import api_client, diverging_pool, publish_strength_rows

    repo = init_repo(tmp_path / "jp-core.db")
    publish_strength_rows(repo, diverging_pool())
    client = api_client(tmp_path, monkeypatch)
    first = client.get("/api/strength/scan", params={"top": 5}).json()
    second = client.get("/api/strength/scan", params={"top": 5, "ranking_algorithm": "a0"}).json()
    assert first["publication_id"] == second["publication_id"]
    assert first["input_data_through"] == second["input_data_through"]
    assert first["queried_at"]
    assert second["queried_at"]
    assert first["built_at"] == second["built_at"]
    freshness = evaluate_freshness(
        stored_trade_date=first["trade_date"],
        expected=first["expected_trade_date"],
        stored_score_version=first["stored_score_version"],
        current_score_version=first["expected_score_version"],
        coverage=first.get("coverage") or {},
    )
    assert freshness["freshness"] in {"current", "stale", "partial", "degraded", "unknown"}


def test_expected_trade_date_uses_tokyo_batch_gate():
    def latest(on_or_before: str) -> str | None:
        cursor = date.fromisoformat(on_or_before)
        for _ in range(10):
            if cursor.weekday() < 5:
                return cursor.isoformat()
            cursor -= timedelta(days=1)
        return None

    session = lambda value: date.fromisoformat(value).weekday() < 5
    before = expected_trade_date(
        today="2026-03-16",
        now=jst(16, 0),
        batch_hhmm="17:00",
        latest_trading_day=latest,
        session_status=session,
    )
    after = expected_trade_date(
        today="2026-03-16",
        now=jst(17, 5),
        batch_hhmm="17:00",
        latest_trading_day=latest,
        session_status=session,
    )
    assert before == "2026-03-13"
    assert after == "2026-03-16"
