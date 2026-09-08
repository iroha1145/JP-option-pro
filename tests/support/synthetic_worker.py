"""Independent worker process for dual-service freshness tests.

Uses production Supervisor / tasks / publication. Vendor steps are
synthetic so CI does not call J-Quants. Started only by pytest.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from app.data_paths import get_data_paths
from app.worker.lock import ProcessFileLock
from app.worker.runtime import WorkerSupervisor
from app.worker.state import WorkerStateRepository
from app.worker.tasks import TaskContext, build_default_tasks


class _OkEngine:
    def sync_daily_bars(self, _target):
        return {"status": "ok"}

    def sync_index_bars(self, _target):
        return {"status": "ok"}

    def sync_margin_interest(self, _target):
        return {"status": "ok"}

    def sync_margin_alerts(self, _target):
        return {"status": "ok"}

    def sync_short_ratios(self, _target):
        return {"status": "ok"}

    def sync_short_positions(self, _target):
        return {"status": "ok"}

    def sync_earnings_calendar(self):
        return {"status": "ok"}


class _FailBarsEngine(_OkEngine):
    def sync_daily_bars(self, _target):
        return {"status": "error", "error_code": "vendor_error"}


class _NotPublishedEngine(_OkEngine):
    def sync_daily_bars(self, _target):
        return {"status": "not_published"}


class SyntheticContext(TaskContext):
    def __init__(self, engine):
        super().__init__()
        self._engine = engine
        from app.personal_config import RadarConfig

        self.config = self.config.model_copy(
            update={"radar": RadarConfig(min_avg_turnover_jpy=1_000_000.0, min_listed_days=60)}
        )

    @property
    def engine(self):
        return self._engine

    def jquants_ready(self) -> bool:
        return True

    def latest_completed_trading_day(self) -> str | None:
        pinned = os.environ.get("JP_TEST_TARGET", "").strip()
        if pinned:
            return pinned
        return super().latest_completed_trading_day()


async def _run() -> None:
    mode = os.environ.get("JP_TEST_ENGINE", "ok")
    engine = {
        "ok": _OkEngine(),
        "fail_bars": _FailBarsEngine(),
        "not_published": _NotPublishedEngine(),
    }.get(mode, _OkEngine())
    paths = get_data_paths()
    paths.root.mkdir(parents=True, exist_ok=True)
    owner_id = f"synthetic-worker-{os.getpid()}"
    lock = ProcessFileLock(paths.worker_lock)
    if not lock.acquire(owner_id):
        raise SystemExit("another worker process holds the lock")
    try:
        state = WorkerStateRepository(paths.worker_db)
        state.initialize()
        context = SyntheticContext(engine)
        supervisor = WorkerSupervisor(state, build_default_tasks(context), owner_id=owner_id)
        loop = asyncio.get_running_loop()
        for signal_number in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(signal_number, supervisor.request_stop)
        await supervisor.run()
    finally:
        lock.release()


def main() -> int:
    asyncio.run(_run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
