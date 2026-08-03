"""機関空売り行動の歴史再生と検証コマンド。

    python -m app.research.short_behavior_runner --start 2025-07-01 --end 2026-07-31

各評価日について、**その日までに公開された情報だけ**でスナップショットを
組み直し、状態が変わった銘柄を信号として拾い、その後の値動きを測る。
足と指数は 1 回だけ読んで日付で切る（評価日ごとに読み直すと全市場 ×
評価日数のクエリになる）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.data_paths import get_data_paths
from app.repositories.core import CoreRepository
from app.services.short_monitor import pipeline, snapshot as snap
from app.services.short_monitor.states import STATE_NO_SIGNAL

from .outcomes import HORIZONS, compute_outcome
from .short_behavior import evaluate_signals

#: 足の読み込み窓。スナップショットが 252 日分位と 200 日線を要求する。
BAR_LOOKBACK = pipeline.BAR_LOOKBACK_TRADING_DAYS

#: 再生時に評価する銘柄を、直近この営業日数の中に公開イベントがあるものに絞る。
#:
#: 吸収の横断面分位に載るのは「圧力が ADV20 の 2% 以上」の銘柄だけで、それには
#: 20 営業日以内の建玉変化が要る。イベントが無い銘柄は分位の母集団にも入らず、
#: 状態も `no_signal` にしかならないので、母集団も信号も変わらない。
#: 全銘柄を毎回組み立てると 1 評価日あたり約 5 分（10 年で 10 時間）かかる。
EVENT_WINDOW_TRADING_DAYS = 30

#: 1 回の足読み込みでカバーする評価日数。大きいほどクエリは減るが、
#: 保持する足も増える。10 年ぶんを一度に読むと 10M 行が乗って落ちる。
CHUNK_EVALUATION_DAYS = 12


def _slice_until(series: Sequence[Mapping[str, Any]], day: str, lookback: int) -> list[dict[str, Any]]:
    out = [bar for bar in series if str(bar.get("trade_date") or "") <= day]
    return out[-lookback:]


def replay(
    repository: CoreRepository,
    *,
    start: str,
    end: str,
    every: int = 5,
    progress=None,
) -> list[dict[str, Any]]:
    """評価日ごとの信号 + その後の結果。"""

    calendar = repository.trading_days_between("2000-01-01", end)
    if not calendar:
        return []
    evaluation_days = [
        day for index, day in enumerate(calendar)
        if start <= day <= end and index % max(1, every) == 0
    ]
    if not evaluation_days:
        return []

    securities = {row["canonical_code"]: row for row in repository.list_securities()}
    events_all = pipeline._events_by_code(repository, published_through=end)

    records: list[dict[str, Any]] = []
    previous_states: dict[str, str] = {}
    # 足は **区切って** 読む。10 年ぶんを一度に持つと 10M 行が辞書で乗って
    # メモリを食い尽くす（実際にそれで落ちた）。各区間は
    # 「先頭 − 300 営業日」から「末尾 + 20 営業日」まで —— 前は指標の窓、
    # 後ろは結果を測るための先行足。
    bars: dict[str, list[dict[str, Any]]] = {}
    topix_series: list[Mapping[str, Any]] = []
    topix_closes: dict[str, Any] = {}
    loaded_through = ""
    for position, day in enumerate(evaluation_days):
        if day > loaded_through:
            chunk = [d for d in evaluation_days if d >= day][:CHUNK_EVALUATION_DAYS]
            first = calendar[max(0, calendar.index(chunk[0]) - BAR_LOOKBACK)]
            tail = calendar.index(chunk[-1])
            last = calendar[min(len(calendar) - 1, tail + max(HORIZONS) + 5)]
            bars = {
                code: [b for b in series if b["trade_date"] <= last]
                for code, series in repository.bars_matrix_since(first).items()
            }
            topix_series = [
                row for row in repository.index_series("0000", start_date=first)
                if row["trade_date"] <= last
            ]
            topix_closes = {row["trade_date"]: row.get("close") for row in topix_series}
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
        )
        rows = snap.build_snapshots(stocks, market)
        signals = snap.build_signals(rows, previous_states, source_cutoff=day)
        previous_states = {
            str(row["canonical_code"]): str(row["primary_state"]) for row in rows
        }
        by_code = {str(row["canonical_code"]): row for row in rows}

        for signal in signals:
            code = signal["canonical_code"]
            row = by_code.get(code) or {}
            outcome = compute_outcome(
                canonical_code=code,
                signal_date=day,
                bars=bars.get(code, []),
                signal_close=row.get("close"),
                topix_bars=topix_series,
            )
            security = securities.get(code) or {}
            records.append({
                "canonical_code": code,
                "signal_date": day,
                "source_cutoff": signal["source_cutoff"],
                "primary_state": signal["primary_state"],
                "previous_state": signal.get("previous_state"),
                "behavior_score": signal.get("behavior_score"),
                "flags": json.loads(row.get("flags_json") or "[]"),
                "market_code": security.get("market_code"),
                "sector33_code": security.get("sector33_code"),
                "adv20_value": row.get("adv20_value"),
                "visible_short_ratio": row.get("visible_short_ratio"),
                "pressure_adv20_20d": row.get("pressure_adv20_20d"),
                "visible_days_to_cover": row.get("visible_days_to_cover"),
                "visible_institution_count": row.get("visible_institution_count"),
                "data_confidence": row.get("data_confidence"),
                **outcome.as_dict(),
            })
        if progress and position % 10 == 0:
            progress(f"{day}: {len(records)} signals so far ({position + 1}/{len(evaluation_days)})")
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="app.research.short_behavior_runner",
        description="機関空売り行動の走步検証",
    )
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--every", type=int, default=5)
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

    records = replay(
        repository, start=args.start, end=args.end, every=args.every,
        progress=lambda message: print(message, flush=True),
    )
    calendar = repository.trading_days_between(args.start, args.end)
    report = evaluate_signals(
        records, calendar=calendar, train_days=args.train_days, test_days=args.test_days,
    ).as_dict()

    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print()
    print(f"=== 機関空売り行動 走步検証 ({report['version']}) ===")
    print(f"信号 {report['signals']} 件 / 評価可 {report['evaluated']} 件 / 窓 {len(report['windows'])} 個")
    print()
    for state, stats in sorted(
        report["states"]["by_state"].items(), key=lambda item: -(item[1]["samples"])
    ):
        excess = stats.get("median_excess_topix_20d")
        shown = f"{excess:+.4f}" if excess is not None else "   n/a "
        mark = "" if stats["reliable"] else "  (標本不足)"
        print(f"  {state:<20} n={stats['samples']:>6}  20日超過中位={shown}"
              f"  勝率={(stats['hit_rate_20d'] or 0) * 100:5.1f}%{mark}")
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
