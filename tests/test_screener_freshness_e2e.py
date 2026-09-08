"""End-to-end: production scan → publication → API read-back on a fixture DB."""

from __future__ import annotations

import importlib

from starlette.testclient import TestClient

from app.worker.tasks import TaskContext, _run_radar_and_screener


def test_f02_fixture_scan_publishes_and_api_reads_publication(tmp_path, monkeypatch):
    from app.tools.dev_fixture import build_fixture

    data_dir = tmp_path / "data"
    result = build_fixture(str(data_dir), days=140)
    assert result["publication"]["outcome"] == "published"
    publication_id = result["publication"]["publication_id"]

    import app.access as access_module
    import app.api.deps as deps
    import app.config as config_module
    import app.main as main_module

    monkeypatch.setenv("DATA_DIR", str(data_dir))
    deps.reset_dependencies_for_tests()
    config_module.reset_settings_for_tests()
    access_module.reset_access_runtime_for_tests()
    main_module = importlib.reload(main_module)

    class _Loopback:
        def __init__(self, inner):
            self._inner = inner

        async def __call__(self, scope, receive, send):
            if scope.get("type") == "http":
                scope = {**scope, "client": ("127.0.0.1", 40001)}
            await self._inner(scope, receive, send)

    with TestClient(_Loopback(main_module.app), base_url="http://testserver") as client:
        scan = client.get("/api/strength/scan?top=10")
        assert scan.status_code == 200
        body = scan.json()
        assert body["publication_id"] == publication_id
        assert body["stored_score_version"] == result["publication"]["score_version"]
        assert body["query_kind"] == "filter"
        assert body["matched_count"] >= 0
        zero = client.get("/api/strength/scan?top=10&min_score=100")
        assert zero.status_code == 200
        empty = zero.json()
        assert empty["publication_id"] == publication_id
        assert empty["matched_count"] == 0 or empty["rows"] == []
    deps.reset_dependencies_for_tests()


def test_c01_pipeline_does_not_record_success_when_waiting(tmp_path, monkeypatch):
    from app.repositories.core import CoreRepository
    from app.personal_config import RadarConfig
    from tests.test_screener_freshness import _seed

    repo = _seed(tmp_path, ["72030"], "2026-09-07")

    class _Ctx:
        config = type(
            "C",
            (),
            {
                "features": type("F", (), {"radar_enabled": True})(),
                "radar": RadarConfig(min_avg_turnover_jpy=0.0, min_listed_days=30, market_codes=("0111",)),
            },
        )()
        repository = repo

    out = _run_radar_and_screener(_Ctx(), "2026-09-08")
    assert out["outcome"] == "waiting_input"
    for dataset in ("strength_snapshot", "screener_snapshot"):
        state = repo.sync_state(dataset)
        assert state is not None
        assert state.get("last_success_at") is None
        assert state.get("data_through") is None
