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
    """実際に適用する調整量。**検証を通るまで常に 0。**"""

    if not PRIORITY_LINK_ENABLED:
        return 0.0
    return hypothetical_priority_shift(snapshot)


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
    "MAX_PRIORITY_SHIFT",
    "PRIORITY_LINK_ENABLED",
    "STATE_SHIFT",
    "hypothetical_priority_shift",
    "matches",
    "overlay",
    "priority_shift",
]
