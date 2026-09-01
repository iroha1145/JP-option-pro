"""機関空売り行動信号の歴史検証（走步検証）。

問いは 1 つ:

    **どの状態に、その後の値動きとの安定した関係があるか。**

答えが「無い」なら、そう書く。物語の座りがいいという理由で重みを残さない。

点時セマンティクスは信号側で担保されている（`source_cutoff` は公開日ベース）。
ここでは **信号日より後の足だけ** を使い、日付をシャッフルしない。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .outcomes import HORIZONS, compute_outcome
from .walk_forward import _median, walk_forward_windows

SHORT_RESEARCH_VERSION = "sb-research-v1"

#: 1 グループの結論を出すのに要る最低件数。これを割ったら「不足」と書く。
MIN_SAMPLES = 30


@dataclass
class GroupStats:
    key: str
    samples: int
    median_return: dict[int, float | None] = field(default_factory=dict)
    median_excess_topix: dict[int, float | None] = field(default_factory=dict)
    median_excess_sector: dict[int, float | None] = field(default_factory=dict)
    hit_rate_20d: float | None = None
    median_mfe: float | None = None
    median_mae: float | None = None
    reached_target_first: float | None = None
    reliable: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "samples": self.samples,
            **{f"median_return_{h}d": self.median_return.get(h) for h in HORIZONS},
            **{f"median_excess_topix_{h}d": self.median_excess_topix.get(h) for h in HORIZONS},
            **{f"median_excess_sector_{h}d": self.median_excess_sector.get(h) for h in HORIZONS},
            "hit_rate_20d": self.hit_rate_20d,
            "median_mfe": self.median_mfe,
            "median_mae": self.median_mae,
            "reached_target_first": self.reached_target_first,
            "reliable": self.reliable,
        }


def summarise_group(key: str, records: Sequence[Mapping[str, Any]]) -> GroupStats:
    stats = GroupStats(key=key, samples=len(records))
    if not records:
        return stats
    for horizon in HORIZONS:
        stats.median_return[horizon] = _median(
            [r[f"return_{horizon}d"] for r in records if r.get(f"return_{horizon}d") is not None]
        )
        stats.median_excess_topix[horizon] = _median(
            [r[f"excess_topix_{horizon}d"] for r in records
             if r.get(f"excess_topix_{horizon}d") is not None]
        )
        stats.median_excess_sector[horizon] = _median(
            [r[f"excess_sector_{horizon}d"] for r in records
             if r.get(f"excess_sector_{horizon}d") is not None]
        )
    wins = [r for r in records if r.get("return_20d") is not None]
    if wins:
        stats.hit_rate_20d = round(
            sum(1 for r in wins if r["return_20d"] > 0) / len(wins), 4
        )
    stats.median_mfe = _median([r["mfe_pct"] for r in records if r.get("mfe_pct") is not None])
    stats.median_mae = _median([r["mae_pct"] for r in records if r.get("mae_pct") is not None])
    judged = [r for r in records if r.get("hit_r_multiple")]
    if judged:
        stats.reached_target_first = round(
            sum(1 for r in judged if r["hit_r_multiple"] == "target") / len(judged), 4
        )
    stats.reliable = len(records) >= MIN_SAMPLES
    return stats


def group_by(records: Sequence[Mapping[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        value = record.get(key)
        if value is None or value == "":
            value = "(unknown)"
        out.setdefault(str(value), []).append(dict(record))
    return out


def decile_key(value: Any, edges: Sequence[float]) -> str:
    """連続値を分位ラベルに。境界は呼び出し側が **その母集団から** 決める。"""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return "(unknown)"
    for index, edge in enumerate(edges):
        if number <= edge:
            return f"q{index + 1}"
    return f"q{len(edges) + 1}"


def quantile_edges(values: Sequence[float], buckets: int = 5) -> list[float]:
    usable = sorted(v for v in values if v is not None)
    if len(usable) < buckets:
        return []
    return [
        usable[int(len(usable) * (index + 1) / buckets) - 1]
        for index in range(buckets - 1)
    ]


def compare_states(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """状態ごとの結果と、比較したい対の差分。

    指令書 §十六が名指しした 4 つの問いをそのまま出す。答えが「差が無い」
    でも、そのまま書く。
    """

    by_state = {
        key: summarise_group(key, rows).as_dict()
        for key, rows in group_by(records, "primary_state").items()
    }

    def excess(state: str, horizon: int = 20) -> float | None:
        stats = by_state.get(state)
        return stats.get(f"median_excess_topix_{horizon}d") if stats else None

    def samples(state: str) -> int:
        stats = by_state.get(state)
        return int(stats.get("samples") or 0) if stats else 0

    # 比較の相手に `no_signal` は使えない —— 状態が変わった銘柄だけを信号に
    # しているので、`no_signal` は一件も出てこない（最初そう書いていて、
    # 4 つの問いのうち 2 つが永久に `insufficient_data` になっていた）。
    # 母集団全体を基準にする。「この状態は、機関空売りが動いた銘柄全体より
    # 良いか」が答えたい問いなので、そのほうが素直でもある。
    by_state["(all signals)"] = summarise_group("(all signals)", records).as_dict()

    def compare(left: str, right: str) -> dict[str, Any]:
        a, b = excess(left), excess(right)
        enough = samples(left) >= MIN_SAMPLES and samples(right) >= MIN_SAMPLES
        return {
            "left": left, "right": right,
            "left_samples": samples(left), "right_samples": samples(right),
            "left_median_excess_20d": a, "right_median_excess_20d": b,
            "difference": (a - b) if (a is not None and b is not None) else None,
            # 件数が足りないときは「差がある」とも「無い」とも言わない
            "verdict": (
                "insufficient_data" if not enough
                else "left_better" if (a is not None and b is not None and a > b)
                else "right_better" if (a is not None and b is not None and a < b)
                else "no_difference"
            ),
        }

    return {
        "by_state": by_state,
        "questions": {
            # 卖压吸收候选 は 普通の低位株 より良いか
            "absorption_vs_low_conflict": compare("absorption", "low_conflict"),
            # 回补启动 は 機関空売りが動いた銘柄全体より良いか
            "covering_start_vs_all": compare("covering_start", "(all signals)"),
            # 挤空确认 は 回补启动 より良いか（突破確認を足した意味があるか）
            "squeeze_vs_covering_start": compare("squeeze_confirmed", "covering_start"),
            # 背离失效 が実際に悪いか
            "divergence_failed_vs_all": compare("divergence_failed", "(all signals)"),
        },
    }


def compare_flags(records: Sequence[Mapping[str, Any]], flags: Sequence[str]) -> dict[str, Any]:
    """ラベル単独に予測力があるか（機関重新进入 / 机构轮换 など）。"""

    out: dict[str, Any] = {}
    for flag in flags:
        with_flag = [r for r in records if flag in (r.get("flags") or [])]
        without = [r for r in records if flag not in (r.get("flags") or [])]
        a = summarise_group(f"{flag}:yes", with_flag)
        b = summarise_group(f"{flag}:no", without)
        enough = a.reliable and b.reliable
        left = a.median_excess_topix.get(20)
        right = b.median_excess_topix.get(20)
        out[flag] = {
            "with": a.as_dict(), "without": b.as_dict(),
            "difference": (left - right) if (left is not None and right is not None) else None,
            "verdict": (
                "insufficient_data" if not enough
                else "predictive" if (left is not None and right is not None and left > right)
                else "not_predictive"
            ),
        }
    return out


@dataclass
class ShortBehaviorReport:
    signals: int = 0
    evaluated: int = 0
    windows: list[dict[str, Any]] = field(default_factory=list)
    states: dict[str, Any] = field(default_factory=dict)
    flags: dict[str, Any] = field(default_factory=dict)
    groups: dict[str, Any] = field(default_factory=dict)
    limits: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": SHORT_RESEARCH_VERSION,
            "signals": self.signals,
            "evaluated": self.evaluated,
            "windows": self.windows,
            "states": self.states,
            "flags": self.flags,
            "groups": self.groups,
            "point_in_time_limits": self.limits,
        }


#: 正直に書いておく制約。読む人が結論を過大評価しないために必要。
POINT_IN_TIME_LIMITS = [
    "機関空売り残高は 2016-08 まで開示日つきで入っているが、2025-06 より前は"
    "月次の履歴ファイルからの再構成。開示日自体は J-Quants の値なので点時"
    "セマンティクスは守れるが、「当時その日に日次配信されていたか」は検証できない。",
    "再生は直近 30 営業日に公開イベントがある銘柄だけを組み立てる（業種中位の"
    "計算だけは全市場から取る）。圧力が閾値未満の銘柄は吸収の分位母集団にも"
    "信号にも寄与しないが、「全銘柄を毎日評価した」わけではない。",
    "業種・市場区分は現在値を使っている。過去の区分変更は再現していない。",
    "信用取引残高は週次。日次の混雑度は週の値を引き伸ばしている。回放は信用"
    "残高を読み込まないため crowded_margin は一度も発火しない。",
    "ニュース催化剂は現行のニュース DB に依存し、過去に遡って同じ密度では取れない。",
    "挤空確認とコホート E はレーダーの突破確認を要求するが、回放はレーダーを"
    "再生しないため n=0 —— この 2 つは未検証であって「否定された」わけではない。",
    "学習窓でのパラメータ校正は行っていない。これは走步 **校正** ではなく、"
    "固定パラメータの窓別安定性レポートである。",
    "上場廃止・長期売買停止で価格系列が途切れた銘柄は当該期間のリターンが"
    "欠損となり集計から外れる。破滅的な結末が落ちるぶん、生存者バイアスで"
    "結果はやや上振れしうる。",
]


def evaluate_signals(
    records: Sequence[Mapping[str, Any]],
    *,
    calendar: Sequence[str],
    train_days: int = 250,
    test_days: int = 125,
) -> ShortBehaviorReport:
    """全体・状態別・ラベル別・グループ別の結果を 1 レポートにまとめる。"""

    report = ShortBehaviorReport(signals=len(records), limits=list(POINT_IN_TIME_LIMITS))
    usable = [r for r in records if r.get("return_20d") is not None]
    report.evaluated = len(usable)
    if not usable:
        return report

    report.states = compare_states(usable)
    report.flags = compare_flags(usable, ["reentry", "rotation", "new_entry", "crowded_margin"])

    liquidity_edges = quantile_edges([r.get("adv20_value") for r in usable if r.get("adv20_value")])
    cover_edges = quantile_edges(
        [r.get("visible_days_to_cover") for r in usable if r.get("visible_days_to_cover")]
    )
    for record in usable:
        record["liquidity_bucket"] = decile_key(record.get("adv20_value"), liquidity_edges)
        record["days_to_cover_bucket"] = decile_key(
            record.get("visible_days_to_cover"), cover_edges
        )
        count = record.get("visible_institution_count")
        record["institution_bucket"] = (
            "0" if not count else "1" if count == 1 else "2-3" if count <= 3 else "4+"
        )

    for key in (
        "market_code", "sector33_code", "liquidity_bucket",
        "days_to_cover_bucket", "institution_bucket",
    ):
        report.groups[key] = {
            name: summarise_group(name, rows).as_dict()
            for name, rows in group_by(usable, key).items()
        }

    # 走步: 日付をシャッフルしない。学習窓は使わないが、窓ごとに結論が
    # 変わらないかを見るために同じ切り方を使う。
    for _train_start, _train_end, test_start, test_end in walk_forward_windows(
        calendar, train_days=train_days, test_days=test_days
    ):
        in_window = [
            r for r in usable
            if test_start <= str(r.get("signal_date") or "") <= test_end
        ]
        if not in_window:
            continue
        states = compare_states(in_window)
        report.windows.append({
            "test": [test_start, test_end],
            "samples": len(in_window),
            "by_state": {
                name: {
                    "samples": stats["samples"],
                    "median_excess_topix_20d": stats["median_excess_topix_20d"],
                    "reliable": stats["reliable"],
                }
                for name, stats in states["by_state"].items()
            },
        })
    return report


__all__ = [
    "GroupStats",
    "MIN_SAMPLES",
    "POINT_IN_TIME_LIMITS",
    "SHORT_RESEARCH_VERSION",
    "ShortBehaviorReport",
    "compare_flags",
    "compare_states",
    "decile_key",
    "evaluate_signals",
    "group_by",
    "quantile_edges",
    "summarise_group",
]
