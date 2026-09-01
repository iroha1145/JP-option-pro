"""機関空売り行動の歴史再生と検証コマンド。

    python -m app.research.short_behavior_runner --start 2017-01-01 --end 2026-06-30

各評価日について、**その日までに公開された情報だけ**でスナップショットを
組み直し、状態が変わった銘柄を信号として拾い、その後の値動きを測る。

第十三轮の監査対応で意味が 3 つ変わっている:

* **入場は翌営業日の始値**（既定）。空売り残高の公表は当日 16:00 締め ——
  公開日の終値では入れない。`--entry-basis next_close / signal_close` で
  比較用の基準も出せる。
* **状態は評価候補から外れても保持する**。以前は評価プールの入れ替わりで
  状態が消え、同じ状態への「再遷移」が偽の信号として数えられていた。
* **業種中位は全市場から計算する**。以前は「直近に公開イベントがある銘柄」
  の部分集合から取っていて、本番と別の業種基準になっていた。TOPIX 超過に
  加えて業種中位超過も、入場日に揃えた終値で計算する。

さらに、原案（低位 + 新規/再参入 + 抗跌 + 回補）に対応する **狭い条件の
コホート A〜D** を状態機とは独立に追跡する。広い `absorption` 状態の否定は
狭い組み合わせの否定を意味しない —— 別々に測る。E（+突破確認）はレーダーを
再生しないため測れない（正直にそう書く）。
"""

from __future__ import annotations

import argparse
import bisect
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.data_paths import get_data_paths
from app.repositories.core import CoreRepository
from app.services.radar.adjustment import adjust_series
from app.services.short_monitor import pipeline, snapshot as snap
from app.services.short_monitor.states import STATE_NO_SIGNAL

from .outcomes import HORIZONS, compute_outcome
from .short_behavior import evaluate_signals, summarise_group

#: 足の読み込み窓。スナップショットが 252 日分位と 200 日線を要求する。
BAR_LOOKBACK = pipeline.BAR_LOOKBACK_TRADING_DAYS

#: 再生時に評価する銘柄を、直近この営業日数の中に公開イベントがあるものに絞る。
#: 圧力の分位母集団にも信号にも寄与しない銘柄はスナップショットを組まないが、
#: **業種中位はこの絞り込みの外（全市場）から計算する**。
EVENT_WINDOW_TRADING_DAYS = 30

#: 1 回の足読み込みでカバーする評価日数。10 年ぶんを一度に読むと 10M 行が
#: 乗って落ちる。逐日再生（every=1）では 12 日刻みだと読み込みが 200 回を
#: 超えるので広めに取る。
CHUNK_EVALUATION_DAYS = 12
CHUNK_EVALUATION_DAYS_DAILY = 40

#: コホート定義（原案の狭い条件を段階的に積む）。
#:   A: 公開空頭の増加（>= 2% ADV20）+ 20 日リターンが非負（増空不跌）
#:   B: A + 深い低位（252 日分位の下位 1/4）
#:   C: B + 20 日内に新規参入または再参入
#:   D: C + 公開回補が始まっている（5 日の逐機関差がマイナス）
#:   E: D + 技術的突破確認 —— レーダーを再生しないため **測れない**。
COHORT_KEYS = ("cohort_a", "cohort_b", "cohort_c", "cohort_d")


def _slice_until(series: Sequence[Mapping[str, Any]], day: str, lookback: int) -> list[dict[str, Any]]:
    out = [bar for bar in series if str(bar.get("trade_date") or "") <= day]
    return out[-lookback:]


class _CloseIndex:
    """code → (dates[], adjusted closes[]) の索引。日付でのルックアップ専用。"""

    def __init__(self, bars: Mapping[str, Sequence[Mapping[str, Any]]]):
        self.dates: dict[str, list[str]] = {}
        self.closes: dict[str, list[float]] = {}
        for code, series in bars.items():
            dates: list[str] = []
            closes: list[float] = []
            # 一括 CSV は adj_close が無く adjustment_factor だけ。生値のままだと
            # 分割が業種中位・コホート判定に −50% / +900% として混ざる。
            for bar in adjust_series(series):
                value = bar.get("close")
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    continue
                if number != number or number <= 0:
                    continue
                dates.append(str(bar["trade_date"]))
                closes.append(number)
            if dates:
                self.dates[code] = dates
                self.closes[code] = closes

    def at(self, code: str, day: str) -> float | None:
        dates = self.dates.get(code)
        if not dates:
            return None
        index = bisect.bisect_right(dates, day) - 1
        if index < 0:
            return None
        return self.closes[code][index]

    def ret(self, code: str, start: str, end: str) -> float | None:
        a = self.at(code, start)
        b = self.at(code, end)
        if a is None or b is None or a <= 0:
            return None
        return b / a - 1.0

    def ret_window(self, code: str, day: str, back: int) -> float | None:
        """day から back 営業日前（その銘柄の足基準）に対するリターン。"""

        dates = self.dates.get(code)
        if not dates:
            return None
        index = bisect.bisect_right(dates, day) - 1
        if index < 0 or index - back < 0:
            return None
        a = self.closes[code][index - back]
        b = self.closes[code][index]
        if a <= 0:
            return None
        return b / a - 1.0


def _sector_median_map(
    index: _CloseIndex, sectors: Mapping[str, str], day: str, back: int
) -> dict[str, float]:
    """その評価日の {業種: 中位リターン}。**全市場** から計算する。"""

    buckets: dict[str, list[float]] = {}
    for code, sector in sectors.items():
        value = index.ret_window(code, day, back)
        if value is None:
            continue
        buckets.setdefault(sector, []).append(value)
    out: dict[str, float] = {}
    for sector, values in buckets.items():
        if len(values) < 3:
            continue
        values.sort()
        middle = len(values) // 2
        out[sector] = values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2.0
    return out


def _sector_forward_median(
    cache: dict[tuple[str, str, str], float | None],
    index: _CloseIndex,
    members: Mapping[str, list[str]],
    sector: str | None,
    entry: str,
    end: str,
) -> float | None:
    """業種メンバーの entry→end 中位リターン（前向き・入場日に揃える）。"""

    if not sector or not entry or not end:
        return None
    key = (sector, entry, end)
    if key in cache:
        return cache[key]
    values: list[float] = []
    for code in members.get(sector, ()):  # メンバーは全市場から
        value = index.ret(code, entry, end)
        if value is not None:
            values.append(value)
    if len(values) < 3:
        cache[key] = None
        return None
    values.sort()
    middle = len(values) // 2
    result = values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2.0
    cache[key] = result
    return result


def _cohorts_of(row: Mapping[str, Any], return_20d: float | None) -> set[str]:
    def _f(key: str) -> float | None:
        value = row.get(key)
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if number == number else None

    out: set[str] = set()
    pressure = _f("pressure_adv20_20d")
    if pressure is None or pressure < 0.02 or return_20d is None or return_20d < 0.0:
        return out
    out.add("cohort_a")
    percentile = _f("price_percentile_252")
    if percentile is None or percentile > 0.25:
        return out
    out.add("cohort_b")
    entries = int(row.get("entry_count_20d") or 0) + int(row.get("reentry_count_20d") or 0)
    if entries < 1:
        return out
    out.add("cohort_c")
    covering_5 = _f("shares_change_5d")
    if covering_5 is None or covering_5 >= 0.0:
        return out
    out.add("cohort_d")
    return out


def replay(
    repository: CoreRepository,
    *,
    start: str,
    end: str,
    every: int = 1,
    entry_basis: str = "next_open",
    progress=None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """評価日ごとの (状態変化信号 + 結果, コホート入り信号 + 結果)。"""

    calendar = repository.trading_days_between("2000-01-01", end)
    if not calendar:
        return [], []
    evaluation_days = [
        day for index, day in enumerate(calendar)
        if start <= day <= end and index % max(1, every) == 0
    ]
    if not evaluation_days:
        return [], []

    securities = {row["canonical_code"]: row for row in repository.list_securities()}
    sectors = {
        code: str(row.get("sector33_code") or "")
        for code, row in securities.items()
        if row.get("sector33_code")
    }
    sector_members: dict[str, list[str]] = {}
    for code, sector in sectors.items():
        sector_members.setdefault(sector, []).append(code)
    events_all = pipeline._events_by_code(repository, published_through=end)

    records: list[dict[str, Any]] = []
    cohort_records: list[dict[str, Any]] = []
    # 状態は **プールから外れても保持** する。評価のたびに上書きすると、
    # 一時的にプールを離れた銘柄の状態が消え、戻ってきたときに同じ状態への
    # 「再遷移」が新しい信号として数えられる（監査指摘）。
    previous_states: dict[str, str] = {}
    previous_cohorts: dict[str, set[str]] = {}

    chunk_days = CHUNK_EVALUATION_DAYS_DAILY if every <= 2 else CHUNK_EVALUATION_DAYS
    bars: dict[str, list[dict[str, Any]]] = {}
    close_index = _CloseIndex({})
    topix_series: list[Mapping[str, Any]] = []
    topix_closes: dict[str, Any] = {}
    topix_dates: list[str] = []
    topix_values: list[float] = []
    sector_cache: dict[tuple[str, str, str], float | None] = {}
    loaded_through = ""

    def topix_ret(entry: str, end_day: str) -> float | None:
        if not topix_dates:
            return None
        a_index = bisect.bisect_right(topix_dates, entry) - 1
        b_index = bisect.bisect_right(topix_dates, end_day) - 1
        if a_index < 0 or b_index < 0:
            return None
        a, b = topix_values[a_index], topix_values[b_index]
        return (b / a - 1.0) if a > 0 else None

    for position, day in enumerate(evaluation_days):
        if day > loaded_through:
            chunk = [d for d in evaluation_days if d >= day][:chunk_days]
            first = calendar[max(0, calendar.index(chunk[0]) - BAR_LOOKBACK)]
            tail = calendar.index(chunk[-1])
            last = calendar[min(len(calendar) - 1, tail + max(HORIZONS) + 5)]
            bars = {
                code: [b for b in series if b["trade_date"] <= last]
                for code, series in repository.bars_matrix_since(first).items()
            }
            close_index = _CloseIndex(bars)
            sector_cache = {}
            topix_series = [
                row for row in repository.index_series("0000", start_date=first)
                if row["trade_date"] <= last
            ]
            topix_closes = {row["trade_date"]: row.get("close") for row in topix_series}
            topix_dates = []
            topix_values = []
            for row in topix_series:
                try:
                    value = float(row.get("close"))
                except (TypeError, ValueError):
                    continue
                if value > 0:
                    topix_dates.append(str(row["trade_date"]))
                    topix_values.append(value)
            loaded_through = chunk[-1]
            if progress:
                progress(f"bars loaded {first}..{last} for {len(chunk)} evaluation days")

        window = [d for d in calendar if d <= day][-BAR_LOOKBACK:]
        event_floor = window[-EVENT_WINDOW_TRADING_DAYS] if len(window) > EVENT_WINDOW_TRADING_DAYS else window[0]
        stocks: list[snap.StockInputs] = []
        for code, series in bars.items():
            # 公開日で切る。仓位日で切ると未来の情報が入る。
            code_events = [
                event for event in events_all.get(code, [])
                if str(event.get("published_date") or "") <= day
            ]
            if not code_events:
                continue
            # 直近に動きが無い銘柄は分位の母集団にも信号にも寄与しない。
            if str(code_events[-1].get("effective_trade_date") or "") < event_floor:
                continue
            trimmed = _slice_until(series, day, BAR_LOOKBACK)
            if len(trimmed) < 60:
                continue
            security = securities.get(code) or {}
            stocks.append(snap.StockInputs(
                canonical_code=code, bars=trimmed, events=code_events,
                sector33_code=security.get("sector33_code"),
            ))

        market = snap.MarketInputs(
            as_of_date=day, trading_days=window, topix_closes=topix_closes,
            # 過去に遡って同じ密度のニュースは取れない。無いものは無いと扱う。
            has_news_feed=False,
            # 業種中位は全市場から。評価プールの部分集合から取ると本番と
            # 別の業種基準になる（監査指摘）。
            sector_median_5d=_sector_median_map(close_index, sectors, day, 5),
            sector_median_20d=_sector_median_map(close_index, sectors, day, 20),
        )
        rows = snap.build_snapshots(stocks, market)
        signals = snap.build_signals(rows, previous_states, source_cutoff=day)
        previous_states.update({
            str(row["canonical_code"]): str(row["primary_state"]) for row in rows
        })
        by_code = {str(row["canonical_code"]): row for row in rows}

        def build_record(code: str, row: Mapping[str, Any], label: str, previous: str | None):
            outcome = compute_outcome(
                canonical_code=code,
                signal_date=day,
                bars=bars.get(code, []),
                signal_close=None if entry_basis != "signal_close" else row.get("close"),
                topix_bars=topix_series if entry_basis == "signal_close" else None,
                entry_basis=entry_basis,
            )
            record = {
                "canonical_code": code,
                "signal_date": day,
                "source_cutoff": day,
                "primary_state": label,
                "previous_state": previous,
                "behavior_score": row.get("behavior_score"),
                "flags": json.loads(row.get("flags_json") or "[]"),
                "market_code": (securities.get(code) or {}).get("market_code"),
                "sector33_code": (securities.get(code) or {}).get("sector33_code"),
                "adv20_value": row.get("adv20_value"),
                "visible_short_ratio": row.get("visible_short_ratio"),
                "reported_in_scope_ratio": row.get("reported_in_scope_ratio"),
                "pressure_adv20_20d": row.get("pressure_adv20_20d"),
                "shares_change_5d": row.get("shares_change_5d"),
                "visible_days_to_cover": row.get("visible_days_to_cover"),
                "visible_institution_count": row.get("visible_institution_count"),
                "data_confidence": row.get("data_confidence"),
                **outcome.as_dict(),
            }
            # next 基準では超過を **入場日に揃えた終値** で計算し直す。
            if entry_basis != "signal_close":
                entry_date = record.get("entry_date")
                sector = record.get("sector33_code")
                stock_dates = close_index.dates.get(code) or []
                if entry_date:
                    entry_pos = bisect.bisect_right(stock_dates, str(entry_date)) - 1
                    for horizon in HORIZONS:
                        own = record.get(f"return_{horizon}d")
                        if own is None or entry_pos < 0:
                            continue
                        end_pos = entry_pos + horizon
                        if end_pos >= len(stock_dates):
                            continue
                        end_date = stock_dates[end_pos]
                        bench = topix_ret(str(entry_date), end_date)
                        record[f"excess_topix_{horizon}d"] = (
                            own - bench if bench is not None else None
                        )
                        sector_bench = _sector_forward_median(
                            sector_cache, close_index, sector_members,
                            str(sector or ""), str(entry_date), end_date,
                        )
                        record[f"excess_sector_{horizon}d"] = (
                            own - sector_bench if sector_bench is not None else None
                        )
            return record

        for signal in signals:
            code = signal["canonical_code"]
            row = by_code.get(code) or {}
            records.append(build_record(
                code, row, signal["primary_state"], signal.get("previous_state"),
            ))

        # コホート: 条件が **偽→真に変わった日** だけを 1 信号として数える。
        # 毎日メンバー全員を数えると、同じ建玉が保有期間の日数だけ重複する。
        for code, row in by_code.items():
            return_20d = close_index.ret_window(code, day, 20)
            current = _cohorts_of(row, return_20d)
            before = previous_cohorts.get(code, set())
            fresh = current - before
            previous_cohorts[code] = current
            for cohort in fresh:
                cohort_records.append(build_record(code, row, cohort, None))
        # プール外の銘柄のコホート状態は保持（状態と同じ理由）。

        if progress and position % 20 == 0:
            progress(
                f"{day}: {len(records)} signals / {len(cohort_records)} cohort entries "
                f"({position + 1}/{len(evaluation_days)})"
            )
    return records, cohort_records


def _apply_slippage(records: list[dict[str, Any]], bps: float) -> None:
    """入場側の片道コストを引く。中位・勝率はこの後で計算される。"""

    if bps <= 0:
        return
    cost = bps / 10_000.0
    for record in records:
        for horizon in HORIZONS:
            for key in (f"return_{horizon}d", f"excess_topix_{horizon}d", f"excess_sector_{horizon}d"):
                value = record.get(key)
                if value is not None:
                    record[key] = value - cost


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="app.research.short_behavior_runner",
        description="機関空売り行動の走步検証",
    )
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--every", type=int, default=1)
    parser.add_argument(
        "--entry-basis", default="next_open",
        choices=("next_open", "next_close", "signal_close"),
        help="入場基準。既定は翌営業日の始値（公表は当日引け後なので当日終値では入れない）",
    )
    parser.add_argument("--slippage-bps", type=float, default=0.0)
    parser.add_argument("--train-days", type=int, default=250)
    parser.add_argument("--test-days", type=int, default=125)
    parser.add_argument("--core-db", default=None)
    parser.add_argument("--out", default=None, help="レポートの書き出し先 JSON")
    args = parser.parse_args(argv)

    paths = get_data_paths()
    repository = CoreRepository(Path(args.core_db) if args.core_db else paths.core_db)
    if not repository.exists():
        print("コア DB がありません", file=sys.stderr)
        return 2

    records, cohort_records = replay(
        repository, start=args.start, end=args.end, every=args.every,
        entry_basis=args.entry_basis,
        progress=lambda message: print(message, flush=True),
    )
    _apply_slippage(records, args.slippage_bps)
    _apply_slippage(cohort_records, args.slippage_bps)

    calendar = repository.trading_days_between(args.start, args.end)
    report = evaluate_signals(
        records, calendar=calendar, train_days=args.train_days, test_days=args.test_days,
    ).as_dict()
    report["entry_basis"] = args.entry_basis
    report["slippage_bps"] = args.slippage_bps
    report["cohorts"] = {
        key: summarise_group(key, [r for r in cohort_records if r["primary_state"] == key]).as_dict()
        for key in COHORT_KEYS
    }
    report["cohort_definitions"] = {
        "cohort_a": "公開空頭の増加(>=2% ADV20) + 20日リターン非負",
        "cohort_b": "A + 深い低位（252日分位の下位1/4）",
        "cohort_c": "B + 20日内の新規参入/再参入",
        "cohort_d": "C + 公開回補の開始（5日の逐機関差 < 0）",
        "cohort_e": "D + 技術的突破確認 —— レーダー未再生のため測定不能",
    }

    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print()
    print(f"=== 機関空売り行動 走步検証 ({report['version']}) ===")
    print(f"入場基準 {args.entry_basis} / 片道コスト {args.slippage_bps}bp / every={args.every}")
    print(f"信号 {report['signals']} 件 / 評価可 {report['evaluated']} 件 / 窓 {len(report['windows'])} 個")
    print()
    for state, stats in sorted(
        report["states"]["by_state"].items(), key=lambda item: -(item[1]["samples"])
    ):
        excess = stats.get("median_excess_topix_20d")
        shown = f"{excess:+.4f}" if excess is not None else "   n/a "
        sector_excess = stats.get("median_excess_sector_20d")
        sector_shown = f"{sector_excess:+.4f}" if sector_excess is not None else "   n/a "
        mark = "" if stats["reliable"] else "  (標本不足)"
        print(f"  {state:<20} n={stats['samples']:>6}  20日超過中位={shown}"
              f"  対業種={sector_shown}  勝率={(stats['hit_rate_20d'] or 0) * 100:5.1f}%{mark}")
    print()
    print("  --- 狭い条件のコホート（原案の段階） ---")
    for key in COHORT_KEYS:
        stats = report["cohorts"][key]
        excess = stats.get("median_excess_topix_20d")
        shown = f"{excess:+.4f}" if excess is not None else "   n/a "
        mark = "" if stats["reliable"] else "  (標本不足)"
        print(f"  {key:<20} n={stats['samples']:>6}  20日超過中位={shown}"
              f"  勝率={(stats['hit_rate_20d'] or 0) * 100:5.1f}%{mark}")
    print("  cohort_e             測定不能（レーダー未再生）")
    print()
    for name, comparison in report["states"]["questions"].items():
        print(f"  {name:<36} {comparison['verdict']:<18} "
              f"差={comparison['difference'] if comparison['difference'] is not None else 'n/a'}")
    print()
    print("点時の制約:")
    for limit in report["point_in_time_limits"]:
        print(f"  - {limit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
