"""回填計画が「立てた窓」に対してしか完了しないこと。

実害:`backfill_years` を 1 → 10 に広げた後も、空売り残高・空売り比率・
信用余額は 2025-06 起点の古い計画のまま `pending=0` を返し続け、10 年分ある
アーカイブのうち 35 本しか取り込めていなかった。日足だけは別の機会に計画が
立て直されて 141 本入っており、**同じ DB の中で片方だけ 10 年分**という
気づきにくい状態になっていた。
"""

import json

import httpx
import pytest

from app.providers.jquants.client import JQuantsClient
from app.repositories.core import CoreRepository
from app.services import jquants_sync as sync
from app.worker.tasks import build_default_tasks


ARCHIVE = {
    # 履歴は月次、直近は日次。J-Quants の実際の並びに合わせる。
    "2016-08-01": [
        f"markets/short-sale-report/historical/{year}/markets_short-sale-report_{year}{month:02d}.csv.gz"
        for year in (2016, 2025)
        for month in (6, 7)
    ],
}
WIDE_KEYS = sorted(ARCHIVE["2016-08-01"])
NARROW_KEYS = sorted(k for k in WIDE_KEYS if "/2025/" in k)


def _core(tmp_path):
    core = CoreRepository(tmp_path / "core.db")
    core.initialize()
    return core


def _engine(core, keys_for_window):
    """`from=` で見える範囲が変わるアーカイブを模す。"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/bulk/list"):
            start = request.url.params.get("from") or "0000-00-00"
            keys = keys_for_window(start)
            return httpx.Response(200, json={"data": [{"Key": k} for k in keys]})
        return httpx.Response(404, json={})

    client = JQuantsClient("k", transport=httpx.MockTransport(handler), sleep=lambda s: None)
    return sync.JQuantsSyncEngine(client, core, backfill_years=10)


def _window(start: str):
    return WIDE_KEYS if start <= "2016-08-01" else NARROW_KEYS


def test_plan_records_the_window_it_was_built_for(tmp_path):
    core = _core(tmp_path)
    engine = _engine(core, _window)
    result = engine.backfill_plan(sync.DATASET_SHORT_POSITIONS)

    assert result["status"] == "planned"
    checkpoint = (core.sync_state(sync.DATASET_SHORT_POSITIONS) or {})["checkpoint"]
    assert checkpoint["bulk_history_from"] == engine.backfill_window_start(), (
        "どの窓に対して立てた計画なのかが残らないと、窓が広がったことに気づけない"
    )


def test_window_start_is_month_aligned(tmp_path):
    """窓の文字列が毎日変わると「窓が変わったら立て直す」が毎日の立て直しになる。"""

    engine = _engine(_core(tmp_path), _window)
    start = engine.backfill_window_start()
    assert start.endswith("-01") and len(start) == 10


def test_replanning_a_wider_window_keeps_what_was_already_ingested(tmp_path):
    core = _core(tmp_path)

    # まず狭い窓で計画を立て、全部取り込んだことにする。
    narrow = _engine(core, lambda _start: NARROW_KEYS)
    narrow.backfill_plan(sync.DATASET_SHORT_POSITIONS)
    core.record_sync_success(
        sync.DATASET_SHORT_POSITIONS,
        checkpoint={"bulk_pending": [], "bulk_done": NARROW_KEYS, "last_synced_date": "2026-08-03"},
    )

    # 窓が広がった状態で立て直す。
    wide = _engine(core, _window)
    result = wide.backfill_plan(sync.DATASET_SHORT_POSITIONS)

    checkpoint = (core.sync_state(sync.DATASET_SHORT_POSITIONS) or {})["checkpoint"]
    assert result["pending"] == len(WIDE_KEYS) - len(NARROW_KEYS)
    assert set(checkpoint["bulk_pending"]).isdisjoint(NARROW_KEYS), "取り込み済みを積み直している"
    assert set(checkpoint["bulk_done"]) == set(NARROW_KEYS), "取り込み済みの記録を捨てている"
    assert checkpoint["last_synced_date"] == "2026-08-03", "増分レーンの位置を巻き戻している"


class _FakeContext:
    """`backfill` タスク本体だけを回すための最小の器。"""

    def __init__(self, core, engine):
        from app.personal_config import get_personal_config

        self.repository = core
        self._engine = engine
        self.config = get_personal_config()
        self.calls: list[str] = []

    @property
    def engine(self):
        return self._engine

    def jquants_ready(self) -> bool:
        return True


def _seed_up_to_date(core, engine, *, skip=None):
    """`skip` 以外のデータセットを「現在の窓で取り込み済み」にしておく。

    回填タスクは 1 ティックで 1 データセットしか進めないので、こうしないと
    先頭の日足で止まって検証したいデータセットに届かない。
    """

    for dataset in (
        sync.DATASET_DAILY_PRICES, sync.DATASET_INDEX_PRICES, sync.DATASET_FINANCIAL_SUMMARY,
        sync.DATASET_MARGIN_INTEREST, sync.DATASET_MARGIN_ALERTS, sync.DATASET_SHORT_RATIO,
        sync.DATASET_SHORT_POSITIONS,
    ):
        if dataset == skip:
            continue
        core.record_sync_success(
            dataset,
            checkpoint={
                "bulk_pending": [], "bulk_done": ["x"],
                "bulk_history_from": engine.backfill_window_start(),
                "last_synced_date": "2026-08-03",
            },
        )


def _backfill_task(context):
    for spec in build_default_tasks(context):
        if spec.name == "history_backfill":
            return spec.run
    raise AssertionError("history_backfill task not registered")


def test_worker_replans_when_the_window_widened(tmp_path, monkeypatch):
    """`pending=0` だけを見て「履歴が揃った」と判断しないこと。"""

    core = _core(tmp_path)
    engine = _engine(core, _window)
    _seed_up_to_date(core, engine, skip=sync.DATASET_SHORT_POSITIONS)
    core.record_sync_success(
        sync.DATASET_SHORT_POSITIONS,
        checkpoint={
            "bulk_pending": [],
            "bulk_done": NARROW_KEYS,
            "bulk_history_from": "2025-06-01",   # 狭い窓で立てた古い計画
            "last_synced_date": "2026-08-03",
        },
    )

    planned: list[str] = []
    original_plan = engine.backfill_plan
    monkeypatch.setattr(
        engine, "backfill_plan",
        lambda dataset: (planned.append(dataset), original_plan(dataset))[1],
    )
    # 実ファイルは落とさない。ここで見たいのは「立て直したか」だけ。
    monkeypatch.setattr(
        engine, "backfill_step",
        lambda dataset, **kw: sync.SyncResult(dataset=dataset, status="ok", rows=0, pending=1),
    )

    run = _backfill_task(_FakeContext(core, engine))
    result = run(None)

    assert sync.DATASET_SHORT_POSITIONS in planned, (
        "窓が広がっても計画を立て直さないので、10 年分あるうち 35 本で凍ったままになる"
    )
    assert result.status == "completed"
    assert result.details.get("reason") != "no_pending_backfill"


def test_worker_does_not_replan_when_the_window_is_unchanged(tmp_path, monkeypatch):
    """立て直しは窓が変わったときだけ。毎ティック listing を叩かない。"""

    core = _core(tmp_path)
    engine = _engine(core, _window)
    core.record_sync_success(
        sync.DATASET_SHORT_POSITIONS,
        checkpoint={
            "bulk_pending": [],
            "bulk_done": WIDE_KEYS,
            "bulk_history_from": engine.backfill_window_start(),
            "last_synced_date": "2026-08-03",
        },
    )
    _seed_up_to_date(core, engine)

    planned: list[str] = []
    monkeypatch.setattr(
        engine, "backfill_plan",
        lambda dataset: (planned.append(dataset), sync.SyncResult(dataset=dataset, status="planned"))[1],
    )

    run = _backfill_task(_FakeContext(core, engine))
    result = run(None)

    assert planned == []
    assert result.details.get("reason") == "no_pending_backfill"


def test_party_fields_survive_the_mapper():
    """住所と DIC を落とすと、機関実体の正規化が名前の文字列一致だけになる。"""

    from app.providers.jquants import mapping

    mapped = mapping.map_short_position({
        "DiscDate": "2026-08-03", "CalcDate": "2026-07-31", "Code": "39050",
        "SSName": "モルガン・スタンレーMUFG証券株式会社",
        "SSAddr": "東京都千代田区大手町1-9-7",
        "DICName": "Morgan Stanley Investment Management Inc.",
        "DICAddr": "New York",
        "FundName": "-", "ShrtPosToSO": "0.0123", "ShrtPosShares": "395600",
        "ShrtPosUnits": "3956", "PrevRptDate": "2026-07-30", "PrevRptRatio": "0.0110",
        "Notes": "-",
    })
    assert mapped["holder_address"] == "東京都千代田区大手町1-9-7"
    assert mapped["manager_name"] == "Morgan Stanley Investment Management Inc."
    assert mapped["manager_address"] == "New York"


def test_migration_from_v5_adds_the_party_columns(tmp_path):
    """既存 DB が v5 のままでも前方移行できること（列追加は冪等）。"""

    from app.repositories import core_schema

    core = CoreRepository(tmp_path / "core.db")
    core.initialize()
    with core.write() as connection:
        columns = {r[1] for r in connection.execute("PRAGMA table_info(short_positions)")}
    assert {"holder_address", "manager_name", "manager_address"} <= columns
    assert core_schema.CORE_SCHEMA_VERSION == "jp-core-v6"
    # v5 の移行元が連鎖に残っていること（既存本番 DB はここから上がる）
    assert "jp-core-v5" in core_schema.CORE_MIGRATIONS


def test_short_monitor_tables_exist(tmp_path):
    core = CoreRepository(tmp_path / "core.db")
    core.initialize()
    with core.write() as connection:
        names = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert {
        "institution_entities", "institution_aliases", "short_position_events",
        "short_position_last_known", "short_behavior_snapshots", "short_behavior_signals",
    } <= names


def test_checkpoint_json_round_trips(tmp_path):
    """`bulk_history_from` が他のキーを消さずに載ること（merge 更新）。"""

    core = _core(tmp_path)
    core.record_sync_success("x", checkpoint={"last_synced_date": "2026-08-03"})
    core.record_sync_success("x", checkpoint={"bulk_history_from": "2016-08-01"})
    checkpoint = (core.sync_state("x") or {})["checkpoint"]
    assert checkpoint == json.loads(
        '{"bulk_history_from": "2016-08-01", "last_synced_date": "2026-08-03"}'
    )
