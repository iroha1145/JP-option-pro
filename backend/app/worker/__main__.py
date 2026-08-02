"""Worker entry point: ``python -m app.worker`` / ``--healthcheck`` / ``--once``."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys

from app.data_paths import get_data_paths
from app.runtime_environment import load_runtime_environment
from app.worker.lock import ProcessFileLock
from app.worker.runtime import WorkerSupervisor
from app.worker.state import WorkerStateRepository
from app.worker.tasks import DEFAULT_TASK_NAMES, TaskContext, build_default_tasks


def _healthcheck() -> int:
    paths = get_data_paths()
    repository = WorkerStateRepository(paths.worker_db, read_only=True)
    if not repository.exists():
        print(json.dumps({"healthy": False, "reason": "worker_db_missing"}))
        return 1
    try:
        health = repository.health(DEFAULT_TASK_NAMES)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"healthy": False, "reason": f"unreadable:{type(exc).__name__}"}))
        return 1
    print(json.dumps(health, ensure_ascii=False, default=str))
    return 0 if health.get("healthy") else 1


def _run_once() -> int:
    context = TaskContext()
    outcomes = {}
    for spec in build_default_tasks(context):
        result = spec.run(None)
        outcomes[spec.name] = {"status": result.status, "details": result.details}
    print(json.dumps(outcomes, ensure_ascii=False, default=str))
    return 0


async def _run_forever() -> None:
    paths = get_data_paths()
    paths.root.mkdir(parents=True, exist_ok=True)
    owner_id = f"worker-{os.getpid()}"
    lock = ProcessFileLock(paths.worker_lock)
    if not lock.acquire(owner_id):
        raise SystemExit("another worker process holds the lock")
    try:
        state = WorkerStateRepository(paths.worker_db)
        state.initialize()
        context = TaskContext()
        supervisor = WorkerSupervisor(state, build_default_tasks(context), owner_id=owner_id)
        loop = asyncio.get_running_loop()
        for signal_number in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(signal_number, supervisor.request_stop)
        await supervisor.run()
    finally:
        lock.release()


def main(argv: list[str] | None = None) -> int:
    load_runtime_environment()
    parser = argparse.ArgumentParser(prog="app.worker")
    parser.add_argument("--healthcheck", action="store_true")
    parser.add_argument("--once", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.healthcheck:
        return _healthcheck()
    if arguments.once:
        return _run_once()
    asyncio.run(_run_forever())
    return 0


if __name__ == "__main__":
    sys.exit(main())
