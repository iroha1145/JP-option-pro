"""Credit balances use publication coverage without inventing stored data dates."""

import httpx
import pytest

from app.domain.timeutil import add_days
from app.providers.jquants.client import JQuantsClient
from app.providers.jquants.rate_limit import JQuantsRateLimits
from app.repositories.core import CoreRepository
from app.services import data_status as status_module
from app.services.jquants_sync import DATASET_MARGIN_INTEREST, JQuantsSyncEngine


def _core(tmp_path, *, stored_date="2026-09-29", checkpoint=None):
    core = CoreRepository(tmp_path / "core.db")
    core.initialize()
    if stored_date:
        core.upsert_margin_interest([
            {"canonical_code": "72030", "application_date": stored_date,
             "long_total": 1000, "short_total": 500},
        ])
    core.record_sync_success(
        DATASET_MARGIN_INTEREST, checkpoint=checkpoint or {"last_synced_date": "2026-10-09"},
        rows_total=0, data_through="2026-10-09",
    )
    return core


def _row(day, *, long_total=2000):
    return {"Code": "72030", "Date": day, "LongVol": long_total, "ShrtVol": 500}


def _engine(core, handler):
    return JQuantsSyncEngine(JQuantsClient(
        "test-key", transport=httpx.MockTransport(handler), sleep=lambda _: None,
        rate_limits=JQuantsRateLimits(global_per_minute=10000),
    ), core)


def test_false_checkpoint_is_repaired_and_late_publications_are_revisited(tmp_path):
    core = _core(tmp_path)
    seen = []
    late_available = False

    def handler(request):
        assert request.url.path.endswith("/markets/margin-interest")
        params = dict(request.url.params)
        seen.append(params)
        rows = [_row("2026-10-08")] if late_available and params.get("published_date") == "2026-10-09" else []
        return httpx.Response(200, json={"data": rows})

    engine = _engine(core, handler)
    first = engine.sync_margin_interest("2026-10-09")
    assert first["status"] == "ok"
    assert first["rows_total"] == 1
    assert first["data_through"] == "2026-09-29"
    state = core.sync_state(DATASET_MARGIN_INTEREST)
    assert state["checkpoint"]["last_synced_date"] == "2026-09-29"
    assert state["checkpoint"]["last_checked_publication_date"] == "2026-10-09"
    assert seen[0] == {"date": "2026-09-26"}
    assert seen[2] == {"published_date": "2026-09-28"}

    late_available = True
    seen.clear()
    second = engine.sync_margin_interest("2026-10-12")
    assert {"published_date": "2026-10-09"} in seen
    assert second["rows_total"] == 2
    assert second["data_through"] == "2026-10-08"
    assert core.margin_interest_for_code("72030")[-1]["long_total"] == 2000

    # Repeated coverage can update the same row without inflating the stored count.
    assert engine.sync_margin_interest("2026-10-12")["rows_total"] == 2


def test_empty_results_preserve_data_and_repair_stored_statistics(tmp_path):
    core = _core(tmp_path)
    result = _engine(core, lambda _: httpx.Response(200, json={"data": []})).sync_margin_interest("2026-10-09")
    state = core.sync_state(DATASET_MARGIN_INTEREST)
    assert result["rows"] == 0
    assert state["rows_total"] == 1
    assert state["data_through"] == "2026-09-29"
    assert state["checkpoint"]["last_synced_date"] == "2026-09-29"
    assert core.margin_interest_for_code("72030")[0]["long_total"] == 1000


def test_empty_database_requests_backfill_and_clears_false_data_date(tmp_path):
    core = _core(tmp_path, stored_date=None)

    def must_not_fetch(_):
        raise AssertionError("Empty history should use the bulk backfill lane")

    result = _engine(core, must_not_fetch).sync_margin_interest("2026-10-09")
    assert result["status"] == "backfill_required"
    assert core.sync_state(DATASET_MARGIN_INTEREST)["rows_total"] == 0
    assert core.sync_state(DATASET_MARGIN_INTEREST)["data_through"] is None


def test_partial_failure_keeps_writes_and_last_successful_query_coverage(tmp_path):
    core = _core(tmp_path, checkpoint={
        "last_synced_date": "2026-10-09", "last_checked_publication_date": "2026-09-30",
    })
    previous_success = core.sync_state(DATASET_MARGIN_INTEREST)["last_success_at"]

    def handler(request):
        day = dict(request.url.params).get("published_date")
        if day == "2026-10-03":
            return httpx.Response(403, json={"message": "provider denied"})
        return httpx.Response(200, json={"data": [_row("2026-10-01")] if day == "2026-10-02" else []})

    result = _engine(core, handler).sync_margin_interest("2026-10-09")
    state = core.sync_state(DATASET_MARGIN_INTEREST)
    assert result["status"] == "error"
    assert result["rows"] == 1
    assert result["rows_total"] == state["rows_total"] == 2
    assert result["data_through"] == state["data_through"] == "2026-10-01"
    assert state["checkpoint"]["last_synced_date"] == "2026-10-01"
    assert state["checkpoint"]["last_checked_publication_date"] == "2026-09-30"
    assert state["last_success_at"] == previous_success
    assert state["last_error_code"] == result["error_code"]
    assert core.margin_interest_for_code("72030")[-1]["application_date"] == "2026-10-01"


@pytest.mark.parametrize("stored_date,checkpoint", [
    ("2026-09-29", {"last_synced_date": "2026-10-09", "last_checked_publication_date": "2026-09-30"}),
    ("2026-01-09", {"last_synced_date": "2026-10-09"}),
])
def test_long_outage_and_empty_historical_batches_make_bounded_progress(tmp_path, stored_date, checkpoint):
    core = _core(tmp_path, stored_date=stored_date, checkpoint=checkpoint)
    calls = []

    def handler(request):
        params = dict(request.url.params)
        calls.append(params.get("published_date") or params["date"])
        return httpx.Response(200, json={"data": []})

    engine = _engine(core, handler)
    previous_end = None
    for _ in range(14):
        calls.clear()
        result = engine.sync_margin_interest("2026-12-15")
        assert 1 <= len(calls) <= 45
        assert calls[0] == result["query_from"]
        assert calls[-1] == result["query_through"]
        assert core.sync_state(DATASET_MARGIN_INTEREST)["checkpoint"]["last_checked_query_date"] == calls[-1]
        if previous_end:
            assert calls[0] == add_days(previous_end, -13)
            assert calls[-1] > previous_end
        previous_end = calls[-1]
        if result["caught_up"]:
            break
    assert result["caught_up"] is True
    assert result["data_through"] == stored_date
    assert result["rows_total"] == 1


@pytest.mark.parametrize("stored_date,freshness", [
    ("2026-09-29", "stale"), ("2026-10-08", "fresh"),
])
def test_status_uses_physical_rows_and_next_business_day_publication(tmp_path, monkeypatch, stored_date, freshness):
    core = _core(tmp_path, stored_date=stored_date)
    core.upsert_trading_days([
        {"calendar_date": day, "holiday_division": "1"}
        for day in ("2026-10-08", "2026-10-09")
    ])
    core.upsert_daily_bars([{"canonical_code": "72030", "trade_date": "2026-10-09", "close": 100}])
    monkeypatch.setattr(status_module, "intraday_addon_status", lambda _: {"minute": {}, "tick": {}})
    item = next(row for row in status_module.data_status(core, jquants_configured=True)["datasets"]
                if row["key"] == DATASET_MARGIN_INTEREST)
    assert item["cadence"] == "daily"
    assert item["data_through"] == stored_date
    assert item["rows_total"] == 1
    assert item["freshness"] == freshness


def test_transition_friday_keeps_weekly_freshness_until_first_daily_publication(tmp_path, monkeypatch):
    core = _core(tmp_path, stored_date="2026-09-18")
    core.upsert_trading_days([{"calendar_date": "2026-09-24", "holiday_division": "1"}])
    core.upsert_daily_bars([{"canonical_code": "72030", "trade_date": "2026-09-25", "close": 100}])
    monkeypatch.setattr(status_module, "intraday_addon_status", lambda _: {"minute": {}, "tick": {}})
    item = next(row for row in status_module.data_status(core, jquants_configured=True)["datasets"]
                if row["key"] == DATASET_MARGIN_INTEREST)
    assert item["freshness"] == "fresh"


def test_status_preserves_provider_error_even_with_recent_stored_rows(tmp_path, monkeypatch):
    core = _core(tmp_path, stored_date="2026-10-08")
    core.record_sync_error(DATASET_MARGIN_INTEREST, "jquants_test_failure")
    monkeypatch.setattr(status_module, "intraday_addon_status", lambda _: {"minute": {}, "tick": {}})
    item = next(row for row in status_module.data_status(core, jquants_configured=True)["datasets"]
                if row["key"] == DATASET_MARGIN_INTEREST)
    assert item["freshness"] == "error"
    assert item["last_error_code"] == "jquants_test_failure"
