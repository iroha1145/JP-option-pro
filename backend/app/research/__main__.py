"""研究バッチの起動口。Web プロセスとは別に回す。

    python -m app.research --start 2017-01-01 --end 2026-06-30

進捗は stdout に出す。中断しても同じコマンドで再開する（日付チェックポイント）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.config import get_settings
from app.repositories.core import CoreRepository

from .runner import ResearchStore, RunParams, run_backtest


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
    args = parser.parse_args(argv)

    settings = get_settings()
    core_path = Path(args.core_db) if args.core_db else Path(settings.DATA_DIR) / "jp-core.db"
    research_path = (
        Path(args.research_db) if args.research_db
        else Path(settings.DATA_DIR) / "jp-research.db"
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
    report = run_backtest(
        repository, ResearchStore(research_path), params,
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
    print()
    for window in report["windows"]:
        head = f"検証 {window['test'][0]}〜{window['test'][1]}  n={window['samples']}"
        print(f"{head}  単調={window['monotonic']}")
        for bucket in window["buckets"]:
            excess = bucket["median_excess_topix"]
            mark = "" if bucket["reliable"] else "  (標本不足)"
            shown = f"{excess:+.4f}" if excess is not None else "   n/a "
            print(f"    {bucket['bucket']:>7}  n={bucket['samples']:>5}  "
                  f"超過中位={shown}{mark}")
        print()
    print("点時の制約:")
    for limit in report["point_in_time_limits"]:
        print(f"  - {limit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
