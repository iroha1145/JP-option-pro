"""JP-04: retry deadlines stay independent of manual radar_refresh."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.services.publication import absolute_retry_iso, seconds_until_deadline
from app.worker.runtime import TaskResult, WorkerSupervisor
from app.worker.state import WorkerStateRepository
from app.worker.tasks import POST_CLOSE_RETRY_SECONDS, TASK_POST_CLOSE


def test_d01_manual_radar_does_not_postpone_bar_retry(tmp_path):
    repo = WorkerStateRepository(tmp_path / "worker.db")
    repo.initialize()
    token = repo.acquire_lease("owner")
    supervisor = WorkerSupervisor(repo, [], owner_id="owner")
    supervisor._fencing_token = token
    jst = ZoneInfo("Asia/Tokyo")
    now = datetime.now(jst)
    deadline = absolute_retry_iso(now=now, delay_seconds=POST_CLOSE_RETRY_SECONDS)
    waiting = TaskResult(
        status="completed",
        next_delay_seconds=POST_CLOSE_RETRY_SECONDS,
        outcome="waiting_input",
        details={
            "retry": {
                "task_name": TASK_POST_CLOSE,
                "target_trade_date": "2026-09-08",
                "dataset_scope": "daily_bars",
                "reason": "not_published",
                "next_retry_at": deadline,
            }
        },
    )
    delay = supervisor._apply_retry_policy(TASK_POST_CLOSE, waiting, POST_CLOSE_RETRY_SECONDS)
    pending = repo.pending_retries_for_task(TASK_POST_CLOSE)
    assert pending and pending[0]["next_retry_at"] == deadline
    assert pending[0]["target_trade_date"] == "2026-09-08"

    later = now
    radar = TaskResult(
        status="completed",
        next_delay_seconds=86100.0,
        outcome="retained",
        details={"radar": {"status": "skipped", "reason": "bars_not_current"}},
    )
    delay_after = supervisor._apply_retry_policy(TASK_POST_CLOSE, radar, 86100.0)
    still = repo.pending_retries_for_task(TASK_POST_CLOSE)
    assert still[0]["next_retry_at"] == deadline
    remaining = seconds_until_deadline(deadline, now=later)
    assert delay_after < 2000
    assert abs(delay_after - remaining) < 2.0
    assert delay >= 0.5


def test_d02_unrelated_task_does_not_clear_retry(tmp_path):
    repo = WorkerStateRepository(tmp_path / "worker.db")
    repo.initialize()
    repo.upsert_retry(
        task_name=TASK_POST_CLOSE,
        target_trade_date="2026-09-08",
        dataset_scope="daily_bars",
        reason="not_published",
        next_retry_at="2026-09-08T17:20:00+09:00",
    )
    supervisor = WorkerSupervisor(repo, [], owner_id="owner")
    supervisor._fencing_token = repo.acquire_lease("owner")
    other = TaskResult(status="completed", next_delay_seconds=1800, outcome="published", details={})
    supervisor._apply_retry_policy("news_sync", other, 1800)
    pending = repo.pending_retries_for_task(TASK_POST_CLOSE)
    assert len(pending) == 1


def test_d03_same_target_publish_clears_retry(tmp_path):
    repo = WorkerStateRepository(tmp_path / "worker.db")
    repo.initialize()
    supervisor = WorkerSupervisor(repo, [], owner_id="owner")
    supervisor._fencing_token = repo.acquire_lease("owner")
    repo.upsert_retry(
        task_name=TASK_POST_CLOSE,
        target_trade_date="2026-09-08",
        dataset_scope="daily_bars",
        reason="not_published",
        next_retry_at="2026-09-08T17:20:00+09:00",
    )
    done = TaskResult(
        status="completed",
        next_delay_seconds=86400,
        outcome="published",
        details={
            "retry": {
                "clear": True,
                "task_name": TASK_POST_CLOSE,
                "target_trade_date": "2026-09-08",
                "dataset_scope": "daily_bars",
            }
        },
    )
    supervisor._apply_retry_policy(TASK_POST_CLOSE, done, 86400)
    assert repo.pending_retries_for_task(TASK_POST_CLOSE) == []


def test_d05_retry_attempts_exhaust(tmp_path):
    repo = WorkerStateRepository(tmp_path / "worker.db")
    repo.initialize()
    last = None
    for _ in range(12):
        last = repo.upsert_retry(
            task_name=TASK_POST_CLOSE,
            target_trade_date="2026-09-08",
            dataset_scope="daily_bars",
            reason="not_published",
            next_retry_at="2026-09-08T17:20:00+09:00",
            max_attempts=12,
        )
    assert last is not None and last["exhausted"] is True
    assert last["next_retry_at"] == "2026-09-08T17:20:00+09:00"
    assert repo.pending_retries_for_task(TASK_POST_CLOSE) == []


def test_d08_negative_delay_is_clamped():
    past = seconds_until_deadline("2020-01-01T00:00:00+09:00", now=datetime.now(timezone.utc))
    assert past == 0.5


def test_d06_retry_survives_supervisor_restart(tmp_path):
    db_path = tmp_path / "worker.db"
    first = WorkerStateRepository(db_path)
    first.initialize()
    first.upsert_retry(
        task_name=TASK_POST_CLOSE,
        target_trade_date="2026-09-08",
        dataset_scope="daily_bars",
        reason="not_published",
        next_retry_at="2026-09-08T17:20:00+09:00",
    )
    restarted = WorkerStateRepository(db_path)
    pending = restarted.pending_retries_for_task(TASK_POST_CLOSE)
    assert len(pending) == 1
    assert pending[0]["next_retry_at"] == "2026-09-08T17:20:00+09:00"
    supervisor = WorkerSupervisor(restarted, [], owner_id="owner-2")
    supervisor._fencing_token = restarted.acquire_lease("owner-2")
    radar = TaskResult(
        status="completed",
        next_delay_seconds=86100.0,
        outcome="retained",
        details={},
    )
    delay = supervisor._apply_retry_policy(TASK_POST_CLOSE, radar, 86100.0)
    assert delay < 86100.0
    assert restarted.pending_retries_for_task(TASK_POST_CLOSE)[0]["next_retry_at"] == (
        "2026-09-08T17:20:00+09:00"
    )
