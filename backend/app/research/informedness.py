"""報告主体ごとの「情報量」を測る —— 増仓イベントの後に何が起きたか。

    python -m app.research.informedness --start 2023-06-01 --out /data/informedness.json

各イベント（new / reentry / increased / decreased / below_threshold）について、
**効力日（公開日の翌営業日）の終値** を基準に 20 営業日後の終値を取り、
TOPIX の同期間リターンを引く。同一銘柄の複数イベントは重複して独立ではない
ので、ここで出すのは **相対的な高低** であって有意性ではない。

出力は 3 層:

* イベント種別 / ヘッジ標注 / 報告増幅 / 仓位水準 / reporter_class ごとの中位
* 実体（legal_id）ごとの中位（標本 >= --min-samples のみ）と年別の安定性
* reporter_class の校正材料 —— 名簿に無い実体で標本が多いものを列挙する

2026-09-02 の初回実測（2023-06〜2026-07、662,445 イベント）:
全種別が負（回補 −2.56% が最も負）、報告増幅・仓位水準に単調性、
`Notes` のヘッジ標注は区別できず、海外 PB 名義 ≈ −3% / 国内証券名義 ≈ 0。
"""

from __future__ import annotations

import argparse
import bisect
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from app.data_paths import get_data_paths
from app.repositories.core import CoreRepository
from app.services.short_monitor import reporters

INFORMEDNESS_VERSION = "informedness-v1"
HORIZON = 20
EVENT_TYPES = ("new", "reentry", "increased", "decreased", "below_threshold")
BEARISH_TYPES = ("new", "reentry", "increased")


def _median(values: Sequence[float]) -> float | None:
    usable = [v for v in values if v is not None]
    return statistics.median(usable) if usable else None


def _hit_rate(values: Sequence[float]) -> float | None:
    usable = [v for v in values if v is not None]
    return (sum(1 for v in usable if v > 0) / len(usable)) if usable else None


def summarise(values: Sequence[float]) -> dict[str, Any]:
    median = _median(values)
    return {
        "n": len(values),
        "median_excess_20d": round(median, 6) if median is not None else None,
        "hit_rate_20d": round(_hit_rate(values), 4) if values else None,
    }


def _ratio_bucket(ratio: float | None) -> str:
    value = ratio or 0.0
    return "0.5-0.6" if value < 0.006 else "0.6-1.0" if value < 0.01 else "1.0-2.0" if value < 0.02 else ">=2.0"


def _delta_bucket(delta: float | None) -> str | None:
    if delta is None:
        return None
    return "<0.1%" if delta < 0.001 else "0.1-0.3%" if delta < 0.003 else "0.3-0.5%" if delta < 0.005 else ">=0.5%"


def event_outcomes(
    repository: CoreRepository, *, start: str, end: str | None = None, horizon: int = HORIZON,
) -> list[dict[str, Any]]:
    """イベントごとの 20 日超過。銘柄ごとに足を 1 度読み、拆併股の窓は除く。"""

    with repository.read() as connection:
        calendar = [
            row[0] for row in connection.execute(
                "SELECT DISTINCT trade_date FROM daily_bars WHERE trade_date >= ? ORDER BY trade_date",
                (_shift(start, -60),),
            ).fetchall()
        ]
        if len(calendar) <= horizon + 1:
            return []
        cutoff = end or calendar[-(horizon + 2)]
        topix = {
            row[0]: row[1] for row in connection.execute(
                "SELECT trade_date, close FROM index_bars WHERE index_code = '0000' AND trade_date >= ?",
                (calendar[0],),
            ).fetchall()
        }
        events = connection.execute(
            "SELECT canonical_code, legal_id, group_id, raw_holder_name, event_type, is_hedge_disclosed, "
            "effective_trade_date, short_ratio, ratio_delta FROM short_position_events "
            "WHERE effective_trade_date BETWEEN ? AND ? AND correction_status = 'original' "
            f"AND event_type IN ({','.join('?' for _ in EVENT_TYPES)})",
            (start, cutoff, *EVENT_TYPES),
        ).fetchall()
    by_code: dict[str, list[Any]] = {}
    for row in events:
        by_code.setdefault(row[0], []).append(row)

    out: list[dict[str, Any]] = []
    for code, rows in by_code.items():
        with repository.read() as connection:
            bars = connection.execute(
                "SELECT trade_date, close, adjustment_factor FROM daily_bars "
                "WHERE canonical_code = ? AND trade_date >= ? ORDER BY trade_date",
                (code, calendar[0]),
            ).fetchall()
        dates = [b[0] for b in bars]
        closes = [b[1] for b in bars]
        splits: list[int] = []
        count = 0
        for bar in bars:
            if bar[2] is not None and float(bar[2]) != 1.0:
                count += 1
            splits.append(count)
        for row in rows:
            day = row[6]
            index = bisect.bisect_left(dates, day)
            if index >= len(dates) or dates[index] != day:
                continue
            later = index + horizon
            if later >= len(dates) or splits[later] != splits[index]:
                continue
            p0, p1 = closes[index], closes[later]
            t0, t1 = topix.get(day), topix.get(dates[later])
            if not p0 or not p1 or not t0 or not t1:
                continue
            legal_id = str(row[1] or "")
            out.append({
                "canonical_code": code,
                "legal_id": legal_id,
                "group_id": row[2],
                "raw_holder_name": row[3],
                "reporter_class": reporters.classify(
                    row[3], group_id=row[2], is_aggregate=legal_id.startswith("aggregate-"),
                ),
                "event_type": row[4],
                "is_hedge_disclosed": bool(row[5]),
                "effective_trade_date": day,
                "short_ratio": row[7],
                "ratio_delta": row[8],
                "excess_20d": (p1 / p0 - 1.0) - (t1 / t0 - 1.0),
            })
    return out


def _shift(day: str, days: int) -> str:
    from datetime import date, timedelta

    try:
        return (date.fromisoformat(day[:10]) + timedelta(days=days)).isoformat()
    except ValueError:
        return day


def build_report(
    outcomes: Sequence[Mapping[str, Any]], *, min_samples: int = 150
) -> dict[str, Any]:
    def group(records: Iterable[Mapping[str, Any]], key) -> dict[str, dict[str, Any]]:
        buckets: dict[str, list[float]] = {}
        for record in records:
            label = key(record)
            if label is None:
                continue
            buckets.setdefault(str(label), []).append(float(record["excess_20d"]))
        return {label: summarise(values) for label, values in sorted(buckets.items())}

    bearish = [r for r in outcomes if r["event_type"] in BEARISH_TYPES]
    covering = [r for r in outcomes if r["event_type"] in ("decreased", "below_threshold")]

    entities: dict[str, list[float]] = {}
    names: dict[str, tuple[str, str]] = {}
    years: dict[tuple[str, str], list[float]] = {}
    for record in bearish:
        if record["is_hedge_disclosed"]:
            continue
        legal_id = record["legal_id"]
        entities.setdefault(legal_id, []).append(float(record["excess_20d"]))
        names.setdefault(legal_id, (record["raw_holder_name"], record["reporter_class"]))
        years.setdefault((legal_id, record["effective_trade_date"][:4]), []).append(float(record["excess_20d"]))

    ranked = []
    for legal_id, values in entities.items():
        if len(values) < min_samples:
            continue
        summary = summarise(values)
        summary.update({
            "legal_id": legal_id,
            "raw_holder_name": names[legal_id][0],
            "reporter_class": names[legal_id][1],
            "by_year": {
                year: summarise(years[(legal_id, year)])
                for (lid, year) in sorted(years) if lid == legal_id
            },
        })
        ranked.append(summary)
    ranked.sort(key=lambda item: (item["median_excess_20d"] is None, item["median_excess_20d"]))

    # 校正材料: 名簿に無い（unknown）のに標本が多い実体
    unknown_heavy = [
        item for item in ranked if item["reporter_class"] == reporters.CLASS_UNKNOWN
    ][:40]

    return {
        "version": INFORMEDNESS_VERSION,
        "reporter_version": reporters.REPORTER_VERSION,
        "events": len(outcomes),
        "horizon_trading_days": HORIZON,
        "by_event_type": group(outcomes, lambda r: r["event_type"]),
        "bearish_by_hedge_flag": group(bearish, lambda r: "hedge" if r["is_hedge_disclosed"] else "no_flag"),
        "bearish_by_reporter_class": group(bearish, lambda r: r["reporter_class"]),
        "bearish_informed_vs_not": group(
            bearish, lambda r: "informed" if reporters.is_informed(r["reporter_class"]) else "not_informed",
        ),
        "covering_by_reporter_class": group(covering, lambda r: r["reporter_class"]),
        "bearish_by_ratio_bucket": group(bearish, lambda r: _ratio_bucket(r["short_ratio"])),
        "bearish_by_delta_bucket": group(bearish, lambda r: _delta_bucket(r["ratio_delta"])),
        "entities": ranked,
        "entity_spread": {
            "count": len(ranked),
            "p10": ranked[len(ranked) // 10]["median_excess_20d"] if ranked else None,
            "p50": ranked[len(ranked) // 2]["median_excess_20d"] if ranked else None,
            "p90": ranked[-max(1, len(ranked) // 10)]["median_excess_20d"] if ranked else None,
        },
        "unclassified_with_many_events": unknown_heavy,
        "caveats": [
            "同一銘柄の複数イベントは重複して独立ではない。相対的な高低のみ読むこと。",
            "基準は TOPIX。披露サンプルは小型株に偏るので、水準そのものは市場区分効果を含む。",
            "入場は効力日（公開翌営業日）の終値。翌営業日始値より 1 日楽観側。",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.research.informedness", description="報告主体の情報量")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", default=None)
    parser.add_argument("--min-samples", type=int, default=150)
    parser.add_argument("--core-db", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    paths = get_data_paths()
    repository = CoreRepository(Path(args.core_db) if args.core_db else paths.core_db, read_only=True)
    if not repository.exists():
        print("コア DB がありません", file=sys.stderr)
        return 2
    outcomes = event_outcomes(repository, start=args.start, end=args.end)
    report = build_report(outcomes, min_samples=args.min_samples)
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"=== 報告主体の情報量 ({report['version']} / {report['reporter_version']}) ===")
    print(f"イベント {report['events']} 件")
    for section in ("by_event_type", "bearish_by_reporter_class", "bearish_informed_vs_not",
                    "covering_by_reporter_class", "bearish_by_delta_bucket"):
        print(f"  --- {section}")
        for label, stats in report[section].items():
            median = stats["median_excess_20d"]
            shown = f"{median * 100:+.2f}%" if median is not None else "n/a"
            print(f"    {label:<18} n={stats['n']:>7}  20日超過中位={shown}")
    spread = report["entity_spread"]
    print(f"  実体 {spread['count']} 件 (>= {args.min_samples} 標本): p10={spread['p10']} p50={spread['p50']} p90={spread['p90']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
