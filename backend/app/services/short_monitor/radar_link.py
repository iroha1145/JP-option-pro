"""レーダーとの連動。**触ってよいのは `alert_priority` だけ。**

空売りの情報を正式な技術品質（`base_quality` / `breakout_confirmation` /
`intrinsic_strength`）に書き込まない。書き込み先を物理的に 1 か所に限る。

v4 で **状態由来の ± 調整を廃止した**。旧版は「挤空确认 +8 / 回补启动 +5 /
卖压吸收 +4 / 背离失效 −6」を（スイッチを切ったまま）持っていたが、その状態は
3 回の検証でどれも方向が逆か無関係だったので、状態ごと無くなった。残るのは
拥挤度の「只減不加」だけで、これも **スイッチは切ったまま** —— 空売りは参考
情報という位置づけで、レーダーの並び順は技術系スコアのまま。
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from .states import crowding_level

#: 状態由来の優先度連動。v4 で廃止（常に False、後方互換のために名前だけ残す）。
PRIORITY_LINK_ENABLED = False

#: 優先度をずらせる最大幅（100 点満点に対して）。
MAX_PRIORITY_SHIFT = 8.0

#: **拥挤度の「只減不加」叠加**。状態機とは独立に、可視機関数が多いほど
#: 優先度を **下げるだけ** の調整。第十二轮の走步で唯一安定して単調だった
#: 関係（可見機構数 0/1/2–3/4+ → 20 日超過 −1.10/−1.42/−1.98/−2.85%）を、
#: 上げる方向には一切使わず、リスク側だけに使う。
#:
#: **スイッチは切ったまま。** 空売りは参考情報という位置づけ（2026-09-02 の
#: 利用者判断）で、本番で走步検証を回す予定も無い。並び順を動かすのは
#: 利用者が明示的に求めたときだけ。仮の値は `hypothetical_crowding_shift`。
CROWDING_LINK_ENABLED = False

#: 拥挤度と後続リターンの関係について分かっていること（`states.EVIDENCE` と同じ向き）。
CROWDING_VALIDATION: dict[str, Any] = {
    "status": "not_applied",
    "summary": (
        "可见机构数越多、公开持仓越高，之后越弱——第十二轮走步、2026-09 事件研究与"
        "2026-08 至 11 月的线上快照三次方向一致。空卖定位为参考信息，叠加保持关闭，"
        "雷达排序不受影响。"
    ),
}

#: 可視機関数（informed 口径を優先、無ければ全鎖口径）に応じた素の引き下げ。
#: 上から順に最初に当たった段を使う。正の値は絶対に置かない。
CROWDING_SHIFT_BY_COUNT: tuple[tuple[int, float], ...] = (
    (4, -4.0),
    (2, -2.0),
)


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def informed_institution_count(snapshot: Mapping[str, Any] | None) -> int | None:
    """informed 口径の可視機関数。スナップショット行の components_json から読む。

    無ければ None（全鎖口径へのフォールバックは呼び出し側で判断する）。
    """

    if not snapshot:
        return None
    direct = snapshot.get("informed_institution_count")
    if direct is not None:
        return int(direct)
    raw = snapshot.get("components_json")
    components = snapshot.get("components")
    if components is None and raw:
        import json

        try:
            components = json.loads(raw)
        except ValueError:
            components = None
    informed = (components or {}).get("informed") if isinstance(components, Mapping) else None
    if isinstance(informed, Mapping) and informed.get("institution_count") is not None:
        return int(informed["institution_count"])
    return None


def hypothetical_crowding_shift(snapshot: Mapping[str, Any] | None) -> float:
    """もし拥挤度叠加が有効だったら適用される調整量。**0 以下しか返さない。**"""

    if not snapshot:
        return 0.0
    count = informed_institution_count(snapshot)
    if count is None:
        count = int(snapshot.get("visible_institution_count") or 0)
    confidence = _num(snapshot.get("data_confidence"))
    confidence = 0.0 if confidence is None else max(0.0, min(1.0, confidence))
    shift = 0.0
    for threshold, value in CROWDING_SHIFT_BY_COUNT:
        if count >= threshold:
            shift = value
            break
    shift = min(0.0, shift) * confidence
    return max(-MAX_PRIORITY_SHIFT, min(0.0, round(shift, 2)))


def crowding_shift(snapshot: Mapping[str, Any] | None) -> float:
    """実際に適用する拥挤度の調整量。**窓別検証を通るまで常に 0。**"""

    if not CROWDING_LINK_ENABLED:
        return 0.0
    return hypothetical_crowding_shift(snapshot)


def priority_shift(snapshot: Mapping[str, Any] | None) -> float:
    """実際に適用する調整量。拥挤度のスイッチが切れている間は常に 0。"""

    return max(-MAX_PRIORITY_SHIFT, min(0.0, round(crowding_shift(snapshot), 2)))


def overlay(
    events: Sequence[Mapping[str, Any]], snapshots: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """レーダーイベントに空売り行動を **重ねる**（書き換えない）。

    `alert_priority` は調整後の値に差し替えるが、素の値は
    `alert_priority_base` として残す —— どちらが技術由来でどちらが
    空売り由来か、画面から辿れないと検証できない。
    """

    out: list[dict[str, Any]] = []
    for event in events:
        code = str(event.get("canonical_code") or "")
        snapshot = snapshots.get(code)
        shift = priority_shift(snapshot)
        base = _num(event.get("alert_priority")) or 0.0
        merged = dict(event)
        merged["alert_priority_base"] = base
        merged["alert_priority"] = round(max(0.0, min(100.0, base + shift)), 2)
        merged["short_behavior"] = (
            {
                "state": snapshot.get("primary_state"),
                "crowding_level": crowding_level(
                    snapshot.get("visible_institution_count"), snapshot.get("visible_short_ratio"),
                ),
                # 拥挤度叠加（只減不加）。スイッチが切れている間、適用量は 0 で、
                # 仮の値だけ出す。
                "hypothetical_crowding_shift": hypothetical_crowding_shift(snapshot),
                "crowding_link_enabled": CROWDING_LINK_ENABLED,
                "informed_institution_count": informed_institution_count(snapshot),
                "flags": snapshot.get("flags") or [],
                "data_confidence": snapshot.get("data_confidence"),
                "visible_short_ratio": snapshot.get("visible_short_ratio"),
                "visible_institution_count": snapshot.get("visible_institution_count"),
                "below_threshold_count": snapshot.get("below_threshold_count"),
                "visible_days_to_cover": snapshot.get("visible_days_to_cover"),
                "priority_shift": shift,
            }
            if snapshot
            else None
        )
        out.append(merged)
    out.sort(key=lambda item: (-(item.get("alert_priority") or 0.0), item.get("canonical_code") or ""))
    return out


def matches(
    snapshot: Mapping[str, Any] | None,
    *,
    states: Iterable[str] | None = None,
    flags: Iterable[str] | None = None,
    exclude_flags: Iterable[str] | None = None,
    min_confidence: float | None = None,
) -> bool:
    """レーダー側の絞り込み条件。スナップショットが無ければ通さない。"""

    wanted_states = list(states or [])
    wanted_flags = list(flags or [])
    banned = list(exclude_flags or [])
    if not (wanted_states or wanted_flags or banned or min_confidence is not None):
        return True
    if snapshot is None:
        # 条件を付けたのにデータが無い銘柄を「条件を満たした」とは扱わない。
        return False
    if wanted_states and str(snapshot.get("primary_state") or "") not in wanted_states:
        return False
    present = set(snapshot.get("flags") or [])
    if wanted_flags and not present.intersection(wanted_flags):
        return False
    if banned and present.intersection(banned):
        return False
    if min_confidence is not None:
        confidence = _num(snapshot.get("data_confidence"))
        if confidence is None or confidence < min_confidence:
            return False
    return True


__all__ = [
    "CROWDING_LINK_ENABLED",
    "CROWDING_SHIFT_BY_COUNT",
    "CROWDING_VALIDATION",
    "MAX_PRIORITY_SHIFT",
    "PRIORITY_LINK_ENABLED",
    "crowding_shift",
    "hypothetical_crowding_shift",
    "informed_institution_count",
    "matches",
    "overlay",
    "priority_shift",
]
