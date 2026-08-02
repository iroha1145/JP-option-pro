"""分足: マッピング・リサンプリング・正直な可用性状態。"""

import httpx

from app.providers.jquants import mapping
from app.repositories.core import CoreRepository
from app.repositories.intraday_store import (
    AVAILABILITY_PLAN_NOT_INCLUDED,
    IntradayStore,
)
from app.services.intraday import fetch_recent_minutes, intraday_chart, resample_minutes
from app.providers.jquants.client import JQuantsClient


def _minute(date, time, open_, high, low, close, volume=100.0, turnover=1000.0):
    return {
        "canonical_code": "72030", "trade_date": date, "bar_time": time,
        "open": open_, "high": high, "low": low, "close": close,
        "volume": volume, "turnover_value": turnover,
    }


def test_map_minute_bar_wire_format():
    mapped = mapping.map_minute_bar(
        {"Date": "2026-07-31", "Time": "09:01", "Code": "72030",
         "O": "3200", "H": 3205.0, "L": 3199, "C": 3201.5, "Vo": 15000, "Va": 4.8e7}
    )
    assert mapped["bar_time"] == "09:01"
    assert mapped["open"] == 3200.0
    assert mapped["turnover_value"] == 4.8e7
    assert mapping.map_minute_bar({"Date": "2026-07-31", "Code": "72030"}) is None  # Time 欠落


def test_resample_5m_and_60m_buckets():
    rows = [
        _minute("2026-07-31", "09:00", 100, 101, 99, 100.5),
        _minute("2026-07-31", "09:01", 100.5, 102, 100, 101.0),
        _minute("2026-07-31", "09:04", 101.0, 103, 101, 102.5),
        _minute("2026-07-31", "09:05", 102.5, 104, 102, 103.0),  # 次の5分バケット
        _minute("2026-07-31", "10:07", 103.0, 105, 103, 104.0),  # 60分では次バケット
    ]
    five = resample_minutes(rows, "5m")
    assert [(bar["bar_time"], bar["open"], bar["high"], bar["close"]) for bar in five] == [
        ("09:00", 100, 103, 102.5),
        ("09:05", 102.5, 104, 103.0),
        ("10:05", 103.0, 105, 104.0),
    ]
    assert five[0]["volume"] == 300.0  # 出来高は合算

    hourly = resample_minutes(rows, "60m")
    assert [(bar["bar_time"], bar["high"]) for bar in hourly] == [("09:00", 104), ("10:00", 105)]
    # 欠けた分は埋めない: バケット数は入力に存在する時間帯だけ
    assert len(resample_minutes(rows, "1m")) == 5


def test_resample_does_not_cross_dates():
    rows = [
        _minute("2026-07-30", "15:29", 100, 101, 99, 100.0),
        _minute("2026-07-31", "09:00", 102, 103, 101, 102.5),
    ]
    hourly = resample_minutes(rows, "60m")
    assert len(hourly) == 2
    assert hourly[0]["trade_date"] == "2026-07-30"
    assert hourly[1]["trade_date"] == "2026-07-31"


def test_intraday_chart_honest_states(tmp_path):
    store = IntradayStore(tmp_path / "intraday.db")
    store.initialize()
    # 未取得
    view = intraday_chart(store, "72030", interval="5m")
    assert view["available"] is False and view["reason"] == "not_fetched"
    # アドオン未契約
    store.record_availability(AVAILABILITY_PLAN_NOT_INCLUDED, error_code="jquants_plan_not_included")
    view = intraday_chart(store, "72030", interval="1m")
    assert view["available"] is False
    assert view["reason"] == "plan_not_included"
    assert "アドオン" in view["note_ja"]
    assert view["bars"] == []  # 空配列で「データなし」を偽装しない + 理由を明示


def test_fetch_records_plan_not_included_on_403(tmp_path):
    core = CoreRepository(tmp_path / "core.db")
    core.initialize()
    core.upsert_trading_days(
        [{"calendar_date": f"2026-07-{day:02d}", "holiday_division": "1"} for day in range(27, 32)]
    )
    core.upsert_daily_bars(
        [{"canonical_code": "72030", "trade_date": "2026-07-31", "close": 1.0,
          "open": 1.0, "high": 1.0, "low": 1.0, "turnover_value": 1.0}]
    )
    store = IntradayStore(tmp_path / "intraday.db")
    store.initialize()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    client = JQuantsClient("k", transport=httpx.MockTransport(handler), sleep=lambda s: None)
    result = fetch_recent_minutes(client=client, store=store, core=core, canonical_code="72030")
    assert result["status"] == "plan_not_included"
    assert store.availability()["availability"] == AVAILABILITY_PLAN_NOT_INCLUDED


def test_fetch_caches_completed_days(tmp_path):
    core = CoreRepository(tmp_path / "core.db")
    core.initialize()
    core.upsert_trading_days(
        [{"calendar_date": f"2026-07-{day:02d}", "holiday_division": "1"} for day in range(28, 32)]
    )
    core.upsert_daily_bars(
        [{"canonical_code": "72030", "trade_date": "2026-07-31", "close": 1.0,
          "open": 1.0, "high": 1.0, "low": 1.0, "turnover_value": 1.0}]
    )
    store = IntradayStore(tmp_path / "intraday.db")
    store.initialize()
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(
            200,
            json={"data": [
                {"Date": "2026-07-31", "Time": "09:00", "Code": "72030",
                 "O": 1, "H": 2, "L": 0.5, "C": 1.5, "Vo": 10, "Va": 15},
            ]},
        )

    client = JQuantsClient("k", transport=httpx.MockTransport(handler), sleep=lambda s: None)
    first = fetch_recent_minutes(client=client, store=store, core=core, canonical_code="72030", days=3)
    assert first["status"] == "ok" and first["fetched_days"] == 3
    calls_after_first = calls["count"]
    second = fetch_recent_minutes(client=client, store=store, core=core, canonical_code="72030", days=3)
    # 完了日はキャッシュ済み → 最新日だけ再取得
    assert second["fetched_days"] == 1
    assert calls["count"] == calls_after_first + 1
