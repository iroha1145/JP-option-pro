"""株式分割・併合が偽の突破や偽の暴落を作らないこと。

これが壊れていても例外は出ない。1:2 分割はただの −50% の日として、10:1 併合は
ただの +900% の日として、静かに指標へ混ざる。本番 10 年分では 2,600 件・
1,959 銘柄（全体の 36%）が該当したので、テストが唯一の防波堤になる。

数値は J-Quants の AdjC と突き合わせて確認したもの（銘柄 76780、2026-07-30 に
factor 0.5）。
"""

from __future__ import annotations

import pytest

from app.research.outcomes import compute_outcome, forward_bars
from app.services.radar.adjustment import (
    adjust_series,
    cumulative_factors,
    has_corporate_action,
)
from app.services.radar.features import clean_series, compute_features_from_series


def _bar(date, price, *, factor=1.0, volume=100_000.0):
    return {
        "trade_date": date, "open": price, "high": price * 1.01, "low": price * 0.99,
        "close": price, "adjustment_factor": factor,
        "turnover_value": price * volume, "volume": volume, "upper_limit": 0,
    }


def _dates(count):
    return [f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}" for i in range(count)]


# ---------------------------------------------------------------------------
# 1. 係数の規則（J-Quants の実データと一致すること）
# ---------------------------------------------------------------------------


def test_cumulative_factor_matches_jquants_adjusted_close():
    """銘柄 76780 の実データで検算。

        07-27 C=6280 → AdjC=3140
        07-28 C=6350 → AdjC=3175
        07-29 C=6330 → AdjC=3165
        07-30 C=3035 → AdjC=3035   (この日に factor 0.5)
        07-31 C=2990 → AdjC=2990
    """

    bars = [
        _bar("2026-07-27", 6280.0), _bar("2026-07-28", 6350.0),
        _bar("2026-07-29", 6330.0), _bar("2026-07-30", 3035.0, factor=0.5),
        _bar("2026-07-31", 2990.0),
    ]
    adjusted = adjust_series(bars)
    assert [round(row["close"], 1) for row in adjusted] == [
        3140.0, 3175.0, 3165.0, 3035.0, 2990.0
    ]


def test_the_latest_bar_is_never_rescaled():
    """直近の値は生値のまま。画面の現在値と約定可能価格の意味を変えない。"""

    bars = [_bar(d, 100.0) for d in _dates(5)]
    bars[2]["adjustment_factor"] = 0.5
    factors = cumulative_factors(bars)
    assert factors[-1] == 1.0
    assert adjust_series(bars)[-1]["close"] == 100.0


def test_factor_applies_only_to_bars_before_the_action():
    bars = [_bar(d, 100.0) for d in _dates(4)]
    bars[2]["adjustment_factor"] = 0.5
    factors = cumulative_factors(bars)
    assert factors == [0.5, 0.5, 1.0, 1.0]


def test_multiple_actions_compound():
    bars = [_bar(d, 100.0) for d in _dates(5)]
    bars[2]["adjustment_factor"] = 0.5
    bars[4]["adjustment_factor"] = 0.2
    factors = cumulative_factors(bars)
    assert factors[0] == pytest.approx(0.1)   # 0.5 × 0.2
    assert factors[3] == pytest.approx(0.2)
    assert factors[4] == 1.0


def test_absurd_factors_are_ignored_rather_than_applied():
    """1e-9 のような値は調整ではなくデータ異常。適用すると価格が壊れる。"""

    bars = [_bar(d, 100.0) for d in _dates(3)]
    bars[1]["adjustment_factor"] = 1e-9
    assert cumulative_factors(bars) == [1.0, 1.0, 1.0]


def test_missing_or_unparseable_factor_is_neutral():
    bars = [_bar(d, 100.0) for d in _dates(3)]
    bars[1]["adjustment_factor"] = None
    bars[2]["adjustment_factor"] = "x"
    assert cumulative_factors(bars) == [1.0, 1.0, 1.0]


# ---------------------------------------------------------------------------
# 2. 分割が偽の暴落・偽の突破を作らない
# ---------------------------------------------------------------------------


def test_a_two_for_one_split_is_not_a_fifty_percent_crash():
    """生値のままだと 1:2 分割は前日比 −50%。指標に入れてはいけない。"""

    dates = _dates(80)
    bars = [_bar(dates[i], 1000.0) for i in range(60)]
    bars += [_bar(dates[i], 500.0) for i in range(60, 80)]
    bars[60]["adjustment_factor"] = 0.5

    series = clean_series(bars)
    assert series is not None
    closes = series["closes"]
    worst = min(closes[i + 1] / closes[i] - 1.0 for i in range(len(closes) - 1))
    assert worst > -0.02, f"分割が {worst:.1%} の暴落として残っている"


def test_a_reverse_split_is_not_a_breakout():
    """10:1 併合は生値では +900%。52 週高値更新として検出されてはいけない。"""

    dates = _dates(80)
    bars = [_bar(dates[i], 100.0) for i in range(60)]
    bars += [_bar(dates[i], 1000.0) for i in range(60, 80)]
    bars[60]["adjustment_factor"] = 10.0

    features = compute_features_from_series(clean_series(bars))
    assert features is not None
    # 併合前の高値は調整後 1000 相当になるので、当日終値がそれを超えない
    assert features["close"] == pytest.approx(1000.0)
    assert features["prior_high_60"] == pytest.approx(1010.0, rel=0.02)
    assert features["return_20d"] == pytest.approx(0.0, abs=0.01), (
        "併合が 20 日リターンに残っている"
    )


def test_split_does_not_create_a_giant_drawdown_in_outcomes():
    """結果側でも同じ。分割が MAE −50% として記録されない。"""

    dates = _dates(30)
    bars = [_bar(dates[i], 1000.0) for i in range(10)]
    bars += [_bar(dates[i], 500.0) for i in range(10, 30)]
    bars[10]["adjustment_factor"] = 0.5

    outcome = compute_outcome(
        canonical_code="14140", signal_date=dates[5], bars=bars,
    )
    assert outcome.mae_pct is not None
    assert outcome.mae_pct > -5.0, f"分割が MAE {outcome.mae_pct:.1f}% を作っている"
    assert outcome.returns[20] == pytest.approx(0.0, abs=0.02)


def test_forward_bars_are_adjusted_on_the_same_basis_as_the_signal_day():
    dates = _dates(30)
    bars = [_bar(dates[i], 1000.0) for i in range(10)]
    bars += [_bar(dates[i], 500.0) for i in range(10, 30)]
    bars[10]["adjustment_factor"] = 0.5

    ahead = forward_bars(bars, dates[5], 5)
    # シグナル日(1000, 調整後 500)の後は全て 500 前後で連続していること
    assert all(bar.close == pytest.approx(500.0, rel=0.02) for bar in ahead)


def test_raw_signal_close_does_not_poison_split_adjusted_outcomes():
    """呼び出し側が生のシグナル日終値を渡しても、基準は調整後で取る。

    本番の runner は features.close（未調整）を signal_close に渡す。
    前向きバーだけ調整すると 1:2 分割が −50% リターンとして残る。
    """

    dates = _dates(30)
    bars = [_bar(dates[i], 1000.0) for i in range(10)]
    bars += [_bar(dates[i], 500.0) for i in range(10, 30)]
    bars[10]["adjustment_factor"] = 0.5

    outcome = compute_outcome(
        canonical_code="14140", signal_date=dates[5], bars=bars,
        signal_close=1000.0,
    )
    assert outcome.entry_reference_close == pytest.approx(500.0)
    assert outcome.returns[20] == pytest.approx(0.0, abs=0.02)
    assert outcome.mae_pct is not None
    assert outcome.mae_pct > -5.0, f"生の基準が MAE {outcome.mae_pct:.1f}% を作っている"


def test_close_index_applies_split_factor_when_adj_close_is_missing():
    """業種中位 / コホート用の終値索引も、一括 CSV の係数を使う。"""

    from app.research.short_behavior_runner import _CloseIndex

    dates = _dates(5)
    bars = [_bar(dates[i], 1000.0 if i < 3 else 500.0) for i in range(5)]
    bars[3]["adjustment_factor"] = 0.5
    index = _CloseIndex({"14140": bars})
    assert index.at("14140", dates[0]) == pytest.approx(500.0)
    assert index.at("14140", dates[3]) == pytest.approx(500.0)
    assert index.ret("14140", dates[0], dates[4]) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 3. 既に adj_* が入っている行はそのまま尊重する
# ---------------------------------------------------------------------------


def test_stored_adjusted_values_win_over_recomputation():
    """REST 経由で入った行は J-Quants 計算済み。二重に係数を掛けない。"""

    bars = [_bar(d, 100.0) for d in _dates(3)]
    bars[0].update(adj_close=42.0, adj_high=43.0, adj_low=41.0, adj_open=42.0)
    bars[2]["adjustment_factor"] = 0.5
    adjusted = adjust_series(bars)
    assert adjusted[0]["close"] == 42.0, "保存済みの調整値を上書きしている"


def test_has_corporate_action_detects_the_window():
    quiet = [_bar(d, 100.0) for d in _dates(5)]
    assert has_corporate_action(quiet) is False
    quiet[3]["adjustment_factor"] = 0.5
    assert has_corporate_action(quiet) is True


def test_volume_adjusts_inversely_and_turnover_is_untouched():
    bars = [_bar(d, 1000.0, volume=1000.0) for d in _dates(3)]
    bars[2]["adjustment_factor"] = 0.5
    adjusted = adjust_series(bars)
    # 価格が半分になる行では株数は倍
    assert adjusted[0]["close"] == pytest.approx(500.0)
    assert adjusted[0]["volume"] == pytest.approx(2000.0)
    # 売買代金は会社行動で変わらない
    assert adjusted[0]["turnover_value"] == bars[0]["turnover_value"]
