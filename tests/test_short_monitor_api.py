"""接口の契約: 読み取り専用・ETag・語義の注意書き・説明の規律。"""

import json

import pytest
from starlette.testclient import TestClient

from app.repositories.core import CoreRepository
from app.services.short_monitor import explain, pipeline, states


DAYS = [f"2026-06-{d:02d}" for d in range(1, 31)] + [f"2026-07-{d:02d}" for d in range(1, 32)]
DAYS = [d for d in DAYS if d <= "2026-07-31"]
AS_OF = DAYS[-1]
CODES = [f"1{i:04d}" for i in range(5)]


@pytest.fixture()
def client(data_dir, monkeypatch):
    import app.access as access_module
    import app.api.deps as deps
    import app.config as config_module
    from app.data_paths import get_data_paths

    deps.reset_dependencies_for_tests()
    config_module.reset_settings_for_tests()
    access_module.reset_access_runtime_for_tests()
    paths = get_data_paths()

    core = CoreRepository(paths.core_db)
    core.initialize()
    core.upsert_trading_days([{"calendar_date": d, "holiday_division": "1"} for d in DAYS])
    bars, index = [], []
    for code in CODES:
        price = 1000.0
        for day in DAYS:
            price *= 0.996
            bars.append({
                "canonical_code": code, "trade_date": day,
                "open": price, "high": price * 1.01, "low": price * 0.99, "close": price,
                "volume": 1_000_000, "turnover_value": price * 1_000_000,
                "adjustment_factor": 1.0,
            })
    for day in DAYS:
        index.append({"index_code": "0000", "trade_date": day, "close": 2000.0})
    core.upsert_daily_bars(bars)
    core.upsert_index_bars(index)
    core.replace_security_master(
        [{
            "canonical_code": code, "display_code": code[:4], "name_ja": f"銘柄{code}",
            "sector33_code": "3650", "sector33_name": "電気機器",
            "market_code": "0111", "market_name": "プライム",
        } for code in CODES],
        as_of_date=AS_OF,
    )
    core.upsert_short_positions([
        {
            "canonical_code": "10000", "holder_name": "Alpha Capital Ltd",
            "calculated_date": "2026-06-20", "disclosed_date": "2026-06-22",
            "short_position_ratio": 0.010, "short_position_shares": 500_000,
            "previous_ratio": None, "notes": "-", "previous_report_date": "",
        },
        {
            "canonical_code": "10000", "holder_name": "Alpha Capital Ltd",
            "calculated_date": "2026-07-28", "disclosed_date": "2026-07-30",
            "short_position_ratio": 0.040, "short_position_shares": 2_000_000,
            "previous_ratio": 0.010, "notes": "-", "previous_report_date": "2026-06-20",
        },
        {
            "canonical_code": "10000", "holder_name": "Beta Securities Ltd",
            "calculated_date": "2026-07-20", "disclosed_date": "2026-07-22",
            "short_position_ratio": 0.004, "short_position_shares": 200_000,
            "previous_ratio": 0.008, "notes": "-", "previous_report_date": "2026-07-10",
        },
    ])
    pipeline.rebuild_events(core)
    pipeline.refresh_snapshots(core, as_of_date=AS_OF)

    import importlib

    import app.main as main_module

    main_module = importlib.reload(main_module)

    class _Loopback:
        """オーナー判定はループバック IP で満たす（private_network モード）。"""

        def __init__(self, inner):
            self._inner = inner

        async def __call__(self, scope, receive, send):
            if scope.get("type") == "http":
                scope = {**scope, "client": ("127.0.0.1", 40001)}
            await self._inner(scope, receive, send)

    with TestClient(_Loopback(main_module.app), base_url="http://testserver") as test_client:
        yield test_client
    deps.reset_dependencies_for_tests()


def test_overview_carries_the_disclosure_note_and_version(client):
    payload = client.get("/api/short-monitor/overview").json()
    assert payload["as_of_date"] == AS_OF
    assert "不代表市场全部空头仓位" in payload["note"]
    assert payload["validated"] == {"gates": False, "score": False}
    assert payload["coverage"]["covered"] == len(CODES)


def test_overview_returns_304_on_matching_etag(client):
    first = client.get("/api/short-monitor/overview")
    etag = first.headers["ETag"]
    again = client.get("/api/short-monitor/overview", headers={"If-None-Match": etag})
    assert again.status_code == 304


def test_rankings_are_bounded_and_explainable(client):
    payload = client.get("/api/short-monitor/rankings", params={"limit": 3}).json()
    assert payload["total"] == len(CODES)
    assert len(payload["rows"]) == 3
    row = payload["rows"][0]
    # 点数だけを返さない
    assert set(row["scores"]) >= {"absorption", "covering", "low_position", "risk"}
    assert "visible_short_ratio" in row
    assert "total_short_ratio" not in row, "総空売り残高であるかのような名前を出している"


def test_rankings_reject_unknown_views(client):
    assert client.get("/api/short-monitor/rankings", params={"view": "moon"}).status_code == 400


def test_rankings_reject_unknown_sort_columns(client):
    """並び替え列は許可リスト。任意の列名を SQL に通さない。"""

    payload = client.get(
        "/api/short-monitor/rankings", params={"order_by": "1; DROP TABLE securities"}
    ).json()
    assert payload["order_by"] == "1; DROP TABLE securities"
    assert payload["total"] == len(CODES)   # 既定列にフォールバックして壊れない


def test_rankings_filter_by_state_and_confidence(client):
    by_state = client.get(
        "/api/short-monitor/rankings", params={"states": states.STATE_NO_SIGNAL},
    ).json()
    assert all(r["primary_state"] == states.STATE_NO_SIGNAL for r in by_state["rows"])

    strict = client.get(
        "/api/short-monitor/rankings", params={"min_confidence": 0.99},
    ).json()
    assert strict["total"] <= by_state["total"]


def test_stock_detail_keeps_below_threshold_holders_visible(client):
    payload = client.get("/api/short-monitor/stocks/1000").json()
    holders = {h["name"]: h for h in payload["holders"]}
    below = holders["Beta Securities Ltd"]
    assert below["visibility_status"] == "below_public_threshold"
    assert below["exact_position_known"] is False
    assert below["last_reported_ratio"] == pytest.approx(0.004)
    assert payload["visible_short_ratio"] == pytest.approx(0.040), "閾値割れを合計に混ぜている"


def test_stock_detail_explanation_is_deterministic_and_caveated(client):
    a = client.get("/api/short-monitor/stocks/1000").json()["explanation"]
    b = client.get("/api/short-monitor/stocks/1000").json()["explanation"]
    assert a == b
    joined = " ".join(a["lines"])
    assert "跌破公开披露门槛" in joined
    assert "不代表机构意图" in joined


def test_events_endpoint_is_paginated(client):
    payload = client.get("/api/short-monitor/stocks/1000/events", params={"limit": 1}).json()
    assert payload["total"] == 3
    assert len(payload["events"]) == 1
    event = payload["events"][0]
    assert event["published_date"] >= event["position_date"]
    assert event["effective_trade_date"] >= event["published_date"]


def test_unknown_stock_is_404(client):
    assert client.get("/api/short-monitor/stocks/zzzz").status_code == 404


def test_status_reports_versions(client):
    raw = client.get("/api/short-monitor/status")
    assert raw.status_code == 200, raw.text
    payload = raw.json()
    assert payload["as_of_date"] == AS_OF
    assert "inst-" in payload["algorithm_version"]
    assert payload["validated"]["score"] is False


def test_institutions_do_not_merge_legal_entities(client):
    payload = client.get("/api/short-monitor/institutions").json()
    names = {row["name"] for row in payload["institutions"]}
    assert {"Alpha Capital Ltd", "Beta Securities Ltd"} <= names


def test_squeeze_label_always_carries_its_caveat():
    """「挤空确认」の但し書きは外せない。"""

    described = explain.describe({"primary_state": states.STATE_SQUEEZE_CONFIRMED})
    assert described["caveat"] and "不表示掌握全部市场空头仓位" in described["caveat"]


def test_explanation_never_claims_intent():
    banned = ("吸筹", "压盘", "拉升", "必然", "暴涨", "清零")
    for state in states.ORDERED_STATES:
        described = explain.describe({"primary_state": state})
        text = " ".join(described["lines"]) + " " + (described["caveat"] or "")
        for word in banned:
            assert word not in text or "不代表" in text or "不表示" in text, (
                f"{state} の文言に断定的な表現がある: {word}"
            )
