"""引け後バッチが J-Quants の publish 遅れに遭ったときの不変条件。

publish 前に 0 行が返った営業日でチェックポイントを進めてしまうと、次回は
last+1 から探すためその日は二度と取得されず恒久的な欠測になる。ここを守る。
"""

import httpx
import pytest

from app.providers.jquants.client import JQuantsClient
from app.repositories.core import CoreRepository
from app.services import jquants_sync as sync


TRADING_DAYS = ["2026-07-30", "2026-07-31", "2026-08-03"]


def _core(tmp_path):
    core = CoreRepository(tmp_path / "core.db")
    core.initialize()
    core.upsert_trading_days(
        [{"calendar_date": day, "holiday_division": "1"} for day in TRADING_DAYS]
    )
    return core


def _bar_row(code: str, day: str) -> dict:
    return {
        "Date": day, "Code": code, "O": 100, "H": 110, "L": 90, "C": 105,
        "Vo": 1000, "Va": 105000, "AdjC": 105, "AdjO": 100, "AdjH": 110,
        "AdjL": 90, "AdjVo": 1000, "AdjFactor": 1,
    }


def _engine(core, handler):
    client = JQuantsClient("k", transport=httpx.MockTransport(handler), sleep=lambda s: None)
    return sync.JQuantsSyncEngine(client, core)


@pytest.mark.parametrize(
    ("method", "path", "row_builder", "dataset"),
    [
        ("sync_daily_bars", "/equities/bars/daily", _bar_row, sync.DATASET_DAILY_PRICES),
        (
            "sync_index_bars",
            "/indices/bars/daily",
            lambda code, day: {"Date": day, "Code": "0000", "C": 2800},
            sync.DATASET_INDEX_PRICES,
        ),
    ],
)
def test_unpublished_day_does_not_advance_checkpoint(tmp_path, method, path, row_builder, dataset):
    core = _core(tmp_path)
    core.record_sync_success(dataset, checkpoint={"last_synced_date": "2026-07-30"})

    # 1回目: 7/31 はまだ publish されていない（空配列）
    def empty(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    result = getattr(_engine(core, empty), method)("2026-07-31")
    assert result["status"] == "not_published"
    # チェックポイントは 7/30 のまま = 7/31 は次回も取得対象
    assert core.sync_state(dataset)["checkpoint"]["last_synced_date"] == "2026-07-30"

    # 2回目: publish 済み → 取得できる（＝穴にならない）
    def published(request: httpx.Request) -> httpx.Response:
        day = dict(request.url.params)["date"]
        return httpx.Response(200, json={"data": [row_builder("72030", day)]})

    result = getattr(_engine(core, published), method)("2026-07-31")
    assert result["status"] == "ok"
    assert core.sync_state(dataset)["checkpoint"]["last_synced_date"] == "2026-07-31"


def test_daily_bars_stop_at_first_unpublished_day(tmp_path):
    """途中の日が未 publish なら、その先の日を先に取り込んで追い越さない。"""

    core = _core(tmp_path)
    core.record_sync_success(
        sync.DATASET_DAILY_PRICES, checkpoint={"last_synced_date": "2026-07-30"}
    )

    def handler(request: httpx.Request) -> httpx.Response:
        day = dict(request.url.params)["date"]
        if day == "2026-07-31":
            return httpx.Response(200, json={"data": []})  # 未 publish
        return httpx.Response(200, json={"data": [_bar_row("72030", day)]})

    result = _engine(core, handler).sync_daily_bars("2026-08-03")
    assert result["status"] == "not_published"
    assert core.sync_state(sync.DATASET_DAILY_PRICES)["checkpoint"]["last_synced_date"] == "2026-07-30"
    # 8/3 を先に入れて 7/31 を飛ばしていないこと
    assert core.bars_for_code("72030") == []


def test_financial_summaries_tolerate_empty_days(tmp_path):
    """開示は暦日ベースで「その日 0 件」が正常。日足と同じ扱いにしてはいけない。"""

    core = _core(tmp_path)
    core.record_sync_success(
        sync.DATASET_FINANCIAL_SUMMARY, checkpoint={"last_synced_date": "2026-07-30"}
    )

    def empty(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    result = _engine(core, empty).sync_financial_summaries("2026-08-01")
    assert result["status"] == "ok"
    # 空でも進む（進まないと開示のない日で永久に止まる）
    assert core.sync_state(sync.DATASET_FINANCIAL_SUMMARY)["checkpoint"]["last_synced_date"] == "2026-08-01"
