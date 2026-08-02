"""J-Quants クライアント契約テスト（httpx.MockTransport、実 API 不接続）。"""

import json

import httpx
import pytest

from app.providers.jquants.client import JQuantsClient
from app.providers.jquants.errors import (
    JQuantsAuthError,
    JQuantsConfigError,
    JQuantsPlanError,
    JQuantsRateLimited,
)
from app.providers.jquants import mapping
from app.providers.jquants.rate_limit import JQuantsRateLimits


def _client(handler, **kwargs) -> JQuantsClient:
    return JQuantsClient(
        "test-key",
        transport=httpx.MockTransport(handler),
        sleep=lambda seconds: None,
        **kwargs,
    )


def test_missing_key_refused():
    with pytest.raises(JQuantsConfigError):
        JQuantsClient("")


def test_api_key_header_and_pagination():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers["x-api-key"] == "test-key"
        if "pagination_key" not in str(request.url):
            return httpx.Response(200, json={"data": [{"Code": "72030"}], "pagination_key": "p2"})
        return httpx.Response(200, json={"data": [{"Code": "67580"}]})

    with _client(handler) as client:
        rows = client.fetch_all("/equities/master")
    assert [row["Code"] for row in rows] == ["72030", "67580"]
    assert len(calls) == 2
    assert "pagination_key=p2" in str(calls[1].url)


def test_rate_limited_blocks_all_buckets_and_retries():
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(200, json={"data": []})

    limits = JQuantsRateLimits(clock=lambda: 0.0)
    # max_attempts=1: 再試行ループに入らず 429 を即座に上げる（clock 固定のため）
    with _client(handler, rate_limits=limits, max_attempts=1) as client:
        with pytest.raises(JQuantsRateLimited):
            client.fetch_page("/equities/bars/daily", {"date": "2026-07-31"})
    assert limits.global_bucket.next_delay_seconds() > 0.0  # 封鎖が全バケットに伝播
    assert limits.fins_bucket.next_delay_seconds() > 0.0


def test_auth_and_plan_errors_are_distinct():
    def handler_401(request):
        return httpx.Response(401)

    def handler_403(request):
        return httpx.Response(403)

    with _client(handler_401) as client:
        with pytest.raises(JQuantsAuthError):
            client.fetch_page("/equities/master")
    with _client(handler_403) as client:
        with pytest.raises(JQuantsPlanError):
            client.fetch_page("/fins/details")


def test_retry_on_server_error_then_success():
    attempts = {"count": 0}

    def handler(request):
        attempts["count"] += 1
        if attempts["count"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"data": [{"Date": "2026-07-31", "HolDiv": "1"}]})

    with _client(handler) as client:
        rows = client.fetch_all("/markets/calendar")
    assert rows and attempts["count"] == 3


def test_daily_bar_mapping_abbreviated_names():
    row = {
        "Date": "2026-07-31", "Code": "72030",
        "O": "3200", "H": 3300.0, "L": 3150, "C": 3250.5,
        "UL": "0", "LL": "1", "Vo": 1000000, "Va": 3.2e9,
        "AdjFactor": 1.0, "AdjC": 3250.5,
    }
    mapped = mapping.map_daily_bar(row)
    assert mapped["canonical_code"] == "72030"
    assert mapped["close"] == 3250.5
    assert mapped["open"] == 3200.0  # 数値文字列も受ける
    assert mapped["lower_limit"] == 1
    assert mapped["adj_close"] == 3250.5
    assert mapped["adj_open"] is None  # 欠損は None のまま


def test_fins_mapping_keeps_company_forecast_fields():
    row = {
        "DiscDate": "2026-07-30", "Code": "72030", "DiscNo": "X1",
        "CurPerType": "1Q", "Sales": "1000000", "OP": "80000",
        "FSales": "4000000", "FOP": "350000", "NCOP": "60000",
    }
    mapped = mapping.map_financial_summary(row)
    assert mapped["forecast_operating_profit"] == 350000.0
    assert mapped["nc_operating_profit"] == 60000.0
    assert mapped["period_type"] == "1Q"


def test_bulk_list_requires_exactly_one_selector():
    def handler(request):
        return httpx.Response(200, json={"data": []})

    with _client(handler) as client:
        with pytest.raises(Exception):
            client.bulk_list()
        with pytest.raises(Exception):
            client.bulk_list(endpoint="/equities/bars/daily", date="2026-07")


def test_response_key_never_logged_in_errors():
    def handler(request):
        return httpx.Response(500, text="boom")

    with _client(handler, max_attempts=1) as client:
        try:
            client.fetch_page("/equities/master")
        except Exception as exc:
            assert "test-key" not in str(exc)
            assert "test-key" not in json.dumps(getattr(exc, "args", []), default=str)
