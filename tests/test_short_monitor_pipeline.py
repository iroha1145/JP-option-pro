"""再構築と再計算を実際の SQLite に対して回す。

ここで確かめたいのは「同じ入力を二度流しても同じ結果になるか」「訂正が
遡らないか」「途中で何も無い日でも前回の結果を壊さないか」。
"""

import pytest

from app.repositories.core import CoreRepository
from app.services.short_monitor import pipeline
from app.services.short_monitor import states


DAYS = [f"2026-06-{d:02d}" for d in range(1, 31)] + [f"2026-07-{d:02d}" for d in range(1, 32)]
DAYS = [d for d in DAYS if d <= "2026-07-31"]
AS_OF = DAYS[-1]


def _core(tmp_path):
    core = CoreRepository(tmp_path / "core.db")
    core.initialize()
    core.upsert_trading_days(
        [{"calendar_date": day, "holiday_division": "1"} for day in DAYS]
    )
    return core


def _seed_prices(core, codes, *, drift=0.0):
    bars = []
    index = []
    for code in codes:
        price = 1000.0
        for day in DAYS:
            price *= (1.0 + drift)
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
        [
            {
                "canonical_code": code, "display_code": code[:4], "name_ja": f"銘柄{code}",
                "sector33_code": "3650", "sector33_name": "電気機器",
                "market_code": "0111", "market_name": "プライム",
            }
            for code in codes
        ],
        as_of_date=AS_OF,
    )


def _seed_reports(core, rows):
    core.upsert_short_positions(rows)


def _report(code, holder, calc, ratio, prev=None, shares=None, disc=None):
    return {
        "canonical_code": code, "holder_name": holder,
        "calculated_date": calc, "disclosed_date": disc or calc,
        "short_position_ratio": ratio, "previous_ratio": prev,
        "short_position_shares": shares, "notes": "-", "previous_report_date": "",
        "short_position_units": None, "investment_fund_name": "-",
    }


CODES = [f"1{i:04d}" for i in range(6)]


def test_rebuild_is_idempotent(tmp_path):
    core = _core(tmp_path)
    _seed_prices(core, CODES)
    _seed_reports(core, [
        _report("10000", "Alpha Capital Ltd", "2026-07-01", 0.010, shares=500_000),
        _report("10000", "Alpha Capital Ltd", "2026-07-20", 0.020, prev=0.010, shares=1_000_000),
    ])

    first = pipeline.rebuild_events(core)
    second = pipeline.rebuild_events(core)

    with core.read() as connection:
        total = connection.execute("SELECT COUNT(*) FROM short_position_events").fetchone()[0]
    assert first.events == second.events == 2
    assert total == 2, "同じ報告から二重にイベントを作っている"


def test_rebuild_records_entities_and_aliases(tmp_path):
    core = _core(tmp_path)
    _seed_prices(core, CODES)
    _seed_reports(core, [
        _report("10000", "MORGAN STANLEY & CO. INTERNATIONAL PLC", "2026-07-01", 0.010),
        _report("10001", "Morgan Stanley & Co. International plc", "2026-07-02", 0.012),
        _report("10002", "モルガン・スタンレーMUFG証券株式会社", "2026-07-03", 0.011),
    ])
    pipeline.rebuild_events(core)

    with core.read() as connection:
        entities = {r["legal_id"]: dict(r) for r in connection.execute(
            "SELECT * FROM institution_entities")}
        aliases = {r["raw_name"]: dict(r) for r in connection.execute(
            "SELECT * FROM institution_aliases")}

    assert len(aliases) == 3, "生表記を 1 件も落としていないこと"
    groups = {e["group_id"] for e in entities.values()}
    assert groups == {"morgan-stanley"}
    assert len(entities) == 2, "英国法人と日本法人は別の法的主体のまま"


def test_last_known_keeps_below_threshold_visible(tmp_path):
    core = _core(tmp_path)
    _seed_prices(core, CODES)
    _seed_reports(core, [
        _report("10000", "Alpha", "2026-07-01", 0.010, shares=500_000),
        _report("10000", "Alpha", "2026-07-20", 0.004, prev=0.010, shares=200_000),
    ])
    pipeline.rebuild_events(core)

    known = core.short_position_last_known_for_code("10000")
    assert len(known) == 1
    assert known[0]["visibility_status"] == "below_public_threshold"
    assert known[0]["exact_position_known"] == 0
    assert known[0]["last_reported_ratio"] == pytest.approx(0.004)


def test_report_age_is_counted_up_to_today_not_the_end_of_the_calendar(tmp_path):
    """取引カレンダーは 1 年先まで入っている。

    そのまま末尾から数えると、昨日出たばかりの報告が「247 営業日前」になり、
    全銘柄のデータ信頼度が一律に落ちる（本番の実データでそうなっていた）。
    """

    core = _core(tmp_path)
    # カレンダーを 1 年先まで伸ばす（本番と同じ状況）
    core.upsert_trading_days(
        [{"calendar_date": f"2027-0{m}-{d:02d}", "holiday_division": "1"}
         for m in (1, 2, 3) for d in range(1, 29)]
    )
    _seed_prices(core, CODES)
    _seed_reports(core, [
        _report("10000", "Alpha", "2026-07-29", 0.012, shares=500_000, disc="2026-07-31"),
    ])
    pipeline.rebuild_events(core)

    known = core.short_position_last_known_for_code("10000")
    assert known and known[0]["state_age_trading_days"] is not None
    assert known[0]["state_age_trading_days"] <= 3, (
        "未来のカレンダーぶんを経過日数に数えている"
    )


def test_refresh_writes_snapshots_and_signals(tmp_path):
    core = _core(tmp_path)
    _seed_prices(core, CODES, drift=-0.004)
    _seed_reports(core, [
        _report("10000", "Alpha", "2026-06-20", 0.010, shares=500_000),
        _report("10000", "Alpha", "2026-07-28", 0.040, prev=0.010, shares=2_000_000),
    ])
    pipeline.rebuild_events(core)

    result = pipeline.refresh_snapshots(core, as_of_date=AS_OF)
    assert result.as_of_date == AS_OF
    assert result.snapshots == len(CODES)

    row = core.short_behavior_snapshot("10000", AS_OF)
    assert row is not None
    assert row["visible_short_ratio"] == pytest.approx(0.040)
    assert row["pressure_adv20_20d"] > 0
    assert row["algorithm_version"] == result.algorithm_version
    assert result.signals >= 1


def test_refresh_is_idempotent_for_the_same_day(tmp_path):
    core = _core(tmp_path)
    _seed_prices(core, CODES, drift=-0.004)
    _seed_reports(core, [
        _report("10000", "Alpha", "2026-06-20", 0.010, shares=500_000),
        _report("10000", "Alpha", "2026-07-28", 0.040, prev=0.010, shares=2_000_000),
    ])
    pipeline.rebuild_events(core)

    pipeline.refresh_snapshots(core, as_of_date=AS_OF)
    before = core.short_behavior_snapshot("10000", AS_OF)
    pipeline.refresh_snapshots(core, as_of_date=AS_OF)
    after = core.short_behavior_snapshot("10000", AS_OF)

    ignored = {"generated_at"}
    assert {k: v for k, v in before.items() if k not in ignored} == {
        k: v for k, v in after.items() if k not in ignored
    }
    with core.read() as connection:
        rows = connection.execute(
            "SELECT COUNT(*) FROM short_behavior_snapshots WHERE as_of_date = ?", (AS_OF,)
        ).fetchone()[0]
    assert rows == len(CODES)


def test_a_day_with_no_usable_data_keeps_the_previous_snapshot(tmp_path):
    """外部データが取れなかった日に、前回の有効な結果を消さない。"""

    core = _core(tmp_path)
    _seed_prices(core, CODES)
    pipeline.rebuild_events(core)
    pipeline.refresh_snapshots(core, as_of_date=AS_OF)
    kept = core.short_behavior_snapshot(CODES[0], AS_OF)
    assert kept is not None

    empty = CoreRepository(tmp_path / "empty.db")
    empty.initialize()
    result = pipeline.refresh_snapshots(empty, as_of_date=AS_OF)
    assert result.snapshots == 0

    assert core.short_behavior_snapshot(CODES[0], AS_OF) is not None


def test_events_published_after_the_target_date_are_not_used(tmp_path):
    """点時: 対象日より後に公開された報告をスナップショットに入れない。"""

    core = _core(tmp_path)
    _seed_prices(core, CODES)
    _seed_reports(core, [
        _report("10000", "Alpha", "2026-07-10", 0.010, shares=500_000, disc="2026-07-14"),
        _report("10000", "Alpha", "2026-07-25", 0.050, prev=0.010, shares=2_500_000,
                disc="2026-07-30"),
    ])
    pipeline.rebuild_events(core)

    pipeline.refresh_snapshots(core, as_of_date="2026-07-29")
    early = core.short_behavior_snapshot("10000", "2026-07-29")
    pipeline.refresh_snapshots(core, as_of_date="2026-07-30")
    late = core.short_behavior_snapshot("10000", "2026-07-30")

    assert early["visible_short_ratio"] == pytest.approx(0.010), "公開前の値が漏れている"
    assert late["visible_short_ratio"] == pytest.approx(0.050)


def test_rankings_read_only_the_snapshot_table(tmp_path):
    core = _core(tmp_path)
    _seed_prices(core, CODES, drift=-0.004)
    _seed_reports(core, [
        _report("10000", "Alpha", "2026-06-20", 0.010, shares=500_000),
        _report("10000", "Alpha", "2026-07-28", 0.040, prev=0.010, shares=2_000_000),
    ])
    pipeline.rebuild_events(core)
    pipeline.refresh_snapshots(core, as_of_date=AS_OF)

    rows, total = core.short_behavior_rankings(AS_OF, limit=10)
    assert total == len(CODES)
    assert rows[0]["display_code"], "銘柄名の join が効いていない"

    filtered, count = core.short_behavior_rankings(
        AS_OF, states=[states.STATE_NO_SIGNAL], limit=10,
    )
    assert all(r["primary_state"] == states.STATE_NO_SIGNAL for r in filtered)
    assert count == len(filtered)

    by_market, _ = core.short_behavior_rankings(AS_OF, markets=["9999"], limit=10)
    assert by_market == []


def test_state_counts_and_coverage(tmp_path):
    core = _core(tmp_path)
    _seed_prices(core, CODES)
    pipeline.rebuild_events(core)
    pipeline.refresh_snapshots(core, as_of_date=AS_OF)

    counts = core.short_behavior_state_counts(AS_OF)
    coverage = core.short_behavior_coverage(AS_OF)
    assert sum(counts.values()) == coverage["covered"] == len(CODES)
    assert coverage["with_visible_short"] == 0


# -- 第十三轮監査対応の追加テスト ------------------------------------------------

def test_raw_rows_with_different_funds_do_not_overwrite(tmp_path):
    """同一機関が同じ日に複数のファンド名義で報告 —— 旧 PK では静かに片方が
    消えていた（監査 高-2）。"""

    core = _core(tmp_path)
    _seed_prices(core, ["10000"])
    row_a = _report("10000", "MegaFund", DAYS[-5], 0.0060, shares=600_000)
    row_a["investment_fund_name"] = "Fund Alpha"
    row_b = _report("10000", "MegaFund", DAYS[-5], 0.0070, shares=700_000)
    row_b["investment_fund_name"] = "Fund Beta"
    _seed_reports(core, [row_a, row_b])

    with core.read() as connection:
        count = connection.execute("SELECT COUNT(*) FROM short_positions").fetchone()[0]
    assert count == 2, "ファンド違いの並行報告が主キーで潰れている"

    pipeline.rebuild_events(core)
    with core.read() as connection:
        events = connection.execute(
            "SELECT COUNT(*) FROM short_position_events"
        ).fetchone()[0]
        state = connection.execute(
            "SELECT last_reported_ratio, chain_count FROM short_position_last_known"
        ).fetchone()
    assert events == 2
    assert state["chain_count"] == 2
    assert state["last_reported_ratio"] == pytest.approx(0.0130)


def test_rebuild_sweeps_rows_that_are_no_longer_derived(tmp_path):
    """全量再構築は UPSERT + **掃除**。原始行が消えたのに導出行が残ると、
    存在しない報告が画面に出続ける（監査 高-3）。"""

    core = _core(tmp_path)
    _seed_prices(core, ["10000"])
    _seed_reports(core, [_report("10000", "Ghost Fund", DAYS[-5], 0.0080, shares=800_000)])
    pipeline.rebuild_events(core)
    with core.read() as connection:
        before = connection.execute("SELECT COUNT(*) FROM short_position_events").fetchone()[0]
    assert before == 1

    # 原始行を削除（訂正で置き換えられた・取り込みミスの巻き戻し等を模す）
    with core.write() as connection:
        connection.execute("DELETE FROM short_positions")
    pipeline.rebuild_events(core)
    with core.read() as connection:
        events = connection.execute("SELECT COUNT(*) FROM short_position_events").fetchone()[0]
        known = connection.execute("SELECT COUNT(*) FROM short_position_last_known").fetchone()[0]
    assert events == 0, "導出元が消えたのにイベントが幽霊として残っている"
    assert known == 0


def test_curated_aliases_survive_the_sweep(tmp_path):
    core = _core(tmp_path)
    _seed_prices(core, ["10000"])
    with core.write() as connection:
        connection.execute(
            "INSERT INTO institution_aliases (raw_name, legal_id, match_kind, confidence, updated_at) "
            "VALUES ('手動エイリアス', 'manual-entity', 'curated', 1.0, '2026-01-01T00:00:00Z')"
        )
    _seed_reports(core, [_report("10000", "SomeFund", DAYS[-5], 0.0080, shares=800_000)])
    pipeline.rebuild_events(core)
    with core.read() as connection:
        curated = connection.execute(
            "SELECT COUNT(*) FROM institution_aliases WHERE match_kind = 'curated'"
        ).fetchone()[0]
    assert curated == 1, "人手の別名表を掃除で消している"


def test_snapshot_publication_is_atomic_and_changes_the_run_token(tmp_path):
    """同じ日を作り直したら run が変わる（ETag が 304 に化けない）。
    run 行と断面行は 1 トランザクションなので、半端な断面が「最新」に
    見えることはない（監査 P0-6）。"""

    core = _core(tmp_path)
    _seed_prices(core, CODES)
    _seed_reports(core, [
        _report("10000", "Alpha", DAYS[-10], 0.0123, shares=500_000),
    ])
    pipeline.rebuild_events(core)
    first = pipeline.refresh_snapshots(core, as_of_date=AS_OF)
    assert first.snapshots > 0
    run_1 = core.latest_short_monitor_run(AS_OF)
    assert run_1 and run_1["status"] == "ready"
    assert run_1["row_count"] == first.snapshots

    second = pipeline.refresh_snapshots(core, as_of_date=AS_OF)
    run_2 = core.latest_short_monitor_run(AS_OF)
    assert second.snapshots == first.snapshots
    assert run_2["run_id"] != run_1["run_id"], (
        "同じ日の再計算で run が変わらない —— ETag が古い断面を 304 で返し続ける"
    )


# -- スキーマ移行 --------------------------------------------------------------

def test_v7_database_migrates_to_v8_without_losing_rows(tmp_path, monkeypatch):
    """v7 → v8 は生表を作り直す。**行を落とさない**こと。

    本番ではこの移行が `database or disk is full` で落ちた —— ディスクでは
    なく、コンテナの `/tmp`（128MB tmpfs）に SQLite のソート一時ファイルが
    溢れたため。移行そのものは 1 トランザクションなので巻き戻ったが、
    移行経路はテストが 1 本も無かった。ここで塞ぐ。
    """

    from app.repositories import core_schema
    from app.repositories.core import CoreRepository

    db = tmp_path / "legacy.db"
    # v7 相当（生表の主キーにファンド/住所が入っていない）で作る
    monkeypatch.setattr(CoreRepository, "SCHEMA_VERSION", "jp-core-v7")
    legacy_ddl = tuple(
        stmt.replace(
            "holder_address TEXT NOT NULL DEFAULT '',", "holder_address TEXT,"
        ).replace(
            "investment_fund_name TEXT NOT NULL DEFAULT '',", "investment_fund_name TEXT,"
        ).replace(
            "PRIMARY KEY (\n            canonical_code, disclosed_date, calculated_date,\n"
            "            holder_name, investment_fund_name, holder_address\n        )",
            "PRIMARY KEY (canonical_code, disclosed_date, calculated_date, holder_name)",
        )
        for stmt in core_schema.CORE_DDL
    )
    monkeypatch.setattr(CoreRepository, "DDL", legacy_ddl)
    old = CoreRepository(db)
    old.initialize()
    # 旧主キーの表なので、新しい upsert（衝突先が違う）は使えない。素で入れる。
    with old.write() as connection:
        connection.executemany(
            "INSERT INTO short_positions (canonical_code, disclosed_date, calculated_date, "
            "holder_name, short_position_ratio, short_position_shares, ingested_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("10000", DAYS[-5], DAYS[-5], f"Holder {i}", 0.0060 + i / 10_000,
                 600_000 + i, "2026-08-04T00:00:00Z")
                for i in range(50)
            ],
        )
    with old.read() as connection:
        before = connection.execute("SELECT COUNT(*) FROM short_positions").fetchone()[0]
    assert before == 50

    monkeypatch.undo()
    fresh = CoreRepository(db)
    fresh.initialize()   # ここで v7 → v8
    with fresh.read() as connection:
        after = connection.execute("SELECT COUNT(*) FROM short_positions").fetchone()[0]
        keys = connection.execute("PRAGMA table_info(short_positions)").fetchall()
        runs = connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'short_monitor_runs'"
        ).fetchone()
    assert after == before, "移行で行が消えている"
    assert runs is not None
    pk_columns = {row["name"] for row in keys if row["pk"]}
    assert {"investment_fund_name", "holder_address"} <= pk_columns


def test_sqlite_temp_files_go_next_to_the_database(tmp_path):
    """一時ファイルは 128MB tmpfs ではなくデータボリューム側に置く。"""

    import os

    from app.repositories.core import CoreRepository

    core = CoreRepository(tmp_path / "core.db")
    core.initialize()
    assert os.environ.get("SQLITE_TMPDIR") == str(tmp_path / "sqlite-tmp")
    assert (tmp_path / "sqlite-tmp").is_dir()
