"""機関空売り行動分（0〜100）と監視優先度。

**上昇確率ではない。** 同じ日の銘柄を並べ替えるための研究用の点数で、
歴史検証を通るまでは正式な突破品質分に一切書き込まない（影子評分）。

重みは初期パラメータ。「日本株の最適重み」とは書かない —— まだ測っていない。
"""

from __future__ import annotations

from typing import Any, Mapping

#: 評分の版。重み・合成規則を変えたら上げる。
SCORE_VERSION = "sbscore-v1"

#: 歴史検証を通っていないので、影子評分としてしか使わない。
SCORE_VALIDATED = False

#: 検証の**結果**。「まだ検証していない」と「検証したが通らなかった」は別のこと。
#: 通らなかったのに `未検証` と出し続けるのは、事実を弱めて伝えることになる。
#:
#: 2017-01〜2026-06、62,609 信号、16 窓（走步）。すべての状態がすべての保有
#: 期間で TOPIX を下回り、重みが最大の `absorption`（0.30）が最悪だった。
#: 詳細は docs/round-12-delivery.md §12。
VALIDATION: dict[str, Any] = {
    "status": "failed",
    "run": "2017-01-01..2026-06-30",
    "signals": 62609,
    "windows": 16,
    "summary": (
        "首次走步验证结论为否定：所有状态在所有持有期都跑输 TOPIX；"
        "权重最高的「卖压吸收」表现最差（−2.55%），而看空的「背离失效」"
        "反而略好于基准 —— 看多与看空两个状态的排序是反的。"
        "分数目前只能作为描述性分类，不能作为预期超额收益的排序。"
    ),
    # 首轮验证自身的已知缺陷（第十三轮审阅确认，已在 evt-v3 修正数据语义）：
    # 入场用了公开日当日收盘（JPX 当日 16:00 截止公布，当日收盘不可得）、
    # 变化量来自可视合计差（跌破门槛被放大成清仓）、行业中位取自回放子集。
    # 修正后的重跑未完成前，上面的数字只能读作「未通过」，不能读作精确幅度。
    "caveats": [
        "entry_used_same_day_close",
        "deltas_from_visible_total_diff",
        "sector_median_from_replay_subset",
    ],
    "document": "docs/round-12-delivery.md#12",
}

#: 初期重み（合計 1.0）。検証前に「最適」と書かないこと。
WEIGHTS: dict[str, float] = {
    "absorption": 0.30,
    "covering": 0.22,
    "low_position": 0.18,
    "short_pressure": 0.15,
    "rotation": 0.08,
    "catalyst": 0.07,
}

#: リスクの減点上限。減点は **順位に効く**（表示だけの飾りにしない）。
MAX_RISK_PENALTY = 25.0


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def behavior_score(components: Mapping[str, Any]) -> dict[str, Any]:
    """分項 → 総合。

    欠けている分項は **0 点として足さず**、重みごと外して残りで割り直す。
    欠測を 0 で埋めると「データが無い銘柄」が「悪い銘柄」に化ける。
    """

    used: dict[str, float] = {}
    weight_total = 0.0
    raw = 0.0
    for key, weight in WEIGHTS.items():
        value = _num(components.get(key))
        if value is None:
            continue
        used[key] = round(value, 2)
        raw += weight * value
        weight_total += weight

    if weight_total <= 0.0:
        return {
            "raw_score": None, "risk_penalty": 0.0, "score": None,
            "components": used, "coverage": 0.0, "score_version": SCORE_VERSION,
        }

    raw_score = raw / weight_total
    risk = _num(components.get("risk")) or 0.0
    penalty = MAX_RISK_PENALTY * max(0.0, min(1.0, risk / 100.0))
    final = max(0.0, min(100.0, raw_score - penalty))

    return {
        "raw_score": round(raw_score, 2),
        "risk_penalty": round(penalty, 2),
        "score": round(final, 2),
        "components": used,
        "coverage": round(weight_total, 4),
        "score_version": SCORE_VERSION,
    }


def monitor_priority(score: float | None, confidence: float | None) -> float | None:
    """並べ替えに使う優先度。

    信頼度は **順位に効かせる**。信頼度が低い銘柄が高い点だけで上位に来ると、
    画面上は「有望候補」に見えてしまう。
    """

    value = _num(score)
    if value is None:
        return None
    weight = _num(confidence)
    weight = 1.0 if weight is None else max(0.0, min(1.0, weight))
    # 信頼度ゼロでも完全には消さない（存在は見えるが上には来ない）
    return round(value * (0.35 + 0.65 * weight), 2)


__all__ = [
    "MAX_RISK_PENALTY",
    "SCORE_VALIDATED",
    "VALIDATION",
    "SCORE_VERSION",
    "WEIGHTS",
    "behavior_score",
    "monitor_priority",
]
