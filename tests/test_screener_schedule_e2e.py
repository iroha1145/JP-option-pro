"""Real supervisor + persistent queue + production post_close / radar path.

Vendor sync is replaced; cleaning, scoring, publication, queue and the
supervisor are the production modules.
"""

from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace

from app.personal_config import get_personal_config
from app.worker.runtime import TaskSpec, WorkerSupervisor
from app.worker.state import WorkerStateRepository
from app.worker.tasks import TASK_POST_CLOSE, build_default_tasks, _run_radar_and_screener
from tests.test_screener_freshness import _config, _seed


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


class _TaskCtx:
    def __init__(self, repo, engine, *, target="2026-09-08", radar=None):
        base = get_personal_config()
        self.repository = repo
        self._engine = engine
        self.config = SimpleNamespace(
            features=base.features,
            radar=radar if radar is not None else base.radar,
            sync=base.sync,
        )
        self.paths = SimpleNamespace(news_db=repo.db_path.parent / "jp-news.db")
        self._target = target

    @property
    def engine(self):
        return self._engine

    def jquants_ready(self) -> bool:
        return True

    def latest_completed_trading_day(self):
        return self._target


def _post_close_spec(context, *, initial_delay=0.05) -> TaskSpec:
    real = next(spec for spec in build_default_tasks(context) if spec.name == TASK_POST_CLOSE)
    return TaskSpec(
        name=real.name,
        run=real.run,
        initial_delay_seconds=initial_delay,
        action_types=real.action_types,
        failure_backoff_seconds=real.failure_backoff_seconds,
        max_backoff_seconds=real.max_backoff_seconds,
    )


def _drive_action(state: WorkerStateRepository, spec: TaskSpec, action_type: str) -> dict:
    supervisor = WorkerSupervisor(
        state, [spec], owner_id="freshness-owner", action_poll_seconds=0.05
    )
    accepted = state.request_action(action_type, idempotency_key=f"e2e:{action_type}", payload={})
    assert accepted["accepted"] is True
    action_id = accepted["action_id"]

    async def drive() -> dict:
        loop = asyncio.create_task(supervisor.run())
        item = None
        for _ in range(80):
            item = await asyncio.to_thread(state.get_action, action_id)
            if item and item["status"] in {"completed", "failed"}:
                break
            await asyncio.sleep(0.1)
        supervisor.request_stop()
        try:
            await asyncio.wait_for(loop, timeout=5)
        except (asyncio.TimeoutError, Exception):
            supervisor.request_stop()
            loop.cancel()
        return item or {}

    return asyncio.run(drive())


def test_c03_daily_bar_child_fail_does_not_publish(tmp_path):
    repo = _seed(tmp_path, ["72030"], "2026-09-07")
    from app.services.radar.engine import RadarEngine
    from app.services.strength_scan import STRENGTH_SCORE_VERSION, build_strength_rows

    engine = RadarEngine(repo, _config())
    first = engine.scan("2026-09-07", lookback_start="2026-01-01")
    published = repo.replace_strength_rows(
        build_strength_rows(
            trade_date="2026-09-07",
            features_by_code=first["features_by_code"],
            structure_by_code=first["structure_by_code"],
            securities={"72030": repo.get_security("72030")},
            topix_return_63d=None,
        ),
        trade_date="2026-09-07",
        regime={},
        score_version=STRENGTH_SCORE_VERSION,
        coverage=first["coverage"],
        input_fingerprint=first["input_fingerprint"],
        input_data_through="2026-09-07",
    )
    old_id = published.publication_id
    ctx = _TaskCtx(repo, _FailBarsEngine(), target="2026-09-08", radar=_config())
    result = _post_close_spec(ctx).run({})
    assert result.outcome == "failed"
    assert result.status == "failed"
    assert repo.strength_meta()["publication_id"] == old_id
    assert repo.strength_meta()["trade_date"] == "2026-09-07"


def test_d07_stale_target_cannot_overwrite_newer_publication(tmp_path):
    repo = _seed(tmp_path, ["72030"], "2026-09-08")
    ctx = _TaskCtx(repo, _OkEngine(), target="2026-09-08", radar=_config())
    first = _run_radar_and_screener(ctx, "2026-09-08")
    assert first["outcome"] in {"published", "already_current"}
    newer_id = repo.strength_meta()["publication_id"]
    older = _run_radar_and_screener(ctx, "2026-09-07")
    assert older["outcome"] == "retained"
    assert repo.strength_meta()["publication_id"] == newer_id
    assert repo.strength_meta()["trade_date"] == "2026-09-08"


def test_d04_fifo_radar_refresh_does_not_clear_bar_retry(tmp_path):
    repo = _seed(tmp_path, ["72030"], "2026-09-07")
    state = WorkerStateRepository(tmp_path / "worker.db")
    state.initialize()
    state.upsert_retry(
        task_name=TASK_POST_CLOSE,
        target_trade_date="2026-09-08",
        dataset_scope="daily_bars",
        reason="not_published",
        next_retry_at="2026-09-08T17:20:00+09:00",
    )
    ctx = _TaskCtx(repo, _NotPublishedEngine(), target="2026-09-08", radar=_config())
    spec = _post_close_spec(ctx)
    finished = _drive_action(state, spec, "radar_refresh")
    assert finished["status"] == "completed"
    pending = state.pending_retries_for_task(TASK_POST_CLOSE)
    assert pending and pending[0]["next_retry_at"] == "2026-09-08T17:20:00+09:00"


def test_c02_not_published_writes_retry_and_waiting_outcome(tmp_path):
    repo = _seed(tmp_path, ["72030"], "2026-09-07")
    ctx = _TaskCtx(repo, _NotPublishedEngine(), target="2026-09-08", radar=_config())
    result = _post_close_spec(ctx).run({})
    assert result.outcome == "waiting_input"
    assert result.status == "completed"
    retry = result.details["retry"]
    assert retry["target_trade_date"] == "2026-09-08"
    assert retry["dataset_scope"] == "daily_bars"
    assert retry.get("clear") is not True


def test_f02_supervisor_queue_publishes_and_api_reads(tmp_path, monkeypatch):
    from app.tools.dev_fixture import build_fixture

    data_dir = tmp_path / "data"
    fixture = build_fixture(str(data_dir), days=140)
    assert fixture["publication"]["outcome"] == "published"
    old_id = fixture["publication"]["publication_id"]

    import app.access as access_module
    import app.api.deps as deps
    import app.config as config_module
    import app.main as main_module
    from app.repositories.core import CoreRepository

    monkeypatch.setenv("DATA_DIR", str(data_dir))
    deps.reset_dependencies_for_tests()
    config_module.reset_settings_for_tests()
    access_module.reset_access_runtime_for_tests()

    repo = CoreRepository(data_dir / "jp-core.db")
    ctx = _TaskCtx(repo, _OkEngine(), target=fixture["target_date"])
    state = WorkerStateRepository(data_dir / "jp-worker.db")
    state.initialize()
    spec = _post_close_spec(ctx)
    finished = _drive_action(state, spec, "post_close_batch")
    assert finished["status"] == "completed"
    outcome = (finished.get("result") or {}).get("outcome")
    assert outcome in {"published", "already_current"}

    main_module = importlib.reload(main_module)

    class _Loopback:
        def __init__(self, inner):
            self._inner = inner

        async def __call__(self, scope, receive, send):
            if scope.get("type") == "http":
                scope = {**scope, "client": ("127.0.0.1", 40001)}
            await self._inner(scope, receive, send)

    from starlette.testclient import TestClient

    with TestClient(_Loopback(main_module.app), base_url="http://testserver") as client:
        scan = client.get("/api/strength/scan?top=10")
        assert scan.status_code == 200
        body = scan.json()
        assert body["query_kind"] == "filter"
        assert body["publication_id"]
        if outcome == "already_current":
            assert body["publication_id"] == old_id
        assert body["stored_score_version"]
        action = client.get(f"/api/worker/actions/{finished['action_id']}")
        assert action.status_code == 200
        assert action.json()["result"]["outcome"] == outcome
    deps.reset_dependencies_for_tests()


def test_h01_non_owner_cannot_queue_update(tmp_path, monkeypatch):
    from app.tools.dev_fixture import build_fixture
    from starlette.testclient import TestClient

    data_dir = tmp_path / "data"
    build_fixture(str(data_dir), days=140)
    import app.access as access_module
    import app.api.deps as deps
    import app.config as config_module
    import app.main as main_module

    monkeypatch.setenv("DATA_DIR", str(data_dir))
    deps.reset_dependencies_for_tests()
    config_module.reset_settings_for_tests()
    access_module.reset_access_runtime_for_tests()
    main_module = importlib.reload(main_module)

    class _Remote:
        def __init__(self, inner):
            self._inner = inner

        async def __call__(self, scope, receive, send):
            if scope.get("type") == "http":
                scope = {**scope, "client": ("203.0.113.10", 40001)}
            await self._inner(scope, receive, send)

    with TestClient(_Remote(main_module.app), base_url="http://testserver") as client:
        denied = client.post(
            "/api/worker/actions/post_close_batch",
            json={},
            headers={"X-Optix-Action": "1", "Origin": "http://testserver"},
        )
        assert denied.status_code in {401, 403}
        scan = client.get("/api/strength/scan?top=5")
        assert scan.status_code in {200, 403}
        if scan.status_code == 200:
            assert scan.json()["query_kind"] == "filter"
    deps.reset_dependencies_for_tests()
