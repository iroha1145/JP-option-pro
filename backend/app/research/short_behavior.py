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
from .walk_forward import (
    DECILE_LABELS,
    _median,
    check_monotonic,
    summarise_deciles,
    walk_forward_windows,
)

#: v2: 配対基準（市場区分 × 流動性五分位）の超過 `excess_peer_*`、状態別
#:     中位の聚類 bootstrap 区間、`monitor_priority` の逐日十分位単調性、
#:     可視機関数（拥挤度）の窓別安定性、informed 口径の分組、留出期の別集計。
SHORT_RESEARCH_VERSION = "sb-research-v2"

#: 1 グループの結論を出すのに要る最低件数。これを割ったら「不足」と書く。
MIN_SAMPLES = 30

#: 聚類 bootstrap の再抽出回数。銘柄 × 月を 1 単位に再抽出する —— 同じ銘柄が
#: 隣り合う日に何度も状態を出入りする重複を、独立標本として数えないため。
BOOTSTRAP_RESAMPLES = 200

#: 拥挤度叠加（radar_link.CROWDING_LINK_ENABLED）を有効にしてよい条件。
CROWDING_GATE_MIN_NEGATIVE_WINDOWS = 13
CROWDING_GATE_TOTAL_WINDOWS = 16


@dataclass
class GroupStats:
    key: str
    samples: int
    median_return: dict[int, float | None] = field(default_factory=dict)
    median_excess_topix: dict[int, float | None] = field(default_factory=dict)
    median_excess_sector: dict[int, float | None] = field(default_factory=dict)
    #: 配対基準（同じ市場区分 × 流動性五分位の銘柄の中位）に対する超過。
    #: 披露サンプルは小型株に偏るので、TOPIX 超過は市場区分効果を信号に
    #: 帰属させてしまう —— こちらを主指標にする。
    median_excess_peer: dict[int, float | None] = field(default_factory=dict)
    ci95_excess_topix_20d: tuple[float | None, float | None] = (None, None)
    ci95_excess_peer_20d: tuple[float | None, float | None] = (None, None)
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
            **{f"median_excess_peer_{h}d": self.median_excess_peer.get(h) for h in HORIZONS},
            "ci95_excess_topix_20d": list(self.ci95_excess_topix_20d),
            "ci95_excess_peer_20d": list(self.ci95_excess_peer_20d),
            "hit_rate_20d": self.hit_rate_20d,
            "median_mfe": self.median_mfe,
            "median_mae": self.median_mae,
            "reached_target_first": self.reached_target_first,
            "reliable": self.reliable,
        }


def cluster_of(record: Mapping[str, Any]) -> str:
    """bootstrap の再抽出単位: 銘柄 × 信号月。"""

    return f"{record.get('canonical_code') or ''}|{str(record.get('signal_date') or '')[:7]}"


def bootstrap_median_ci(
    records: Sequence[Mapping[str, Any]],
    key: str,
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = 0,
) -> tuple[float | None, float | None]:
    """`key` の中位値の 95% 区間（聚類 bootstrap、銘柄 × 月単位）。

    普通の bootstrap は各行を独立とみなす。ここでは同じ銘柄の同じ月の信号を
    まとめて再抽出する —— 隣り合う日に何度も状態を出入りした銘柄が、独立な
    30 標本に化けるのを防ぐ。件数が MIN_SAMPLES 未満なら区間は出さない。
    """

    import random

    clusters: dict[str, list[float]] = {}
    for record in records:
        value = record.get(key)
        if value is None:
            continue
        clusters.setdefault(cluster_of(record), []).append(float(value))
    keys = list(clusters)
    total = sum(len(v) for v in clusters.values())
    if total < MIN_SAMPLES or len(keys) < 5:
        return None, None
    rng = random.Random(seed)
    medians: list[float] = []
    for _ in range(resamples):
        sample: list[float] = []
        for _ in range(len(keys)):
            sample.extend(clusters[keys[rng.randrange(len(keys))]])
        value = _median(sample)
        if value is not None:
            medians.append(value)
    if not medians:
        return None, None
    medians.sort()
    low = medians[int(0.025 * (len(medians) - 1))]
    high = medians[int(0.975 * (len(medians) - 1))]
    return round(low, 6), round(high, 6)


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
        stats.median_excess_peer[horizon] = _median(
            [r[f"excess_peer_{horizon}d"] for r in records
             if r.get(f"excess_peer_{horizon}d") is not None]
        )
    stats.ci95_excess_topix_20d = bootstrap_median_ci(records, "excess_topix_20d")
    stats.ci95_excess_peer_20d = bootstrap_median_ci(records, "excess_peer_20d")
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
        if not stats:
            return None
        # 配対基準があればそれを使う（市場区分効果を除く）。無ければ TOPIX。
        value = stats.get(f"median_excess_peer_{horizon}d")
        return value if value is not None else stats.get(f"median_excess_topix_{horizon}d")

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
    #: v2: monitor_priority の逐日十分位が単調か（walk_forward と同じ判定）。
    priority_ranking: dict[str, Any] = field(default_factory=dict)
    #: v2: 可視機関数（拥挤度）の窓別安定性と、叠加を有効にしてよいかの判定。
    crowding: dict[str, Any] = field(default_factory=dict)
    #: v2: 留出期（--holdout-start 以降）の状態別集計。
    holdout: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": SHORT_RESEARCH_VERSION,
            "signals": self.signals,
            "evaluated": self.evaluated,
            "windows": self.windows,
            "states": self.states,
            "flags": self.flags,
            "groups": self.groups,
            "priority_ranking": self.priority_ranking,
            "crowding": self.crowding,
            "holdout": self.holdout,
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
    "上場廃止・長期売買停止で価格系列が窓の途中で途切れた銘柄は、その期間の"
    "リターンが欠損（None）となり集計から除外される。破滅的な結末が黙って"
    "落ちるため、生存者バイアスで結果はやや上振れしうる（意図的に「最終バーで"
    "実現」はしない —— 直近シグナルの未経過窓を誤って損益確定させないため）。",
]


def _excess_key(records: Sequence[Mapping[str, Any]]) -> str:
    """配対基準の超過があればそれを、無ければ TOPIX 超過を集計キーにする。"""

    return "excess_peer_20d" if any(r.get("excess_peer_20d") is not None for r in records) else "excess_topix_20d"


def institution_bucket(count: Any) -> str:
    try:
        value = int(count or 0)
    except (TypeError, ValueError):
        value = 0
    return "0" if value <= 0 else "1" if value == 1 else "2-3" if value <= 3 else "4+"


INSTITUTION_BUCKETS = ("0", "1", "2-3", "4+")


def crowding_stability(
    records: Sequence[Mapping[str, Any]],
    windows: Sequence[tuple[str, str, str, str]],
    *,
    holdout_start: str | None = None,
    count_key: str = "visible_institution_count",
) -> dict[str, Any]:
    """可視機関数の多い群（4+）が少ない群（0/1）より悪い、が窓ごとに成り立つか。

    radar_link.CROWDING_LINK_ENABLED を True にしてよいかの判定材料。判定は
    「4+ の中位超過 − 0/1 の中位超過」が負の窓の数。件数不足の窓は数えない。
    """

    key = _excess_key(records)

    def spread(rows: Sequence[Mapping[str, Any]]) -> float | None:
        low = [r[key] for r in rows if institution_bucket(r.get(count_key)) in ("0", "1") and r.get(key) is not None]
        high = [r[key] for r in rows if institution_bucket(r.get(count_key)) == "4+" and r.get(key) is not None]
        if len(low) < MIN_SAMPLES or len(high) < MIN_SAMPLES:
            return None
        a, b = _median(high), _median(low)
        return (a - b) if (a is not None and b is not None) else None

    per_window: list[dict[str, Any]] = []
    negative = 0
    judged = 0
    for _ts, _te, test_start, test_end in windows:
        rows = [r for r in records if test_start <= str(r.get("signal_date") or "") <= test_end]
        value = spread(rows)
        per_window.append({"test": [test_start, test_end], "samples": len(rows), "spread_4plus_minus_01": value})
        if value is not None:
            judged += 1
            if value < 0:
                negative += 1
    overall = {
        bucket: summarise_group(bucket, [r for r in records if institution_bucket(r.get(count_key)) == bucket]).as_dict()
        for bucket in INSTITUTION_BUCKETS
    }
    holdout_spread = None
    if holdout_start:
        holdout_spread = spread([r for r in records if str(r.get("signal_date") or "") >= holdout_start])
    passes = (
        judged >= CROWDING_GATE_TOTAL_WINDOWS
        and negative >= CROWDING_GATE_MIN_NEGATIVE_WINDOWS
        and (holdout_spread is None or holdout_spread < 0)
    )
    return {
        "count_key": count_key,
        "excess_key": key,
        "windows_judged": judged,
        "windows_negative": negative,
        "holdout_start": holdout_start,
        "holdout_spread_4plus_minus_01": holdout_spread,
        "gate": {
            "min_negative_windows": CROWDING_GATE_MIN_NEGATIVE_WINDOWS,
            "total_windows": CROWDING_GATE_TOTAL_WINDOWS,
            "holdout_must_be_negative": True,
        },
        "verdict": "pass" if passes else ("insufficient_data" if judged < CROWDING_GATE_TOTAL_WINDOWS else "fail"),
        "by_bucket": overall,
        "windows": per_window,
    }


def priority_ranking_power(
    records: Sequence[Mapping[str, Any]],
    windows: Sequence[tuple[str, str, str, str]],
    *,
    score_field: str = "monitor_priority",
) -> dict[str, Any]:
    """`monitor_priority` に順位付けの力があるか —— 走步と同じ逐日十分位の単調性。"""

    per_window: list[dict[str, Any]] = []
    monotonic = 0
    judged = 0
    spreads: list[float] = []
    for _ts, _te, test_start, test_end in windows:
        rows = [r for r in records if test_start <= str(r.get("signal_date") or "") <= test_end]
        deciles = summarise_deciles(rows, horizon=20, score_field=score_field)
        verdict, detail = check_monotonic(deciles)
        top = next((b for b in deciles if b.label == DECILE_LABELS[0]), None)
        bottom = next((b for b in deciles if b.label == DECILE_LABELS[-1]), None)
        spread = None
        if (
            top is not None and bottom is not None and top.reliable and bottom.reliable
            and top.median_excess_topix is not None and bottom.median_excess_topix is not None
        ):
            spread = top.median_excess_topix - bottom.median_excess_topix
            spreads.append(spread)
        if verdict is not None:
            judged += 1
            monotonic += 1 if verdict else 0
        per_window.append({
            "test": [test_start, test_end], "samples": len(rows),
            "decile_monotonic": verdict, "detail": detail, "top_bottom_spread": spread,
        })
    share = (monotonic / judged) if judged else None
    return {
        "score_field": score_field,
        "windows_judged": judged,
        "windows_monotonic": monotonic,
        "median_top_bottom_spread": _median(spreads) if spreads else None,
        "verdict": (
            "insufficient_data" if not judged
            else "monotonic" if share >= 0.8 else "weak" if share >= 0.5 else "not_monotonic"
        ),
        "windows": per_window,
    }


def evaluate_signals(
    records: Sequence[Mapping[str, Any]],
    *,
    calendar: Sequence[str],
    train_days: int = 250,
    test_days: int = 125,
    holdout_start: str | None = None,
) -> ShortBehaviorReport:
    """全体・状態別・ラベル別・グループ別の結果を 1 レポートにまとめる。"""

    report = ShortBehaviorReport(signals=len(records), limits=list(POINT_IN_TIME_LIMITS))
    usable = [r for r in records if r.get("return_20d") is not None]
    report.evaluated = len(usable)
    if not usable:
        return report

    report.states = compare_states(usable)
    report.flags = compare_flags(usable, [
        "reentry", "rotation", "new_entry", "crowded_margin",
        "parked_below", "voluntary_covering", "forced_covering", "no_informed_reporter",
    ])

    liquidity_edges = quantile_edges([r.get("adv20_value") for r in usable if r.get("adv20_value")])
    cover_edges = quantile_edges(
        [r.get("visible_days_to_cover") for r in usable if r.get("visible_days_to_cover")]
    )
    for record in usable:
        record["liquidity_bucket"] = decile_key(record.get("adv20_value"), liquidity_edges)
        record["days_to_cover_bucket"] = decile_key(
            record.get("visible_days_to_cover"), cover_edges
        )
        record["institution_bucket"] = institution_bucket(record.get("visible_institution_count"))
        record["informed_bucket"] = institution_bucket(record.get("informed_institution_count"))

    for key in (
        "market_code", "sector33_code", "liquidity_bucket",
        "days_to_cover_bucket", "institution_bucket", "informed_bucket",
    ):
        report.groups[key] = {
            name: summarise_group(name, rows).as_dict()
            for name, rows in group_by(usable, key).items()
        }

    windows = walk_forward_windows(calendar, train_days=train_days, test_days=test_days)
    report.priority_ranking = priority_ranking_power(usable, windows)
    report.crowding = {
        "visible": crowding_stability(usable, windows, holdout_start=holdout_start),
        "informed": crowding_stability(
            usable, windows, holdout_start=holdout_start, count_key="informed_institution_count",
        ),
    }
    if holdout_start:
        held = [r for r in usable if str(r.get("signal_date") or "") >= holdout_start]
        report.holdout = {
            "start": holdout_start, "samples": len(held),
            "states": compare_states(held) if held else {},
        }

    # 走步: 日付をシャッフルしない。学習窓は使わないが、窓ごとに結論が
    # 変わらないかを見るために同じ切り方を使う。
    for _train_start, _train_end, test_start, test_end in windows:
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
                    "median_excess_peer_20d": stats.get("median_excess_peer_20d"),
                    "reliable": stats["reliable"],
                }
                for name, stats in states["by_state"].items()
            },
        })
    return report


__all__ = [
    "BOOTSTRAP_RESAMPLES",
    "GroupStats",
    "INSTITUTION_BUCKETS",
    "MIN_SAMPLES",
    "POINT_IN_TIME_LIMITS",
    "SHORT_RESEARCH_VERSION",
    "ShortBehaviorReport",
    "bootstrap_median_ci",
    "cluster_of",
    "compare_flags",
    "compare_states",
    "crowding_stability",
    "decile_key",
    "evaluate_signals",
    "group_by",
    "institution_bucket",
    "priority_ranking_power",
    "quantile_edges",
    "summarise_group",
]
