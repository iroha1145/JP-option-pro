"""売買代金の **安定性**（=毎日ちゃんと出来ているか）を測る。

旧実装は `turnover_today is not None → 100.0` だった。これは「売買代金の
データが存在する」以上のことを一切言っておらず、普段ほぼ商いが無く 1 日だけ
爆発した銘柄が満点の流動性安定性を得ていた。指標名と中身が食い違っている
典型なので、実際の統計に置き換える。

設計方針:

* 売買代金は対数正規に近いので **対数空間**で扱う（生の円で分散を取ると
  大型株の絶対額に支配される）。
* ばらつきは標準偏差ではなく **MAD（中央絶対偏差）**。1 日の異常出来高で
  指標が壊れないため。
* 「直近の активность が数日の突発で出来ているか」を別次元で見る
  （上位 2 日の占有率）。分散が小さくても、実は 2 日で全部という形は弾く。
* 商いゼロ・極小の日数を欠測ではなく **減点**として数える。

3 次元とも「小さいほど良い」量なので、`linear_score` に (悪い値, 良い値) の
順で渡して 0-100 に写す。
"""

from __future__ import annotations

import math

# 観測が少なすぎると MAD も占有率も意味を成さない。
MIN_OBSERVATIONS = 12
# 実質的に商いが無い日の閾値（円）。日本株の最小単位を考えると 100 万円未満は
# 「板が立っていない」に近い。
DEAD_DAY_JPY = 1_000_000.0

# MAD（log10）: 0.35 ≒ 日々 2 倍以上ぶれる、0.08 ≒ ほぼ一定。
_MAD_BAD, _MAD_GOOD = 0.35, 0.08
# 上位 2 日の占有率: 20 日なら期待値 0.10。0.45 は「2 日で半分」= 突発。
_TOP2_BAD, _TOP2_GOOD = 0.45, 0.15
# 商いゼロ日の比率。
_DEAD_BAD, _DEAD_GOOD = 0.25, 0.0

_WEIGHTS = {"dispersion": 0.50, "concentration": 0.30, "continuity": 0.20}


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    size = len(ordered)
    middle = size // 2
    if size % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _linear(value: float, low: float, high: float) -> float:
    """low→0, high→100（low > high の反転レンジも許す）。"""

    if high == low:
        return 50.0
    ratio = (value - low) / (high - low)
    return max(0.0, min(100.0, ratio * 100.0))


def turnover_stability(turnover: list[float | None]) -> float | None:
    """0-100。観測不足なら None（中立値で埋めない）。

    `turnover` は日次売買代金（円）の時系列。None / 欠測はそのまま渡してよい。
    """

    if not turnover:
        return None
    observed = [value for value in turnover if value is not None]
    if len(observed) < MIN_OBSERVATIONS:
        return None

    dead_days = sum(1 for value in observed if value < DEAD_DAY_JPY)
    live = [value for value in observed if value >= DEAD_DAY_JPY]
    if len(live) < MIN_OBSERVATIONS // 2:
        # ほとんど商いが立っていない —— 安定していないことは確かなので
        # None（判定不能）ではなく最低点を返す。
        return 0.0

    logs = [math.log10(value) for value in live]
    centre = _median(logs)
    mad = _median([abs(value - centre) for value in logs])
    dispersion = _linear(mad, _MAD_BAD, _MAD_GOOD)

    total = sum(live)
    top2 = sum(sorted(live, reverse=True)[:2])
    # 標本数が違うと期待占有率も違うので、20 日基準に正規化して比較する。
    expected = 2.0 / len(live)
    share = (top2 / total) if total > 0 else 1.0
    normalised = share * (0.10 / expected) if expected > 0 else share
    concentration = _linear(normalised, _TOP2_BAD, _TOP2_GOOD)

    continuity = _linear(dead_days / len(observed), _DEAD_BAD, _DEAD_GOOD)

    # 加重 **幾何** 平均。算術平均だと 1 つの次元が破滅していても他の満点で
    # 埋め合わされる —— 実際「普段 200 万円・2 日だけ 300 億円」は MAD が
    # ほぼ 0（58 日が同じ値なので「ぶれていない」）になり、算術平均では 70 点
    # 付いてしまった。3 条件は同時に成り立って初めて「安定」なので、どれかが
    # 崩れたら全体を引きずり下ろす形にする。
    score = 100.0
    for value, weight in (
        (dispersion, _WEIGHTS["dispersion"]),
        (concentration, _WEIGHTS["concentration"]),
        (continuity, _WEIGHTS["continuity"]),
    ):
        score *= (max(value, 1.0) / 100.0) ** weight
    return round(max(0.0, min(100.0, score)), 2)


__all__ = ["DEAD_DAY_JPY", "MIN_OBSERVATIONS", "turnover_stability"]
