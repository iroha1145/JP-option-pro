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
    CROWDING_HIGH,
    CROWDING_LOW,
    CROWDING_MID,
    STATE_BUILDING,
    STATE_COVERING,
    STATE_MIXED,
    STATE_NO_SIGNAL,
    STATE_STEADY,
    crowding_level,
)

STATE_LABELS: dict[str, str] = {
    STATE_BUILDING: "增加中",
    STATE_COVERING: "减少中",
    STATE_MIXED: "方向反复",
    STATE_STEADY: "持平",
    STATE_NO_SIGNAL: "无公开空头动向",
}

#: 状態ごとに添える範囲の補足。
STATE_CAVEATS: dict[str, str] = {
    STATE_BUILDING: "仅统计达到披露门槛的持仓，门槛以下未计入。",
    STATE_COVERING: "仅统计报告义务范围内的减持，跌破门槛后的剩余持仓不可见。",
    STATE_MIXED: "近 20 日与近 5 日净变动方向相反，机构间增减互现。",
}

#: 拥挤度の段 → 説明文（段の規則をそのまま書く。`states.CROWDING_RULES` と揃える）。
CROWDING_LINES: dict[int, str] = {
    CROWDING_HIGH: "公开空头拥挤度：高（近期机构 ≥ 4 家，或公开持仓 ≥ 4%）。",
    CROWDING_MID: "公开空头拥挤度：中（近期机构 ≥ 2 家，或公开持仓 ≥ 2%）。",
    CROWDING_LOW: "公开空头拥挤度：低（近期机构 1 家，且公开持仓 < 2%）。",
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
        say("近期更新的报告义务中机构 {n} 家，公开持仓合计 {ratio}。",
            n=len(reporting), ratio=ratio)
    elif not reporting:
        say("当前无近期更新的报告义务中机构，公开持仓比例为 0。")
    if stale:
        oldest = max((h.get("state_age_trading_days") or 0) for h in stale)
        in_scope = _pct(snapshot.get("reported_in_scope_ratio"))
        if in_scope:
            say(
                "另有 {n} 家最后报告在 {days} 个交易日之前，未计入公开持仓；含其在册合计为 {ratio}。",
                n=len(stale), days=oldest, ratio=in_scope,
            )
        else:
            say(
                "另有 {n} 家最后报告在 {days} 个交易日之前，未计入公开持仓。",
                n=len(stale), days=oldest,
            )
    if below:
        say("另有 {n} 家已跌破公开披露门槛，未计入合计。", n=len(below))
    if unknown:
        say("另有 {n} 家最新报告缺少持仓比例，未计入合计。", n=len(unknown))

    level = crowding_level(
        snapshot.get("visible_institution_count"), snapshot.get("visible_short_ratio"),
    )
    if level in CROWDING_LINES:
        say(CROWDING_LINES[level])

    # 純変化は発行済株式数に対する比率（報告と同じ単位）で言う。出来高比は
    # 「その銘柄にとってどれだけ大きいか」の補足。
    change = snapshot.get("ratio_change_20d")
    change_text = _pct(abs(float(change))) if _num(change) is not None else None
    if change_text is not None and abs(float(change)) >= 0.0001:
        pressure = snapshot.get("pressure_adv20_20d")
        size = f"{abs(float(pressure)):.2f}" if _num(pressure) is not None else None
        rising = float(change) > 0
        if size is not None and abs(float(pressure)) >= 0.01:
            say(
                "过去 20 个交易日公开空头净增加 {delta}，相当于约 {size} 个20 日平均成交量。" if rising
                else "过去 20 个交易日公开空头净减少 {delta}，相当于约 {size} 个20 日平均成交量。",
                delta=change_text, size=size,
            )
        else:
            say(
                "过去 20 个交易日公开空头净增加 {delta}。" if rising
                else "过去 20 个交易日公开空头净减少 {delta}。",
                delta=change_text,
            )

    rel_topix = _pct(snapshot.get("rel_topix_20d"))
    rel_sector = _pct(snapshot.get("rel_sector_20d"))
    if rel_topix and rel_sector:
        say("同期相对 TOPIX {topix}，相对东证33行业 {sector}。", topix=rel_topix, sector=rel_sector)

    days_to_cover = snapshot.get("visible_days_to_cover")
    if days_to_cover is not None:
        say("公开持仓回补约 {days} 天。", days=_num(days_to_cover))

    # 件数の並びは言語ごとに語順が違う。1 項目 = 1 テンプレートにして、
    # つなぎ（、）もフロント側の区切りに任せる。
    moves: list[dict[str, Any]] = []
    for value, template in (
        (snapshot.get("entry_count_20d"), "{n}家新进"),
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
    say("近 20 日动向归为「{label}」。", label=label)

    return {
        "state": state,
        "state_label": label,
        # 中文で置換済み（API 単体で読める・既存の利用者を壊さない）
        "lines": [item["template"].format(**item["params"]) for item in items],
        # テンプレート + パラメータ。UI はこちらを t() に通して翻訳する。
        "line_items": items,
        "caveat": STATE_CAVEATS.get(state),
    }


__all__ = ["CROWDING_LINES", "STATE_CAVEATS", "STATE_LABELS", "describe"]
