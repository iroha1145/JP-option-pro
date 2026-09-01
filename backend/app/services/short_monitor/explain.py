"""確定的な説明文。**モデルに理由を作らせない。**

出せるのは、数えたもの・比べたもの・見えないものだけ。「機関が仕込んでいる」
「意図的に売り崩している」といった内心の推定は出さない。

**多言語**: 文はここで組み立てるが、サーバは相手の言語を知らない（応答は
ETag で共有される）。そこで **中文のテンプレート文字列 + パラメータ** を
返し、置換はフロントの `t()` に任せる —— この辞書は「簡体中文の原文を
msgid にする」gettext 方式なので、テンプレートをそのまま msgid にできる。
`lines` には中文で置換済みのものも従来どおり載せる（API 単体で読める）。
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

    items: list[dict[str, Any]] = []

    def say(template: str, **params: Any) -> None:
        items.append({"template": template, "params": params})

    # 「報告義務中」でも報告が止まっているものは合計に入っていない。
    # 件数だけ数えて比率を合計から取ると、行数と合計が食い違う。
    reporting = [
        h for h in holders
        if h.get("visibility_status") == "reporting" and not h.get("stale_reporting")
    ]
    stale = [h for h in holders if h.get("stale_reporting")]
    below = [h for h in holders if h.get("visibility_status") == "below_public_threshold"]
    unknown = [h for h in holders if h.get("visibility_status") == "unknown"]
    ratio = _pct(snapshot.get("visible_short_ratio"))
    if ratio and reporting:
        say("近期有更新的报告义务中机构 {n} 家，公开可见空头比例合计 {ratio}。",
            n=len(reporting), ratio=ratio)
    elif not reporting:
        say("当前没有近期更新的报告义务中机构，公开可见空头比例为 0。")
    if stale:
        oldest = max((h.get("state_age_trading_days") or 0) for h in stale)
        in_scope = _pct(snapshot.get("reported_in_scope_ratio"))
        if in_scope:
            say(
                "另有 {n} 家按官方口径仍在报告义务中，但最后一次报告已是 {days} 个交易日之前。"
                "官方规则没有失效期限——变动不足 0.1% 就无需再报，所以旧值可能仍然成立，"
                "也可能早已不同；含这些机构的在册合计为 {ratio}，上面的「公开可见」口径未计入它们。",
                n=len(stale), days=oldest, ratio=in_scope,
            )
        else:
            say(
                "另有 {n} 家按官方口径仍在报告义务中，但最后一次报告已是 {days} 个交易日之前。"
                "官方规则没有失效期限——变动不足 0.1% 就无需再报，所以旧值可能仍然成立，"
                "也可能早已不同；上面的「公开可见」口径未计入它们。",
                n=len(stale), days=oldest,
            )
    if below:
        say("另有 {n} 家已跌破公开披露门槛——该机构已降至门槛以下，实际剩余仓位未知，未计入合计。",
            n=len(below))
    if unknown:
        say("另有 {n} 家的最新报告缺少可读的比例数值，状态未知，未计入任何合计。", n=len(unknown))

    pressure = snapshot.get("pressure_adv20_20d")
    pressure_text = _num(pressure)
    if pressure_text is not None and abs(float(pressure)) >= 0.01:
        size = f"{abs(float(pressure)):.2f}"
        if float(pressure) > 0:
            say("过去 20 个交易日公开空头增加，规模相当于约 {size} 个20 日平均成交量。", size=size)
        else:
            say("过去 20 个交易日公开空头减少，规模相当于约 {size} 个20 日平均成交量。", size=size)

    rel_topix = _pct(snapshot.get("rel_topix_20d"))
    rel_sector = _pct(snapshot.get("rel_sector_20d"))
    if rel_topix and rel_sector:
        say("同期相对 TOPIX {topix}，相对东证33行业 {sector}。", topix=rel_topix, sector=rel_sector)

    days_to_cover = snapshot.get("visible_days_to_cover")
    if days_to_cover is not None:
        say("公开可见回补天数约 {days} 天（仅按可见部分计算，不是市场总空头回补天数）。",
            days=_num(days_to_cover))

    # 件数の並びは言語ごとに語順が違う。1 項目 = 1 テンプレートにして、
    # つなぎ（、）もフロント側の区切りに任せる。
    moves: list[dict[str, Any]] = []
    for value, template in (
        (snapshot.get("entry_count_20d"), "{n}家新规进入"),
        (snapshot.get("reentry_count_20d"), "{n}家重新进入"),
        (snapshot.get("reduction_count_20d"), "{n}家减仓"),
        (snapshot.get("threshold_exit_count_20d"), "{n}家跌破门槛"),
    ):
        if value:
            moves.append({"template": template, "params": {"n": int(value)}})
    if moves:
        items.append({
            "template": "过去 20 个交易日：{moves}。",
            "params": {"moves": "、".join(
                item["template"].format(**item["params"]) for item in moves
            )},
            "parts": moves,
        })

    state = str(snapshot.get("primary_state") or STATE_NO_SIGNAL)
    label = STATE_LABELS.get(state, state)
    confidence = snapshot.get("data_confidence")
    say("当前被分类为「{label}」，数据置信度 {confidence}。该结果是模型分类，不代表机构意图。",
        label=label, confidence=_num(confidence, 2) or "—")

    return {
        "state": state,
        "state_label": label,
        # 中文で置換済み（API 単体で読める・既存の利用者を壊さない）
        "lines": [item["template"].format(**item["params"]) for item in items],
        # テンプレート + パラメータ。UI はこちらを t() に通して翻訳する。
        "line_items": items,
        "caveat": STATE_CAVEATS.get(state),
    }


__all__ = ["STATE_CAVEATS", "STATE_LABELS", "describe"]
