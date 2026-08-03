"""ティック: マッピング・間引き・歩み値・可用性・v1→v2 移行。"""

import sqlite3

import httpx

from app.providers.jquants import mapping
from app.providers.jquants.client import JQuantsClient
from app.repositories.core import CoreRepository
from app.repositories.intraday_store import (
    AVAILABILITY_PLAN_NOT_INCLUDED,
    AVAILABILITY_UNKNOWN,
    DATASET_MINUTE,
    DATASET_TICK,
    IntradayStore,
)
from app.services.intraday import (
    downsample_ticks,
    fetch_latest_ticks,
    tick_tape,
    tick_view,
)


def _tick(time, price, volume=100.0):
    return {"canonical_code": "72030", "trade_date": "2026-07-31",
            "tick_time": time, "price": price, "volume": volume}


# ---------------- マッピング ----------------

def test_map_trade_tick_wire_variants():
    base = {"Date": "2026-07-31", "Time": "09:00:01", "Code": "72030"}
    # CSV 一括配信の実フィールド名（ここを取り違えると数量が丸ごと欠測になる）
    real = mapping.map_trade_tick({
        **base, "SessionDistinction": "01", "Price": "3181", "TradingVolume": "1999100",
        "TransactionId": "000000001246",
    })
    assert real["price"] == 3181.0
    assert real["volume"] == 1999100.0
    assert mapping.map_trade_tick({**base, "P": "3200", "Vo": 500})["price"] == 3200.0
    assert mapping.map_trade_tick({**base, "Price": 3201.5, "V": 300})["volume"] == 300.0
    assert mapping.map_trade_tick({**base, "P": 3200, "Size": 200})["volume"] == 200.0
    # 価格キーが全滅した行は歩み値として無意味 → None
    assert mapping.map_trade_tick({**base, "Vo": 100}) is None
    # Time 欠落 → None
    assert mapping.map_trade_tick({"Date": "2026-07-31", "Code": "72030", "P": 1}) is None


# ---------------- 間引き ----------------

def test_downsample_keeps_small_sets_intact():
    rows = [_tick("09:00:00", 100), _tick("09:00:05", 101), _tick("09:00:09", 100.5)]
    points, bucket = downsample_ticks(rows, max_points=1200)
    assert bucket == 1
    assert len(points) == 3
    assert points[0]["price"] == 100


def test_downsample_buckets_and_conserves_volume():
    # 09:00:00〜15:30:00 に 4 秒間隔で 5,851 ティック
    rows = []
    for index in range(5851):
        seconds = 9 * 3600 + index * 4
        rows.append(_tick(f"{seconds//3600:02d}:{seconds%3600//60:02d}:{seconds%60:02d}",
                          3000 + (index % 7), volume=10.0))
    points, bucket = downsample_ticks(rows, max_points=1200)
    assert len(points) <= 1200
    assert bucket >= 2
    assert sum(point["volume"] for point in points) == sum(row["volume"] for row in rows)
    assert all(point["low"] <= point["price"] <= point["high"] for point in points)


def test_downsample_skips_lunch_gap_without_filling():
    rows = [_tick("11:29:59", 100), _tick("12:30:00", 101)]
    points, _bucket = downsample_ticks(rows, max_points=4)
    assert len(points) == 2  # 昼休みバケットは生成されない


# ---------------- 歩み値 ----------------

def test_tick_tape_directions_and_window_context():
    rows = [_tick("09:00:00", 100), _tick("09:00:01", 101),
            _tick("09:00:02", 101), _tick("09:00:03", 100.5)]
    tape = tick_tape(rows, limit=3)
    assert [entry["direction"] for entry in tape] == ["down", "flat", "up"]  # 新しい順
    assert tape[0]["time"] == "09:00:03"
    # limit より少ない場合: 先頭は前値なし → flat
    short = tick_tape(rows[:2], limit=10)
    assert [entry["direction"] for entry in short] == ["up", "flat"]


# ---------------- ビューの正直な状態 ----------------

def test_tick_view_honest_states(tmp_path):
    store = IntradayStore(tmp_path / "intraday.db")
    view = tick_view(store, "72030")
    assert view["available"] is False and view["reason"] == "not_fetched"

    store.initialize()
    store.record_availability(
        AVAILABILITY_PLAN_NOT_INCLUDED, error_code="jquants_plan_not_included", dataset=DATASET_TICK
    )
    view = tick_view(store, "72030")
    assert view["reason"] == "plan_not_included"
    assert "note_ja" in view

    store.record_availability("available", dataset=DATASET_TICK)
    store.replace_ticks("72030", "2026-07-31", [
        {"tick_time": "09:00:00", "price": 100.0, "volume": 10.0},
        {"tick_time": "09:00:01", "price": 101.0, "volume": 20.0},
    ])
    view = tick_view(store, "72030")
    assert view["available"] is True
    assert view["trade_date"] == "2026-07-31"
    assert view["tick_count"] == 2
    assert len(view["points"]) == 2
    assert view["tape"][0]["direction"] == "up"


# ---------------- 取得（403 / 200 / 完了日キャッシュ） ----------------

def _core_with_calendar(tmp_path):
    core = CoreRepository(tmp_path / "core.db")
    core.initialize()
    core.upsert_trading_days(
        [{"calendar_date": f"2026-07-{day:02d}", "holiday_division": "1"} for day in range(28, 32)]
    )
    core.upsert_daily_bars(
        [{"canonical_code": "72030", "trade_date": "2026-07-31", "close": 1.0,
          "open": 1.0, "high": 1.0, "low": 1.0, "turnover_value": 1.0}]
    )
    return core


def test_fetch_ticks_records_plan_not_included_isolated_from_minute(tmp_path):
    """bulk/list が 403 = アドオン未契約。分足の可用性は汚染しない。"""

    core = _core_with_calendar(tmp_path)
    store = IntradayStore(tmp_path / "intraday.db")
    store.initialize()

    client = JQuantsClient(
        "k", transport=httpx.MockTransport(lambda request: httpx.Response(403)), sleep=lambda s: None
    )
    result = fetch_latest_ticks(client=client, store=store, core=core, canonical_code="72030")
    assert result["status"] == "plan_not_included"
    assert store.availability(DATASET_TICK)["availability"] == AVAILABILITY_PLAN_NOT_INCLUDED
    assert store.availability(DATASET_MINUTE)["availability"] == AVAILABILITY_UNKNOWN


def _tick_csv(rows: list[tuple[str, str, str, str]]) -> bytes:
    """Date,Code,Time,SessionDistinction,Price,TradingVolume,TransactionId"""

    head = "Date,Code,Time,SessionDistinction,Price,TradingVolume,TransactionId\n"
    body = "".join(
        f"2026-07-31,{code},{time},01,{price},{volume},000000000001\n"
        for code, time, price, volume in rows
    )
    return (head + body).encode("utf-8")


def _bulk_transport(csv_bytes: bytes, counter: dict, *, file_date: str = "20260731"):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/bulk/list"):
            counter["list"] = counter.get("list", 0) + 1
            return httpx.Response(200, json={"data": [
                {"Key": f"equities/trades/live/equities_trades_{file_date}.csv.gz", "Size": 1},
            ]})
        if path.endswith("/bulk/get"):
            counter["get"] = counter.get("get", 0) + 1
            return httpx.Response(200, json={"url": "https://example.invalid/presigned.csv"})
        counter["download"] = counter.get("download", 0) + 1
        return httpx.Response(200, content=csv_bytes)

    return handler


def test_fetch_ticks_uses_bulk_csv_and_caches(tmp_path, monkeypatch):
    """ティックは CSV 一括配信から取る（REST エンドポイントは存在しない）。"""

    core = _core_with_calendar(tmp_path)
    store = IntradayStore(tmp_path / "intraday.db")
    store.initialize()
    counter: dict = {}
    csv_bytes = _tick_csv([
        ("72030", "09:00:00.043728", "3181", "1999100"),
        ("72030", "09:00:01.100000", "3180", "4600"),
        ("99840", "09:00:02.000000", "5000", "100"),
    ])

    client = JQuantsClient(
        "k", transport=httpx.MockTransport(_bulk_transport(csv_bytes, counter)), sleep=lambda s: None
    )

    # presigned URL は API キーを付けない別クライアントで取りに行く。ここだけ差し替える
    # （JQuantsClient 生成後にパッチしないと、クライアント自身の httpx まで潰れる）。
    import app.providers.jquants.client as client_module

    class _FakeRaw:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, url):
            counter["download"] = counter.get("download", 0) + 1
            return httpx.Response(200, content=csv_bytes)

    monkeypatch.setattr(client_module.httpx, "Client", _FakeRaw)

    result = fetch_latest_ticks(
        client=client, store=store, core=core, canonical_code="72030", extra_codes={"99840"}
    )
    assert result["status"] == "ok"
    assert result["ticks"] == 2
    # 同じ 1 パスで自選銘柄も入る（50MB を 1 銘柄のために落とさない）
    assert result["codes_stored"] == 2
    assert len(store.ticks_for("99840", "2026-07-31")) == 1
    assert counter["list"] == 1

    # 完了日はキャッシュ済み → 再ダウンロードしない
    again = fetch_latest_ticks(client=client, store=store, core=core, canonical_code="72030")
    assert again.get("cached") is True
    assert counter["list"] == 1


def test_fetch_ticks_reports_not_published_when_file_missing(tmp_path):
    """営業日でもファイルが無い（当日引け前）なら not_published。"""

    core = _core_with_calendar(tmp_path)
    store = IntradayStore(tmp_path / "intraday.db")
    store.initialize()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    client = JQuantsClient("k", transport=httpx.MockTransport(handler), sleep=lambda s: None)
    result = fetch_latest_ticks(client=client, store=store, core=core, canonical_code="72030")
    assert result["status"] == "not_published"
    # 「未契約」と混同しない
    assert store.availability(DATASET_TICK)["availability"] != AVAILABILITY_PLAN_NOT_INCLUDED


# ---------------- v1 → v2 前方移行 ----------------

def test_intraday_v1_database_migrates_forward(tmp_path):
    db_path = tmp_path / "intraday.db"
    store = IntradayStore(db_path)
    store.initialize()
    # v1 の実ファイルを再現: v2 の新テーブルを落とし、旧 intraday_state を復元。
    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP TABLE addon_state")
        connection.execute("DROP TABLE ticks")
        connection.execute("DROP TABLE tick_days")
        connection.execute(
            "CREATE TABLE intraday_state ("
            "id INTEGER PRIMARY KEY CHECK (id = 1), "
            "availability TEXT NOT NULL DEFAULT 'unknown', "
            "last_checked_at TEXT, last_error_code TEXT)"
        )
        connection.execute(
            "INSERT INTO intraday_state (id, availability, last_checked_at, last_error_code) "
            "VALUES (1, 'plan_not_included', '2026-08-01T00:00:00Z', 'jquants_plan_not_included')"
        )
        connection.execute(
            "UPDATE jp_intraday_schema SET version='jp-intraday-v1', checksum='deadbeef' WHERE id=1"
        )
        connection.commit()

    migrated = IntradayStore(db_path)
    migrated.initialize()
    # 旧 availability は addon_state('minute') に引き継がれる
    assert migrated.availability(DATASET_MINUTE)["availability"] == AVAILABILITY_PLAN_NOT_INCLUDED
    assert migrated.availability(DATASET_TICK)["availability"] == AVAILABILITY_UNKNOWN
    with sqlite3.connect(db_path) as connection:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        version = connection.execute(
            "SELECT version FROM jp_intraday_schema WHERE id=1"
        ).fetchone()[0]
    assert "intraday_state" not in tables
    assert {"ticks", "tick_days", "addon_state"} <= tables
    assert version == "jp-intraday-v2"


def test_volume_null_day_is_refetched_not_served_from_cache(tmp_path, monkeypatch):
    """マッパーが壊れていた時期の行はキャッシュとして信用しない（自己修復）。"""

    core = _core_with_calendar(tmp_path)
    store = IntradayStore(tmp_path / "intraday.db")
    store.initialize()
    # 数量が入っていない「壊れた」当日キャッシュを仕込む
    store.replace_ticks("72030", "2026-07-31", [
        {"tick_time": "09:00:00", "price": 100.0, "volume": None},
    ])
    assert store.tick_day_has_volume("72030", "2026-07-31") is False

    counter: dict = {}
    csv_bytes = _tick_csv([("72030", "09:00:00.000000", "3181", "1999100")])
    client = JQuantsClient(
        "k", transport=httpx.MockTransport(_bulk_transport(csv_bytes, counter)), sleep=lambda s: None
    )
    import app.providers.jquants.client as client_module

    class _FakeRaw:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, url): return httpx.Response(200, content=csv_bytes)

    monkeypatch.setattr(client_module.httpx, "Client", _FakeRaw)
    result = fetch_latest_ticks(client=client, store=store, core=core, canonical_code="72030")
    assert result.get("cached") is not True       # キャッシュを返さず取り直した
    assert store.tick_day_has_volume("72030", "2026-07-31") is True
