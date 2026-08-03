"""回測基盤: 先読み禁止・営業日窓・冪等性・単調性判定。

ここで一番大事なのは **先読みが入っていないこと**。入っていても結果は
「良く」なるだけで例外は出ないので、テストが唯一の防波堤になる。
"""

from __future__ import annotations

import pathlib

import pytest

from app.repositories.core import CoreRepository
from app.research.outcomes import HORIZONS, compute_outcome, forward_bars
from app.research.replay import bars_up_to, replay_security, sample_dates
from app.research.runner import ResearchStore, RunParams, run_backtest
from app.research.walk_forward import (
    BUCKET_LABELS,
    BucketStats,
    bucket_of,
    check_monotonic,
    evaluate_window,
    summarise_buckets,
    summarise_run,
    walk_forward_windows,
)


def _bar(date, price, *, high=None, low=None, turnover=8e8):
    return {
        "trade_date": date, "open": price, "high": high or price * 1.01,
        "low": low or price * 0.99, "close": price,
        "adj_open": price, "adj_high": high or price * 1.01,
        "adj_low": low or price * 0.99, "adj_close": price,
        "turnover_value": turnover, "volume": turnover / price, "upper_limit": 0,
    }


def _dates(count, *, start_month=1):
    return [
        f"2026-{(i // 28) + start_month:02d}-{(i % 28) + 1:02d}"
        for i in range(count)
    ]


# ---------------------------------------------------------------------------
# 1. 先読み禁止
# ---------------------------------------------------------------------------


def test_outcome_never_includes_the_signal_day_itself():
    """シグナル日の値動きが「その後の成績」に混ざらないこと。"""

    dates = _dates(10)
    bars = [_bar(date, 100.0 + index) for index, date in enumerate(dates)]
    ahead = forward_bars(bars, dates[3], 5)

    assert [bar.trade_date for bar in ahead] == dates[4:9]
    assert all(bar.trade_date > dates[3] for bar in ahead)


def test_bars_up_to_is_inclusive_of_the_as_of_day_only():
    dates = _dates(10)
    bars = [_bar(date, 100.0) for date in dates]
    window = bars_up_to(bars, dates[4])
    assert [row["trade_date"] for row in window] == dates[:5]


def test_replay_refuses_a_day_the_security_did_not_trade():
    """休場・売買停止の日に「その日の断面」を作らない（前日で代用しない）。"""

    dates = _dates(200)
    bars = [_bar(date, 100.0 + index * 0.1) for index, date in enumerate(dates)]
    assert replay_security("70130", bars, "2026-12-31", min_data_days=30) is None


def test_replay_result_is_identical_when_future_bars_are_appended():
    """未来のバーを足しても過去の評価が変わらない = 先読みしていない。

    これが崩れると、履歴が更新されるたびに過去のスコアが静かに書き換わり、
    「あの日そう見えていた」という記録が意味を失う。
    """

    dates = _dates(220)
    bars = [_bar(date, 100.0 + index * 0.15) for index, date in enumerate(dates)]
    as_of = dates[150]

    without_future = replay_security("70130", bars[:151], as_of, min_data_days=30)
    with_future = replay_security("70130", bars, as_of, min_data_days=30)

    assert without_future is not None and with_future is not None
    assert without_future.intrinsic["score"] == with_future.intrinsic["score"]
    assert without_future.features["close"] == with_future.features["close"]
    assert without_future.features["prior_high_60"] == with_future.features["prior_high_60"]


def test_evaluation_dates_leave_room_for_the_outcome_window():
    """末尾を評価日にすると、結果窓が埋まらないシグナルが混ざる。"""

    days = _dates(100)
    sampled = sample_dates(days, every=5, skip_last=20)
    assert sampled, "評価日が空"
    assert max(sampled) <= days[-21]


# ---------------------------------------------------------------------------
# 2. 営業日で数える
# ---------------------------------------------------------------------------


def test_horizons_count_trading_bars_not_calendar_days():
    """カレンダーに穴（連休）があっても N は N 本のバーであること。"""

    dates = ["2026-04-27", "2026-04-28", "2026-05-07", "2026-05-08", "2026-05-11"]
    bars = [_bar(date, 100.0 * (1.1 ** index)) for index, date in enumerate(dates)]
    ahead = forward_bars(bars, dates[0], 3)
    assert [bar.trade_date for bar in ahead] == dates[1:4]  # 暦では 11 日空くが 3 本


def test_returns_are_measured_from_the_signal_close():
    dates = _dates(30)
    prices = [100.0] * 30
    prices[5] = 100.0
    for index in range(6, 30):
        prices[index] = 110.0
    bars = [_bar(date, prices[index]) for index, date in enumerate(dates)]

    outcome = compute_outcome(
        canonical_code="70130", signal_date=dates[5], bars=bars, signal_close=100.0
    )
    assert outcome.returns[1] == pytest.approx(0.10)
    assert outcome.returns[20] == pytest.approx(0.10)
    assert outcome.entry_reference_close == 100.0


def test_truncated_window_is_flagged_not_silently_short():
    dates = _dates(10)
    bars = [_bar(date, 100.0) for date in dates]
    outcome = compute_outcome(canonical_code="70130", signal_date=dates[5], bars=bars)
    assert outcome.truncated is True
    assert outcome.returns[20] is None       # 20 日分は無い → None（0 ではない）
    assert outcome.returns[1] is not None


# ---------------------------------------------------------------------------
# 3. MFE / MAE / 1R
# ---------------------------------------------------------------------------


def test_mfe_and_mae_use_highs_and_lows_not_closes():
    dates = _dates(8)
    bars = [_bar(dates[0], 100.0)]
    bars.append(_bar(dates[1], 100.0, high=130.0, low=80.0))   # 終値は動かないが振れた
    for date in dates[2:]:
        bars.append(_bar(date, 100.0))

    outcome = compute_outcome(
        canonical_code="70130", signal_date=dates[0], bars=bars, signal_close=100.0
    )
    assert outcome.mfe_pct == pytest.approx(30.0, abs=1.5)
    assert outcome.mae_pct == pytest.approx(-20.0, abs=1.5)


def test_same_day_touch_of_both_levels_resolves_to_the_stop():
    """日足では順序が分からない。楽観側（target）に倒さない。"""

    dates = _dates(6)
    bars = [_bar(dates[0], 100.0)]
    bars.append(_bar(dates[1], 100.0, high=120.0, low=80.0))   # +1R も -1R も触れる
    for date in dates[2:]:
        bars.append(_bar(date, 100.0))

    outcome = compute_outcome(
        canonical_code="70130", signal_date=dates[0], bars=bars,
        signal_close=100.0, stop_price=90.0,
    )
    assert outcome.hit_r_multiple == "stop"


# ---------------------------------------------------------------------------
# 4. 走步検証の窓
# ---------------------------------------------------------------------------


def test_train_and_test_windows_never_overlap():
    days = _dates(300)
    windows = walk_forward_windows(days, train_days=100, test_days=50)
    assert windows
    for train_start, train_end, test_start, test_end in windows:
        assert train_start < train_end < test_start < test_end, (
            "訓練と検証の期間が重なっている"
        )


def test_windows_roll_forward_in_time():
    days = _dates(300)
    windows = walk_forward_windows(days, train_days=100, test_days=50)
    starts = [window[0] for window in windows]
    assert starts == sorted(starts)
    assert len(set(starts)) == len(starts)


def test_evaluate_window_only_uses_signals_inside_the_test_range():
    records = [
        {"signal_date": "2026-01-10", "score": 95.0, "return_20d": 0.5,
         "excess_topix_20d": 0.5},
        {"signal_date": "2026-06-10", "score": 95.0, "return_20d": -0.5,
         "excess_topix_20d": -0.5},
    ]
    result = evaluate_window(
        records, ("2026-01-01", "2026-03-31", "2026-06-01", "2026-06-30"), horizon=20
    )
    assert result.samples == 1


# ---------------------------------------------------------------------------
# 5. 単調性の判定は誠実か
# ---------------------------------------------------------------------------


def test_bucket_boundaries():
    assert bucket_of(95) == "90+"
    assert bucket_of(90) == "90+"
    assert bucket_of(89.9) == "80-89"
    assert bucket_of(0) == "<60"
    assert bucket_of(None) is None


def test_monotonicity_ignores_buckets_with_too_few_samples():
    """3 銘柄しかない層がたまたま強かったのを単調性の証拠にしない。"""

    buckets = [
        BucketStats("90+", samples=3, median_excess_topix=0.9, reliable=False),
        BucketStats("80-89", samples=500, median_excess_topix=0.01, reliable=True),
        BucketStats("70-79", samples=500, median_excess_topix=0.02, reliable=True),
        BucketStats("60-69", samples=500, median_excess_topix=0.03, reliable=True),
        BucketStats("<60", samples=500, median_excess_topix=0.04, reliable=True),
    ]
    monotonic, detail = check_monotonic(buckets)
    assert monotonic is False, "実際は逆順なのに単調と判定している"
    assert "90+" not in detail, "標本不足の層を判定に混ぜている"


def test_monotonicity_is_undecidable_without_enough_buckets():
    buckets = [
        BucketStats("90+", samples=5, median_excess_topix=0.9, reliable=False),
        BucketStats("80-89", samples=5, median_excess_topix=0.5, reliable=False),
    ]
    monotonic, detail = check_monotonic(buckets)
    assert monotonic is None
    assert "判定できない" in detail


def test_verdict_requires_stability_across_windows():
    from app.research.walk_forward import WindowResult

    def _window(monotonic):
        # 判定の主軸は分位（絶対点の閾値は日本株で校正されていない）
        return WindowResult(
            train_start="a", train_end="b", test_start="c", test_end="d",
            horizon=20, samples=100,
            monotonic=monotonic, decile_monotonic=monotonic,
        )

    assert summarise_run([_window(True)] * 5)["verdict"] == "monotonic"
    assert summarise_run([_window(True)] * 3 + [_window(False)] * 2)["verdict"] == "weak"
    assert summarise_run([_window(False)] * 5)["verdict"] == "not_monotonic"
    assert summarise_run([_window(None)] * 3)["verdict"] == "insufficient_data"


def test_summarise_buckets_keeps_underpowered_buckets_visible():
    """標本不足の層を黙って消すと「上位だけ綺麗」に見える。"""

    records = [
        {"score": 95.0, "return_20d": 0.1, "excess_topix_20d": 0.1} for _ in range(3)
    ]
    stats = summarise_buckets(records, horizon=20)
    labels = [bucket.label for bucket in stats]
    assert labels == list(BUCKET_LABELS)
    top = next(bucket for bucket in stats if bucket.label == "90+")
    assert top.samples == 3 and top.reliable is False


# ---------------------------------------------------------------------------
# 6. 実行の冪等性と再開
# ---------------------------------------------------------------------------


def _seed_repo(tmp_path, *, days=320, codes=("70130", "80130", "90130")):
    repo = CoreRepository(tmp_path / "core.db")
    repo.initialize()
    dates = _dates(days)
    for offset, code in enumerate(codes):
        repo.upsert_daily_bars([
            {**_bar(date, 100.0 + index * (0.1 + offset * 0.05)), "canonical_code": code}
            for index, date in enumerate(dates)
        ])
    repo.replace_security_master(
        [
            {"canonical_code": code, "name_ja": code, "market_code": "0111",
             "sector33_code": "3650", "sector33_name": "電気機器"}
            for code in codes
        ],
        as_of_date=dates[-1],
    )
    repo.upsert_trading_days([{"calendar_date": d, "holiday_division": "1"} for d in dates])
    repo.upsert_index_bars(
        [{"index_code": "0000", "trade_date": d, "close": 2700.0 + i}
         for i, d in enumerate(dates)]
    )
    return repo, dates


def test_run_is_idempotent_for_the_same_params(tmp_path):
    repo, dates = _seed_repo(tmp_path)
    store = ResearchStore(tmp_path / "research.db")
    params = RunParams(
        start_date=dates[200], end_date=dates[-1], every_n_trading_days=10,
        min_data_days=60, train_days=30, test_days=20, horizon=5,
    )

    first = run_backtest(repo, store, params)
    second = run_backtest(repo, store, params)

    assert first["run_id"] == second["run_id"], "同じ条件なのに別 run になっている"
    assert first["signals"] == second["signals"], "再実行で行が増えている"


def test_changing_the_score_version_produces_a_separate_run(tmp_path, monkeypatch):
    """スコア版を上げても過去の結果を上書きしないこと。"""

    repo, dates = _seed_repo(tmp_path)
    params = RunParams(
        start_date=dates[200], end_date=dates[-1], every_n_trading_days=10,
        min_data_days=60, train_days=30, test_days=20, horizon=5,
    )
    before = params.run_id()

    import app.research.runner as runner_module

    monkeypatch.setattr(runner_module, "SCORE_VERSION", "jp-score-vNEXT")
    after = params.run_id()
    assert before != after


def test_report_declares_its_point_in_time_limits(tmp_path):
    """無バイアスのふりをしない（制約を必ず添える）。"""

    repo, dates = _seed_repo(tmp_path)
    store = ResearchStore(tmp_path / "research.db")
    report = run_backtest(
        repo, store,
        RunParams(start_date=dates[200], end_date=dates[-1], every_n_trading_days=10,
                  min_data_days=60, train_days=30, test_days=20, horizon=5),
    )
    assert report["point_in_time_limits"], "点時の制約が報告されていない"
    assert any("業種" in limit or "sector" in limit for limit in report["point_in_time_limits"])
    assert report["summary"]["verdict"] in {
        "monotonic", "weak", "not_monotonic", "insufficient_data",
    }


# ---------------------------------------------------------------------------
# 7. 分位バケット（絶対閾値に頼らない順位付け能力の判定）
# ---------------------------------------------------------------------------


def test_deciles_are_cut_per_evaluation_date():
    """全期間まとめて切らないこと。

    まとめて切ると相場が強かった年の銘柄が丸ごと上位に入り、「スコアが
    効いた」のか「その年が良かった」のかを分離できない。
    """

    from app.research.walk_forward import DECILE_LABELS, assign_deciles

    # 日Aは全体的に低スコア、日Bは全体的に高スコア。日ごとに切れば
    # それぞれの日の最上位が D1 になる。
    day_a = [{"signal_date": "2026-01-05", "score": 10.0 + i} for i in range(20)]
    day_b = [{"signal_date": "2026-02-05", "score": 70.0 + i} for i in range(20)]
    labels = assign_deciles(day_a + day_b)

    top_a = max(day_a, key=lambda r: r["score"])
    top_b = max(day_b, key=lambda r: r["score"])
    assert labels[id(top_a)] == DECILE_LABELS[0], "低スコアの日にも上位10%が要る"
    assert labels[id(top_b)] == DECILE_LABELS[0]


def test_a_thin_day_is_not_forced_into_deciles():
    from app.research.walk_forward import assign_deciles

    thin = [{"signal_date": "2026-01-05", "score": float(i)} for i in range(4)]
    assert assign_deciles(thin) == {}, "4 銘柄を十分位に割っている"


def test_decile_summary_orders_by_score_and_detects_ranking_power():
    from app.research.walk_forward import DECILE_LABELS, check_monotonic, summarise_deciles

    # スコアが高いほど超過リターンが高い、という理想的な断面を作る
    records = []
    for date in ("2026-01-05", "2026-01-12", "2026-01-19"):
        for i in range(200):
            score = 100.0 - i * 0.4
            records.append({
                "signal_date": date, "score": score,
                "return_20d": score / 1000.0,
                "excess_topix_20d": score / 1000.0,
            })
    deciles = summarise_deciles(records, horizon=20)
    assert deciles[0].label == DECILE_LABELS[0]
    assert deciles[0].median_excess_topix > deciles[-1].median_excess_topix
    monotonic, _detail = check_monotonic(deciles)
    assert monotonic is True


def test_top_bottom_spread_is_none_when_either_end_is_underpowered():
    from app.research.walk_forward import evaluate_window

    records = [
        {"signal_date": "2026-02-10", "score": 50.0 + i,
         "return_20d": 0.01, "excess_topix_20d": 0.01}
        for i in range(12)          # 十分位に割れない薄さ
    ]
    result = evaluate_window(
        records, ("2026-01-01", "2026-01-31", "2026-02-01", "2026-02-28"), horizon=20
    )
    assert result.top_bottom_spread is None


# ---------------------------------------------------------------------------
# 8. 研究 API は読むだけ（ページ表示が履歴計算を起動しない）
# ---------------------------------------------------------------------------


def test_research_api_never_triggers_a_computation(tmp_path, monkeypatch):
    """API から run を作れないこと。

    ページを開くたびに数時間の履歴計算が走る、という事故を構造的に防ぐ
    （doc §十一）。API モジュールは runner を import すらしない。
    """

    import app.api.research as research_api

    source = pathlib.Path(research_api.__file__).read_text(encoding="utf-8")
    assert "run_backtest" not in source, "API がバックテスト実行を参照している"
    assert "evaluate_run" not in source
    # 読み取り専用で開いていること
    assert "mode=ro" in source and "query_only" in source


def test_research_api_reports_missing_database_as_unavailable(tmp_path, monkeypatch):
    import app.api.research as research_api
    from fastapi import HTTPException

    monkeypatch.setattr(research_api, "_db_path", lambda: tmp_path / "absent.db")
    for call in (research_api.list_runs, research_api.get_report):
        try:
            call(20) if call is research_api.list_runs else call(None)
        except HTTPException as error:
            assert error.status_code == 503
        else:
            raise AssertionError("欠落を成功として返している")


def test_research_api_distinguishes_running_from_missing(tmp_path, monkeypatch):
    """走行中（レポート未確定）を 404 でも 200 でもなく 409 で返す。"""

    import app.api.research as research_api
    from fastapi import HTTPException

    store = ResearchStore(tmp_path / "research.db")
    store.initialize()
    params = RunParams(start_date="2026-01-01", end_date="2026-02-01")
    store.start_run(params.run_id(), params)          # 開始のみ、未完了

    monkeypatch.setattr(research_api, "_db_path", lambda: tmp_path / "research.db")
    runs = research_api.list_runs(limit=20)
    assert runs["runs"][0]["complete"] is False
    assert runs["runs"][0]["has_report"] is False
    try:
        research_api.get_report(run_id=params.run_id())
    except HTTPException as error:
        assert error.status_code == 409
    else:
        raise AssertionError("未完了のレポートを返している")
