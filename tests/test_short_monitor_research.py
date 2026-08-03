"""歴史検証: 点時セマンティクスと、答えが「無い」ときにそう言えること。"""

import pytest

from app.repositories.core import CoreRepository
from app.research import short_behavior as sb
from app.research.short_behavior_runner import replay
from app.services.short_monitor import pipeline, states


DAYS = (
    [f"2026-04-{d:02d}" for d in range(1, 31)]
    + [f"2026-05-{d:02d}" for d in range(1, 32)]
    + [f"2026-06-{d:02d}" for d in range(1, 31)]
    + [f"2026-07-{d:02d}" for d in range(1, 32)]
)
CODES = [f"1{i:04d}" for i in range(8)]


def _core(tmp_path):
    core = CoreRepository(tmp_path / "core.db")
    core.initialize()
    core.upsert_trading_days([{"calendar_date": d, "holiday_division": "1"} for d in DAYS])
    bars, index = [], []
    for position, code in enumerate(CODES):
        price = 1000.0
        drift = -0.003 if position % 2 else 0.002
        for day in DAYS:
            price *= (1.0 + drift)
            bars.append({
                "canonical_code": code, "trade_date": day,
                "open": price, "high": price * 1.02, "low": price * 0.98, "close": price,
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
        as_of_date=DAYS[-1],
    )
    core.upsert_short_positions([
        {
            "canonical_code": "10000", "holder_name": "Alpha",
            "calculated_date": "2026-05-10", "disclosed_date": "2026-05-14",
            "short_position_ratio": 0.010, "short_position_shares": 500_000,
            "previous_ratio": None, "notes": "-", "previous_report_date": "",
        },
        {
            "canonical_code": "10000", "holder_name": "Alpha",
            "calculated_date": "2026-06-20", "disclosed_date": "2026-06-24",
            "short_position_ratio": 0.050, "short_position_shares": 2_500_000,
            "previous_ratio": 0.010, "notes": "-", "previous_report_date": "2026-05-10",
        },
    ])
    pipeline.rebuild_events(core)
    return core


def test_replay_never_uses_information_before_it_was_published(tmp_path):
    """6/20 の残高（5.0%）が 6/24 に公開されたなら、6/23 の断面には現れない。

    5/10 の残高（1.0%）は 5/14 に公開済みなので、それ以降に見えているのは正しい。
    ここで見たいのは「公開前の値が漏れていないか」だけ。
    """

    core = _core(tmp_path)
    records = replay(core, start="2026-05-20", end="2026-07-31", every=1)
    mine = [r for r in records if r["canonical_code"] == "10000"]
    assert mine, "この銘柄の信号が一件も出ていない（前提が壊れている）"

    early = [r for r in mine if r["signal_date"] < "2026-06-24"]
    for record in early:
        assert record["visible_short_ratio"] == pytest.approx(0.010), (
            "公開前の 5.0% が過去の断面に漏れている"
        )
    late = [r for r in mine if r["signal_date"] >= "2026-06-24"]
    if late:
        assert max(r["visible_short_ratio"] for r in late) == pytest.approx(0.050)


def test_replay_records_the_information_cutoff_on_every_signal(tmp_path):
    core = _core(tmp_path)
    records = replay(core, start="2026-06-01", end="2026-07-31", every=5)
    assert records
    for record in records:
        assert record["source_cutoff"] == record["signal_date"]


def test_replay_returns_forward_outcomes(tmp_path):
    core = _core(tmp_path)
    records = replay(core, start="2026-05-01", end="2026-07-31", every=5)
    with_outcome = [r for r in records if r.get("return_20d") is not None]
    assert with_outcome, "先の値動きが一件も測れていない"
    for record in with_outcome:
        assert record["forward_bars"] > 0


def test_group_summary_marks_small_groups_as_unreliable():
    rows = [{"return_20d": 0.01, "excess_topix_20d": 0.01} for _ in range(5)]
    stats = sb.summarise_group("tiny", rows)
    assert stats.samples == 5
    assert stats.reliable is False


def test_comparison_says_insufficient_data_rather_than_guessing():
    records = [
        {"primary_state": states.STATE_ABSORPTION, "return_20d": 0.02,
         "excess_topix_20d": 0.02, "flags": []},
        {"primary_state": states.STATE_LOW_CONFLICT, "return_20d": -0.01,
         "excess_topix_20d": -0.01, "flags": []},
    ]
    result = sb.compare_states(records)
    assert result["questions"]["absorption_vs_low_conflict"]["verdict"] == "insufficient_data"


def test_comparison_reports_no_difference_when_there_is_none():
    records = (
        [{"primary_state": states.STATE_ABSORPTION, "return_20d": 0.01,
          "excess_topix_20d": 0.01, "flags": []} for _ in range(40)]
        + [{"primary_state": states.STATE_LOW_CONFLICT, "return_20d": 0.01,
            "excess_topix_20d": 0.01, "flags": []} for _ in range(40)]
    )
    verdict = sb.compare_states(records)["questions"]["absorption_vs_low_conflict"]
    assert verdict["verdict"] == "no_difference"
    assert verdict["difference"] == pytest.approx(0.0)


def test_flag_comparison_can_conclude_not_predictive():
    records = (
        [{"flags": ["reentry"], "return_20d": 0.0, "excess_topix_20d": 0.0,
          "primary_state": states.STATE_LOW_CONFLICT} for _ in range(40)]
        + [{"flags": [], "return_20d": 0.02, "excess_topix_20d": 0.02,
            "primary_state": states.STATE_LOW_CONFLICT} for _ in range(40)]
    )
    result = sb.compare_flags(records, ["reentry"])
    assert result["reentry"]["verdict"] == "not_predictive"


def test_report_always_states_its_point_in_time_limits():
    report = sb.evaluate_signals([], calendar=DAYS).as_dict()
    assert report["point_in_time_limits"], "制約を書かずに結論だけ出している"
    assert any("開示日" in line for line in report["point_in_time_limits"])


def test_quantile_edges_come_from_the_population_not_a_constant():
    small = sb.quantile_edges([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], buckets=5)
    large = sb.quantile_edges([100, 200, 300, 400, 500, 600, 700, 800, 900, 1000], buckets=5)
    assert small != large
    assert sb.decile_key(150, large) == "q1"
    assert sb.decile_key(950, large) == "q5"


def test_evaluate_produces_walk_forward_windows_not_shuffled_dates(tmp_path):
    core = _core(tmp_path)
    records = replay(core, start="2026-05-01", end="2026-07-31", every=1)
    report = sb.evaluate_signals(records, calendar=DAYS, train_days=30, test_days=15).as_dict()
    windows = report["windows"]
    if windows:
        starts = [w["test"][0] for w in windows]
        assert starts == sorted(starts), "窓が時間順になっていない"
        for window in windows:
            assert window["test"][0] <= window["test"][1]


def test_replay_gives_the_same_answer_chunked_or_not(tmp_path, monkeypatch):
    """足を区切って読んでも結果が変わらないこと。

    10 年ぶんを一度に読むと 10M 行が辞書で乗って落ちる（実際に落ちた）ので
    区切って読むが、区切り方で答えが変わるなら意味が無い。
    """

    import app.research.short_behavior_runner as runner

    core = _core(tmp_path)
    monkeypatch.setattr(runner, "CHUNK_EVALUATION_DAYS", 1000)
    whole = replay(core, start="2026-05-01", end="2026-07-31", every=5)
    monkeypatch.setattr(runner, "CHUNK_EVALUATION_DAYS", 2)
    chunked = replay(core, start="2026-05-01", end="2026-07-31", every=5)

    keys = ("canonical_code", "signal_date", "primary_state", "return_20d",
            "excess_topix_20d", "visible_short_ratio")
    assert [{k: r.get(k) for k in keys} for r in whole] == [
        {k: r.get(k) for k in keys} for r in chunked
    ]


def test_replay_keeps_enough_forward_bars_to_measure_outcomes(tmp_path, monkeypatch):
    """区間の末尾でも T+20 が測れること（先行足を切り落とさない）。"""

    import app.research.short_behavior_runner as runner

    core = _core(tmp_path)
    monkeypatch.setattr(runner, "CHUNK_EVALUATION_DAYS", 2)
    records = replay(core, start="2026-05-01", end="2026-06-30", every=5)
    measurable = [r for r in records if r.get("return_20d") is not None]
    assert measurable, "区間の切り方で先の値動きが測れなくなっている"
