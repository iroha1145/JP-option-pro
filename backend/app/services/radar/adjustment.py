"""株式分割・併合の遡及調整。

**なぜ必要か**: 一括配信 CSV には `AdjFactor` しか入っておらず、REST が返す
`AdjO/AdjH/AdjL/AdjC/AdjVo` の列そのものが無い。したがって取り込み済みの
日足は全て「未調整」で、1:2 分割は前日比 −50% の暴落、10:1 併合は +900% の
急騰として記録されている。本番 10 年分で **2,600 件・1,959 銘柄（全体の 36%）**
が該当する —— 52 週高値も最大回撤もリターンも、その銘柄では全部でたらめになる。

**規則**（J-Quants の AdjC と一致することを実測で確認）:

    調整後(t) = 生値(t) × Π{ factor(d) : d > t }

つまり「その日より **後** に起きた調整の累積」を掛ける。分割当日とそれ以降は
その分割の影響を受けない。76780（2026-07-30 に factor 0.5）で検算:

    07-29: 6330 × 0.5 = 3165  （J-Quants の AdjC = 3165）
    07-30: 3035 × 1.0 = 3035  （同 3035）

**窓の中だけで計算してよい理由**: 窓の外（もっと後）で起きた調整は窓内の
全バーに同じ係数として掛かるため、リターン・比率・相対比較では相殺される。
そして窓の最終バーには「後の調整」が無いので、**直近の値は生値のまま**になる
—— 画面に出る現在値と約定可能な価格の意味が変わらない（doc §五）。

出来高は価格と逆向きに調整する（売買代金は不変なので触らない）。
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

#: 係数として妥当な範囲。1e-6 や 1e6 のような値は調整ではなくデータ異常なので、
#: 適用すると価格が壊れる。無視して 1.0 として扱う（黙って壊すよりよい）。
MIN_FACTOR = 1e-4
MAX_FACTOR = 1e4


def _factor(bar: Mapping[str, Any]) -> float:
    value = bar.get("adjustment_factor")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 1.0
    if not math.isfinite(number) or not (MIN_FACTOR <= number <= MAX_FACTOR):
        return 1.0
    return number


def cumulative_factors(bars: Sequence[Mapping[str, Any]]) -> list[float]:
    """各バーに掛ける累積係数（そのバー **より後** の調整の積）。

    `bars` は日付昇順であること。戻り値は同じ長さで、最終要素は必ず 1.0。
    """

    size = len(bars)
    out = [1.0] * size
    running = 1.0
    for index in range(size - 1, -1, -1):
        out[index] = running
        running *= _factor(bars[index])
    return out


def has_corporate_action(bars: Sequence[Mapping[str, Any]]) -> bool:
    """この窓に調整イベントが含まれるか（テスト・診断用）。"""

    return any(_factor(bar) != 1.0 for bar in bars)


def adjusted_bar(
    bar: Mapping[str, Any], factor: float
) -> dict[str, float | None]:
    """1 本分の調整後 OHLC と出来高。

    取り込み済みの `adj_*` 列があればそれを優先する（REST 経由で入った分は
    J-Quants が計算済み）。無い場合だけ生値 × 係数で作る。
    """

    def _pick(adj_key: str, raw_key: str) -> float | None:
        stored = bar.get(adj_key)
        if stored is not None:
            try:
                number = float(stored)
            except (TypeError, ValueError):
                stored = None
            else:
                if math.isfinite(number) and number > 0:
                    return number
        raw = bar.get(raw_key)
        try:
            number = float(raw)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(number) or number <= 0:
            return None
        return number * factor

    volume = bar.get("adj_volume")
    if volume is None:
        try:
            raw_volume = float(bar.get("volume"))
        except (TypeError, ValueError):
            raw_volume = None
        # 出来高は価格と逆向き（分割で株数は増える）。売買代金は不変。
        volume = (raw_volume / factor) if (raw_volume is not None and factor) else None

    return {
        "open": _pick("adj_open", "open"),
        "high": _pick("adj_high", "high"),
        "low": _pick("adj_low", "low"),
        "close": _pick("adj_close", "close"),
        "volume": volume,
    }


def adjust_series(bars: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """窓全体を調整後の値に置き換えた新しいリストを返す（元は変更しない）。"""

    factors = cumulative_factors(bars)
    out: list[dict[str, Any]] = []
    for bar, factor in zip(bars, factors):
        merged = dict(bar)
        merged.update(adjusted_bar(bar, factor))
        merged["applied_adjustment"] = factor
        out.append(merged)
    return out


__all__ = [
    "MAX_FACTOR",
    "MIN_FACTOR",
    "adjust_series",
    "adjusted_bar",
    "cumulative_factors",
    "has_corporate_action",
]
