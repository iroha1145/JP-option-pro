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


def test_strength_scan_endpoints(client):
    profiles = client.get("/api/strength/profiles").json()
    assert [p["id"] for p in profiles["profiles"]] == ["conservative", "balanced", "aggressive"]
    assert len(profiles["sectors"]) == 33
    assert abs(sum(profiles["family_weights"].values()) - 1.0) < 1e-9

    market = client.get("/api/strength/market")
    assert market.status_code == 200
    regime = market.json()["market_regime"]
    assert set(regime["dims"]) == {
        "index_trend", "momentum", "breadth", "volume", "risk_appetite", "risk_on_spread",
    }

    scan = client.get("/api/strength/scan?timeframe=all&profile=balanced&top=10")
    assert scan.status_code == 200
    body = scan.json()
    assert body["trade_date"] == "2026-07-31"
    assert body["universe_count"] >= body["screened_count"] >= len(body["rows"]) > 0
    assert body["tier_distribution"]["total"] == body["screened_count"]
    top_row = body["rows"][0]
    assert top_row["selected_view_rank"] == 1
    assert top_row["ranking_score"] is not None
    assert set(top_row["families"]) == {"short", "mid", "long", "trend", "breakout", "price_action"}
    # profile を変えると ranking が変わり得るが intrinsic は不変。
    aggressive = client.get("/api/strength/scan?profile=aggressive&top=10").json()
    by_code = {row["canonical_code"]: row for row in aggressive["rows"]}
    if top_row["canonical_code"] in by_code:
        assert by_code[top_row["canonical_code"]]["intrinsic_score"] == top_row["intrinsic_score"]
    # 不正パラメータは 422。
    assert client.get("/api/strength/scan?timeframe=weekly").status_code == 422
    assert client.get("/api/strength/scan?sector_id=9999x").status_code == 422


def test_account_register_and_personal_watchlist(client, monkeypatch):
    import app.api.access as access_api
    import app.api.account as account_api
    from app.services.accounts import AccountStore, set_account_store

    # ループバック HTTP なので HTTPS 判定だけテスト内で満たす。
    monkeypatch.setattr(account_api, "request_uses_https", lambda _request: True)
    monkeypatch.setattr(access_api, "request_uses_https", lambda _request: True)
    account_api.reset_rate_limits()
    import tempfile
    from pathlib import Path

    tmp = tempfile.mkdtemp(prefix="jp-accounts-")
    set_account_store(AccountStore(Path(tmp) / "accounts.db"))
    try:
        write_headers = {
            "X-Optix-Action": "1",
            "Origin": "http://testserver",
            "Content-Type": "application/json",
        }
        created = client.post(
            "/api/account/register",
            json={"username": "taro", "password": "pw-1234"},
            headers=write_headers,
        )
        assert created.status_code == 201
        assert created.json()["username"] == "taro"
        # Secure 属性付き cookie は http のテスト jar に載らないため手で拾う。
        set_cookie = created.headers.get("set-cookie", "")
        token = set_cookie.split("optix_user_session=", 1)[1].split(";", 1)[0]
        client.cookies.set("optix_user_session", token)
        me = client.get("/api/account/me").json()
        assert me["logged_in"] is True and me["username"] == "taro"
        status_body = client.get("/api/access/status").json()
        assert status_body["account"]["username"] == "taro"

        # アカウント主体の自選はオーナーの自選と別空間（private_network では
        # ループバックがオーナーだが、account cookie が優先される）。
        added = client.post("/api/watchlist/6758", headers=write_headers)
        assert added.status_code == 201
        listing = client.get("/api/watchlist").json()
        assert listing["principal"] == "account"
        assert [item["canonical_code"] for item in listing["items"]] == ["67580"]

        # 予約名 admin では登録できない。
        reserved = client.post(
            "/api/account/register",
            json={"username": "admin", "password": "pw"},
            headers=write_headers,
        )
        assert reserved.status_code == 400
        assert reserved.json()["detail"]["code"] == "username_reserved"

        # ログアウトで account セッションも失効。
        out = client.post("/api/access/logout", headers=write_headers)
        assert out.status_code == 200
        assert client.get("/api/account/me").json()["logged_in"] is False
    finally:
        set_account_store(None)
        account_api.reset_rate_limits()


def test_earnings_upcoming_view_contract(client):
    body = client.get("/api/earnings/upcoming").json()
    assert set(body["counts"]) == {"released", "confirmed", "estimated", "tbd"}
    assert "前年同期" in body["coverage_note"]
    statuses = {item["status"] for item in body["items"]}
    assert statuses <= {"released", "confirmed", "estimated"}
    for item in body["items"]:
        assert item["date"] is not None
        assert item["display_code"]
        if item["status"] == "released":
            assert "actual" in item  # 実績は released 行にだけ載る
        else:
            assert "actual" not in item
        if item["status"] == "estimated":
            assert item["confirmed"] is False
            assert item["estimate_basis"]
    # 未定は本流から隔離される
    for item in body["tbd_items"]:
        assert item["date"] is None


def test_stock_ticks_contract(client):
    """ティック: ルート健在 + 正直な not_fetched 形状（夹具にティック無し）。"""

    response = client.get("/api/stocks/7203/ticks")
    assert response.status_code == 200
    body = response.json()
    assert body["display_code"] == "7203"
    assert body["available"] is False
    assert body["reason"] in ("not_fetched", "plan_not_included")
    assert body["points"] == [] and body["tape"] == []
    assert {"availability", "trade_date", "tick_count"} <= set(body)
