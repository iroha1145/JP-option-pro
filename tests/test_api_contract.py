"""API 契約スモーク: フィクスチャ DB で主要エンドポイントを実測。

実プロバイダには一切接続しない。オーナー判定はループバック IP を名乗る
ASGI トランスポートで満たす（private_network モード）。
"""

import httpx
import pytest


@pytest.fixture()
def client(data_dir, monkeypatch):
    from app.tools.dev_fixture import build_fixture

    build_fixture(str(data_dir), days=140)

    import app.api.deps as deps
    import app.config as config_module
    import app.access as access_module

    deps.reset_dependencies_for_tests()
    config_module.reset_settings_for_tests()
    access_module.reset_access_runtime_for_tests()

    import importlib
    import app.main as main_module

    main_module = importlib.reload(main_module)

    class _LoopbackClient:
        """テストクライアントの scope['client'] をループバック IP に固定する。"""

        def __init__(self, inner):
            self._inner = inner

        async def __call__(self, scope, receive, send):
            if scope.get("type") == "http":
                scope = {**scope, "client": ("127.0.0.1", 40001)}
            await self._inner(scope, receive, send)

    from starlette.testclient import TestClient

    with TestClient(_LoopbackClient(main_module.app), base_url="http://testserver") as http_client:
        yield http_client
    deps.reset_dependencies_for_tests()


def test_health_and_market_overview(client):
    health = client.get("/health").json()
    assert health["app"] == "Optix Japan"

    overview = client.get("/api/market/overview")
    assert overview.status_code == 200
    body = overview.json()
    assert body["data_through"] == "2026-07-31"
    assert any(index["index_code"] == "0000" for index in body["indices"])
    assert body["breadth"]["advancers"] is not None


def test_radar_current_and_event_detail(client):
    current = client.get("/api/radar/current").json()
    assert current["scan_date"] == "2026-07-31"
    assert current["granularity"] == "daily"
    assert current["events"], "フィクスチャはブレイクを内包しているはず"
    event = current["events"][0]
    assert event["display_code"]
    detail = client.get(f"/api/radar/events/{event['event_id']}")
    assert detail.status_code == 200
    assert detail.json()["transitions"]


def test_stock_overview_resolves_letter_code(client):
    response = client.get("/api/stocks/285A")
    assert response.status_code == 200
    body = response.json()
    assert body["security"]["display_code"] == "285A"
    assert body["quote"]["close"] is not None
    assert body["financials"]["summaries"], "会社予想を含む財務サマリー"
    assert body["financials"]["summaries"][0]["forecast_label"] == "会社予想"


def test_screener_query_and_options(client):
    options = client.get("/api/screener/options").json()
    assert any(market["code"] == "0111" for market in options["markets"])
    result = client.post(
        "/api/screener/query",
        json={"markets": ["0111"], "sort_by": "rs_topix_63d", "limit": 5},
        headers={"X-Optix-Action": "1", "Origin": "http://testserver"},
    )
    assert result.status_code == 200
    body = result.json()
    assert body["trade_date"] == "2026-07-31"
    assert body["total"] >= 5
    assert len(body["rows"]) == 5


def test_watchlist_write_requires_same_origin(client):
    denied = client.post("/api/watchlist/7203")
    assert denied.status_code in (403, 415)
    allowed = client.post(
        "/api/watchlist/7203",
        headers={
            "X-Optix-Action": "1",
            "Origin": "http://testserver",
            "Content-Type": "application/json",
        },
    )
    assert allowed.status_code == 201
    listing = client.get("/api/watchlist").json()
    assert any(item["canonical_code"] == "72030" for item in listing["items"])


def test_data_status_declares_capabilities(client):
    body = client.get("/api/data-status").json()
    keys = {dataset["key"]: dataset for dataset in body["datasets"]}
    assert keys["daily_prices"]["status"] == "enabled"
    assert keys["financial_details"]["status"] == "unavailable"  # Premium 限定は正直に
    assert body["intraday"]["enabled"] is False
    assert body["market_timezone"] == "Asia/Tokyo"


def test_earnings_calendar_declares_coverage_note(client):
    body = client.get("/api/earnings/calendar?start=2026-07-31&end=2026-08-31").json()
    assert "3月期・9月期" in body["coverage_note"]
    assert body["items"], "フィクスチャの発表予定"
    assert any(item["announcement_date"] is None for item in body["items"])  # 未定は null で返す
