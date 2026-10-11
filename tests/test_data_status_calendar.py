"""Status uses TOPIX's own rows and preserves market-date and error boundaries."""

import pytest

from app.repositories.core import CoreRepository
from app.services import data_status as status_module


@pytest.fixture
def core(tmp_path, monkeypatch):
    repository = CoreRepository(tmp_path / "core.db")
    repository.initialize()
    repository.upsert_daily_bars([
        {"canonical_code": "72030", "trade_date": "2026-10-09", "close": 100},
    ])
    monkeypatch.setattr(status_module, "intraday_addon_status", lambda _: {"minute": {}, "tick": {}})
    # Sunday exceeds 40 hours since Friday's batch.
    monkeypatch.setattr(status_module, "_hours_since", lambda _: 60)
    return repository


def _item(core, dataset):
    return next(row for row in status_module.data_status(core, jquants_configured=True)["datasets"]
                if row["key"] == dataset)


def test_topix_uses_own_physical_rows_and_shared_index_task(core):
    core.upsert_index_bars([
        {"index_code": "0000", "trade_date": day, "close": 2800}
        for day in ("2026-10-08", "2026-10-09")
    ] + [{"index_code": "0028", "trade_date": "2026-10-09", "close": 1400}])
    core.record_sync_success("index_prices", rows_total=79, data_through="2026-10-09")
    shared = core.sync_state("index_prices")
    assert core.sync_state("topix_prices") is None
    item = _item(core, "topix_prices")
    assert item["freshness"] == "fresh"
    assert item["rows_total"] == 2
    assert item["data_through"] == "2026-10-09"
    assert item["last_success_at"] == shared["last_success_at"]


def test_topix_without_rows_is_not_invented_from_other_indices(core):
    core.upsert_index_bars([{"index_code": "0028", "trade_date": "2026-10-09", "close": 1400}])
    core.record_sync_success("index_prices", rows_total=79, data_through="2026-10-09")
    item = _item(core, "topix_prices")
    assert item["rows_total"] == 0
    assert item["data_through"] is None
    assert item["freshness"] == "never_synced"


def test_topix_physical_date_can_lag_shared_index_date(core):
    core.upsert_index_bars([
        {"index_code": "0000", "trade_date": "2026-10-08", "close": 2800},
        {"index_code": "0028", "trade_date": "2026-10-09", "close": 1400},
    ])
    core.record_sync_success("index_prices", rows_total=79, data_through="2026-10-09")
    item = _item(core, "topix_prices")
    assert item["data_through"] == "2026-10-08"
    assert item["freshness"] == "stale"


@pytest.mark.parametrize("dataset", ["margin_alerts", "short_sale_ratio"])
def test_friday_coverage_remains_fresh_on_sunday(core, dataset):
    core.record_sync_success(dataset, rows_total=1, data_through="2026-10-09")
    assert _item(core, dataset)["freshness"] == "fresh"


@pytest.mark.parametrize("dataset", ["margin_alerts", "short_sale_ratio"])
def test_lagging_market_date_remains_stale_after_recent_attempt(core, monkeypatch, dataset):
    monkeypatch.setattr(status_module, "_hours_since", lambda _: 1)
    core.record_sync_success(dataset, rows_total=1, data_through="2026-10-08")
    assert _item(core, dataset)["freshness"] == "stale"


@pytest.mark.parametrize("dataset", ["topix_prices", "margin_alerts", "short_sale_ratio"])
def test_current_data_does_not_hide_real_provider_error(core, monkeypatch, dataset):
    monkeypatch.setattr(status_module, "_hours_since", lambda _: 1)
    state_key = "index_prices" if dataset == "topix_prices" else dataset
    if dataset == "topix_prices":
        core.upsert_index_bars([{"index_code": "0000", "trade_date": "2026-10-09", "close": 2800}])
    core.record_sync_success(state_key, rows_total=1, data_through="2026-10-09")
    core.record_sync_error(state_key, "jquants_test_failure")
    item = _item(core, dataset)
    assert item["freshness"] == "error"
    assert item["last_error_code"] == "jquants_test_failure"


def test_legacy_topix_import_state_is_fallback_when_no_shared_task_exists(core):
    core.upsert_index_bars([{"index_code": "0000", "trade_date": "2026-10-09", "close": 2800}])
    core.record_sync_success("topix_prices", rows_total=79, data_through="2026-10-09")
    item = _item(core, "topix_prices")
    assert item["rows_total"] == 1
    assert item["last_success_at"] == core.sync_state("topix_prices")["last_success_at"]
    assert item["freshness"] == "fresh"


def test_unrelated_dataset_keeps_elapsed_time_freshness(core):
    core.record_sync_success("financial_summary", rows_total=1, data_through="2026-10-09")
    assert _item(core, "financial_summary")["freshness"] == "stale"
