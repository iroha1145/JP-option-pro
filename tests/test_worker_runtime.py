"""Worker 動作キュー: 同一タスクの複数アクションを落とさない / 投入の accepted。"""

from __future__ import annotations

import asyncio

from app.worker.runtime import TaskResult, TaskSpec, WorkerSupervisor
from app.worker.state import WorkerStateRepository
from app.worker.tasks import news_sync_outcome


class _FakeState:
    def __init__(self) -> None:
        self.completed: list[tuple[int, str]] = []

    def record_task(self, *args, **kwargs) -> None:
        return None

    def complete_action(self, _owner, _token, action_id, *, status, **_kwargs) -> None:
        self.completed.append((action_id, status))


def test_request_action_accepted_and_retry_after_complete(tmp_path):
    repo = WorkerStateRepository(tmp_path / "worker.db")
    repo.initialize()
    first = repo.request_action("intraday_fetch", idempotency_key="auto:minute:72030:latest", payload={"code": "72030"})
    assert first["accepted"] is True and first["duplicate"] is False

    coalesced = repo.request_action(
        "intraday_fetch", idempotency_key="auto:minute:72030:latest", payload={"code": "72030"}
    )
    assert coalesced["accepted"] is True and coalesced["duplicate"] is True
    assert coalesced["action_id"] == first["action_id"]

    other = repo.request_action("intraday_fetch", idempotency_key="auto:minute:67580:latest", payload={"code": "67580"})
    assert other["accepted"] is False and other["reason"] == "type_busy"


def test_request_action_retry_after_terminal(tmp_path):
    repo = WorkerStateRepository(tmp_path / "worker.db")
    repo.initialize()
    token = repo.acquire_lease("owner")
    first = repo.request_action("intraday_fetch", idempotency_key="auto:minute:72030:latest", payload={"code": "72030"})
    repo.complete_action("owner", token, first["action_id"], status="failed", error_code="x")

    retry = repo.request_action(
        "intraday_fetch", idempotency_key="auto:minute:72030:latest", payload={"code": "72030"}
    )
    assert retry["accepted"] is True
    assert retry["duplicate"] is False
    assert retry["action_id"] != first["action_id"]


def test_two_action_types_same_task_both_run():
    state = _FakeState()
    ran: list[int] = []

    def body(payload):
        ran.append(int((payload or {}).get("n") or 0))
        return TaskResult(status="completed", next_delay_seconds=30.0)

    spec = TaskSpec(name="intraday_fetch", run=body, action_types=("intraday_fetch", "tick_fetch"))
    supervisor = WorkerSupervisor(state, [spec], owner_id="o")  # type: ignore[arg-type]
    supervisor._triggers[spec.name] = asyncio.Event()
    from collections import deque

    supervisor._pending_payloads[spec.name] = deque(
        [
            {"n": 1, "__action_id": 11, "__action_type": "intraday_fetch"},
            {"n": 2, "__action_id": 22, "__action_type": "tick_fetch"},
        ]
    )

    async def drive() -> None:
        loop = asyncio.create_task(supervisor._task_loop(spec))
        await asyncio.sleep(0.2)
        supervisor.request_stop()
        await asyncio.wait_for(loop, timeout=2.0)

    asyncio.run(drive())
    assert ran == [1, 2]
    assert state.completed == [(11, "completed"), (22, "completed")]


def test_ensure_intraday_fetch_only_when_accepted(tmp_path, monkeypatch):
    from app.api import stocks as stocks_api
    from app.data_paths import get_data_paths
    import app.api.deps as deps

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    deps.reset_dependencies_for_tests()
    repo = WorkerStateRepository(get_data_paths().worker_db)
    repo.initialize()
    token = repo.acquire_lease("owner")
    first = repo.request_action("intraday_fetch", idempotency_key="auto:minute:72030:latest", payload={"code": "72030"})
    assert stocks_api._ensure_intraday_fetch("72030", "minute", None) is True
    assert stocks_api._ensure_intraday_fetch("67580", "minute", None) is False
    repo.complete_action("owner", token, first["action_id"], status="failed", error_code="x")
    assert stocks_api._ensure_intraday_fetch("72030", "minute", None) is True
    deps.reset_dependencies_for_tests()


def test_news_sync_outcome_fails_when_every_feed_errors():
    assert news_sync_outcome({"feeds": 3, "feed_errors": {"a": "x", "b": "y", "c": "z"}}) == (
        "failed",
        "all_feeds_failed",
    )
    assert news_sync_outcome({"feeds": 2, "feed_errors": {"a": "x"}}) == ("completed", None)
    assert news_sync_outcome({"feeds": 0, "feed_errors": {}}) == ("completed", None)
