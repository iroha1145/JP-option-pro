"""確定的な説明文。**モデルに理由を作らせない。**

出せるのは、数えたもの・比べたもの・見えないものだけ。「機関が仕込んでいる」
「意図的に売り崩している」といった内心の推定は出さない。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .states import (
    STATE_ABSORPTION,
    STATE_COVERING_START,
    STATE_DIVERGENCE_FAILED,
    STATE_LOW_CONFLICT,
    STATE_NORMAL_SHORTING,
    STATE_NO_SIGNAL,
    STATE_SQUEEZE_CONFIRMED,
)

STATE_LABELS: dict[str, str] = {
    STATE_NORMAL_SHORTING: "正常做空",
    STATE_LOW_CONFLICT: "低位冲突",
    STATE_ABSORPTION: "卖压吸收",
    STATE_COVERING_START: "回补启动",
    STATE_SQUEEZE_CONFIRMED: "挤空确认",
    STATE_DIVERGENCE_FAILED: "背离失效",
    STATE_NO_SIGNAL: "无公开空头动向",
}

#: 状態ごとの但し書き。**「挤空确认」には必ず付ける。**
STATE_CAVEATS: dict[str, str] = {
    STATE_SQUEEZE_CONFIRMED: (
        "「挤空确认」是基于公开空头变化和价格行为的模型分类，"
        "不表示掌握全部市场空头仓位。"
    ),
    STATE_ABSORPTION: "承接迹象来自价格对公开空头压力的反应，不代表机构正在吸筹。",
    STATE_LOW_CONFLICT: "深度低位只表示处于较低价格区域，不表示一定见底。",
    STATE_COVERING_START: "公开空头减少只说明报告义务范围内的仓位下降，剩余仓位未知。",
}


def _pct(value: Any, digits: int = 2) -> str | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return f"{number * 100:.{digits}f}%"


def _num(value: Any, digits: int = 2) -> str | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return f"{number:.{digits}f}"


def describe(
    snapshot: Mapping[str, Any], holders: Sequence[Mapping[str, Any]] = ()
) -> dict[str, Any]:
    """スナップショット 1 件 → 事実の列挙 + 但し書き。"""

    lines: list[str] = []

    reporting = [h for h in holders if h.get("visibility_status") == "reporting"]
    below = [h for h in holders if h.get("visibility_status") == "below_public_threshold"]
    ratio = _pct(snapshot.get("visible_short_ratio"))
    if ratio and reporting:
        lines.append(f"当前处于报告义务中的机构 {len(reporting)} 家，公开可见空头比例合计 {ratio}。")
    elif not reporting:
        lines.append("当前没有处于报告义务中的机构，公开可见空头比例为 0。")
    if below:
        lines.append(
            f"另有 {len(below)} 家已跌破公开披露门槛——该机构已降至门槛以下，"
            "实际剩余仓位未知，未计入合计。"
        )

    pressure = snapshot.get("pressure_adv20_20d")
    pressure_text = _num(pressure)
    if pressure_text is not None and abs(float(pressure)) >= 0.01:
        direction = "增加" if float(pressure) > 0 else "减少"
        lines.append(
            f"过去 20 个交易日公开空头{direction}，规模相当于约 {abs(float(pressure)):.2f} 个"
            "20 日平均成交量。"
        )

    rel_topix = _pct(snapshot.get("rel_topix_20d"))
    rel_sector = _pct(snapshot.get("rel_sector_20d"))
    if rel_topix and rel_sector:
        lines.append(f"同期相对 TOPIX {rel_topix}，相对东证33行业 {rel_sector}。")

    days = snapshot.get("visible_days_to_cover")
    if days is not None:
        lines.append(
            f"公开可见回补天数约 {_num(days)} 天（仅按可见部分计算，不是市场总空头回补天数）。"
        )

    counts = [
        (snapshot.get("entry_count_20d"), "家新规进入"),
        (snapshot.get("reentry_count_20d"), "家重新进入"),
        (snapshot.get("reduction_count_20d"), "家减仓"),
        (snapshot.get("threshold_exit_count_20d"), "家跌破门槛"),
    ]
    moves = [f"{int(value)}{label}" for value, label in counts if value]
    if moves:
        lines.append("过去 20 个交易日：" + "、".join(moves) + "。")

    state = str(snapshot.get("primary_state") or STATE_NO_SIGNAL)
    label = STATE_LABELS.get(state, state)
    confidence = snapshot.get("data_confidence")
    lines.append(
        f"当前被分类为「{label}」，数据置信度 {_num(confidence, 2) or '—'}。"
        "该结果是模型分类，不代表机构意图。"
    )

    return {
        "state": state,
        "state_label": label,
        "lines": lines,
        "caveat": STATE_CAVEATS.get(state),
    }


__all__ = ["STATE_CAVEATS", "STATE_LABELS", "describe"]
