"""主要状態と補助ラベル。

1 つの排他的な状態に全部を押し込まない。「機関の入れ替わり」は吸収とも
低位衝突とも回補開始とも同時に起こりうるので、**ラベル**として別に持つ。

状態は上から順に判定する。より強い主張（挤空確認）ほど条件が厳しく、
満たさなければ弱い主張に落ちる。判定に使うのは公開済みの空売り変化と
価格の反応だけで、機関の意図は推定しない。
"""

from __future__ import annotations

from typing import Any, Mapping

#: 状態機の版。閾値や条件を変えたら上げる。
#: v2: 挤空確認は 5 日と 20 日の **両方** の減少を要求（交付文書は最初から
#:     そう書いてあったが、コードは片側で通していた）。さらに強い主張には
#:     対 TOPIX と対業種の **両方のデータが存在** することを要求する ——
#:     片方欠けたまま「市場と業種の双方で転強」とは言えない。
STATE_VERSION = "sbs-v2"

#: **この閾値群は歴史検証を経ていない初期パラメータ**。
#: 「日本株の最適値」ではない。検証結果が出るまでこの表記を外さないこと。
GATES_VALIDATED = False

STATE_NORMAL_SHORTING = "normal_shorting"      # 正常做空
STATE_LOW_CONFLICT = "low_conflict"            # 低位冲突
STATE_ABSORPTION = "absorption"                # 卖压吸收
STATE_COVERING_START = "covering_start"        # 回补启动
STATE_SQUEEZE_CONFIRMED = "squeeze_confirmed"  # 挤空确认
STATE_DIVERGENCE_FAILED = "divergence_failed"  # 背离失效
STATE_NO_SIGNAL = "no_signal"                  # 公開空頭に動きが無い

ORDERED_STATES = (
    STATE_SQUEEZE_CONFIRMED,
    STATE_COVERING_START,
    STATE_ABSORPTION,
    STATE_DIVERGENCE_FAILED,
    STATE_NORMAL_SHORTING,
    STATE_LOW_CONFLICT,
    STATE_NO_SIGNAL,
)

# 補助ラベル
FLAG_NEW_ENTRY = "new_entry"
FLAG_REENTRY = "reentry"
FLAG_ROTATION = "rotation"
FLAG_CONCENTRATED = "concentrated"
FLAG_MULTI_REDUCTION = "multi_reduction"
FLAG_BELOW_THRESHOLD = "below_threshold"
FLAG_NOT_VISIBLE = "not_visible"
FLAG_CROWDED_MARGIN = "crowded_margin"
FLAG_REGULATED = "regulated"
FLAG_EARNINGS_NEAR = "earnings_near"
FLAG_NEWS_CATALYST = "news_catalyst"
FLAG_THIN_LIQUIDITY = "thin_liquidity"
FLAG_STALE_DATA = "stale_data"
FLAG_HEDGE_DISCLOSED = "hedge_disclosed"
FLAG_SINGLE_INSTITUTION = "single_institution"

#: 初期パラメータ（未検証）
GATES: dict[str, float] = {
    # 「圧力があった」と言ってよい下限（20 日平均出来高に対する比）
    "pressure_floor": 0.03,
    # 深い低位と呼ぶ下限
    "low_position_floor": 55.0,
    # 吸収と呼ぶ下限
    "absorption_floor": 60.0,
    # 回補と呼ぶ下限
    "covering_floor": 45.0,
    # 挤空確認に要る公開可視回補日数
    "squeeze_days_to_cover": 1.0,
    # 相対リターン（対 TOPIX / 業種）の改善下限
    "relative_strength_floor": 0.0,
    # 背離失効の相対悪化幅
    "breakdown_relative": -0.05,
    # 判定に足る最低データ信頼度
    "confidence_floor": 0.35,
}


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def classify(evidence: Mapping[str, Any], gates: Mapping[str, float] | None = None) -> dict[str, Any]:
    """主要状態 1 つ + 補助ラベル。

    `evidence` に要るもの（欠けていれば None 扱い）:
        pressure_adv20_20d, pressure_adv20_5d, absorption_score, price_damage_score,
        covering_score, low_position_score, rotation_score, visible_days_to_cover,
        rel_topix_20d, rel_sector_20d, breakout_confirmed, turnover_confirmed,
        made_new_low, broke_long_support, data_confidence, …
    """

    g = dict(GATES)
    g.update(gates or {})

    pressure_20 = _num(evidence.get("pressure_adv20_20d")) or 0.0
    pressure_5 = _num(evidence.get("pressure_adv20_5d")) or 0.0
    absorption = _num(evidence.get("absorption_score"))
    covering_score = _num(evidence.get("covering_score"))
    low_position = _num(evidence.get("low_position_score"))
    rel_topix = _num(evidence.get("rel_topix_20d"))
    rel_sector = _num(evidence.get("rel_sector_20d"))
    confidence = _num(evidence.get("data_confidence")) or 0.0
    days_to_cover = _num(evidence.get("visible_days_to_cover"))

    increasing = max(pressure_20, pressure_5) >= g["pressure_floor"]
    # either: どちらかの窓で減少（回補開始に使う）。
    # both: 両方の窓で減少（挤空確認に使う。片側だけなら 1 本の窓のノイズかも
    # しれない —— 文書は最初から両方と書いてある）。
    decreasing = min(pressure_20, pressure_5) <= -g["pressure_floor"]
    decreasing_both = max(pressure_20, pressure_5) <= -g["pressure_floor"]
    relative = _weakest(rel_topix, rel_sector)
    strengthening = relative is not None and relative > g["relative_strength_floor"]
    # 「市場対比・業種対比の双方で転強」は両方の値があるときにしか言えない。
    strengthening_both = (
        rel_topix is not None and rel_sector is not None
        and min(rel_topix, rel_sector) > g["relative_strength_floor"]
    )

    flags = _flags(evidence, g)
    state = _pick_state(
        evidence=evidence, gates=g, increasing=increasing, decreasing=decreasing,
        decreasing_both=decreasing_both, strengthening_both=strengthening_both,
        absorption=absorption, covering_score=covering_score, low_position=low_position,
        relative=relative, strengthening=strengthening, days_to_cover=days_to_cover,
    )

    # データが薄すぎるときに強い主張をしない。ラベルは残す（何が起きたかは事実）。
    if confidence < g["confidence_floor"] and state in (
        STATE_SQUEEZE_CONFIRMED, STATE_ABSORPTION, STATE_COVERING_START,
    ):
        state = STATE_LOW_CONFLICT if (low_position or 0.0) >= g["low_position_floor"] else STATE_NO_SIGNAL
        flags = sorted(set(flags) | {FLAG_STALE_DATA})

    return {"primary_state": state, "flags": flags, "state_version": STATE_VERSION}


def _weakest(*values: float | None) -> float | None:
    usable = [v for v in values if v is not None]
    return min(usable) if usable else None


def _pick_state(
    *, evidence, gates, increasing, decreasing, decreasing_both, strengthening_both,
    absorption, covering_score, low_position, relative, strengthening, days_to_cover,
) -> str:
    broke_support = bool(evidence.get("broke_long_support"))
    made_new_low = bool(evidence.get("made_new_low"))
    breakout = bool(evidence.get("breakout_confirmed"))
    turnover_ok = bool(evidence.get("turnover_confirmed"))

    # 1. 挤空確認 —— いちばん強い主張なので条件を全部揃える。
    # 減少は 5 日と 20 日の両方、転強は対 TOPIX と対業種の両方（データが
    # 揃っていることも条件のうち）。
    if (
        decreasing_both
        and covering_score is not None and covering_score >= gates["covering_floor"]
        and days_to_cover is not None and days_to_cover >= gates["squeeze_days_to_cover"]
        and breakout and turnover_ok and strengthening_both
    ):
        return STATE_SQUEEZE_CONFIRMED

    # 2. 背離失効 —— 空頭が増え続け、価格が長期支持を割り、相対も悪化。
    relative_bad = relative is not None and relative <= gates["breakdown_relative"]
    if increasing and broke_support and relative_bad:
        return STATE_DIVERGENCE_FAILED

    # 3. 回補開始 —— 正式な突破は要求しない。
    if decreasing and covering_score is not None and covering_score >= gates["covering_floor"] and strengthening:
        return STATE_COVERING_START

    # 4. 売り圧の吸収 —— 圧力があったのに、見合う下げが出ていない。
    if (
        increasing
        and absorption is not None and absorption >= gates["absorption_floor"]
        and not made_new_low
    ):
        return STATE_ABSORPTION

    # 5. 正常做空 —— 圧力が効いている。
    if increasing and (absorption is None or absorption < gates["absorption_floor"]):
        if relative is not None and relative < 0.0:
            return STATE_NORMAL_SHORTING

    # 6. 低位衝突 —— 深い低位に新規/再参入。まだ抗跌は証明されていない。
    if low_position is not None and low_position >= gates["low_position_floor"]:
        if increasing or evidence.get("entry_count_20d") or evidence.get("reentry_count_20d"):
            return STATE_LOW_CONFLICT

    if increasing:
        return STATE_NORMAL_SHORTING
    return STATE_NO_SIGNAL


def _flags(evidence: Mapping[str, Any], gates: Mapping[str, float]) -> list[str]:
    flags: set[str] = set()
    if int(evidence.get("entry_count_20d") or 0) > 0:
        flags.add(FLAG_NEW_ENTRY)
    if int(evidence.get("reentry_count_20d") or 0) > 0:
        flags.add(FLAG_REENTRY)
    if _num(evidence.get("rotation_score")) and float(evidence["rotation_score"]) >= 45.0:
        flags.add(FLAG_ROTATION)
    concentration = _num(evidence.get("concentration"))
    if concentration is not None and concentration >= 0.6:
        flags.add(FLAG_CONCENTRATED)
    if int(evidence.get("reduction_count_20d") or 0) >= 2:
        flags.add(FLAG_MULTI_REDUCTION)
    if int(evidence.get("threshold_exit_count_20d") or 0) > 0:
        flags.add(FLAG_BELOW_THRESHOLD)
    if int(evidence.get("visible_institution_count") or 0) == 0:
        flags.add(FLAG_NOT_VISIBLE)
    elif int(evidence.get("visible_institution_count") or 0) == 1:
        flags.add(FLAG_SINGLE_INSTITUTION)
    if evidence.get("crowded_long"):
        flags.add(FLAG_CROWDED_MARGIN)
    if int(evidence.get("regulation_severity") or 0) > 0:
        flags.add(FLAG_REGULATED)
    if evidence.get("earnings_near"):
        flags.add(FLAG_EARNINGS_NEAR)
    if evidence.get("news_catalyst"):
        flags.add(FLAG_NEWS_CATALYST)
    if evidence.get("thin_liquidity"):
        flags.add(FLAG_THIN_LIQUIDITY)
    stale = evidence.get("days_since_last_report")
    if stale is not None and int(stale) > 20:
        flags.add(FLAG_STALE_DATA)
    if int(evidence.get("hedge_institution_count") or 0) > 0:
        flags.add(FLAG_HEDGE_DISCLOSED)
    return sorted(flags)


__all__ = [
    "FLAG_BELOW_THRESHOLD",
    "FLAG_CONCENTRATED",
    "FLAG_CROWDED_MARGIN",
    "FLAG_EARNINGS_NEAR",
    "FLAG_HEDGE_DISCLOSED",
    "FLAG_MULTI_REDUCTION",
    "FLAG_NEWS_CATALYST",
    "FLAG_NEW_ENTRY",
    "FLAG_NOT_VISIBLE",
    "FLAG_REENTRY",
    "FLAG_REGULATED",
    "FLAG_ROTATION",
    "FLAG_SINGLE_INSTITUTION",
    "FLAG_STALE_DATA",
    "FLAG_THIN_LIQUIDITY",
    "GATES",
    "GATES_VALIDATED",
    "ORDERED_STATES",
    "STATE_ABSORPTION",
    "STATE_COVERING_START",
    "STATE_DIVERGENCE_FAILED",
    "STATE_LOW_CONFLICT",
    "STATE_NORMAL_SHORTING",
    "STATE_NO_SIGNAL",
    "STATE_SQUEEZE_CONFIRMED",
    "STATE_VERSION",
    "classify",
]
