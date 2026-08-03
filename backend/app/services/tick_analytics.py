"""ティック（歩み値）でしか出せない日中分析。

分足では潰れてしまう情報だけを扱う:
- 大口約定: 1 約定あたりの数量分布の裾。日中の板を動かした「誰か」の足跡。
- 真の VWAP: Σ(価格×数量)/Σ数量。分足の平均では代用できない（分足内の
  約定配分が均一という誤った仮定が入る）。
- 日中出来高分布: 価格帯ごとの出来高（ボリュームプロファイル）。
- 寄付/引けの板寄せ: SessionDistinction と時刻から集合競売の 1 本を切り出す。

すべて J-Quants の Tick アドオン（CSV 一括配信）由来の確定データで計算する。
遅延気配（Yahoo）はここに一切混ぜない。
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

# 板寄せ（オークション）は寄付と引けに 1 本の巨大約定として現れる。
# 時計で 09:00 と決め打ってはいけない —— 特別気配が出た銘柄は寄りが後ろへ
# ずれる（実測: 7203 の 2026-07-31 は 09:03 寄り）。「その日の最初の約定」
# 「最後の約定」という構造で取る。後場寄りだけは 12:30 以降の最初の約定。
AFTERNOON_OPEN_FROM = "12:30"

# 「大口」の定義: 中央値の N 倍以上、かつ当日出来高の一定割合以上。
# 単純な固定株数だと、値がさ株と低位株で意味が変わってしまう。
LARGE_PRINT_MEDIAN_MULTIPLE = 25.0
LARGE_PRINT_MIN_DAY_SHARE = 0.002  # 当日出来高の 0.2%
LARGE_PRINT_MAX_ROWS = 20
VOLUME_PROFILE_BUCKETS = 24


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in (float("inf"), float("-inf")) else None


def _median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _same_instant(rows: Sequence[Mapping[str, Any]], index: int) -> list[Mapping[str, Any]]:
    """同一タイムスタンプの約定をまとめる（板寄せは 1 時刻に複数行来ることがある）。"""

    if not rows:
        return []
    stamp = str(rows[index].get("tick_time") or "")
    out = [rows[index]]
    step = -1 if index else 1
    cursor = index + step
    while 0 <= cursor < len(rows) and str(rows[cursor].get("tick_time") or "") == stamp:
        out.append(rows[cursor])
        cursor += step
    return out


def auction_prints(rows: Sequence[Mapping[str, Any]]) -> set[int]:
    """寄付・引けの板寄せに属する行インデックス（連続売買から除くため）。"""

    if not rows:
        return set()
    opening = {id(row) for row in _same_instant(rows, 0)}
    closing = {id(row) for row in _same_instant(rows, len(rows) - 1)}
    return opening | closing


def vwap_series(rows: Sequence[Mapping[str, Any]], *, points: int = 120) -> dict[str, Any]:
    """累積 VWAP と現値の乖離。

    VWAP は「その日に売買した平均的な参加者の値段」。終値との乖離ではなく
    各時点の価格との乖離を見たいので、累積系列で返す。
    """

    cumulative_value = 0.0
    cumulative_volume = 0.0
    series: list[dict[str, Any]] = []
    step = max(1, len(rows) // max(1, int(points)))
    last_price: float | None = None
    for index, row in enumerate(rows):
        price = _finite(row.get("price"))
        volume = _finite(row.get("volume")) or 0.0
        if price is None:
            continue
        cumulative_value += price * volume
        cumulative_volume += volume
        last_price = price
        if cumulative_volume <= 0:
            continue
        if index % step == 0 or index == len(rows) - 1:
            series.append(
                {
                    "t": str(row.get("tick_time") or "")[:8],
                    "vwap": round(cumulative_value / cumulative_volume, 2),
                    "price": price,
                }
            )
    if cumulative_volume <= 0 or last_price is None:
        return {"vwap": None, "last_price": last_price, "deviation_pct": None, "series": []}
    vwap = cumulative_value / cumulative_volume
    return {
        "vwap": round(vwap, 2),
        "last_price": last_price,
        "deviation_pct": (last_price / vwap - 1.0) if vwap else None,
        "total_volume": cumulative_volume,
        "series": series,
    }


def large_prints(
    rows: Sequence[Mapping[str, Any]],
    *,
    limit: int = LARGE_PRINT_MAX_ROWS,
) -> dict[str, Any]:
    """1 約定あたりが突出して大きい約定（板寄せは別枠で除く）。

    しきい値は中央値比 + 当日出来高比の二重条件。片方だけだと、閑散銘柄で
    ただの通常売買が並んだり、大型株で何も出なかったりする。
    """

    excluded = auction_prints(rows)
    continuous = [row for row in rows if id(row) not in excluded]
    volumes = [v for row in continuous if (v := _finite(row.get("volume"))) and v > 0]
    if not volumes:
        return {"threshold": None, "median_size": None, "rows": [], "count": 0, "volume_share": None}
    median_size = _median(volumes) or 0.0
    day_volume = sum(_finite(row.get("volume")) or 0.0 for row in rows)
    threshold = max(
        median_size * LARGE_PRINT_MEDIAN_MULTIPLE,
        day_volume * LARGE_PRINT_MIN_DAY_SHARE,
    )
    hits = [
        {
            "time": str(row.get("tick_time") or "")[:12],
            "price": _finite(row.get("price")),
            "volume": _finite(row.get("volume")),
        }
        for row in continuous
        if (_finite(row.get("volume")) or 0.0) >= threshold
    ]
    hits.sort(key=lambda item: item["volume"] or 0.0, reverse=True)
    hit_volume = sum(item["volume"] or 0.0 for item in hits)
    return {
        "threshold": round(threshold),
        "median_size": median_size,
        "count": len(hits),
        "volume_share": (hit_volume / day_volume) if day_volume else None,
        "rows": hits[: max(1, int(limit))],
    }


def volume_profile(
    rows: Sequence[Mapping[str, Any]], *, buckets: int = VOLUME_PROFILE_BUCKETS
) -> dict[str, Any]:
    """価格帯別の出来高分布と最多価格帯（POC）。"""

    prices = [p for row in rows if (p := _finite(row.get("price"))) is not None]
    if not prices:
        return {"low": None, "high": None, "poc": None, "buckets": []}
    low, high = min(prices), max(prices)
    if high <= low:
        total = sum(_finite(row.get("volume")) or 0.0 for row in rows)
        return {
            "low": low, "high": high, "poc": low,
            "buckets": [{"price_low": low, "price_high": high, "volume": total}],
        }
    count = max(4, int(buckets))
    width = (high - low) / count
    totals = [0.0] * count
    for row in rows:
        price = _finite(row.get("price"))
        if price is None:
            continue
        index = min(count - 1, int((price - low) / width))
        totals[index] += _finite(row.get("volume")) or 0.0
    peak = max(range(count), key=lambda i: totals[i])
    return {
        "low": low,
        "high": high,
        "poc": round(low + width * (peak + 0.5), 2),
        "total_volume": sum(totals),
        "buckets": [
            {
                "price_low": round(low + width * i, 2),
                "price_high": round(low + width * (i + 1), 2),
                "volume": totals[i],
            }
            for i in range(count)
        ],
    }


def auction_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """寄付・引けの板寄せ 1 本を切り出し、当日出来高に占める比重を出す。

    引けの板寄せが極端に大きい日はインデックス入替やリバランスの痕跡であり、
    「終値が需給で作られた」ことを示す —— 日足だけ見ていると絶対に見えない。
    """

    if not rows:
        return {"day_volume": 0.0, "opening": None, "closing": None, "afternoon_open": None}
    day_volume = sum(_finite(row.get("volume")) or 0.0 for row in rows)

    def pack(matched: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
        if not matched:
            return None
        volume = sum(_finite(row.get("volume")) or 0.0 for row in matched)
        largest = max(matched, key=lambda row: _finite(row.get("volume")) or 0.0)
        return {
            "time": str(largest.get("tick_time") or "")[:8],
            "price": _finite(largest.get("price")),
            "volume": volume,
            "prints": len(matched),
            "day_volume_share": (volume / day_volume) if day_volume else None,
        }

    afternoon_index = next(
        (
            index
            for index, row in enumerate(rows)
            if str(row.get("tick_time") or "")[:5] >= AFTERNOON_OPEN_FROM
        ),
        None,
    )
    return {
        "day_volume": day_volume,
        "opening": pack(_same_instant(rows, 0)),
        "closing": pack(_same_instant(rows, len(rows) - 1)),
        "afternoon_open": (
            pack(_same_instant(rows, afternoon_index)) if afternoon_index is not None else None
        ),
    }


def session_split(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """前場/後場の約定回数と出来高（板寄せ込み）。"""

    def bucket(row: Mapping[str, Any]) -> str:
        time_text = str(row.get("tick_time") or "")
        return "morning" if time_text[:5] < "11:35" else "afternoon"

    out = {
        "morning": {"prints": 0, "volume": 0.0},
        "afternoon": {"prints": 0, "volume": 0.0},
    }
    for row in rows:
        slot = out[bucket(row)]
        slot["prints"] += 1
        slot["volume"] += _finite(row.get("volume")) or 0.0
    return out


def analyse(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """個股頁のティック分析パック。行が無ければ全項目 None で返す（捏造しない）。"""

    ordered = list(rows)
    if not ordered:
        return {
            "available": False,
            "vwap": None,
            "large_prints": None,
            "volume_profile": None,
            "auctions": None,
            "sessions": None,
        }
    return {
        "available": True,
        "tick_count": len(ordered),
        "vwap": vwap_series(ordered),
        "large_prints": large_prints(ordered),
        "volume_profile": volume_profile(ordered),
        "auctions": auction_summary(ordered),
        "sessions": session_split(ordered),
    }


__all__ = [
    "LARGE_PRINT_MEDIAN_MULTIPLE",
    "auction_prints",
    "LARGE_PRINT_MIN_DAY_SHARE",
    "analyse",
    "auction_summary",
    "large_prints",
    "session_split",
    "volume_profile",
    "vwap_series",
]
