"""近 20 日の動向（主要状態）と補助ラベル。

**v4 で状態を作り直した。** 旧版（sbs-v3 まで）は「卖压吸收」「回补启动」
「挤空确认」「背离失效」「低位冲突」「正常做空」という、価格の読みを混ぜた
状態だった。3 回の独立した検証がどれも同じ結論を出している:

* 第十二轮の走步（2017-01〜2026-06、62,609 信号）: 全状態が全保有期間で
  TOPIX を下回り、強気側の「卖压吸收」が最悪。
* 2026-09 の事件研究（66 万イベント）: 増仓・減仓・回補のどの後も負。
* 本番に保存された日次スナップショット（2026-08〜11、当時の判定そのまま）:
  「卖压吸收」−1.5%、「挤空确认」−1.5%、「回补启动」−0.9%（20 日、同市場
  区分の中位に対する超過）。

加えて、ラベルが数字と食い違っていた（2026-11-20: 「背离失效」311 行のうち
64 行は 20 日では純減、「低位增空不跌」241 行のうち 201 行は空頭が増えて
おらず 170 行は市場に負けていた）。

だから状態は **公開された持仓比率の純変化だけ** で決める。価格の解釈は
入れない —— 価格は事実として横に並べる。閾値は 0.10 ポイント（法定の
再報告の刻み）で、報告そのものと突き合わせて確かめられる。
"""

from __future__ import annotations

from typing import Any, Mapping

#: 状態機の版。閾値や条件を変えたら上げる。
#: v4: 価格の読みを混ぜた 6 状態をやめ、公開持仓比率の純変化だけで決める
#:     5 状態にした（building / covering / mixed / steady / no_signal）。
#:     ラベルから rotation / news_catalyst / voluntary_covering /
#:     forced_covering を外した（解釈であって事実ではない）。
STATE_VERSION = "sbs-v4"

STATE_BUILDING = "building"    # 増加中
STATE_COVERING = "covering"    # 減少中
STATE_MIXED = "mixed"          # 方向反复（20 日と 5 日が逆）
STATE_STEADY = "steady"        # 持平（公開持仓はあるが動いていない）
STATE_NO_SIGNAL = "no_signal"  # 公開空頭に動きが無い

ORDERED_STATES = (
    STATE_BUILDING,
    STATE_COVERING,
    STATE_MIXED,
    STATE_STEADY,
    STATE_NO_SIGNAL,
)

#: 「動いた」と言う下限。発行済株式数に対する比率で 0.10 ポイント ——
#: 報告義務が再び生じる刻みと同じ。これ未満の純変化は報告 1 本ぶんに満たない。
CHANGE_FLOOR_RATIO = 0.001

# 拥挤度（公開空頭の集まり具合）。
CROWDING_NONE = 0
CROWDING_LOW = 1
CROWDING_MID = 2
CROWDING_HIGH = 3

#: 拥挤度の段。上から順に最初に当たった段を使う。(機関数の下限, 比率の下限)
#: のどちらかを満たせばその段。数字は検証で使った区切りそのまま
#: （機関数 0 / 1 / 2–3 / 4+、比率 2% / 4%）。
CROWDING_RULES: tuple[tuple[int, int, float], ...] = (
    (CROWDING_HIGH, 4, 0.04),
    (CROWDING_MID, 2, 0.02),
)

#: 拥挤度について分かっていること。**これ以外の読みは持たない。**
#:
#: 同じ市場区分の中位に対する 20 日超過（公開の翌営業日寄り付き → 20 営業日後
#: 終値）。本番の事件表を機関名で畳み直して 2026-08-03〜2026-10-22 の 18 断面
#: （3 営業日おき）で測った平均: 無 +0.56% / 低 +0.40% / 中 −0.15% / 高 −1.22%。
#: 窓が重なっているので独立な標本は 3 つ程度しか無い —— この数字自体は強い
#: 証拠ではない。向きが第十二轮の走步（可視機関数 0→4+ で −1.10%→−2.85%）と
#: 2026-09 の事件研究（仓位水準が高いほど悪い）と同じ、というところまで。
EVIDENCE: dict[str, Any] = {
    "status": "descriptive",
    "relation": "more_crowded_weaker",
    "sample": "2026-08-03..2026-10-22, 18 cross-sections",
    "excess_20d_by_level": {"none": 0.0056, "low": 0.0040, "mid": -0.0015, "high": -0.0122},
    "document": "docs/short-monitor.md#12",
}

# 補助ラベル
FLAG_NEW_ENTRY = "new_entry"
FLAG_REENTRY = "reentry"
FLAG_CONCENTRATED = "concentrated"
FLAG_MULTI_REDUCTION = "multi_reduction"
FLAG_BELOW_THRESHOLD = "below_threshold"
FLAG_NOT_VISIBLE = "not_visible"
FLAG_CROWDED_MARGIN = "crowded_margin"
FLAG_REGULATED = "regulated"
FLAG_EARNINGS_NEAR = "earnings_near"
FLAG_THIN_LIQUIDITY = "thin_liquidity"
FLAG_STALE_DATA = "stale_data"
FLAG_HEDGE_DISCLOSED = "hedge_disclosed"
FLAG_SINGLE_INSTITUTION = "single_institution"
#: 公開線のすぐ下に最近止まった機関がいる（潜伏空頭）。
FLAG_PARKED_BELOW = "parked_below"
#: 可視機関はいるが、全部が集合名義（個人 など）。
FLAG_NO_INFORMED_REPORTER = "no_informed_reporter"


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def crowding_level(visible_institution_count: Any, visible_short_ratio: Any) -> int:
    """公開空頭の集まり具合（0 無 / 1 低 / 2 中 / 3 高）。

    重みも合成もしない。機関数と比率という、報告と突き合わせて確かめられる
    2 つの事実に対する固定の区切りだけ。
    """

    count = int(_num(visible_institution_count) or 0)
    ratio = _num(visible_short_ratio) or 0.0
    if count <= 0:
        return CROWDING_NONE
    for level, min_count, min_ratio in CROWDING_RULES:
        if count >= min_count or ratio >= min_ratio:
            return level
    return CROWDING_LOW


def classify(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """主要状態 1 つ + 補助ラベル。

    `evidence` に要るもの（欠けていれば 0 / None 扱い）:
        ratio_change_20d, ratio_change_5d, visible_institution_count,
        entry_count_20d, reentry_count_20d, reduction_count_20d,
        threshold_exit_count_20d, concentration, parked_below_count, …
    """

    change_20 = _num(evidence.get("ratio_change_20d")) or 0.0
    change_5 = _num(evidence.get("ratio_change_5d")) or 0.0
    visible = int(evidence.get("visible_institution_count") or 0)

    up_20 = change_20 >= CHANGE_FLOOR_RATIO
    down_20 = change_20 <= -CHANGE_FLOOR_RATIO
    up_5 = change_5 >= CHANGE_FLOOR_RATIO
    down_5 = change_5 <= -CHANGE_FLOOR_RATIO

    if (up_20 and down_5) or (down_20 and up_5):
        # 20 日では増えたが直近 5 日は減っている（またはその逆）。
        state = STATE_MIXED
    elif up_20:
        state = STATE_BUILDING
    elif down_20:
        state = STATE_COVERING
    elif up_5 or down_5:
        # 20 日の純変化は刻みに届かないのに、直近 5 日は動いている ——
        # 窓の前半で逆向きに動いていたということ。
        state = STATE_MIXED
    elif visible > 0:
        state = STATE_STEADY
    else:
        state = STATE_NO_SIGNAL

    return {
        "primary_state": state,
        "flags": _flags(evidence),
        "crowding_level": crowding_level(visible, evidence.get("visible_short_ratio")),
        "state_version": STATE_VERSION,
    }


def _flags(evidence: Mapping[str, Any]) -> list[str]:
    flags: set[str] = set()
    visible = int(evidence.get("visible_institution_count") or 0)
    if int(evidence.get("parked_below_count") or 0) > 0:
        flags.add(FLAG_PARKED_BELOW)
    informed_count = evidence.get("informed_institution_count")
    if informed_count is not None and int(informed_count) == 0 and visible > 0:
        flags.add(FLAG_NO_INFORMED_REPORTER)
    if int(evidence.get("entry_count_20d") or 0) > 0:
        flags.add(FLAG_NEW_ENTRY)
    if int(evidence.get("reentry_count_20d") or 0) > 0:
        flags.add(FLAG_REENTRY)
    concentration = _num(evidence.get("concentration"))
    if visible >= 2 and concentration is not None and concentration >= 0.6:
        # 1 社だけなら集中度は定義上 1.0。それは single_institution が言う。
        flags.add(FLAG_CONCENTRATED)
    if int(evidence.get("reduction_count_20d") or 0) >= 2:
        flags.add(FLAG_MULTI_REDUCTION)
    if int(evidence.get("threshold_exit_count_20d") or 0) > 0:
        flags.add(FLAG_BELOW_THRESHOLD)
    if visible == 0:
        flags.add(FLAG_NOT_VISIBLE)
    elif visible == 1:
        flags.add(FLAG_SINGLE_INSTITUTION)
    if evidence.get("crowded_long"):
        flags.add(FLAG_CROWDED_MARGIN)
    if int(evidence.get("regulation_severity") or 0) > 0:
        flags.add(FLAG_REGULATED)
    if evidence.get("earnings_near"):
        flags.add(FLAG_EARNINGS_NEAR)
    if evidence.get("thin_liquidity"):
        flags.add(FLAG_THIN_LIQUIDITY)
    stale = evidence.get("days_since_last_report")
    if visible > 0 and stale is not None and int(stale) > 20:
        flags.add(FLAG_STALE_DATA)
    if int(evidence.get("hedge_institution_count") or 0) > 0:
        flags.add(FLAG_HEDGE_DISCLOSED)
    return sorted(flags)


__all__ = [
    "CHANGE_FLOOR_RATIO",
    "CROWDING_HIGH",
    "CROWDING_LOW",
    "CROWDING_MID",
    "CROWDING_NONE",
    "CROWDING_RULES",
    "EVIDENCE",
    "FLAG_BELOW_THRESHOLD",
    "FLAG_CONCENTRATED",
    "FLAG_CROWDED_MARGIN",
    "FLAG_EARNINGS_NEAR",
    "FLAG_HEDGE_DISCLOSED",
    "FLAG_MULTI_REDUCTION",
    "FLAG_NEW_ENTRY",
    "FLAG_NOT_VISIBLE",
    "FLAG_NO_INFORMED_REPORTER",
    "FLAG_PARKED_BELOW",
    "FLAG_REENTRY",
    "FLAG_REGULATED",
    "FLAG_SINGLE_INSTITUTION",
    "FLAG_STALE_DATA",
    "FLAG_THIN_LIQUIDITY",
    "ORDERED_STATES",
    "STATE_BUILDING",
    "STATE_COVERING",
    "STATE_MIXED",
    "STATE_NO_SIGNAL",
    "STATE_STEADY",
    "STATE_VERSION",
    "classify",
    "crowding_level",
]
