"""機関空売りの **事実量**。

すべて公開済み情報だけで組み立てる。v3 でここから「点数」を全部外した ——
吸収・回補・入れ替わり・催化剤の各スコアとその合成（行動分）は、3 回の検証で
どれも順位付けの力が無いか逆向きだった（`states.py` の冒頭を参照）。残したのは
報告や日足と突き合わせて確かめられる量だけで、解釈は付けない。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

#: 因子計算の版。定義を変えたら上げる（スナップショットに載る）。
#: v2: 回補の広がりから `threshold_exits` を外す。潜伏空頭 `parked_below_count`
#:     と `combined_visible_days_to_cover` を追加。
#: v3: 点数（低位・圧力・吸収・価格損害・回補・入れ替わり・催化剤・リスク）を
#:     廃止し、事実量だけを残す。データ信頼度から「正規化で表記が一致した」
#:     だけの減点を外す —— 大手の報告主体はほぼ全部が大小文字違いの表記を
#:     持つので、可視空頭のある 1,564 銘柄中 1,450 銘柄が一律に下がり、
#:     信頼度が銘柄を区別しなくなっていた。
FACTOR_VERSION = "sbf-v3"

#: 「公開線の下に駐めている」とみなす最終報告の下限比率と、その新鮮さ。
PARKED_BELOW_FLOOR_RATIO = 0.004
PARKED_BELOW_MAX_AGE_TRADING_DAYS = 60

#: 比の外れ値を切る位置（片側）。1 社の巨大報告で分布が壊れるのを防ぐ。
WINSOR_LIMIT = 5.0


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def percentile_rank(values: Sequence[float], target: float) -> float | None:
    """`values` の中で `target` が下から何 % か（0〜1）。"""

    usable = [v for v in values if v is not None]
    if len(usable) < 2:
        return None
    below = sum(1 for v in usable if v < target)
    equal = sum(1 for v in usable if v == target)
    return (below + 0.5 * equal) / len(usable)


# ---------------------------------------------------------------------------
# 1. 価格の位置
# ---------------------------------------------------------------------------

def low_position(
    *,
    close: float | None,
    high_52w: float | None,
    closes_252: Sequence[float],
    ma200: float | None,
) -> dict[str, Any]:
    """52 週高値からの下落・252 日の価格分位・200 日線からの乖離。**底だとは言っていない。**"""

    close_value = _finite(close)
    if close_value is None or close_value <= 0.0:
        return {"drawdown_52w": None, "price_percentile_252": None, "below_ma200_pct": None}

    high = _finite(high_52w)
    drawdown = (close_value / high - 1.0) if (high and high > 0.0) else None

    usable = [v for v in (_finite(c) for c in closes_252) if v is not None and v > 0.0]
    percentile = percentile_rank(usable, close_value) if len(usable) >= 60 else None

    ma = _finite(ma200)
    below_ma = ((close_value / ma) - 1.0) if (ma and ma > 0.0) else None

    return {
        "drawdown_52w": round(drawdown, 6) if drawdown is not None else None,
        "price_percentile_252": round(percentile, 4) if percentile is not None else None,
        "below_ma200_pct": round(below_ma, 6) if below_ma is not None else None,
    }


# ---------------------------------------------------------------------------
# 2. 公開空頭の変化（出来高比）
# ---------------------------------------------------------------------------

def short_pressure(
    *,
    shares_change: float | None,
    adv20_shares: float | None,
    entries: int = 0,
    reentries: int = 0,
) -> dict[str, Any]:
    """公開空頭の変化が、その銘柄の平常の出来高の何日分に当たるか。

    `pressure_adv20 = 株数の変化 / 20 日平均出来高`。正なら増加、負なら減少。
    外れ値は ±`WINSOR_LIMIT` で切る。
    """

    change = _finite(shares_change)
    adv = _finite(adv20_shares)
    if change is None or adv is None or adv <= 0.0:
        return {"pressure_adv20": None, "known": False}

    pressure = change / adv
    capped = max(-WINSOR_LIMIT, min(WINSOR_LIMIT, pressure))
    return {
        "pressure_adv20": round(capped, 6),
        "entries": int(entries),
        "reentries": int(reentries),
        "known": True,
    }


def visible_days_to_cover(
    visible_short_shares: float | None, adv20_shares: float | None
) -> float | None:
    """公開可視分の建玉が、平常の出来高で何日分か。

    **市場全体の回補日数ではない。** 見えている分だけの下限であって、
    実際の空売り総量はこれより大きいことが普通。
    """

    shares = _finite(visible_short_shares)
    adv = _finite(adv20_shares)
    if shares is None or adv is None or adv <= 0.0:
        return None
    return round(min(500.0, max(0.0, shares / adv)), 4)


def combined_visible_days_to_cover(
    visible_short_shares: float | None,
    margin_short_shares: float | None,
    adv20_shares: float | None,
) -> float | None:
    """機関の可視分 + 信用売残（2026-09-25から日次、以前は週次）を平常出来高で割った日数。

    信用売残は個人の空売り。機関の可視分だけより「回補されうる量」に近いが、
    それでも 0.5% 未満の機関建玉と貸株市場の残りは見えない —— 名前に
    `visible` を残す。どちらか欠けたら出さない（片方だけを合計と呼ばない）。
    """

    shares = _finite(visible_short_shares)
    margin = _finite(margin_short_shares)
    adv = _finite(adv20_shares)
    if shares is None or margin is None or adv is None or adv <= 0.0:
        return None
    return round(min(500.0, max(0.0, (shares + margin) / adv)), 4)


def parked_below_count(
    states: Mapping[str, Mapping[str, Any]],
    *,
    floor_ratio: float = PARKED_BELOW_FLOOR_RATIO,
    max_age_trading_days: int = PARKED_BELOW_MAX_AGE_TRADING_DAYS,
) -> int:
    """公開線のすぐ下（既定 0.40〜0.50%）に **最近** 止まった機関の数。

    閾値割れの最終報告の 79% がこの帯に落ちる（2025-09〜の実測）。欧州の
    データでは公開線の下に留まる空頭は **より悪い** 後続収益に対応する
    （Jank–Roling–Smajlbegovic, JFE 2021）。「見えなくなった」を中立にも
    ゼロにも読まず、潜伏している売り方として数える。
    """

    count = 0
    for state in states.values():
        if state.get("visibility_status") != "below_public_threshold":
            continue
        ratio = _finite(state.get("last_reported_ratio"))
        if ratio is None or ratio < floor_ratio:
            continue
        age = state.get("state_age_trading_days")
        if age is not None and int(age) > max_age_trading_days:
            continue
        count += 1
    return count


# ---------------------------------------------------------------------------
# 3. 信用取引の環境
# ---------------------------------------------------------------------------

def margin_environment(
    *,
    margin_long: float | None,
    margin_short: float | None,
    adv20_shares: float | None,
    regulation_severity: int | None = None,
) -> dict[str, Any]:
    """信用買いの混雑と規制。方向は決めない —— 事実として出す。"""

    long_balance = _finite(margin_long)
    short_balance = _finite(margin_short)
    adv = _finite(adv20_shares)
    ratio = None
    if long_balance is not None and short_balance not in (None, 0.0):
        ratio = round(long_balance / short_balance, 4)

    crowding = None
    if long_balance is not None and adv and adv > 0.0:
        crowding = round(long_balance / adv, 4)

    severity = int(regulation_severity or 0)
    return {
        "margin_ratio": ratio,
        "long_crowding_adv20": crowding,
        "regulation_severity": severity,
        "crowded_long": bool(crowding is not None and crowding >= 5.0),
        "known": crowding is not None or ratio is not None or severity > 0,
    }


# ---------------------------------------------------------------------------
# 4. データ信頼度
# ---------------------------------------------------------------------------

#: これ未満の対応づけ信頼度だけを減点する。正規化で表記が一致しただけ
#: （0.75）は減点しない —— 集合名義（個人 など、0.35）が対象。
MAPPING_PENALTY_BELOW = 0.75


def data_confidence(
    *,
    mapping_confidence: float | None,
    visible_institution_count: int,
    days_since_last_report: int | None,
    bars_available: int,
    below_threshold_count: int = 0,
    has_correction: bool = False,
    adv20_value: float | None = None,
    unknown_records: int = 0,
    regulation_unknown: bool = False,
) -> dict[str, Any]:
    """この銘柄の数字をどれだけ信じてよいか（0〜1）と、その理由。

    古い・薄い・見えない要素があるほど下げる。**リスク無しとは仮定しない。**
    """

    reasons: list[str] = []
    confidence = 1.0

    mapping = _finite(mapping_confidence)
    if mapping is not None and mapping < MAPPING_PENALTY_BELOW:
        confidence *= max(0.5, mapping)
        reasons.append("aggregate_reporter")

    if visible_institution_count <= 0:
        confidence *= 0.35
        reasons.append("no_visible_institution")
    elif visible_institution_count == 1:
        confidence *= 0.8
        reasons.append("single_visible_institution")

    stale = days_since_last_report
    if stale is None:
        confidence *= 0.5
        reasons.append("no_report_date")
    elif stale > 60:
        confidence *= 0.55
        reasons.append("stale_over_60_trading_days")
    elif stale > 20:
        confidence *= 0.8
        reasons.append("stale_over_20_trading_days")

    if bars_available < 252:
        confidence *= 0.7
        reasons.append("short_price_history")
    if bars_available < 60:
        confidence *= 0.6
        reasons.append("very_short_price_history")

    if below_threshold_count > 0 and visible_institution_count == 0:
        confidence *= 0.7
        reasons.append("only_below_threshold_remains")

    if has_correction:
        confidence *= 0.9
        reasons.append("correction_in_window")

    if unknown_records > 0:
        # 比率の読めない報告行がある。欠損は「解消」ではないが、判定の素材と
        # しても使えない —— その分だけ信頼を下げる。
        confidence *= 0.85
        reasons.append("unreadable_report_rows")

    if regulation_unknown:
        # 信用規制が解決できない（例: 貸借注意喚起の同期が古い）。
        confidence *= 0.9
        reasons.append("regulation_unknown")

    value = _finite(adv20_value)
    if value is not None and value < 50_000_000.0:
        confidence *= 0.7
        reasons.append("thin_liquidity")

    return {"confidence": round(max(0.0, min(1.0, confidence)), 4), "reasons": reasons}


__all__ = [
    "FACTOR_VERSION",
    "MAPPING_PENALTY_BELOW",
    "PARKED_BELOW_FLOOR_RATIO",
    "PARKED_BELOW_MAX_AGE_TRADING_DAYS",
    "WINSOR_LIMIT",
    "combined_visible_days_to_cover",
    "data_confidence",
    "low_position",
    "margin_environment",
    "parked_below_count",
    "percentile_rank",
    "short_pressure",
    "visible_days_to_cover",
]
