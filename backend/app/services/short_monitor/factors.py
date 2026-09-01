"""機関空売り行動の因子。

すべて **公開済み情報だけ** で組み立てる。単純な割り算で極値を作らないため、
生の比は一度作ってから **同じ日の横断面での分位** に落とす（絶対閾値を
どこかから輸入しない）。日本株の分布に合わせた閾値を持っていないので、
「この日の全銘柄の中でどのくらいか」に置き換えるのが正直なやり方。

因子は独立に読めるように分けてある。総合点は最後に合成するだけで、
どれか 1 つが壊れても他が見えるようにしておく。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

#: 因子計算の版。定義を変えたら上げる（スナップショットに載る）。
FACTOR_VERSION = "sbf-v1"

#: 圧力がこれ未満の銘柄で「吸収された/されなかった」を語らない。
#: 20 日平均出来高の 2% 相当の建玉変化。これ未満は値動きの説明にならない。
MIN_PRESSURE_ADV20 = 0.02

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


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _saturating(value: float, scale: float) -> float:
    """0 以上の量を 0〜100 に潰す。大きいほど 100 に漸近するが飽和する。

    `value = scale` でおよそ 63 点。単純な線形や割り算だと、1 銘柄の極端な
    値がスケール全体を支配する。
    """

    if value <= 0.0 or scale <= 0.0:
        return 0.0
    return _clamp(100.0 * (1.0 - math.exp(-value / scale)))


def percentile_rank(values: Sequence[float], target: float) -> float | None:
    """`values` の中で `target` が下から何 % か（0〜1）。"""

    usable = [v for v in values if v is not None]
    if len(usable) < 2:
        return None
    below = sum(1 for v in usable if v < target)
    equal = sum(1 for v in usable if v == target)
    return (below + 0.5 * equal) / len(usable)


# ---------------------------------------------------------------------------
# 1. 低位程度
# ---------------------------------------------------------------------------

def low_position(
    *,
    close: float | None,
    high_52w: float | None,
    closes_252: Sequence[float],
    ma200: float | None,
) -> dict[str, Any]:
    """どれだけ深く売られた位置にいるか。**底だとは言っていない。**"""

    close_value = _finite(close)
    if close_value is None or close_value <= 0.0:
        return {"score": None, "drawdown_52w": None, "price_percentile_252": None}

    high = _finite(high_52w)
    drawdown = (close_value / high - 1.0) if (high and high > 0.0) else None

    usable = [v for v in (_finite(c) for c in closes_252) if v is not None and v > 0.0]
    percentile = percentile_rank(usable, close_value) if len(usable) >= 60 else None

    ma = _finite(ma200)
    below_ma = ((close_value / ma) - 1.0) if (ma and ma > 0.0) else None

    parts: list[float] = []
    if drawdown is not None:
        # −50% で満点。−10% ではほとんど点が付かない。
        parts.append(_saturating(max(0.0, -drawdown), 0.35))
    if percentile is not None:
        parts.append(_clamp(100.0 * (1.0 - percentile)))
    if below_ma is not None:
        parts.append(_saturating(max(0.0, -below_ma), 0.20))

    return {
        "score": round(sum(parts) / len(parts), 2) if parts else None,
        "drawdown_52w": round(drawdown, 6) if drawdown is not None else None,
        "price_percentile_252": round(percentile, 4) if percentile is not None else None,
        "below_ma200_pct": round(below_ma, 6) if below_ma is not None else None,
    }


# ---------------------------------------------------------------------------
# 2. 公開空頭圧力
# ---------------------------------------------------------------------------

def short_pressure(
    *,
    shares_change: float | None,
    adv20_shares: float | None,
    entries: int = 0,
    reentries: int = 0,
    largest_increase_shares: float | None = None,
) -> dict[str, Any]:
    """公開空頭の変化が、その銘柄の平常の出来高に比べてどれだけ大きいか。

    比率の変化だけで時価総額の違う銘柄を比べない。株数の変化を 20 日平均
    出来高で割った `pressure_adv20`（= 何日分の出来高に相当するか）が主役。
    """

    change = _finite(shares_change)
    adv = _finite(adv20_shares)
    if change is None or adv is None or adv <= 0.0:
        return {"score": None, "pressure_adv20": None, "known": False}

    pressure = change / adv
    capped = max(-WINSOR_LIMIT, min(WINSOR_LIMIT, pressure))
    score = _saturating(max(0.0, capped), 0.30)
    # 新規/再参入が複数あると、同じ株数でも「合意の広がり」が違う。
    breadth = min(20.0, 6.0 * (entries + reentries))
    largest = _finite(largest_increase_shares)
    concentrated = bool(largest is not None and change > 0 and largest >= 0.8 * change)

    return {
        "score": round(_clamp(score + breadth), 2),
        "pressure_adv20": round(capped, 6),
        "entries": int(entries),
        "reentries": int(reentries),
        "single_institution_driven": concentrated,
        "known": True,
    }


# ---------------------------------------------------------------------------
# 3. 価格の傷み と 売り圧の吸収
# ---------------------------------------------------------------------------

@dataclass
class DamageInput:
    """吸収判定に要る素材。横断面に載せる前の生の比を作る。"""

    pressure_adv20: float | None
    rel_topix: float | None
    rel_sector: float | None
    made_new_low: bool = False
    close_position_in_range: float | None = None   # 当日足の終値位置 0〜1

    def raw_damage(self) -> float | None:
        """圧力 1 単位あたり、市場対比でどれだけ削られたか。

        圧力が小さいときは何も言わない（`None`）。小さい分母で割って極端な
        値を作るのが、この種の指標で一番よくある壊れ方。
        """

        pressure = _finite(self.pressure_adv20)
        if pressure is None or pressure < MIN_PRESSURE_ADV20:
            return None
        # 市場対比と業種対比の **弱いほう** を採る（都合のいいほうを選ばない）
        excess = _weaker(self.rel_topix, self.rel_sector)
        if excess is None:
            return None
        return max(-WINSOR_LIMIT, min(WINSOR_LIMIT, -excess / pressure))


def _weaker(a: float | None, b: float | None) -> float | None:
    values = [v for v in (_finite(a), _finite(b)) if v is not None]
    return min(values) if values else None


def absorption_from_percentile(
    damage_percentile: float | None, *, made_new_low: bool, consistent: bool
) -> dict[str, Any]:
    """横断面分位 → 吸収スコア。

    傷みが小さい（分位が低い）ほど吸収が高い。ただし
    「まだ安値を更新している」なら吸収とは呼ばない —— 更新している限り、
    売り圧はまだ効いている。
    """

    if damage_percentile is None:
        return {"absorption_score": None, "price_damage_score": None, "known": False}
    damage_score = round(_clamp(100.0 * damage_percentile), 2)
    absorption = _clamp(100.0 - damage_score)
    if made_new_low:
        absorption *= 0.4
    if not consistent:
        # 5 日と 20 日で向きが揃わないなら、1 本の窓のノイズかもしれない。
        absorption *= 0.7
    return {
        "absorption_score": round(absorption, 2),
        "price_damage_score": damage_score,
        "known": True,
    }


# ---------------------------------------------------------------------------
# 4. 公開空頭の回補
# ---------------------------------------------------------------------------

def covering(
    *,
    shares_change: float | None,
    adv20_shares: float | None,
    reducing_institutions: int = 0,
    threshold_exits: int = 0,
    rel_topix: float | None = None,
    concentrated: bool = False,
) -> dict[str, Any]:
    """公開空頭が減っていること。**残りがゼロだとは言っていない。**

    閾値割れで見えなくなった分は「その値以下」でしかないので、回補量として
    数えるのは **報告されている減少分だけ**。
    """

    change = _finite(shares_change)
    adv = _finite(adv20_shares)
    if change is None or adv is None or adv <= 0.0:
        return {"score": None, "visible_covering_adv20": None, "known": False}

    covered = max(0.0, -change) / adv
    capped = min(WINSOR_LIMIT, covered)
    score = _saturating(capped, 0.30)
    breadth = min(20.0, 5.0 * (reducing_institutions + threshold_exits))
    excess = _finite(rel_topix)
    if excess is not None and excess > 0.0:
        # 減っている最中に市場をアウトパフォームしているかどうかで意味が変わる
        score += min(20.0, 200.0 * excess)
    if concentrated:
        score *= 0.75   # 1〜2 社に偏った減少は、市場全体の見方の変化とは限らない
    return {
        "score": round(_clamp(score + breadth), 2),
        "visible_covering_adv20": round(capped, 6),
        "reducing_institutions": int(reducing_institutions),
        "threshold_exits": int(threshold_exits),
        "concentrated": bool(concentrated),
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


# ---------------------------------------------------------------------------
# 5. 機関の入れ替わり
# ---------------------------------------------------------------------------

def rotation(
    *, entries: int, reentries: int, exits: int, reductions: int, concentration: float | None
) -> dict[str, Any]:
    """一方が抜けて別が入る動き。**それ自体は強気でも弱気でもない。**"""

    incoming = int(entries) + int(reentries)
    outgoing = int(exits)
    if incoming + outgoing == 0:
        return {"score": 0.0, "incoming": 0, "outgoing": 0, "balanced": False}
    # 両側が動いているときだけ高い（片側だけなら「入れ替わり」ではない）
    balance = 2.0 * min(incoming, outgoing) / (incoming + outgoing)
    volume = _saturating(float(incoming + outgoing), 4.0)
    score = _clamp(balance * volume)
    conc = _finite(concentration)
    if conc is not None and conc > 0.6:
        # 数社しか見えていないときの「入れ替わり」は当てにならない
        score *= 0.7
    return {
        "score": round(score, 2),
        "incoming": incoming,
        "outgoing": outgoing,
        "reductions": int(reductions),
        "balanced": bool(balance >= 0.5 and incoming + outgoing >= 2),
    }


# ---------------------------------------------------------------------------
# 6. 信用取引の環境（リスク側）
# ---------------------------------------------------------------------------

def margin_environment(
    *,
    margin_long: float | None,
    margin_short: float | None,
    margin_long_change: float | None,
    adv20_shares: float | None,
    regulation_severity: int | None = None,
) -> dict[str, Any]:
    """信用買いの混雑と規制。

    機関空頭が多く、かつ **個人の信用買いも極端に混雑している** 状態は、
    「踏み上げ候補」と読むより先に「玉の構造が危うい」と読むべき場面がある。
    ここでは方向を決めず、リスク側の材料として出す。
    """

    long_balance = _finite(margin_long)
    short_balance = _finite(margin_short)
    adv = _finite(adv20_shares)
    ratio = None
    if long_balance is not None and short_balance not in (None, 0.0):
        ratio = round(long_balance / short_balance, 4)

    crowding = None
    if long_balance is not None and adv and adv > 0.0:
        crowding = round(long_balance / adv, 4)

    risk = 0.0
    if crowding is not None:
        risk += _saturating(crowding, 6.0) * 0.6
    if ratio is not None and ratio >= 10.0:
        risk += 15.0
    change = _finite(margin_long_change)
    if change is not None and adv and adv > 0.0 and change > 0:
        risk += min(15.0, 100.0 * change / adv)
    severity = int(regulation_severity or 0)
    risk += {0: 0.0, 1: 5.0, 2: 10.0, 3: 18.0, 4: 26.0}.get(severity, 0.0)

    return {
        "score": round(_clamp(risk), 2),
        "margin_ratio": ratio,
        "long_crowding_adv20": crowding,
        "regulation_severity": severity,
        "crowded_long": bool(crowding is not None and crowding >= 5.0),
        "known": crowding is not None or ratio is not None or severity > 0,
    }


# ---------------------------------------------------------------------------
# 7. データ信頼度
# ---------------------------------------------------------------------------

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
    """この銘柄の判定をどれだけ信じてよいか（0〜1）。

    古い・薄い・見えない要素があるほど下げる。**リスク無しとは仮定しない。**
    """

    reasons: list[str] = []
    confidence = 1.0

    mapping = _finite(mapping_confidence)
    if mapping is not None and mapping < 1.0:
        confidence *= max(0.5, mapping)
        reasons.append("institution_mapping_uncertain")

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
        # 「規制なし」と確信してはいけないので信頼度を下げる。
        confidence *= 0.9
        reasons.append("regulation_unknown")

    value = _finite(adv20_value)
    if value is not None and value < 50_000_000.0:
        confidence *= 0.7
        reasons.append("thin_liquidity")

    return {"confidence": round(max(0.0, min(1.0, confidence)), 4), "reasons": reasons}


# ---------------------------------------------------------------------------
# 8. 催化剂
# ---------------------------------------------------------------------------

def catalyst(
    *, trading_days_to_earnings: int | None, news_count_5d: int = 0, has_news_feed: bool = True
) -> dict[str, Any]:
    """決算とニュース。**無ければ「中立」ではなく「無い」。**"""

    if not has_news_feed and trading_days_to_earnings is None:
        return {"score": None, "available": False, "items": []}

    items: list[str] = []
    score = 0.0
    days = trading_days_to_earnings
    if days is not None and 0 <= days <= 10:
        score += 60.0 - 4.0 * days
        items.append("earnings_within_10_trading_days")
    if news_count_5d > 0:
        score += min(40.0, 12.0 * news_count_5d)
        items.append("recent_news")
    if not items:
        return {"score": None, "available": True, "items": []}
    return {"score": round(_clamp(score), 2), "available": True, "items": items}


@dataclass
class FactorBundle:
    """1 銘柄 1 日分の因子。合成前の素材をそのまま持ち回る。"""

    low_position: dict[str, Any] = field(default_factory=dict)
    pressure: dict[str, Any] = field(default_factory=dict)
    absorption: dict[str, Any] = field(default_factory=dict)
    covering: dict[str, Any] = field(default_factory=dict)
    rotation: dict[str, Any] = field(default_factory=dict)
    margin: dict[str, Any] = field(default_factory=dict)
    catalyst: dict[str, Any] = field(default_factory=dict)
    confidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "low_position": self.low_position,
            "pressure": self.pressure,
            "absorption": self.absorption,
            "covering": self.covering,
            "rotation": self.rotation,
            "margin": self.margin,
            "catalyst": self.catalyst,
            "confidence": self.confidence,
        }


__all__ = [
    "DamageInput",
    "FACTOR_VERSION",
    "FactorBundle",
    "MIN_PRESSURE_ADV20",
    "absorption_from_percentile",
    "catalyst",
    "covering",
    "data_confidence",
    "low_position",
    "margin_environment",
    "percentile_rank",
    "rotation",
    "short_pressure",
    "visible_days_to_cover",
]
