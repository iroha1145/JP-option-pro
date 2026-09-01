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


def resolve_target(
    current: str,
    observation: Mapping[str, bool],
) -> tuple[str, str]:
    """Priority-ordered evaluation of one day's observation flags."""

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
