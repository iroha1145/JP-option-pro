"""Daily-bar breakout lifecycle for the Japan radar.

参照プロジェクトの状態機械を移植し、米国市場特有のセッション分岐
（場前ギャップ系）を取り除いた版。完了した JST セッションだけを観測する
ため、全遷移は日足終値で駆動される。隣接表に無い遷移は拒否（例外は投げ
ない）——再スキャンはリプレイ可能かつ冪等。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Mapping

STATE_DISCOVERED = "discovered"
STATE_WATCHING = "watching"
STATE_TRIGGERED = "triggered"
STATE_CONFIRMED = "confirmed"
STATE_HOLDING = "holding"
STATE_RETESTING = "retesting"
STATE_RETEST_HELD = "retest_held"
STATE_REACCELERATING = "reaccelerating"
STATE_EXTENDED = "extended"
STATE_FAILED = "failed"
STATE_EXPIRED = "expired"

TERMINAL_STATES = frozenset({STATE_FAILED, STATE_EXPIRED})

ALL_STATES = (
    STATE_DISCOVERED,
    STATE_WATCHING,
    STATE_TRIGGERED,
    STATE_CONFIRMED,
    STATE_HOLDING,
    STATE_RETESTING,
    STATE_RETEST_HELD,
    STATE_REACCELERATING,
    STATE_EXTENDED,
    STATE_FAILED,
    STATE_EXPIRED,
)

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    STATE_DISCOVERED: frozenset({STATE_WATCHING, STATE_TRIGGERED, STATE_FAILED, STATE_EXPIRED}),
    STATE_WATCHING: frozenset({STATE_TRIGGERED, STATE_FAILED, STATE_EXPIRED}),
    STATE_TRIGGERED: frozenset({STATE_CONFIRMED, STATE_RETESTING, STATE_EXTENDED, STATE_FAILED, STATE_EXPIRED}),
    STATE_CONFIRMED: frozenset({STATE_HOLDING, STATE_RETESTING, STATE_EXTENDED, STATE_FAILED, STATE_EXPIRED}),
    STATE_HOLDING: frozenset({STATE_RETESTING, STATE_REACCELERATING, STATE_EXTENDED, STATE_FAILED, STATE_EXPIRED}),
    STATE_RETESTING: frozenset({STATE_RETEST_HELD, STATE_FAILED, STATE_EXPIRED}),
    STATE_RETEST_HELD: frozenset({STATE_REACCELERATING, STATE_RETESTING, STATE_EXTENDED, STATE_FAILED, STATE_EXPIRED}),
    STATE_REACCELERATING: frozenset({STATE_HOLDING, STATE_RETESTING, STATE_EXTENDED, STATE_FAILED, STATE_EXPIRED}),
    STATE_EXTENDED: frozenset({STATE_HOLDING, STATE_RETESTING, STATE_FAILED, STATE_EXPIRED}),
    STATE_FAILED: frozenset(),
    STATE_EXPIRED: frozenset(),
}

# Stable reason strings — surfaced verbatim in the API and the UI timeline.
REASON_TRIGGERED = "close_above_pivot"
REASON_CONFIRMED_HOLD = "hold_days_satisfied"
REASON_CONFIRMED_STRONG = "strong_single_close"
REASON_HOLDING = "holding_above_pivot"
REASON_RETESTING = "price_reentered_pivot_zone"
REASON_RETEST_HELD = "retest_reclaimed_pivot"
REASON_REACCELERATING = "new_event_high_after_hold"
REASON_EXTENDED = "distance_threshold_exceeded"
REASON_FAILED = "invalidation_broken"
REASON_EXPIRED = "event_ttl_expired"
REASON_WATCHING = "approaching_pivot"


@dataclass(frozen=True)
class TransitionResult:
    previous_state: str
    state: str
    changed: bool
    reason: str


def transition(current: str, target: str, reason: str) -> TransitionResult:
    if target == current:
        return TransitionResult(current, current, False, "no_change")
    allowed = ALLOWED_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        return TransitionResult(current, current, False, "transition_not_allowed")
    return TransitionResult(current, target, True, reason)


def resolve_path(
    current: str,
    observation: Mapping[str, bool],
) -> list[tuple[str, str]]:
    """1 日分の観測フラグを、**順序付きの遷移列**に落とす。

    1 日で 2 段進むことがあるので単一の目標状態では足りない。典型例が窓開け
    突破: ピボットを飛び越え、同時に伸び切り閾値まで超えている日は
    `WATCHING → TRIGGERED → EXTENDED` の 2 段になる。ここを単一目標
    （`EXTENDED`）で返すと隣接表に無い遷移として棄却され、**明らかに
    突破しているのに WATCHING のまま**という状態が残る（実際の不具合）。

    返すのは必ず隣接表上を歩ける列（`test_lifecycle_paths_are_all_legal`
    が全状態 × 全観測の組合せで検査する）。空列 = 変化なし。
    """

    if observation.get("expired"):
        return [(STATE_EXPIRED, REASON_EXPIRED)]
    if observation.get("failed"):
        return [(STATE_FAILED, REASON_FAILED)]

    path: list[tuple[str, str]] = []
    state = current

    # 伸び切ったまま維持している日は「変化なし」。ここを抜くと毎日
    # EXTENDED → HOLDING → EXTENDED を記録し続け、遷移履歴が実体のない
    # 往復で埋まる（「保ち続けている」は伸び切りに含意される）。
    if current == STATE_EXTENDED and observation.get("extended") and not observation.get("retesting"):
        return []

    # 1) 突破そのものの前進（未突破 → 突破 → 確認）
    if state in (STATE_DISCOVERED, STATE_WATCHING):
        if observation.get("triggered"):
            path.append((STATE_TRIGGERED, REASON_TRIGGERED))
            state = STATE_TRIGGERED
        elif state == STATE_DISCOVERED:
            path.append((STATE_WATCHING, REASON_WATCHING))
            state = STATE_WATCHING
    if state == STATE_TRIGGERED:
        if observation.get("confirmed_strong"):
            path.append((STATE_CONFIRMED, REASON_CONFIRMED_STRONG))
            state = STATE_CONFIRMED
        elif observation.get("confirmed_hold"):
            path.append((STATE_CONFIRMED, REASON_CONFIRMED_HOLD))
            state = STATE_CONFIRMED
        elif observation.get("retesting"):
            path.append((STATE_RETESTING, REASON_RETESTING))
            state = STATE_RETESTING
    elif state in (STATE_CONFIRMED, STATE_REACCELERATING, STATE_EXTENDED):
        if observation.get("retesting"):
            path.append((STATE_RETESTING, REASON_RETESTING))
            state = STATE_RETESTING
        elif observation.get("holding"):
            path.append((STATE_HOLDING, REASON_HOLDING))
            state = STATE_HOLDING
    elif state == STATE_HOLDING:
        if observation.get("retesting"):
            path.append((STATE_RETESTING, REASON_RETESTING))
            state = STATE_RETESTING
        elif observation.get("new_event_high"):
            path.append((STATE_REACCELERATING, REASON_REACCELERATING))
            state = STATE_REACCELERATING
    elif state == STATE_RETESTING:
        if observation.get("retest_reclaimed"):
            path.append((STATE_RETEST_HELD, REASON_RETEST_HELD))
            state = STATE_RETEST_HELD
    elif state == STATE_RETEST_HELD:
        if observation.get("new_event_high"):
            path.append((STATE_REACCELERATING, REASON_REACCELERATING))
            state = STATE_REACCELERATING
        elif observation.get("retesting"):
            path.append((STATE_RETESTING, REASON_RETESTING))
            state = STATE_RETESTING

    # 2) 伸び切りは「突破済みの銘柄に付く注意書き」。突破の記録を先に済ませて
    #    から重ねる（順序を逆にすると窓開け日の突破が履歴から消える）。
    if observation.get("extended") and state != STATE_EXTENDED:
        if STATE_EXTENDED in ALLOWED_TRANSITIONS.get(state, frozenset()):
            path.append((STATE_EXTENDED, REASON_EXTENDED))
    return path


def resolve_target(
    current: str,
    observation: Mapping[str, bool],
) -> tuple[str, str]:
    """`resolve_path` の最終到達点だけを返す互換ラッパ。"""

    if observation.get("expired"):
        return STATE_EXPIRED, REASON_EXPIRED
    if observation.get("failed"):
        return STATE_FAILED, REASON_FAILED
    # Only pre-empt with EXTENDED where it is a legal transition. For DISCOVERED/
    # WATCHING it is not (a name must trigger before it can be extended), so a
    # single large gap-up (>3.5 ATR) must resolve to TRIGGERED first — otherwise
    # transition() rejects WATCHING/DISCOVERED->EXTENDED and the event is stranded.
    if observation.get("extended") and STATE_EXTENDED in ALLOWED_TRANSITIONS.get(
        current, frozenset()
    ):
        return STATE_EXTENDED, REASON_EXTENDED
    if current in (STATE_DISCOVERED, STATE_WATCHING):
        if observation.get("triggered"):
            return STATE_TRIGGERED, REASON_TRIGGERED
        return STATE_WATCHING, REASON_WATCHING
    if current == STATE_TRIGGERED:
        if observation.get("confirmed_strong"):
            return STATE_CONFIRMED, REASON_CONFIRMED_STRONG
        if observation.get("confirmed_hold"):
            return STATE_CONFIRMED, REASON_CONFIRMED_HOLD
        if observation.get("retesting"):
            return STATE_RETESTING, REASON_RETESTING
        return current, "no_change"
    if current in (STATE_CONFIRMED, STATE_REACCELERATING, STATE_EXTENDED):
        if observation.get("retesting"):
            return STATE_RETESTING, REASON_RETESTING
        if observation.get("holding"):
            return STATE_HOLDING, REASON_HOLDING
        return current, "no_change"
    if current == STATE_HOLDING:
        if observation.get("retesting"):
            return STATE_RETESTING, REASON_RETESTING
        if observation.get("new_event_high"):
            return STATE_REACCELERATING, REASON_REACCELERATING
        return current, "no_change"
    if current == STATE_RETESTING:
        if observation.get("retest_reclaimed"):
            return STATE_RETEST_HELD, REASON_RETEST_HELD
        return current, "no_change"
    if current == STATE_RETEST_HELD:
        if observation.get("new_event_high"):
            return STATE_REACCELERATING, REASON_REACCELERATING
        # 回収済み（close > pivot*1.005）のまま帯の上端にいる日は
        # RETESTING に戻さない。戻すと翌日また RETEST_HELD へ振動する。
        if observation.get("retesting") and not observation.get("retest_reclaimed"):
            return STATE_RETESTING, REASON_RETESTING
        return current, "no_change"
    return current, "no_change"


def event_identity(canonical_code: str, signal_type: str, pivot_date: str, pivot_price: float | None) -> str:
    price_text = f"{pivot_price:.4f}" if pivot_price is not None else "na"
    payload = f"{canonical_code}|{signal_type}|{pivot_date}|{price_text}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


__all__ = [
    "ALLOWED_TRANSITIONS",
    "ALL_STATES",
    "TERMINAL_STATES",
    "TransitionResult",
    "event_identity",
    "resolve_path",
    "resolve_target",
    "transition",
    "STATE_CONFIRMED",
    "STATE_DISCOVERED",
    "STATE_EXPIRED",
    "STATE_EXTENDED",
    "STATE_FAILED",
    "STATE_HOLDING",
    "STATE_REACCELERATING",
    "STATE_RETESTING",
    "STATE_RETEST_HELD",
    "STATE_TRIGGERED",
    "STATE_WATCHING",
]
