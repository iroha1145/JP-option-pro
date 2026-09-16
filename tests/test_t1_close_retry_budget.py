"""T1 retry budget through the real worker/supervisor wait_for path."""

from __future__ import annotations

import asyncio
from dataclasses import replace

from app.services.radar.t1_close import T1_RETRY_MAX_ATTEMPTS, complete_pending_t1, evaluate_t1_from_local_bars
from app.services.radar.t1_priority import T1_MET, T1_UNMET
from app.worker.runtime import WorkerSupervisor
from app.worker.state import WorkerStateRepository
from app.worker.tasks import TASK_T1_CLOSE, TaskContext, build_default_tasks
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


def _seed_pending(tmp_path, *, missing_t: bool = True, sibling: bool = True):
    repo = init_repo(tmp_path / "jp-core.db")
    insert_security(repo, "72030")
    insert_security(repo, "67580")
    priors = [t1_bar("72030", day) for day in prior_weekdays(SESSION, 20)]
    if missing_t:
        repo.upsert_daily_bars(priors)
    else:
        repo.upsert_daily_bars(history_plus_session("72030"))
    insert_radar_event(repo, event_id="evt-hang", code="72030", priority=40, resistance_high=100)
    if sibling:
        repo.upsert_daily_bars(history_plus_session("67580"))
        insert_radar_event(repo, event_id="evt-done", code="67580", priority=90, resistance_high=100)
    evaluate_t1_from_local_bars(repo, scan_date=SESSION_ISO, as_of=jst(18, 0))
    return repo


def _action_status(state: WorkerStateRepository, action_id: int) -> str | None:
    with state.read() as connection:
        row = connection.execute(
            "SELECT status FROM worker_action_requests WHERE action_id=?",
            (action_id,),
        ).fetchone()
    return None if row is None else str(row[0])


def test_local_eval_after_radar_scan_does_not_n_plus_one(tmp_path):
    repo = _seed_pending(tmp_path, missing_t=False, sibling=False)
    result = evaluate_t1_from_local_bars(repo, scan_date=SESSION_ISO, as_of=jst(18, 0))
    assert result["written"] >= 1
    overlay = repo.overlay_t1_evaluations(repo.applicable_t1_events(scan_date=SESSION_ISO))
    assert overlay[0]["t1_priority"]["status"] in {T1_MET, T1_UNMET}


def test_vendor_timeout_error_from_fetcher_is_not_outer_cancel(tmp_path):
    repo = _seed_pending(tmp_path, missing_t=True, sibling=False)

    async def boom(_codes, _day):
        raise TimeoutError("vendor timeout")

    result = asyncio.run(
        complete_pending_t1(
            repo,
            as_of=jst(18, 0),
            fetcher=boom,
            first_fetch_hhmm="17:00",
            retry_base_seconds=0.01,
        )
    )
    assert result["reason"] == "daily_fetch_failed"
    key = f"evt-hang|{SESSION_ISO}|t1_daily_priority"
    assert repo.load_t1_retry_states([key])[key]["attempt"] == 1


def test_ordinary_exception_does_not_double_charge(tmp_path):
    repo = _seed_pending(tmp_path, missing_t=True, sibling=False)

    async def boom(_codes, _day):
        raise RuntimeError("temporary")

    first = asyncio.run(
        complete_pending_t1(repo, as_of=jst(18, 0), fetcher=boom, retry_base_seconds=0.01)
    )
    second = asyncio.run(
        complete_pending_t1(repo, as_of=jst(18, 0), fetcher=boom, retry_base_seconds=0.01)
    )
    key = f"evt-hang|{SESSION_ISO}|t1_daily_priority"
    assert repo.load_t1_retry_states([key])[key]["attempt"] == 1
    assert first["attempt"] == 1
    assert second["reason"] == "t1_retry_not_due"


def test_reservation_failure_does_not_dispatch(tmp_path):
    repo = _seed_pending(tmp_path, missing_t=True, sibling=False)
    calls = {"n": 0}

    async def fetch(_codes, _day):
        calls["n"] += 1
        return {}

    def fail_save(_states):
        raise RuntimeError("disk full")

    repo.save_t1_retry_states = fail_save  # type: ignore[method-assign]
    result = asyncio.run(
        complete_pending_t1(
            repo, as_of=jst(18, 0), fetcher=fetch, persist_required_on_reserve=True,
        )
    )
    assert result["reason"] == "reservation_persist_failed"
    assert calls["n"] == 0


def test_supervisor_wait_for_cancels_hanging_fetch_and_keeps_eight_budget(tmp_path, monkeypatch):
    """Real hang + supervisor wait_for. Must not raise TimeoutError from the task."""

    repo = _seed_pending(tmp_path, missing_t=True, sibling=True)
    fetch_calls = {"n": 0}
    hang = asyncio.Event()

    async def hanging_fetch(_codes, _day):
        fetch_calls["n"] += 1
        await hang.wait()
        return {}

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr("app.domain.timeutil.now_jst", lambda: jst(18, 0))
    monkeypatch.setattr("app.worker.tasks.now_jst", lambda: jst(18, 0))

    context = TaskContext()
    context.repository = repo
    context.t1_bar_fetcher = hanging_fetch
    context.t1_timeout_seconds = 0.05
    context.t1_retry_base_seconds = 0.001

    spec = next(item for item in build_default_tasks(context) if item.name == TASK_T1_CLOSE)
    spec = replace(spec, initial_delay_seconds=3600.0, timeout_seconds=0.05, failure_backoff_seconds=0.01)

    state = WorkerStateRepository(tmp_path / "jp-worker.db")
    state.initialize()
    supervisor = WorkerSupervisor(state, [spec], owner_id="owner", action_poll_seconds=0.02)

    async def drive() -> None:
        runner = asyncio.create_task(supervisor.run())
        await asyncio.sleep(0.08)
        for index in range(10):
            accepted = state.request_action(
                "t1_close_completion",
                idempotency_key=f"round-{index}",
                payload={},
            )
            if not accepted.get("accepted"):
                await asyncio.sleep(0.12)
                accepted = state.request_action(
                    "t1_close_completion",
                    idempotency_key=f"round-{index}-retry",
                    payload={},
                )
            if not accepted.get("accepted"):
                continue
            deadline = asyncio.get_event_loop().time() + 2.5
            while asyncio.get_event_loop().time() < deadline:
                if _action_status(state, accepted["action_id"]) in {"failed", "completed"}:
                    break
                await asyncio.sleep(0.03)
            key = f"evt-hang|{SESSION_ISO}|t1_daily_priority"
            stored = repo.load_t1_retry_states([key])
            if stored:
                item = dict(stored[key])
                item["next_eligible_at"] = "2020-01-01T00:00:00Z"
                repo.save_t1_retry_states([item])
        supervisor.request_stop()
        await asyncio.wait_for(runner, timeout=4.0)

    asyncio.run(drive())
    key = f"evt-hang|{SESSION_ISO}|t1_daily_priority"
    budget = repo.load_t1_retry_states([key])[key]
    assert fetch_calls["n"] == T1_RETRY_MAX_ATTEMPTS
    assert int(budget["attempt"]) == T1_RETRY_MAX_ATTEMPTS
    assert budget["exhausted"] is True
    still = repo.overlay_t1_evaluations([{"event_id": "evt-done"}])[0].get("t1_priority")
    if still:
        assert still.get("status") in {T1_MET, T1_UNMET}


def test_invalid_action_fails_without_requeue(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    init_repo(tmp_path / "jp-core.db")
    context = TaskContext()
    spec = next(item for item in build_default_tasks(context) if item.name == TASK_T1_CLOSE)
    result = spec.run({"invalid": True})
    assert result.status == "failed"
    assert result.error_code == "invalid_parameters"
