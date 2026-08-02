"""Worker supervisor: per-task async loops over sync task bodies.

Simplified port of the reference design:
- Each task runs in its own asyncio loop; the sync body executes in a
  thread so SQLite and HTTP stay blocking and simple.
- A heartbeat thread renews the SQLite lease; losing the fence kills the
  process (fail-fast, the container restarts it).
- Manual actions arrive through jp-worker.db; one dispatcher loop claims
  them and triggers the owning task immediately.
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from app.worker.state import WorkerLeaseLost, WorkerStateRepository


@dataclass
class TaskResult:
    status: str  # completed | failed | skipped
    next_delay_seconds: float
    details: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None


@dataclass
class TaskSpec:
    name: str
    run: Callable[[dict[str, Any] | None], TaskResult]
    """Sync body; receives the manual-action payload or None on schedule."""
    initial_delay_seconds: float = 5.0
    failure_backoff_seconds: float = 60.0
    max_backoff_seconds: float = 3600.0
    action_types: tuple[str, ...] = ()


class WorkerSupervisor:
    def __init__(
        self,
        state: WorkerStateRepository,
        tasks: list[TaskSpec],
        *,
        owner_id: str,
        action_poll_seconds: float = 2.0,
    ) -> None:
        self._state = state
        self._tasks = tasks
        self._owner_id = owner_id
        self._action_poll_seconds = action_poll_seconds
        self._fencing_token = 0
        self._stop_event = asyncio.Event()
        self._triggers: dict[str, asyncio.Event] = {}
        self._pending_payloads: dict[str, dict[str, Any]] = {}
        self._action_owner: dict[str, str] = {}
        self._lease_lost = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None

    # -- lifecycle ---------------------------------------------------------

    async def run(self) -> None:
        self._fencing_token = await asyncio.to_thread(self._state.acquire_lease, self._owner_id)
        await asyncio.to_thread(
            self._state.recover_interrupted, self._owner_id, self._fencing_token
        )
        await asyncio.to_thread(
            self._state.reconcile_task_inventory, tuple(task.name for task in self._tasks)
        )
        for task in self._tasks:
            self._triggers[task.name] = asyncio.Event()
            for action_type in task.action_types:
                self._action_owner[action_type] = task.name

        self._heartbeat_thread = threading.Thread(target=self._heartbeat, daemon=True)
        self._heartbeat_thread.start()

        loops = [asyncio.create_task(self._task_loop(task)) for task in self._tasks]
        loops.append(asyncio.create_task(self._action_loop()))
        loops.append(asyncio.create_task(self._watch_lease()))
        try:
            done, pending = await asyncio.wait(loops, return_when=asyncio.FIRST_COMPLETED)
            # 任意のループが死んだらプロセスごと落とす（コンテナが再起動する）。
            self._stop_event.set()
            for task in pending:
                task.cancel()
            for task in done:
                exception = task.exception()
                if exception is not None:
                    raise exception
        finally:
            self._stop_event.set()

    def request_stop(self) -> None:
        self._stop_event.set()

    # -- heartbeat ---------------------------------------------------------

    def _heartbeat(self) -> None:
        consecutive_failures = 0
        while not self._stop_event.is_set() and not self._lease_lost.is_set():
            time.sleep(15.0)
            try:
                self._state.renew_lease(self._owner_id, self._fencing_token)
                consecutive_failures = 0
            except WorkerLeaseLost:
                self._lease_lost.set()
                return
            except Exception:  # noqa: BLE001 — 一時的な DB エラーは許容
                consecutive_failures += 1
                if consecutive_failures >= 4:
                    self._lease_lost.set()
                    return

    async def _watch_lease(self) -> None:
        while not self._stop_event.is_set():
            if self._lease_lost.is_set():
                raise WorkerLeaseLost("lease heartbeat failed")
            await asyncio.sleep(1.0)

    # -- manual actions ------------------------------------------------------

    async def _action_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                action = await asyncio.to_thread(
                    self._state.claim_next_action, self._owner_id, self._fencing_token
                )
            except WorkerLeaseLost:
                raise
            if action is None:
                await asyncio.sleep(self._action_poll_seconds)
                continue
            task_name = self._action_owner.get(action["action_type"])
            if task_name is None:
                await asyncio.to_thread(
                    self._state.complete_action,
                    self._owner_id, self._fencing_token, action["action_id"],
                    status="failed", error_code="unknown_action_type",
                )
                continue
            payload = dict(action.get("payload") or {})
            payload["__action_id"] = action["action_id"]
            payload["__action_type"] = action["action_type"]
            self._pending_payloads[task_name] = payload
            self._triggers[task_name].set()

    # -- task loops ------------------------------------------------------------

    async def _task_loop(self, spec: TaskSpec) -> None:
        delay = spec.initial_delay_seconds
        failures = 0
        while not self._stop_event.is_set():
            triggered = await self._wait(spec.name, delay)
            if self._stop_event.is_set():
                return
            payload = self._pending_payloads.pop(spec.name, None) if triggered else None
            action_id = payload.pop("__action_id", None) if payload else None
            payload_type = payload.pop("__action_type", None) if payload else None
            await asyncio.to_thread(
                self._state.record_task,
                self._owner_id, self._fencing_token, spec.name, status="running",
            )
            try:
                result = await asyncio.to_thread(spec.run, payload)
            except WorkerLeaseLost:
                raise
            except Exception as exc:  # noqa: BLE001
                failures += 1
                backoff = min(
                    spec.max_backoff_seconds, spec.failure_backoff_seconds * (2 ** (failures - 1))
                )
                await asyncio.to_thread(
                    self._state.record_task,
                    self._owner_id, self._fencing_token, spec.name,
                    status="failed", error_code=f"unexpected:{type(exc).__name__}"[:120],
                    success=False,
                )
                if action_id is not None:
                    await asyncio.to_thread(
                        self._state.complete_action,
                        self._owner_id, self._fencing_token, action_id,
                        status="failed", error_code=f"unexpected:{type(exc).__name__}"[:120],
                    )
                delay = backoff
                continue

            if result.status == "failed":
                failures += 1
                delay = min(
                    spec.max_backoff_seconds,
                    max(result.next_delay_seconds, spec.failure_backoff_seconds * (2 ** (failures - 1))),
                )
            else:
                failures = 0
                delay = result.next_delay_seconds
            await asyncio.to_thread(
                self._state.record_task,
                self._owner_id, self._fencing_token, spec.name,
                status="completed" if result.status != "failed" else "failed",
                error_code=result.error_code,
                details=result.details,
                success=(result.status == "completed"),
            )
            if action_id is not None:
                await asyncio.to_thread(
                    self._state.complete_action,
                    self._owner_id, self._fencing_token, action_id,
                    status="completed" if result.status != "failed" else "failed",
                    error_code=result.error_code,
                    result={"task": spec.name, "action_type": payload_type, **result.details},
                )

    async def _wait(self, task_name: str, delay: float) -> bool:
        """Sleep until the schedule fires or a manual trigger arrives.
        Returns True when the wake-up was manual."""

        trigger = self._triggers[task_name]
        try:
            await asyncio.wait_for(trigger.wait(), timeout=max(0.5, delay))
            trigger.clear()
            return True
        except asyncio.TimeoutError:
            return False


__all__ = ["TaskResult", "TaskSpec", "WorkerSupervisor"]
