"""Worker bookkeeping retries real SQLite contention without rerunning work."""

from __future__ import annotations

import asyncio
from collections import deque
import sqlite3
import threading

import pytest

from app.services.publication import absolute_retry_iso
from app.worker.runtime import TaskResult, TaskSpec, WorkerSupervisor
from app.worker.state import WorkerLeaseLost, WorkerStateRepository


def _state(tmp_path, monkeypatch):
    state = WorkerStateRepository(tmp_path / "worker.db")
    state.initialize()
    token = state.acquire_lease("owner")
    connect = state._connect_rw

    def short_busy_timeout():
        connection = connect()
        # Exercise the production transactions with a real competing writer,
        # shortening only SQLite's wait so regressions don't take five seconds.
        connection.execute("PRAGMA busy_timeout=20")
        return connection

    monkeypatch.setattr(state, "_connect_rw", short_busy_timeout)
    return state, token


def _supervisor(state, token, spec=None, *, poll=0.05):
    specs = [spec] if spec else []
    supervisor = WorkerSupervisor(state, specs, owner_id="owner", action_poll_seconds=poll)
    supervisor._fencing_token = token
    if spec:
        supervisor._triggers[spec.name] = asyncio.Event()
        supervisor._pending_payloads[spec.name] = deque()
        for action_type in spec.action_types:
            supervisor._action_owner[action_type] = spec.name
    return supervisor


def _locker(state):
    return sqlite3.connect(state.db_path, isolation_level=None, check_same_thread=False)


def _observe_busy(monkeypatch, state, name, *, before=None):
    original = getattr(state, name)
    observed = threading.Event()
    errors = []

    def call(*args, **kwargs):
        if before:
            before(*args, **kwargs)
        try:
            return original(*args, **kwargs)
        except sqlite3.OperationalError as error:
            errors.append(error)
            observed.set()
            raise

    monkeypatch.setattr(state, name, call)
    return observed, errors


async def _until(predicate, timeout=3):
    async with asyncio.timeout(timeout):
        while True:
            value = await asyncio.to_thread(predicate)
            if value:
                return value
            await asyncio.sleep(0.01)


def test_real_write_lock_does_not_kill_action_dispatch_and_claims_once(tmp_path, monkeypatch):
    state, token = _state(tmp_path, monkeypatch)
    action = state.request_action("test", idempotency_key="claim", payload={"value": 7})
    spec = TaskSpec("test-task", lambda _: TaskResult("completed", 60), action_types=("test",))
    supervisor = _supervisor(state, token, spec)
    observed, errors = _observe_busy(monkeypatch, state, "claim_next_action")
    locker = _locker(state)
    locker.execute("BEGIN IMMEDIATE")

    async def drive():
        loop = asyncio.create_task(supervisor._action_loop())
        try:
            assert await asyncio.to_thread(observed.wait, 2)
            assert not loop.done()
            assert state.get_action(action["action_id"])["status"] == "queued"
            locker.execute("ROLLBACK")
            await asyncio.wait_for(supervisor._triggers[spec.name].wait(), 2)
            supervisor.request_stop()
            await asyncio.wait_for(loop, 0.3)
        finally:
            supervisor.request_stop()
            if locker.in_transaction:
                locker.execute("ROLLBACK")
            locker.close()
            await asyncio.gather(loop, return_exceptions=True)

    asyncio.run(drive())
    assert errors and errors[0].sqlite_errorcode == sqlite3.SQLITE_BUSY
    assert state.get_action(action["action_id"])["status"] == "running"
    assert list(supervisor._pending_payloads[spec.name]) == [
        {"value": 7, "__action_id": action["action_id"], "__action_type": "test"}
    ]


def test_unknown_action_completion_survives_real_write_lock(tmp_path, monkeypatch):
    state, token = _state(tmp_path, monkeypatch)
    action = state.request_action("unknown", idempotency_key="unknown", payload={})
    supervisor = _supervisor(state, token)
    locker = _locker(state)
    armed = False

    def before(*_args, **_kwargs):
        nonlocal armed
        if not armed:
            armed = True
            locker.execute("BEGIN IMMEDIATE")

    observed, errors = _observe_busy(monkeypatch, state, "complete_action", before=before)

    async def drive():
        loop = asyncio.create_task(supervisor._action_loop())
        try:
            assert await asyncio.to_thread(observed.wait, 2)
            assert not loop.done()
            locker.execute("ROLLBACK")
            await _until(lambda: state.get_action(action["action_id"])["status"] == "failed")
            supervisor.request_stop()
            await asyncio.wait_for(loop, 0.3)
        finally:
            supervisor.request_stop()
            if locker.in_transaction:
                locker.execute("ROLLBACK")
            locker.close()
            await asyncio.gather(loop, return_exceptions=True)

    asyncio.run(drive())
    finished = state.get_action(action["action_id"])
    assert finished["error_code"] == "unknown_action_type"
    assert errors and errors[0].sqlite_errorcode == sqlite3.SQLITE_BUSY


def test_supervisor_stays_alive_through_dispatch_lock_and_completes_action(tmp_path, monkeypatch):
    state, token = _state(tmp_path, monkeypatch)
    action = state.request_action("test", idempotency_key="supervisor", payload={"value": 3})
    executed = []

    def body(payload):
        executed.append(dict(payload))
        return TaskResult("completed", 3600, details={"receipt": "supervisor-result"})

    spec = TaskSpec("test-task", body, initial_delay_seconds=3600, action_types=("test",))
    supervisor = _supervisor(state, token, spec)
    locker = _locker(state)
    armed = False

    def before(*_args, **_kwargs):
        nonlocal armed
        if not armed:
            armed = True
            locker.execute("BEGIN IMMEDIATE")

    observed, _errors = _observe_busy(monkeypatch, state, "claim_next_action", before=before)

    async def drive():
        loop = asyncio.create_task(supervisor.run())
        try:
            assert await asyncio.to_thread(observed.wait, 2)
            assert not loop.done() and executed == []
            locker.execute("ROLLBACK")
            await _until(lambda: state.get_action(action["action_id"])["status"] == "completed")
            assert not loop.done()
            supervisor.request_stop()
            await asyncio.wait_for(loop, 1)
        finally:
            supervisor.request_stop()
            if locker.in_transaction:
                locker.execute("ROLLBACK")
            locker.close()
            await asyncio.gather(loop, return_exceptions=True)

    asyncio.run(drive())
    assert executed == [{"value": 3, "__action_type": "test"}]
    assert state.get_action(action["action_id"])["result"]["receipt"] == "supervisor-result"


@pytest.mark.parametrize("phase", ["start", "retry", "task_complete", "action_complete", "action_failed"])
def test_task_bookkeeping_lock_preserves_result_without_reexecuting_body(tmp_path, monkeypatch, phase):
    state, token = _state(tmp_path, monkeypatch)
    action = state.request_action("test", idempotency_key=phase, payload={"value": 9})
    state.claim_next_action("owner", token)
    executed = []

    def body(payload):
        executed.append(dict(payload))
        if phase == "action_failed":
            raise ValueError("test task failure")
        return TaskResult(
            "completed", 3600,
            details={
                "receipt": "original-result",
                "retry": {
                    "task_name": "test-task", "target_trade_date": "2026-09-08",
                    "dataset_scope": "daily_bars", "reason": "test-retry",
                    "next_retry_at": absolute_retry_iso(delay_seconds=1200),
                },
            },
        )

    spec = TaskSpec("test-task", body, action_types=("test",))
    supervisor = _supervisor(state, token, spec)
    supervisor._pending_payloads[spec.name].append(
        {"value": 9, "__action_id": action["action_id"], "__action_type": "test"}
    )
    method = (
        "upsert_retry" if phase == "retry"
        else "record_task" if phase in {"start", "task_complete"}
        else "complete_action"
    )
    locker = _locker(state)
    armed = False

    def before(*_args, **kwargs):
        nonlocal armed
        matches = (
            (phase == "start" and kwargs.get("status") == "running")
            or (phase == "task_complete" and kwargs.get("status") == "completed")
            or phase in {"retry", "action_complete", "action_failed"}
        )
        if matches and not armed:
            armed = True
            locker.execute("BEGIN IMMEDIATE")

    observed, errors = _observe_busy(monkeypatch, state, method, before=before)

    async def drive():
        loop = asyncio.create_task(supervisor._task_loop(spec))
        try:
            assert await asyncio.to_thread(observed.wait, 2)
            assert not loop.done()
            assert len(executed) == (0 if phase == "start" else 1)
            locker.execute("ROLLBACK")
            await _until(lambda: state.get_action(action["action_id"])["status"] in {"completed", "failed"})
            supervisor.request_stop()
            await asyncio.wait_for(loop, 0.3)
        finally:
            supervisor.request_stop()
            if locker.in_transaction:
                locker.execute("ROLLBACK")
            locker.close()
            await asyncio.gather(loop, return_exceptions=True)

    asyncio.run(drive())
    assert errors and errors[0].sqlite_errorcode == sqlite3.SQLITE_BUSY
    assert executed == [{"value": 9, "__action_type": "test"}]
    finished = state.get_action(action["action_id"])
    if phase == "action_failed":
        assert finished["status"] == "failed" and finished["error_code"] == "unexpected:ValueError"
    else:
        assert finished["status"] == "completed"
        assert finished["result"]["receipt"] == "original-result"


def test_locked_retry_read_does_not_repeat_committed_attempt_increment(tmp_path, monkeypatch):
    state, token = _state(tmp_path, monkeypatch)
    action = state.request_action("test", idempotency_key="retry-read", payload={})
    state.claim_next_action("owner", token)
    deadline = "2020-01-01T00:00:00Z"
    retry = {
        "task_name": "test-task", "target_trade_date": "2026-09-08",
        "dataset_scope": "daily_bars", "reason": "test-retry", "next_retry_at": deadline,
    }
    state.upsert_retry(**retry)
    executed = []

    def body(_payload):
        executed.append(1)
        return TaskResult("completed", 3600, details={"retry": retry})

    spec = TaskSpec("test-task", body, action_types=("test",))
    supervisor = _supervisor(state, token, spec)
    supervisor._pending_payloads[spec.name].append(
        {"__action_id": action["action_id"], "__action_type": "test"}
    )

    # A shared-cache writer on this table produces a genuine read-side
    # SQLITE_LOCKED after upsert_retry has already committed successfully.
    uri = f"file:{state.db_path}?cache=shared"

    def shared_connection():
        connection = sqlite3.connect(uri, uri=True, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=20")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    monkeypatch.setattr(state, "_connect_rw", shared_connection)
    locker = sqlite3.connect(uri, uri=True, isolation_level=None, check_same_thread=False)
    armed = False

    def before(*_args, **_kwargs):
        nonlocal armed
        if not armed:
            armed = True
            locker.execute("BEGIN IMMEDIATE")
            locker.execute("UPDATE worker_retry_deadlines SET last_reason=last_reason")

    observed, errors = _observe_busy(monkeypatch, state, "pending_retries_for_task", before=before)

    async def drive():
        loop = asyncio.create_task(supervisor._task_loop(spec))
        try:
            assert await asyncio.to_thread(observed.wait, 2)
            assert not loop.done()
            assert locker.execute("SELECT attempt_count FROM worker_retry_deadlines").fetchone()[0] == 2
            locker.execute("ROLLBACK")
            await _until(lambda: state.get_action(action["action_id"])["status"] == "completed")
            supervisor.request_stop()
            await asyncio.wait_for(loop, 0.3)
        finally:
            supervisor.request_stop()
            if locker.in_transaction:
                locker.execute("ROLLBACK")
            locker.close()
            await asyncio.gather(loop, return_exceptions=True)

    asyncio.run(drive())
    assert errors and errors[0].sqlite_errorcode & 0xFF == sqlite3.SQLITE_LOCKED
    assert executed == [1]
    assert state.pending_retries_for_task(spec.name)[0]["attempt_count"] == 2


def test_stop_interrupts_lock_retry_without_waiting_for_lock_release(tmp_path, monkeypatch):
    state, token = _state(tmp_path, monkeypatch)
    supervisor = _supervisor(state, token, poll=60)
    observed, _errors = _observe_busy(monkeypatch, state, "claim_next_action")
    locker = _locker(state)
    locker.execute("BEGIN IMMEDIATE")

    async def drive():
        loop = asyncio.create_task(supervisor._action_loop())
        try:
            assert await asyncio.to_thread(observed.wait, 2)
            supervisor.request_stop()
            await asyncio.wait_for(loop, 0.3)
            assert locker.in_transaction
        finally:
            supervisor.request_stop()
            locker.execute("ROLLBACK")
            locker.close()
            await asyncio.gather(loop, return_exceptions=True)

    asyncio.run(drive())


def test_stop_interrupts_idle_action_poll(tmp_path, monkeypatch):
    state, token = _state(tmp_path, monkeypatch)
    supervisor = _supervisor(state, token, poll=60)
    polled = threading.Event()
    original = state.claim_next_action

    def claim(*args):
        action = original(*args)
        polled.set()
        return action

    monkeypatch.setattr(state, "claim_next_action", claim)

    async def drive():
        loop = asyncio.create_task(supervisor._action_loop())
        try:
            assert await asyncio.to_thread(polled.wait, 2)
            supervisor.request_stop()
            await asyncio.wait_for(loop, 0.3)
        finally:
            supervisor.request_stop()
            await asyncio.gather(loop, return_exceptions=True)

    asyncio.run(drive())


def test_lost_heartbeat_fence_breaks_out_of_lock_retry(tmp_path, monkeypatch):
    state, token = _state(tmp_path, monkeypatch)
    supervisor = _supervisor(state, token)
    observed, _errors = _observe_busy(monkeypatch, state, "claim_next_action")
    locker = _locker(state)
    locker.execute("BEGIN IMMEDIATE")

    async def drive():
        loop = asyncio.create_task(supervisor._action_loop())
        try:
            assert await asyncio.to_thread(observed.wait, 2)
            supervisor._lease_lost.set()
            with pytest.raises(WorkerLeaseLost):
                await asyncio.wait_for(loop, 1)
        finally:
            supervisor.request_stop()
            locker.execute("ROLLBACK")
            locker.close()
            await asyncio.gather(loop, return_exceptions=True)

    asyncio.run(drive())


def test_replaced_owner_fence_still_prevents_claim(tmp_path, monkeypatch):
    state, token = _state(tmp_path, monkeypatch)
    action = state.request_action("test", idempotency_key="stale-owner", payload={})
    supervisor = _supervisor(state, token)
    state.acquire_lease("replacement-owner")
    with pytest.raises(WorkerLeaseLost):
        asyncio.run(asyncio.wait_for(supervisor._action_loop(), 1))
    assert state.get_action(action["action_id"])["status"] == "queued"


@pytest.mark.parametrize("method", ["claim_next_action", "complete_action"])
@pytest.mark.parametrize("kind", ["sql_error", "missing_error_code", "corrupt", "fence"])
def test_non_lock_errors_are_not_retried_or_hidden(tmp_path, monkeypatch, method, kind):
    state, token = _state(tmp_path, monkeypatch)
    state.request_action("unknown", idempotency_key="failure", payload={})
    supervisor = _supervisor(state, token)
    if kind == "fence":
        error = WorkerLeaseLost("stale token")
    elif kind == "corrupt":
        error = sqlite3.DatabaseError("database disk image is malformed")
        error.sqlite_errorcode = sqlite3.SQLITE_CORRUPT
    else:
        # Even this message must not bypass SQLite's actual result code.
        error = sqlite3.OperationalError("database is locked")
        if kind == "sql_error":
            error.sqlite_errorcode = sqlite3.SQLITE_ERROR
    calls = []

    def fail(*_args, **_kwargs):
        calls.append(1)
        raise error

    monkeypatch.setattr(state, method, fail)
    with pytest.raises(type(error)) as caught:
        asyncio.run(asyncio.wait_for(supervisor._action_loop(), 1))
    assert caught.value is error
    assert len(calls) == 1


def test_real_extended_locked_code_is_retried(tmp_path, monkeypatch):
    # Shared-cache table contention produces SQLITE_LOCKED_SHAREDCACHE (262),
    # which must be recognized through its primary result code SQLITE_LOCKED.
    uri = f"file:{tmp_path / 'shared.db'}?cache=shared"
    first = sqlite3.connect(uri, uri=True, isolation_level=None)
    second = sqlite3.connect(uri, uri=True, isolation_level=None)
    try:
        first.execute("CREATE TABLE counter (n INTEGER)")
        first.execute("INSERT INTO counter VALUES (1)")
        first.execute("BEGIN IMMEDIATE")
        first.execute("UPDATE counter SET n=2")
        with pytest.raises(sqlite3.OperationalError) as caught:
            second.execute("UPDATE counter SET n=3")
        locked_error = caught.value
        assert locked_error.sqlite_errorcode & 0xFF == sqlite3.SQLITE_LOCKED
        first.execute("ROLLBACK")
    finally:
        first.close()
        second.close()

    state, token = _state(tmp_path, monkeypatch)
    action = state.request_action("unknown", idempotency_key="extended-locked", payload={})
    supervisor = _supervisor(state, token)
    original = state.claim_next_action
    calls = []

    def claim(*args):
        calls.append(1)
        if len(calls) == 1:
            raise locked_error
        return original(*args)

    monkeypatch.setattr(state, "claim_next_action", claim)

    async def drive():
        loop = asyncio.create_task(supervisor._action_loop())
        try:
            await _until(lambda: state.get_action(action["action_id"])["status"] == "failed")
            supervisor.request_stop()
            await asyncio.wait_for(loop, 0.3)
        finally:
            supervisor.request_stop()
            await asyncio.gather(loop, return_exceptions=True)

    asyncio.run(drive())
    assert len(calls) >= 2
