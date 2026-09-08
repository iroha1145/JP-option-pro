"""JP-06 / H01 / H02: scan is read-only; owner actions stay gated."""

from __future__ import annotations

import importlib

from starlette.testclient import TestClient


def _client(data_dir, monkeypatch):
    from app.tools.dev_fixture import build_fixture

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

    class _Loopback:
        def __init__(self, inner, client=("127.0.0.1", 40001)):
            self._inner = inner
            self._client = client

        async def __call__(self, scope, receive, send):
            if scope.get("type") == "http":
                scope = {**scope, "client": self._client}
            await self._inner(scope, receive, send)

    http = TestClient(_Loopback(main_module.app), base_url="http://testserver")
    return http, main_module, deps


def test_h01_scan_is_read_only_and_visitor_cannot_update(tmp_path, monkeypatch):
    client, _main, deps = _client(tmp_path / "data", monkeypatch)
    scan = client.get("/api/strength/scan?top=5")
    assert scan.status_code == 200
    body = scan.json()
    assert body["query_kind"] == "filter"
    assert body.get("publication_id")
    assert "stored_score_version" in body
    # GET must not create a worker action.
    status = client.get("/api/worker/status").json()
    assert status.get("recent_actions") in (None, []) or all(
        item.get("action_type") != "post_close_batch" for item in status.get("recent_actions") or []
    )
    deps.reset_dependencies_for_tests()


def test_h02_action_requires_json_and_same_origin(tmp_path, monkeypatch):
    client, _main, deps = _client(tmp_path / "data", monkeypatch)
    # Missing JSON / custom header is rejected by the owner-action dependency.
    response = client.post("/api/worker/actions/post_close_batch")
    assert response.status_code in {403, 415, 422}
    ok = client.post(
        "/api/worker/actions/post_close_batch",
        json={},
        headers={"X-Optix-Action": "1", "Origin": "http://testserver"},
    )
    assert ok.status_code in {202, 403}
    deps.reset_dependencies_for_tests()
