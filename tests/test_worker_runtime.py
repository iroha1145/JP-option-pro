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
    assert other["accepted"] is True and other["duplicate"] is False
    assert other["action_id"] != first["action_id"]


def test_same_fetch_code_coalesces_across_keys(tmp_path):
    repo = WorkerStateRepository(tmp_path / "worker.db")
    repo.initialize()
    first = repo.request_action("intraday_fetch", idempotency_key="auto:minute:72030:latest", payload={"code": "72030"})
    manual = repo.request_action("intraday_fetch", idempotency_key="deadbeef", payload={"code": "72030"})
    assert manual["accepted"] is True and manual["duplicate"] is True
    assert manual["action_id"] == first["action_id"]


def test_non_fetch_action_still_type_busy(tmp_path):
    repo = WorkerStateRepository(tmp_path / "worker.db")
    repo.initialize()
    first = repo.request_action("post_close_batch", idempotency_key="a", payload={})
    second = repo.request_action("post_close_batch", idempotency_key="b", payload={})
    assert first["accepted"] is True
    assert second["accepted"] is False and second["reason"] == "type_busy"


def test_request_action_retry_after_terminal(tmp_path):
    repo = WorkerStateRepository(tmp_path / "worker.db")
    repo.initialize()
    token = repo.acquire_lease("owner")
    first = repo.request_action("intraday_fetch", idempotency_key="auto:minute:72030:latest", payload={"code": "72030"})
    repo.complete_action("owner", token, first["action_id"], status="failed", error_code="x")

    blocked = repo.request_action(
        "intraday_fetch", idempotency_key="auto:minute:72030:latest", payload={"code": "72030"}
    )
    assert blocked["accepted"] is False and blocked["reason"] == "recent_failure"

    with repo.write() as connection:
        connection.execute(
            "UPDATE worker_action_requests SET completed_at = '2020-01-01T00:00:00Z' WHERE action_id = ?",
            (first["action_id"],),
        )
    retry = repo.request_action(
        "intraday_fetch", idempotency_key="auto:minute:72030:latest", payload={"code": "72030"}
    )
    assert retry["accepted"] is True
    assert retry["duplicate"] is False
    assert retry["action_id"] != first["action_id"]

    manual = repo.request_action("intraday_fetch", idempotency_key="manual-now", payload={"code": "99840"})
    token2 = repo.acquire_lease("owner")
    repo.complete_action("owner", token2, manual["action_id"], status="failed", error_code="x")
    again = repo.request_action("intraday_fetch", idempotency_key="manual-later", payload={"code": "99840"})
    assert again["accepted"] is True


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
    assert stocks_api._ensure_intraday_fetch("67580", "minute", None) is True
    repo.complete_action("owner", token, first["action_id"], status="failed", error_code="x")
    assert stocks_api._ensure_intraday_fetch("72030", "minute", None) is False
    deps.reset_dependencies_for_tests()


def test_worker_schema_v1_migrates_to_v2(tmp_path):
    import sqlite3

    from app.repositories.base import utc_now_iso
    from app.worker.state import WORKER_SCHEMA_VERSION

    db_path = tmp_path / "worker.db"
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE jp_worker_schema (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                version TEXT NOT NULL,
                checksum TEXT NOT NULL,
                applied_at TEXT NOT NULL
            );
            CREATE TABLE worker_lease (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                owner_id TEXT NOT NULL,
                fencing_token INTEGER NOT NULL,
                acquired_at TEXT NOT NULL,
                renewed_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );
            CREATE TABLE worker_task_status (
                task_name TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                consecutive_failures INTEGER NOT NULL DEFAULT 0,
                last_started_at TEXT,
                last_completed_at TEXT,
                last_success_at TEXT,
                next_run_at TEXT,
                error_code TEXT,
                details_json TEXT NOT NULL DEFAULT '{}'
            ) WITHOUT ROWID;
            CREATE TABLE worker_action_requests (
                action_id INTEGER PRIMARY KEY AUTOINCREMENT,
                action_type TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'queued',
                requested_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                error_code TEXT,
                result_json TEXT,
                UNIQUE (action_type, idempotency_key)
            );
            CREATE UNIQUE INDEX uq_worker_action_active
                ON worker_action_requests(action_type)
                WHERE status IN ('queued', 'running');
            """
        )
        connection.execute(
            "INSERT INTO jp_worker_schema (id, version, checksum, applied_at) VALUES (1, ?, ?, ?)",
            ("jp-worker-v1", "deadbeef", utc_now_iso()),
        )
        connection.commit()

    repo = WorkerStateRepository(db_path)
    repo.initialize()
    with sqlite3.connect(db_path) as connection:
        version = connection.execute("SELECT version FROM jp_worker_schema WHERE id = 1").fetchone()[0]
        indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list('worker_action_requests')").fetchall()
        }
    assert version == WORKER_SCHEMA_VERSION
    assert "uq_worker_action_active" not in indexes
    assert "uq_worker_action_active_nonfetch" in indexes


def test_news_sync_outcome_fails_when_every_feed_errors():
    assert news_sync_outcome({"feeds": 3, "feed_errors": {"a": "x", "b": "y", "c": "z"}}) == (
        "failed",
        "all_feeds_failed",
    )
    assert news_sync_outcome({"feeds": 2, "feed_errors": {"a": "x"}}) == ("completed", None)
    assert news_sync_outcome({"feeds": 0, "feed_errors": {}}) == ("completed", None)
