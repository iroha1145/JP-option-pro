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
    records, _cohorts = replay(core, start="2026-05-20", end="2026-07-31", every=1)
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
    records, _cohorts = replay(core, start="2026-06-01", end="2026-07-31", every=5)
    assert records
    for record in records:
        assert record["source_cutoff"] == record["signal_date"]


def test_replay_returns_forward_outcomes(tmp_path):
    core = _core(tmp_path)
    records, _cohorts = replay(core, start="2026-05-01", end="2026-07-31", every=5)
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
    records, _cohorts = replay(core, start="2026-05-01", end="2026-07-31", every=1)
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
    whole, _cohorts = replay(core, start="2026-05-01", end="2026-07-31", every=5)
    monkeypatch.setattr(runner, "CHUNK_EVALUATION_DAYS", 2)
    chunked, _cohorts = replay(core, start="2026-05-01", end="2026-07-31", every=5)

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
    records, _cohorts = replay(core, start="2026-05-01", end="2026-06-30", every=5)
    measurable = [r for r in records if r.get("return_20d") is not None]
    assert measurable, "区間の切り方で先の値動きが測れなくなっている"


def test_the_baseline_is_a_group_that_actually_exists():
    """比較の相手に `no_signal` は使えない。

    状態が変わった銘柄だけを信号にしているので `no_signal` は一件も出ない。
    最初そう書いていて、4 つの問いのうち 2 つが永久に `insufficient_data`
    だった。母集団全体を基準にする。
    """

    records = (
        [{"primary_state": states.STATE_COVERING_START, "return_20d": 0.03,
          "excess_topix_20d": 0.03, "flags": []} for _ in range(40)]
        + [{"primary_state": states.STATE_NORMAL_SHORTING, "return_20d": -0.02,
            "excess_topix_20d": -0.02, "flags": []} for _ in range(40)]
    )
    result = sb.compare_states(records)
    assert "(all signals)" in result["by_state"]
    assert result["by_state"]["(all signals)"]["samples"] == 80

    verdict = result["questions"]["covering_start_vs_all"]
    assert verdict["verdict"] == "left_better"


def test_a_state_that_never_fires_is_reported_as_insufficient_not_as_equal():
    records = [
        {"primary_state": states.STATE_COVERING_START, "return_20d": 0.01,
         "excess_topix_20d": 0.01, "flags": []} for _ in range(40)
    ]
    verdict = sb.compare_states(records)["questions"]["squeeze_vs_covering_start"]
    assert verdict["left_samples"] == 0
    assert verdict["verdict"] == "insufficient_data"


# -- 第十四轮: 配対基準 / 聚類 bootstrap / 拥挤度の窓別判定 / 信用残高の回放 ------

def test_replay_records_carry_peer_excess_and_priority(tmp_path):
    core = _core(tmp_path)
    records, _cohorts = replay(core, start="2026-06-25", end="2026-07-05", every=1)
    assert records, "信号が出ていない"
    record = records[0]
    assert "monitor_priority" in record
    assert "informed_institution_count" in record
    assert "parked_below_count" in record
    # 8 銘柄しか無い合成データでは五分位が組めない → 配対基準は None（黙って 0 にしない）
    assert record.get("excess_peer_20d") is None or isinstance(record["excess_peer_20d"], float)


def test_margin_map_as_of_never_uses_a_week_that_was_not_yet_published():
    from app.research.short_behavior_runner import _margin_map_as_of

    rows = [
        {"canonical_code": "10000", "application_date": "2026-06-05", "long_total": 100.0, "short_total": 10.0},
        {"canonical_code": "10000", "application_date": "2026-06-12", "long_total": 130.0, "short_total": 12.0},
    ]
    # 6/12 申込分は 6/16 に公表される。6/13 時点では 6/5 分しか知りえない。
    assert _margin_map_as_of(rows, "2026-06-13")["10000"]["long_total"] == 100.0
    later = _margin_map_as_of(rows, "2026-06-20")["10000"]
    assert later["long_total"] == 130.0 and later["long_change"] == 30.0
    assert _margin_map_as_of(rows, "2026-06-01") == {}


def test_liquidity_groups_are_market_times_quintile():
    from app.research.short_behavior_runner import _liquidity_groups

    days = [f"2026-06-{d:02d}" for d in range(1, 29)]
    bars = {}
    securities = {}
    for index in range(60):
        code = f"2{index:04d}"
        turnover = 1_000_000.0 * (index + 1)
        bars[code] = [{"trade_date": d, "turnover_value": turnover} for d in days]
        securities[code] = {"market_code": "0111" if index % 2 else "0112"}
    group_of, members = _liquidity_groups(bars, securities, as_of=days[-1])
    assert set(group_of) == set(bars)
    assert all(key.split("|")[0] in ("0111", "0112") for key in members)
    assert group_of["20000"].endswith("q1") and group_of["20059"].endswith("q5")


def test_bootstrap_ci_brackets_the_median_and_needs_enough_clusters():
    records = [
        {"canonical_code": f"1{i % 12:04d}", "signal_date": f"2026-0{1 + i % 6}-10", "excess_topix_20d": (i % 7 - 3) / 100.0}
        for i in range(120)
    ]
    low, high = sb.bootstrap_median_ci(records, "excess_topix_20d", resamples=50)
    assert low is not None and high is not None and low <= 0.0 <= high
    assert sb.bootstrap_median_ci(records[:10], "excess_topix_20d") == (None, None)


def test_crowding_stability_reports_the_gate_honestly():
    windows = [(f"2025-{m:02d}-01", f"2025-{m:02d}-10", f"2025-{m:02d}-11", f"2025-{m:02d}-28") for m in range(1, 13)]
    records = []
    for m in range(1, 13):
        for i in range(40):
            records.append({"canonical_code": f"3{i:04d}", "signal_date": f"2025-{m:02d}-15",
                            "visible_institution_count": 0, "excess_topix_20d": -0.01})
            records.append({"canonical_code": f"4{i:04d}", "signal_date": f"2025-{m:02d}-15",
                            "visible_institution_count": 5, "excess_topix_20d": -0.03})
    result = sb.crowding_stability(records, windows, holdout_start="2025-07-01")
    assert result["windows_judged"] == 12 and result["windows_negative"] == 12
    assert result["holdout_spread_4plus_minus_01"] < 0
    # 16 窓に届かないので pass とは言わない
    assert result["verdict"] == "insufficient_data"
    assert result["by_bucket"]["4+"]["samples"] == 480


def test_priority_ranking_power_uses_daily_deciles():
    windows = [("2025-01-01", "2025-01-10", "2025-01-11", "2025-01-31")]
    records = []
    for day in ("2025-01-15", "2025-01-20"):
        for i in range(40):
            records.append({"canonical_code": f"5{i:04d}", "signal_date": day,
                            "monitor_priority": float(i), "excess_topix_20d": i / 1000.0})
    result = sb.priority_ranking_power(records, windows)
    assert result["score_field"] == "monitor_priority"
    assert result["windows"][0]["samples"] == 80


def test_report_carries_the_new_sections(tmp_path):
    core = _core(tmp_path)
    records, _ = replay(core, start="2026-06-25", end="2026-07-05", every=1)
    calendar = core.trading_days_between("2026-06-25", "2026-07-05")
    report = sb.evaluate_signals(records, calendar=calendar, holdout_start="2026-07-01").as_dict()
    assert report["version"] == sb.SHORT_RESEARCH_VERSION
    assert set(report["crowding"]) == {"visible", "informed"}
    assert "priority_ranking" in report and "holdout" in report
