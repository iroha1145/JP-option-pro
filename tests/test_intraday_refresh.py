"""Trading-date cache refresh, publication retry and real persisted status."""

import io
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.api import deps, stocks
from app.config import reset_settings_for_tests
from app.data_paths import get_data_paths
from app.repositories.intraday_store import IntradayStore
from app.services.intraday import cache_freshness, fetch_latest_ticks, fetch_recent_minutes
from app.services.data_status import data_status
from app.worker.state import WorkerStateRepository
from app.worker.tasks import TaskContext, build_default_tasks, TASK_INTRADAY

LATEST = "2026-10-09"
OLD = "2026-07-31"
CODE = "72030"


def _minute(day):
    return {"canonical_code": CODE, "trade_date": day, "bar_time": "09:00", "open": 100,
            "high": 102, "low": 99, "close": 101, "volume": 100, "turnover_value": 10100}


class PublishedProvider:
    def fetch_rows(self, path, params):
        assert path == "/equities/bars/minute"
        return [{"Date": params["date"], "Code": CODE, "Time": "09:00",
                 "O": 100, "H": 102, "L": 99, "C": 101, "Vo": 100, "Va": 10100}]

    def bulk_list(self, **kwargs):
        assert kwargs["endpoint"] == "equities/trades"
        return [{"Key": f"equities/trades/live/equities_trades_{LATEST.replace('-', '')}.csv.gz"}]

    def bulk_download_csv(self, key):
        return io.StringIO("Date,Code,Time,Price,TradingVolume\n"
                           f"{LATEST},{CODE},09:00:00,101,100\n")


@pytest.fixture()
def setup(data_dir, monkeypatch):
    monkeypatch.setenv("JQUANTS_API_KEY", "test-only")
    reset_settings_for_tests()
    deps.reset_dependencies_for_tests()
    context = TaskContext()
    context._client = PublishedProvider()
    core = context.repository
    core.replace_security_master([{"canonical_code": CODE, "name_ja": "テスト"}], as_of_date=LATEST)
    core.upsert_trading_days([{"calendar_date": f"2026-10-{day:02d}", "holiday_division": "1"} for day in range(5, 10)])
    # A future calendar row must not turn a weekend request into a Monday fetch.
    core.upsert_trading_days([{"calendar_date": "2026-10-12", "holiday_division": "1"}])
    core.upsert_daily_bars([{"canonical_code": CODE, "trade_date": LATEST, "open": 100,
                            "high": 102, "low": 99, "close": 101, "volume": 100}])
    store = IntradayStore(get_data_paths().intraday_db)
    store.upsert_minute_bars([_minute(OLD)])
    store.record_fetched_day(CODE, OLD, 1)
    store.replace_ticks(CODE, OLD, [{"tick_time": "09:00:00", "price": 100, "volume": 100}])
    for dataset in ("minute", "tick"):
        store.record_availability("available", dataset=dataset)
    worker = WorkerStateRepository(get_data_paths().worker_db)
    worker.initialize()
    app = FastAPI()
    app.include_router(stocks.router)
    with TestClient(app) as client:
        yield context, store, worker, client
    deps.reset_dependencies_for_tests()
    reset_settings_for_tests()


@pytest.mark.parametrize("dataset", ["minute", "tick"])
def test_old_cache_queue_worker_persistence_and_fresh_api(setup, monkeypatch, dataset):
    context, store, worker, client = setup
    other = "99840"
    store.upsert_minute_bars([{**_minute(OLD), "canonical_code": other}])
    store.record_fetched_day(other, OLD, 1)
    store.replace_ticks(other, OLD, [{"tick_time": "09:00:00", "price": 500, "volume": 100}])
    import app.access as access
    monkeypatch.setattr(access, "current_request_can_refresh_public_data", lambda: True)
    url = f"/api/stocks/7203/{'ticks' if dataset == 'tick' else 'chart?interval=1m'}"
    before = client.get(url).json()
    assert before["available"] is True
    assert before["data_through"] == OLD
    assert before["target_date"] == LATEST
    assert before["stale"] and before["refreshing"]
    # Polls join the existing action instead of scheduling duplicate downloads.
    assert client.get(url).json()["refreshing"] is True
    assert len(worker.recent_actions()) == 1
    token = worker.acquire_lease("test")
    action = worker.claim_next_action("test", token)
    assert action["payload"]["code"] == CODE
    task = next(spec for spec in build_default_tasks(context) if spec.name == TASK_INTRADAY)
    result = task.run(action["payload"])
    assert result.status == "completed"
    assert client.get(url).json()["refreshing"] is True
    worker.complete_action("test", token, action["action_id"], status=result.status, result=result.details)
    after = client.get(url).json()
    assert after["available"] and after["data_through"] == LATEST
    assert not after["stale"] and not after["refreshing"]
    assert worker.get_action(action["action_id"])["status"] == "completed"
    assert len(worker.recent_actions()) == 1
    summary = store.dataset_summary(dataset)
    assert summary["data_through"] == LATEST and summary["rows_total"] > 0
    assert store.minute_bars(other, dates=[OLD])
    assert store.ticks_for(other, OLD)


@pytest.mark.parametrize("dataset", ["minute", "tick"])
def test_anonymous_keeps_old_cache_without_queuing(setup, monkeypatch, dataset):
    _, _, worker, client = setup
    import app.access as access
    monkeypatch.setattr(access, "current_request_can_refresh_public_data", lambda: False)
    url = f"/api/stocks/7203/{'ticks' if dataset == 'tick' else 'chart?interval=1m'}"
    body = client.get(url).json()
    assert body["data_through"] == OLD and body["available"] and body["stale"]
    assert not body["queued"] and not body["refreshing"]
    assert worker.recent_actions() == []


def test_unpublished_ticks_retry_then_complete_without_erasing_old_tape(setup):
    context, store, _, _ = setup
    class Waiting(PublishedProvider):
        def bulk_list(self, **kwargs):
            return []
    result = fetch_latest_ticks(client=Waiting(), store=store, core=context.repository, canonical_code=CODE)
    assert result["status"] == "not_published"
    assert store.ticks_for(CODE, OLD)
    pending = cache_freshness(store, CODE, "tick", LATEST)
    assert pending["publication_pending"] and pending["retry_after_seconds"] > 0
    assert not pending["needs_fetch"]
    expired = (datetime.now(timezone.utc) - timedelta(minutes=16)).isoformat()
    with store.write() as conn:
        conn.execute("UPDATE tick_days SET fetched_at=? WHERE trade_date=?", (expired, LATEST))
    assert cache_freshness(store, CODE, "tick", LATEST)["needs_fetch"]
    result = fetch_latest_ticks(client=PublishedProvider(), store=store, core=context.repository, canonical_code=CODE)
    assert result["ticks"] == 1
    assert not cache_freshness(store, CODE, "tick", LATEST)["needs_fetch"]


def test_minute_empty_publication_retries_but_real_no_trade_day_is_complete(setup):
    context, store, _, _ = setup
    class Waiting(PublishedProvider):
        def fetch_rows(self, path, params):
            return []
    result = fetch_recent_minutes(client=Waiting(), store=store, core=context.repository, canonical_code=CODE, days=1)
    assert result["status"] == "not_published"
    assert cache_freshness(store, CODE, "minute", LATEST)["publication_pending"]
    assert store.minute_bars(CODE, dates=[OLD])
    context.repository.upsert_daily_bars([{"canonical_code": CODE, "trade_date": LATEST}])
    result = fetch_recent_minutes(client=Waiting(), store=store, core=context.repository, canonical_code=CODE, days=1)
    assert result["status"] == "ok"
    status = cache_freshness(store, CODE, "minute", LATEST)
    assert status["latest_empty"] and not status["needs_fetch"]


def test_data_status_reads_actual_intraday_cache_and_becomes_fresh(setup):
    context, store, _, _ = setup
    def entries():
        return {row["key"]: row for row in data_status(context.repository, jquants_configured=True)["datasets"]}
    for key in ("intraday_prices", "tick_trades"):
        assert entries()[key]["data_through"] == OLD
        assert entries()[key]["freshness"] == "stale"
        assert entries()[key]["rows_total"] == 1
    fetch_recent_minutes(client=PublishedProvider(), store=store, core=context.repository, canonical_code=CODE)
    fetch_latest_ticks(client=PublishedProvider(), store=store, core=context.repository, canonical_code=CODE)
    for key in ("intraday_prices", "tick_trades"):
        assert entries()[key]["data_through"] == LATEST
        assert entries()[key]["freshness"] == "fresh"
        assert entries()[key]["last_success_at"]


@pytest.mark.parametrize("dataset", ["minute", "tick"])
def test_calendar_future_dates_cannot_be_used_before_daily_data_exists(setup, dataset):
    context, store, _, _ = setup
    with context.repository.write() as conn:
        conn.execute("DELETE FROM daily_bars")
    fetch = fetch_latest_ticks if dataset == "tick" else fetch_recent_minutes
    result = fetch(client=PublishedProvider(), store=store, core=context.repository, canonical_code=CODE)
    assert result == {"status": "error", "error_code": "daily_prices_empty"}


def test_v2_migration_preserves_rows_and_retries_old_zero_markers(setup):
    _, store, _, _ = setup
    store.record_fetched_day(CODE, LATEST, 0)
    store.replace_ticks(CODE, LATEST, [])
    before = {dataset: store.dataset_summary(dataset)["rows_total"] for dataset in ("minute", "tick")}
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("ALTER TABLE fetched_days DROP COLUMN fetch_status")
        conn.execute("ALTER TABLE tick_days DROP COLUMN fetch_status")
        conn.execute("UPDATE jp_intraday_schema SET version='jp-intraday-v2', checksum='old'")
    store.initialize()
    for dataset in ("minute", "tick"):
        assert store.dataset_summary(dataset)["rows_total"] == before[dataset]
        assert cache_freshness(store, CODE, dataset, LATEST)["publication_pending"]
    assert store.fetched_days_for(CODE)[OLD]["fetch_status"] == "complete"
    assert store.tick_days_for(CODE)[OLD]["fetch_status"] == "complete"


@pytest.mark.parametrize("dataset", ["minute", "tick"])
@pytest.mark.parametrize("outcome", ["error", "not_published"])
def test_worker_preserves_old_cache_when_new_data_does_not_arrive(setup, dataset, outcome):
    from app.providers.jquants.errors import JQuantsError
    context, store, _, _ = setup
    class Missing(PublishedProvider):
        def fetch_rows(self, path, params):
            if outcome == "error":
                raise JQuantsError("test unavailable", code="jquants_timeout")
            return []
        def bulk_list(self, **kwargs):
            if outcome == "error":
                raise JQuantsError("test unavailable", code="jquants_timeout")
            return []
    context._client = Missing()
    task = next(spec for spec in build_default_tasks(context) if spec.name == TASK_INTRADAY)
    result = task.run({"code": CODE, "dataset": dataset})
    assert result.status == ("failed" if outcome == "error" else "completed")
    assert store.minute_bars(CODE, dates=[OLD])[0]["close"] == 101
    assert store.ticks_for(CODE, OLD)[0]["price"] == 100
    if outcome == "error":
        assert store.availability(dataset)["last_error_code"] == "jquants_timeout"
