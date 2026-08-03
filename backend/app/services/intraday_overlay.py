"""夜間断面に遅延気配を重ねる「オーバーレイ」。

**再スキャンではない。** レーダーとスクリーナーの入力 25 項目のうち、遅延気配
から作れるのは価格に直接依存するものだけで、63 日相対強度・ベース品質・
移動平均整列・ボラティリティ収縮などは何日分もの履歴が要る。それらを
遅延気配で「作り直した」ふりをするのが一番危険なので、しない。

やるのは 1 つだけ: 夜間に確定した基準（ピボット、252 日高値、移動平均）に
対して **今の値段がどこにいるか** を引き直す。答えたい問いはこれ:

    「昨夜の候補のうち、今まさにピボットを超えているのはどれか」

スコアは夜間のまま動かさない（遅延・非公式の値でスコアを書き換えない）。
出来高は意図的に触らない —— 場中の出来高は 1 日分の途中経過なので、20 日
平均と比べるには時間帯別の正規化曲線が要る。それ無しの「出来高確認」は
午前は全部否決・大引け前は全部通過という嘘になる。
"""

from __future__ import annotations

from typing import Any, Mapping


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in (float("inf"), float("-inf")) else None


def _reference_from_ratio(close: float | None, ratio: float | None) -> float | None:
    """`close / 参照 - 1 = ratio` を参照価格に解く（夜間の基準を復元する）。"""

    if close is None or ratio is None or ratio <= -1.0:
        return None
    return close / (1.0 + ratio)


def overlay_row(row: Mapping[str, Any], live_price: float | None) -> dict[str, Any] | None:
    """1 行分の「今どこにいるか」。live_price が無ければ None（欠落として扱う）。"""

    price = _finite(live_price)
    close = _finite(row.get("close"))
    if price is None or close is None or close <= 0:
        return None
    high_252 = _reference_from_ratio(close, _finite(row.get("pct_from_high_252")))
    ma25 = _reference_from_ratio(close, _finite(row.get("ma25_gap_pct")))
    ma75 = _reference_from_ratio(close, _finite(row.get("ma75_gap_pct")))
    ma200 = _reference_from_ratio(close, _finite(row.get("ma200_gap_pct")))
    return {
        "live_price": price,
        # 前営業日終値に対する当日騰落（気配の previous_close ではなく、こちらが
        # 保持している公式終値を基準にする —— 基準を一本化しないと符号が揺れる）
        "live_change_pct": price / close - 1.0,
        "live_pct_from_high_252": (price / high_252 - 1.0) if high_252 else None,
        "live_ma25_gap_pct": (price / ma25 - 1.0) if ma25 else None,
        "live_ma75_gap_pct": (price / ma75 - 1.0) if ma75 else None,
        "live_ma200_gap_pct": (price / ma200 - 1.0) if ma200 else None,
    }


def overlay_event(event: Mapping[str, Any], live_price: float | None) -> dict[str, Any] | None:
    """レーダー事件に対する「今ピボットの上か下か」。"""

    price = _finite(live_price)
    pivot = _finite(event.get("pivot_price"))
    if price is None:
        return None
    pack: dict[str, Any] = {"live_price": price}
    if pivot and pivot > 0:
        pack["pivot_price"] = pivot
        pack["pivot_distance_pct"] = price / pivot - 1.0
        pack["above_pivot"] = price > pivot
    return pack


def build_overlay(
    rows: list[Mapping[str, Any]],
    quotes: Mapping[str, Any],
    *,
    key: str = "canonical_code",
) -> dict[str, dict[str, Any]]:
    """{code: overlay}。気配の取れなかった銘柄は入らない（古い値で埋めない）。"""

    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = row.get(key)
        quote = quotes.get(code)
        if code is None or quote is None:
            continue
        price = getattr(quote, "price", None)
        if price is None and isinstance(quote, Mapping):
            price = quote.get("price")
        pack = overlay_row(row, price)
        if pack is not None:
            out[str(code)] = pack
    return out


__all__ = ["build_overlay", "overlay_event", "overlay_row"]
