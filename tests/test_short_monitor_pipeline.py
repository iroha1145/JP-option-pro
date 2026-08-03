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
