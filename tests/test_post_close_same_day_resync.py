"""Same-session retries must reach J-Quants after its first non-empty response.

Only the vendor HTTP transport is replaced. The sync engine, checkpoint
storage, post-close task, scoring/publication and supervisor are production
implementations, so a scheduled retry that merely rescans old rows cannot pass.
"""

from __future__ import annotations

import asyncio
from collections import Counter

import httpx
import pytest

from app.providers.jquants.client import JQuantsClient
from app.repositories.core import CoreRepository
from app.services import jquants_sync as sync
from app.worker.runtime import WorkerSupervisor
from app.worker.state import WorkerStateRepository
from app.worker.tasks import TASK_POST_CLOSE, _run_radar_and_screener
from tests.test_screener_freshness import _config, _seed
from tests.test_screener_schedule_e2e import _post_close_spec, _TaskCtx


PREVIOUS = "2026-09-07"
TARGET = "2026-09-08"
CODES = ("72030", "67580")
BAR_DATASETS = (sync.DATASET_DAILY_PRICES, sync.DATASET_INDEX_PRICES)


def _wire_bar(code: str, day: str = TARGET, **updates) -> dict:
    return {
        "Code": code,
        "Date": day,
        "O": 100.0,
        "H": 102.0,
        "L": 99.0,
        "C": 101.0,
        "Vo": 1_000_000.0,
        "Va": 5e8,
        "AdjO": 100.0,
        "AdjH": 102.0,
        "AdjL": 99.0,
        "AdjC": 101.0,
        "AdjVo": 1_000_000.0,
        "AdjFactor": 1.0,
        **updates,
    }


class _Vendor:
    def __init__(self, gap: str | None = None):
        self.gap = gap
        self.complete = gap is None
        self.equity_updates: dict = {}
        self.index_close = 2800.0
        self.bar_requests: list[tuple[str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/v2")
        day = request.url.params.get("date", "")
        if path == "/equities/bars/daily":
            self.bar_requests.append((path, day))
            rows = [_wire_bar(code, day, **self.equity_updates) for code in CODES]
            if not self.complete and self.gap == "missing_equity":
                rows = rows[:1]
            elif not self.complete and self.gap == "invalid_equity":
                rows[1].update(C="", AdjC="")
            return httpx.Response(200, json={"data": rows})
        if path == "/indices/bars/daily":
            self.bar_requests.append((path, day))
            code = "0500" if not self.complete and self.gap == "missing_topix" else "0000"
            return httpx.Response(
                200, json={"data": [{"Code": code, "Date": day, "C": self.index_close}]}
            )
        if path == "/equities/earnings-calendar":
            return httpx.Response(200, json={"data": [{"Code": CODES[0], "Date": TARGET}]})
        raise AssertionError(f"unexpected vendor request: {request.url}")


def _context(repo: CoreRepository, vendor: _Vendor):
    client = JQuantsClient(
        "test-key", transport=httpx.MockTransport(vendor), max_attempts=1, sleep=lambda _: None
    )
    engine = sync.JQuantsSyncEngine(client, repo)
    # These unrelated inputs are already current; they must not affect bar retries.
    for dataset in (
        sync.DATASET_MARGIN_INTEREST,
        sync.DATASET_MARGIN_ALERTS,
        sync.DATASET_SHORT_RATIO,
        sync.DATASET_SHORT_POSITIONS,
    ):
        repo.record_sync_success(dataset, checkpoint={"last_synced_date": TARGET})
    return _TaskCtx(repo, engine, target=TARGET, radar=_config()), client


async def _run_scheduled_once(state: WorkerStateRepository, spec) -> dict:
    supervisor = WorkerSupervisor(state, [spec], owner_id="resync-restarted-owner")
    loop = asyncio.create_task(supervisor.run())
    try:
        async with asyncio.timeout(10):
            while True:
                statuses = await asyncio.to_thread(state.task_statuses)
                if statuses and statuses[0]["status"] in {"completed", "failed"}:
                    return statuses[0]
                if loop.done():
                    await loop
                await asyncio.sleep(0.025)
    finally:
        supervisor.request_stop()
        await asyncio.wait_for(loop, timeout=5)


@pytest.mark.parametrize("gap", ["missing_equity", "invalid_equity"])
def test_scheduled_retry_refetches_checkpointed_partial_day_and_publishes(tmp_path, gap):
    repo = _seed(tmp_path, list(CODES), PREVIOUS)
    repo.upsert_trading_days([{"calendar_date": TARGET, "holiday_division": "1"}])
    vendor = _Vendor(gap)
    context, client = _context(repo, vendor)
    try:
        previous = _run_radar_and_screener(context, PREVIOUS)
        assert previous["outcome"] == "published"
        previous_publication = repo.strength_meta()["publication_id"]
        for dataset in BAR_DATASETS:
            repo.record_sync_success(dataset, checkpoint={"last_synced_date": PREVIOUS})

        spec = _post_close_spec(context)
        first = spec.run(None)
        assert first.status == "completed"
        assert first.outcome == "retained"
        assert first.details["radar"]["reason"] == "incomplete_coverage"
        assert repo.strength_meta()["publication_id"] == previous_publication
        for dataset in BAR_DATASETS:
            assert repo.sync_state(dataset)["checkpoint"]["last_synced_date"] == TARGET

        state = WorkerStateRepository(tmp_path / "worker.db")
        state.initialize()
        supervisor = WorkerSupervisor(state, [], owner_id="resync-first-owner")
        supervisor._fencing_token = state.acquire_lease("resync-first-owner")
        delay = supervisor._apply_retry_policy(TASK_POST_CLOSE, first, first.next_delay_seconds)
        pending = state.pending_retries_for_task(TASK_POST_CLOSE)
        assert len(pending) == 1 and pending[0]["target_trade_date"] == TARGET
        assert 0.5 <= delay <= 1200.0

        # A manual rescan must neither hit the vendor nor consume the bar retry.
        requests_before = list(vendor.bar_requests)
        radar_only = spec.run({"__action_type": "radar_refresh"})
        supervisor._apply_retry_policy(TASK_POST_CLOSE, radar_only, radar_only.next_delay_seconds)
        assert vendor.bar_requests == requests_before
        assert state.pending_retries_for_task(TASK_POST_CLOSE)[0]["next_retry_at"] == (
            pending[0]["next_retry_at"]
        )

        # The next scheduled run uses the same persisted checkpoints after restart.
        vendor.complete = True
        finished = asyncio.run(_run_scheduled_once(state, spec))
        assert finished["status"] == "completed"
        assert finished["details"]["outcome"] == "published"
        counts = Counter(vendor.bar_requests)
        assert counts[("/equities/bars/daily", TARGET)] == 2
        assert counts[("/indices/bars/daily", TARGET)] == 2
        assert repo.strength_meta()["trade_date"] == TARGET
        assert repo.strength_meta()["publication_id"] != previous_publication
        assert len(repo.strength_rows_all()) == 2
        assert repo.screener_trade_date() == TARGET
        assert state.pending_retries_for_task(TASK_POST_CLOSE) == []
    finally:
        client.close()


@pytest.mark.parametrize("correction", ["ohlc", "turnover", "index", "missing_topix"])
def test_same_day_vendor_correction_reaches_new_publication(tmp_path, correction):
    repo = _seed(tmp_path, list(CODES), PREVIOUS)
    repo.upsert_trading_days([{"calendar_date": TARGET, "holiday_division": "1"}])
    vendor = _Vendor("missing_topix" if correction == "missing_topix" else None)
    context, client = _context(repo, vendor)
    try:
        for dataset in BAR_DATASETS:
            repo.record_sync_success(dataset, checkpoint={"last_synced_date": PREVIOUS})
        spec = _post_close_spec(context)
        assert spec.run(None).outcome == "published"
        previous_meta = repo.strength_meta()
        if correction == "ohlc":
            vendor.equity_updates = {"H": 103.0, "C": 102.0, "AdjH": 103.0, "AdjC": 102.0}
        elif correction == "turnover":
            vendor.equity_updates = {"Va": 9e8}
        else:
            vendor.complete = True
            vendor.index_close = 2850.0

        result = spec.run(None)
        assert result.outcome == "published"
        current_meta = repo.strength_meta()
        assert current_meta["publication_id"] != previous_meta["publication_id"]
        assert current_meta["input_fingerprint"] != previous_meta["input_fingerprint"]
        if correction in {"index", "missing_topix"}:
            assert repo.index_series("0000", limit=1)[0]["close"] == 2850.0
        else:
            bar = repo.bars_for_code(CODES[0], start_date=TARGET)[0]
            assert bar["close"] == (102.0 if correction == "ohlc" else 101.0)
            assert bar["turnover_value"] == (9e8 if correction == "turnover" else 5e8)

        # Refetching identical data remains idempotent at the publication layer.
        assert spec.run(None).outcome == "already_current"
        assert repo.strength_meta()["publication_id"] == current_meta["publication_id"]
    finally:
        client.close()


@pytest.mark.parametrize("method,dataset", [
    ("sync_daily_bars", sync.DATASET_DAILY_PRICES),
    ("sync_index_bars", sync.DATASET_INDEX_PRICES),
])
@pytest.mark.parametrize("response_status", [200, 503])
def test_empty_or_failed_same_day_refetch_retains_rows_and_checkpoint(
    tmp_path, method, dataset, response_status
):
    repo = _seed(tmp_path, list(CODES), TARGET)
    repo.record_sync_success(dataset, checkpoint={"last_synced_date": TARGET})
    calls = []

    def handler(request):
        calls.append(request.url.params["date"])
        return httpx.Response(response_status, json={"data": []})

    with JQuantsClient("test-key", transport=httpx.MockTransport(handler), max_attempts=1) as client:
        result = getattr(sync.JQuantsSyncEngine(client, repo), method)(TARGET)
    assert calls == [TARGET]
    assert result["status"] == ("not_published" if response_status == 200 else "error")
    assert repo.sync_state(dataset)["checkpoint"]["last_synced_date"] == TARGET
    assert repo.bars_for_code(CODES[0], start_date=TARGET)[0]["close"] == 100.0
    assert repo.index_series("0000", limit=1)[0]["close"] == 2700.0


@pytest.mark.parametrize("method,dataset", [
    ("sync_daily_bars", sync.DATASET_DAILY_PRICES),
    ("sync_index_bars", sync.DATASET_INDEX_PRICES),
])
def test_refetch_does_not_rewind_checkpoint_or_skip_earlier_pending_days(tmp_path, method, dataset):
    repo = _seed(tmp_path, list(CODES), "2026-09-06")
    repo.upsert_trading_days([
        {"calendar_date": day, "holiday_division": "1"} for day in (PREVIOUS, TARGET)
    ])
    repo.record_sync_success(dataset, checkpoint={"last_synced_date": "2026-09-06"})
    vendor = _Vendor()
    with JQuantsClient("test-key", transport=httpx.MockTransport(vendor)) as client:
        engine = sync.JQuantsSyncEngine(client, repo)
        assert getattr(engine, method)(TARGET)["status"] == "ok"
        assert [day for _path, day in vendor.bar_requests] == [PREVIOUS, TARGET]
        vendor.bar_requests.clear()
        # A previous-session request must not overwrite a newer checkpoint.
        assert getattr(engine, method)(PREVIOUS)["status"] == "ok"
        assert vendor.bar_requests == []
        assert repo.sync_state(dataset)["checkpoint"]["last_synced_date"] == TARGET
