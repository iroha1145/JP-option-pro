"""レーダーとの連動。**触ってよいのは `alert_priority` だけ。**

歴史検証を通るまで、空売り行動分を正式な技術品質（`base_quality` /
`breakout_confirmation` / `intrinsic_strength`）に書き込まない。技術的に
弱い銘柄が「機関が空売りを増やしたから」という理由で高品質の突破候補に
化けるのが、この種の連動で一番起きやすい事故なので、書き込み先を
物理的に 1 か所に限る。

優先度の調整も **有界**。最大でも ±`MAX_PRIORITY_SHIFT` 点しか動かない。

そして **検証を通るまで調整は 0**。走步検証の初回結論は否定 —— 全状態が
全保有期間で TOPIX を下回り、しかも設計上の強気（absorption）と弱気
（divergence_failed）の実測順位が逆だった。方向が逆だと自分のデータで
分かっているモデルに本番の並び順を動かさせるわけにはいかない。仮の
調整量は `hypothetical_priority_shift` として表示だけする。
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from .scoring import SCORE_VALIDATED
from .states import (
    FLAG_CROWDED_MARGIN,
    GATES_VALIDATED,
    STATE_ABSORPTION,
    STATE_COVERING_START,
    STATE_DIVERGENCE_FAILED,
    STATE_SQUEEZE_CONFIRMED,
)

#: 優先度連動の総合スイッチ。**両方の検証を通るまで False。**
#: これが False の間、`priority_shift()` は常に 0 を返し、レーダーの並び順は
#: 技術系スコアのまま —— 空売り行動は表示・絞り込み・影子分に限られる。
PRIORITY_LINK_ENABLED = bool(SCORE_VALIDATED and GATES_VALIDATED)

#: 優先度をずらせる最大幅（100 点満点に対して）。
MAX_PRIORITY_SHIFT = 8.0

#: **拥挤度の「只減不加」叠加**。状態機とは独立に、可視機関数が多いほど
#: 優先度を **下げるだけ** の調整。第十二轮の走步で唯一安定して単調だった
#: 関係（可見機構数 0/1/2–3/4+ → 20 日超過 −1.10/−1.42/−1.98/−2.85%）を、
#: 上げる方向には一切使わず、リスク側だけに使う。
#:
#: それでも **窓別の安定性を確認するまで False**。判定は
#: `python -m app.research.short_behavior_runner` の `crowding` セクション
#: （16 窓中 ≥13 窓で負、かつ 2025-07 以降の留出期でも負）で行い、通ったら
#: `CROWDING_VALIDATION` に結果を書いてこのスイッチを True にする。
CROWDING_LINK_ENABLED = False

#: 拥挤度検証の状態。「まだ検証していない」と「検証したが通らなかった」は別。
CROWDING_VALIDATION: dict[str, Any] = {
    "status": "pending",
    "summary": (
        "第十二轮验证里可见机构数越多后续越差（0→4+：−1.10%→−2.85%）是全样本单调，"
        "但逐窗稳定性与留出期尚未按 informed 口径复核。复核通过前叠加为 0。"
    ),
    "gate": "walk-forward windows negative >= 13/16 and holdout (2025-07..) negative",
}

#: 可視機関数（informed 口径を優先、無ければ全鎖口径）に応じた素の引き下げ。
#: 上から順に最初に当たった段を使う。正の値は絶対に置かない。
CROWDING_SHIFT_BY_COUNT: tuple[tuple[int, float], ...] = (
    (4, -4.0),
    (2, -2.0),
)

#: 状態ごとの素の調整量。信頼度を掛けてから使う。
STATE_SHIFT: dict[str, float] = {
    STATE_SQUEEZE_CONFIRMED: +8.0,
    STATE_COVERING_START: +5.0,
    STATE_ABSORPTION: +4.0,
    STATE_DIVERGENCE_FAILED: -6.0,
}

#: 信用買いが極端に混雑しているときの引き下げ。踏み上げ期待の裏で
#: 玉の構造が危ういことがあるので、上げっぱなしにしない。
CROWDED_MARGIN_SHIFT = -3.0


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


def hypothetical_priority_shift(snapshot: Mapping[str, Any] | None) -> float:
    """もし連動が有効だったら適用される調整量（有界・表示専用）。"""

    if not snapshot:
        return 0.0
    confidence = _num(snapshot.get("data_confidence"))
    confidence = 0.0 if confidence is None else max(0.0, min(1.0, confidence))
    shift = STATE_SHIFT.get(str(snapshot.get("primary_state") or ""), 0.0) * confidence
    flags = snapshot.get("flags") or []
    if FLAG_CROWDED_MARGIN in flags:
        shift += CROWDED_MARGIN_SHIFT * confidence
    return max(-MAX_PRIORITY_SHIFT, min(MAX_PRIORITY_SHIFT, round(shift, 2)))


def priority_shift(snapshot: Mapping[str, Any] | None) -> float:
    """実際に適用する調整量。**それぞれの検証を通るまで常に 0。**

    状態機由来の ±（PRIORITY_LINK_ENABLED）と、拥挤度由来の −
    （CROWDING_LINK_ENABLED）は別々のスイッチ。合計は ±MAX_PRIORITY_SHIFT に収める。
    """

    total = 0.0
    if PRIORITY_LINK_ENABLED:
        total += hypothetical_priority_shift(snapshot)
    total += crowding_shift(snapshot)
    return max(-MAX_PRIORITY_SHIFT, min(MAX_PRIORITY_SHIFT, round(total, 2)))


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
                # 影子分。正式な技術品質には一切入っていない。
                "shadow_score": snapshot.get("behavior_score"),
                # 連動が有効なら適用されたはずの量（表示専用）と、実際に
                # 適用された量。検証を通るまで後者は 0。
                "hypothetical_priority_shift": hypothetical_priority_shift(snapshot),
                "priority_link_enabled": PRIORITY_LINK_ENABLED,
                # 拥挤度叠加（只減不加）。検証を通るまで適用量は 0、仮の値だけ出す。
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
    "CROWDED_MARGIN_SHIFT",
    "CROWDING_LINK_ENABLED",
    "CROWDING_SHIFT_BY_COUNT",
    "CROWDING_VALIDATION",
    "MAX_PRIORITY_SHIFT",
    "PRIORITY_LINK_ENABLED",
    "STATE_SHIFT",
    "crowding_shift",
    "hypothetical_crowding_shift",
    "hypothetical_priority_shift",
    "informed_institution_count",
    "matches",
    "overlay",
    "priority_shift",
]
