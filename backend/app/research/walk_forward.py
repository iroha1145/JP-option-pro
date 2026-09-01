"""分数に順位付けの力があるかを、時系列を守って測る。

無作為分割は使わない。相場は時系列に強く相関するので、ランダムに切ると
訓練側と検証側が同じ相場付近を共有し、成績が実力以上に出る。窓を前へ
転がして、**検証は必ず訓練より後**にする。

出すのは「どの数字が一番良かったか」ではなく **単調性**:

    90点台 > 80点台 > 70点台 > それ以下

が複数の窓で安定して成り立つか。成り立たないなら、その 100 点満点は確率的な
意味を持たない —— そのことをそう書く。数字を良く見せるために定義をいじる
のは禁止（doc §十五）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

# 分数のバケット（上端は含まない）。日本株の断面が薄い日でも数が入るよう
# 粗めに切る。細かく切ると 1 バケット数銘柄になり、中位が個別銘柄になる。
SCORE_BUCKETS = ((90, 101), (80, 90), (70, 80), (60, 70), (0, 60))
BUCKET_LABELS = ("90+", "80-89", "70-79", "60-69", "<60")

# バケットの中位を「その層の成績」と呼ぶために最低限必要な標本数。
MIN_BUCKET_SAMPLES = 30


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def bucket_of(score: float | None) -> str | None:
    value = _finite(score)
    if value is None:
        return None
    for (low, high), label in zip(SCORE_BUCKETS, BUCKET_LABELS):
        if low <= value < high:
            return label
    return None


@dataclass
class BucketStats:
    label: str
    samples: int = 0
    median_return: float | None = None
    median_excess_topix: float | None = None
    hit_rate: float | None = None            # 超過リターンが正の割合
    median_mfe: float | None = None
    median_mae: float | None = None
    target_before_stop: float | None = None  # +1R が -1R より先に来た割合
    reliable: bool = False                   # 標本が足りているか

    def as_dict(self) -> dict[str, Any]:
        return {
            "bucket": self.label, "samples": self.samples,
            "median_return": self.median_return,
            "median_excess_topix": self.median_excess_topix,
            "hit_rate": self.hit_rate,
            "median_mfe": self.median_mfe, "median_mae": self.median_mae,
            "target_before_stop": self.target_before_stop,
            "reliable": self.reliable,
        }


@dataclass
class WindowResult:
    """1 検証窓の結果。"""

    train_start: str
    train_end: str
    test_start: str
    test_end: str
    horizon: int
    samples: int
    buckets: list[BucketStats] = field(default_factory=list)
    deciles: list[BucketStats] = field(default_factory=list)
    monotonic: bool | None = None
    monotonic_detail: str = ""
    decile_monotonic: bool | None = None
    decile_detail: str = ""
    #: 上位10% と下位10% の超過中位の差。単調性より鈍いが、順位付け能力の
    #: 有無だけならこれが一番読みやすい（0 以下なら効いていない）。
    top_bottom_spread: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "train": [self.train_start, self.train_end],
            "test": [self.test_start, self.test_end],
            "horizon_trading_days": self.horizon,
            "samples": self.samples,
            "buckets": [bucket.as_dict() for bucket in self.buckets],
            "deciles": [bucket.as_dict() for bucket in self.deciles],
            "monotonic": self.monotonic,
            "monotonic_detail": self.monotonic_detail,
            "decile_monotonic": self.decile_monotonic,
            "decile_detail": self.decile_detail,
            "top_bottom_spread": self.top_bottom_spread,
        }


#: 分位バケット（上位から）。絶対点のバケットと違い、**その日の断面の中で
#: 相対的にどこか**を見る。日本株の絶対閾値は米国版から持ち込んだもので
#: 校正されていないので、順位付け能力そのものを測るにはこちらが素直
#: （doc §七「横截面归一化」）。
DECILE_LABELS = ("D1(上位10%)", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9", "D10(下位10%)")


def assign_deciles(
    records: Sequence[Mapping[str, Any]], *, score_field: str = "score"
) -> dict[int, str]:
    """`id(record)` → 十分位ラベル。**評価日ごとに**切る。

    全期間まとめて切ると、相場が強かった年の銘柄が丸ごと上位に入り、
    「スコアが効いた」のか「その年が良かった」のかが分離できない。
    """

    by_date: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        value = _finite(record.get(score_field))
        if value is None:
            continue
        by_date.setdefault(str(record.get("signal_date") or ""), []).append(record)

    labels: dict[int, str] = {}
    for rows in by_date.values():
        if len(rows) < len(DECILE_LABELS):
            continue          # その日は十分位に割れない（黙って混ぜない）
        ordered = sorted(rows, key=lambda r: -(_finite(r.get(score_field)) or 0.0))
        size = len(ordered)
        for index, record in enumerate(ordered):
            slot = min(len(DECILE_LABELS) - 1, index * len(DECILE_LABELS) // size)
            labels[id(record)] = DECILE_LABELS[slot]
    return labels


def summarise_deciles(
    records: Sequence[Mapping[str, Any]], *, horizon: int, score_field: str = "score"
) -> list[BucketStats]:
    """日ごとの十分位で層別した成績。"""

    labels = assign_deciles(records, score_field=score_field)
    grouped: dict[str, list[Mapping[str, Any]]] = {label: [] for label in DECILE_LABELS}
    for record in records:
        label = labels.get(id(record))
        if label is not None:
            grouped[label].append(record)
    return [_stats_for(label, grouped[label], horizon) for label in DECILE_LABELS]


def _stats_for(
    label: str, rows: Sequence[Mapping[str, Any]], horizon: int
) -> BucketStats:
    returns = [v for v in (_finite(r.get(f"return_{horizon}d")) for r in rows) if v is not None]
    excess = [
        v for v in (_finite(r.get(f"excess_topix_{horizon}d")) for r in rows) if v is not None
    ]
    mfe = [v for v in (_finite(r.get("mfe_pct")) for r in rows) if v is not None]
    mae = [v for v in (_finite(r.get("mae_pct")) for r in rows) if v is not None]
    decided = [str(r.get("hit_r_multiple")) for r in rows if r.get("hit_r_multiple")]
    return BucketStats(
        label=label,
        samples=len(rows),
        median_return=_median(returns),
        median_excess_topix=_median(excess),
        hit_rate=(sum(1 for v in excess if v > 0) / len(excess) if excess else None),
        median_mfe=_median(mfe),
        median_mae=_median(mae),
        target_before_stop=(
            sum(1 for v in decided if v == "target") / len(decided) if decided else None
        ),
        reliable=len(rows) >= MIN_BUCKET_SAMPLES,
    )


def summarise_buckets(
    records: Iterable[Mapping[str, Any]], *, horizon: int, score_field: str = "score"
) -> list[BucketStats]:
    """分数バケットごとの成績。標本不足のバケットは reliable=False で残す
    （黙って消すと「上位だけ綺麗」に見えてしまう）。"""

    grouped: dict[str, list[Mapping[str, Any]]] = {label: [] for label in BUCKET_LABELS}
    for record in records:
        label = bucket_of(record.get(score_field))
        if label is not None:
            grouped[label].append(record)

    stats: list[BucketStats] = []
    for label in BUCKET_LABELS:
        rows = grouped[label]
        returns = [v for v in (_finite(r.get(f"return_{horizon}d")) for r in rows) if v is not None]
        excess = [
            v for v in (_finite(r.get(f"excess_topix_{horizon}d")) for r in rows) if v is not None
        ]
        mfe = [v for v in (_finite(r.get("mfe_pct")) for r in rows) if v is not None]
        mae = [v for v in (_finite(r.get("mae_pct")) for r in rows) if v is not None]
        decided = [str(r.get("hit_r_multiple")) for r in rows if r.get("hit_r_multiple")]
        stats.append(
            BucketStats(
                label=label,
                samples=len(rows),
                median_return=_median(returns),
                median_excess_topix=_median(excess),
                hit_rate=(
                    sum(1 for v in excess if v > 0) / len(excess) if excess else None
                ),
                median_mfe=_median(mfe),
                median_mae=_median(mae),
                target_before_stop=(
                    sum(1 for v in decided if v == "target") / len(decided) if decided else None
                ),
                reliable=len(rows) >= MIN_BUCKET_SAMPLES,
            )
        )
    return stats


def check_monotonic(buckets: Sequence[BucketStats], *, metric: str = "median_excess_topix"):
    """高い層ほど成績が良い、が成り立っているか。

    判定に使うのは **標本が足りている層だけ**。3 銘柄しかない「90+」が
    たまたま強かったのを単調性の証拠にはしない。
    """

    usable = [
        bucket for bucket in buckets
        if bucket.reliable and getattr(bucket, metric) is not None
    ]
    if len(usable) < 3:
        return None, f"標本の足りる層が {len(usable)} 個しかなく、単調性を判定できない"
    values = [getattr(bucket, metric) for bucket in usable]
    ordered = all(values[i] >= values[i + 1] for i in range(len(values) - 1))
    detail = " > ".join(
        f"{bucket.label}={getattr(bucket, metric):+.4f}" for bucket in usable
    )
    return ordered, detail


def walk_forward_windows(
    trading_days: Sequence[str], *, train_days: int, test_days: int, step_days: int | None = None
) -> list[tuple[str, str, str, str]]:
    """(train_start, train_end, test_start, test_end) を前へ転がす。

    訓練と検証は **日付が重ならない**（重なると同じ相場を両側で見る）。
    """

    days = sorted(set(trading_days))
    step = step_days or test_days
    windows: list[tuple[str, str, str, str]] = []
    start = 0
    while start + train_days + test_days <= len(days):
        train = days[start : start + train_days]
        test = days[start + train_days : start + train_days + test_days]
        windows.append((train[0], train[-1], test[0], test[-1]))
        start += step
    return windows


def evaluate_window(
    records: Sequence[Mapping[str, Any]],
    window: tuple[str, str, str, str],
    *,
    horizon: int,
    score_field: str = "score",
) -> WindowResult:
    """検証区間のシグナルだけで層別成績を出す。"""

    train_start, train_end, test_start, test_end = window
    in_test = [
        record for record in records
        if test_start <= str(record.get("signal_date") or "") <= test_end
    ]
    buckets = summarise_buckets(in_test, horizon=horizon, score_field=score_field)
    monotonic, detail = check_monotonic(buckets)
    deciles = summarise_deciles(in_test, horizon=horizon, score_field=score_field)
    decile_monotonic, decile_detail = check_monotonic(deciles)

    top = next((b for b in deciles if b.label == DECILE_LABELS[0]), None)
    bottom = next((b for b in deciles if b.label == DECILE_LABELS[-1]), None)
    spread = None
    if (
        top is not None and bottom is not None
        and top.reliable and bottom.reliable
        and top.median_excess_topix is not None and bottom.median_excess_topix is not None
    ):
        spread = top.median_excess_topix - bottom.median_excess_topix

    return WindowResult(
        train_start=train_start, train_end=train_end,
        test_start=test_start, test_end=test_end,
        horizon=horizon, samples=len(in_test),
        buckets=buckets, deciles=deciles,
        monotonic=monotonic, monotonic_detail=detail,
        decile_monotonic=decile_monotonic, decile_detail=decile_detail,
        top_bottom_spread=spread,
    )


def summarise_run(results: Sequence[WindowResult]) -> dict[str, Any]:
    """複数窓をまとめた結論。「一度でも単調」ではなく「安定して単調」を見る。"""

    # 絶対点のバケットは米国版由来の閾値なので、日本株の断面では上位層に
    # ほとんど入らないことがある。順位付け能力の判定は **分位** を主とし、
    # 絶対点の結果は参考として併記する。
    judged = [result for result in results if result.decile_monotonic is not None]
    monotonic_count = sum(1 for result in judged if result.decile_monotonic)
    spreads = [r.top_bottom_spread for r in results if r.top_bottom_spread is not None]
    positive_spread = sum(1 for value in spreads if value > 0)
    verdict = "insufficient_data"
    if judged:
        share = monotonic_count / len(judged)
        if share >= 0.8:
            verdict = "monotonic"
        elif share >= 0.5:
            verdict = "weak"
        else:
            verdict = "not_monotonic"
    return {
        "windows": len(results),
        "windows_judged": len(judged),
        "windows_monotonic": monotonic_count,
        "windows_with_spread": len(spreads),
        "windows_positive_spread": positive_spread,
        "median_top_bottom_spread": (
            sorted(spreads)[len(spreads) // 2] if spreads else None
        ),
        "verdict": verdict,
        "note": (
            "verdict=monotonic 以外のとき、100 点満点の分数を『確率的な意味を持つ』"
            "と説明してはいけない。順位付けの材料としてのみ扱うこと。"
        ),
    }


__all__ = [
    "BUCKET_LABELS",
    "DECILE_LABELS",
    "assign_deciles",
    "summarise_deciles",
    "BucketStats",
    "MIN_BUCKET_SAMPLES",
    "SCORE_BUCKETS",
    "WindowResult",
    "bucket_of",
    "check_monotonic",
    "evaluate_window",
    "summarise_buckets",
    "summarise_run",
    "walk_forward_windows",
]
