"""研究バッチの起動口。Web プロセスとは別に回す。

    python -m app.research --start 2017-01-01 --end 2026-06-30

進捗は stdout に出す。中断しても同じコマンドで再開する（日付チェックポイント）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.data_paths import get_data_paths
from app.repositories.core import CoreRepository

from .runner import ResearchStore, RunParams, evaluate_run, run_backtest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.research", description="日本株 走步検証")
    parser.add_argument("--start", required=True, help="評価開始日 YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="評価終了日 YYYY-MM-DD")
    parser.add_argument("--every", type=int, default=5, help="何営業日ごとに断面を取るか")
    parser.add_argument("--train-days", type=int, default=120)
    parser.add_argument("--test-days", type=int, default=60)
    parser.add_argument("--horizon", type=int, default=20, help="保有期間（営業日）")
    parser.add_argument("--min-turnover", type=float, default=100_000_000.0)
    parser.add_argument("--core-db", default=None)
    parser.add_argument("--research-db", default=None)
    parser.add_argument("--json", action="store_true", help="レポートを JSON で出す")
    parser.add_argument(
        "--run-id", default=None,
        help="評価だけやり直す対象の run（保有期間だけ変えて読み直すときに使う）",
    )
    parser.add_argument(
        "--report-only", action="store_true",
        help="断面は再計算せず、保存済みスナップショットだけで評価をやり直す",
    )
    args = parser.parse_args(argv)

    # パスは data_paths に一本化する（ここで独自に組み立てると、本番の
    # DATA_DIR 解決規則と食い違って別のファイルを掴む）。
    paths = get_data_paths()
    core_path = Path(args.core_db) if args.core_db else paths.core_db
    research_path = (
        Path(args.research_db) if args.research_db else paths.root / "jp-research.db"
    )
    repository = CoreRepository(core_path)
    if not repository.exists():
        print(f"コア DB がありません: {core_path}", file=sys.stderr)
        return 2

    params = RunParams(
        start_date=args.start, end_date=args.end, every_n_trading_days=args.every,
        train_days=args.train_days, test_days=args.test_days, horizon=args.horizon,
        min_avg_turnover_jpy=args.min_turnover,
    )
    store = ResearchStore(research_path)
    if args.report_only:
        store.initialize()
        # horizon / train_days / test_days は **評価だけ** のパラメータで、
        # 保存済みスナップショットには影響しない（結果は 1/3/5/10/20 日を
        # 全部持っている）。run_id はそれらも含めてハッシュしているので、
        # 保有期間を変えて読み直すときは対象 run を明示する。
        # 窓は **取引カレンダー** 上で切る。スナップショットの日付だけから
        # 作ると、10 営業日ごとに間引いた 218 日しか無いので
        # train 250 + test 125 が収まらず、窓が 0 個になる。
        calendar = repository.trading_days_between(args.start, args.end)
        report = evaluate_run(store, params, calendar=calendar, run_id=args.run_id)
    else:
        report = run_backtest(
            repository, store, params,
            progress=lambda message: print(message, flush=True),
        )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    summary = report["summary"]
    print()
    print(f"=== 走步検証 {report['run_id']} ===")
    print(f"評価日 {report['evaluation_dates']} / シグナル {report['signals']} 件")
    print(f"窓 {summary['windows']} 個（判定可 {summary['windows_judged']}）"
          f" 単調 {summary['windows_monotonic']} → 結論: {summary['verdict']}")
    if summary.get("median_top_bottom_spread") is not None:
        print(f"上位10% − 下位10% の中央値: {summary['median_top_bottom_spread']:+.4f}"
              f"（{summary['windows_positive_spread']}/{summary['windows_with_spread']} 窓で正）")
    print()
    for window in report["windows"]:
        head = f"検証 {window['test'][0]}〜{window['test'][1]}  n={window['samples']}"
        print(f"{head}  分位単調={window['decile_monotonic']}  絶対点単調={window['monotonic']}")
        for bucket in window["deciles"]:
            excess = bucket["median_excess_topix"]
            mark = "" if bucket["reliable"] else "  (標本不足)"
            shown = f"{excess:+.4f}" if excess is not None else "   n/a "
            hit = bucket["hit_rate"]
            hit_shown = f"{hit*100:5.1f}%" if hit is not None else "  n/a"
            print(f"    {bucket['bucket']:>12}  n={bucket['samples']:>6}  "
                  f"超過中位={shown}  勝率={hit_shown}{mark}")
        if window.get("top_bottom_spread") is not None:
            print(f"    上位10% − 下位10% = {window['top_bottom_spread']:+.4f}")
        print()
    print("点時の制約:")
    for limit in report["point_in_time_limits"]:
        print(f"  - {limit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
