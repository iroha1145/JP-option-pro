"""生命周期の正しさ（窓開け突破・営業日年齢・遷移の合法性）。

いずれも「静的監査で指摘された挙動が実際に直っているか」を、隣接表と
`resolve_path` の両方に対して確かめる回帰テスト。
"""

from __future__ import annotations

import itertools

import pytest

from app.services.radar import lifecycle as lc


OBSERVATION_KEYS = (
    "triggered", "holding", "retesting", "retest_reclaimed",
    "new_event_high", "extended", "confirmed_hold", "confirmed_strong",
)


def _walk(current: str, observation: dict[str, bool]) -> tuple[str, list[str]]:
    """`resolve_path` を隣接表に沿って実際に歩き、到達状態と経路を返す。"""

    state = current
    visited: list[str] = []
    for target, reason in lc.resolve_path(current, observation):
        result = lc.transition(state, target, reason)
        if not result.changed:
            break
        state = result.state
        visited.append(state)
    return state, visited


def test_gap_breakout_beyond_extension_does_not_stay_watching():
    """窓開けでピボットを飛び越え、同時に伸び切り閾値も超えた日。

    旧実装は `EXTENDED` を単一の目標として返し、WATCHING → EXTENDED が
    隣接表に無いため棄却され、**明らかに突破しているのに WATCHING のまま**
    だった。TRIGGERED を経由して EXTENDED に着くこと。
    """

    state, path = _walk(lc.STATE_WATCHING, {"triggered": True, "extended": True})

    assert state == lc.STATE_EXTENDED, "窓開け突破が観察状態に据え置かれている"
    assert path == [lc.STATE_TRIGGERED, lc.STATE_EXTENDED], "突破の記録を飛ばしている"


def test_plain_gap_breakout_reaches_triggered():
    state, path = _walk(lc.STATE_WATCHING, {"triggered": True})
    assert state == lc.STATE_TRIGGERED
    assert path == [lc.STATE_TRIGGERED]


def test_gap_breakout_with_strong_close_reaches_confirmed():
    """新規検出と既存 WATCHING で同じ 1 日が違う結末になっていた不整合。"""

    state, _ = _walk(
        lc.STATE_WATCHING, {"triggered": True, "confirmed_strong": True}
    )
    assert state == lc.STATE_CONFIRMED


def test_intraday_cross_but_close_back_below_stays_watching():
    """場中に越えても終値が下なら突破ではない（日足駆動なので観測されない）。"""

    state, path = _walk(lc.STATE_WATCHING, {"triggered": False})
    assert state == lc.STATE_WATCHING
    assert path == []


def test_failed_and_expired_win_over_forward_progress():
    assert _walk(lc.STATE_TRIGGERED, {"failed": True, "triggered": True})[0] == lc.STATE_FAILED
    assert _walk(lc.STATE_HOLDING, {"expired": True, "holding": True})[0] == lc.STATE_EXPIRED


def test_extended_then_continues_extending_is_idempotent():
    """既に EXTENDED の事件が翌日さらに伸びても状態は動かない。

    「ピボットの上を保っている」は伸び切りに含意されるので、EXTENDED →
    HOLDING → EXTENDED を毎日記録してはいけない（遷移履歴が往復で埋まる）。
    """

    state, path = _walk(lc.STATE_EXTENDED, {"extended": True, "holding": True})
    assert state == lc.STATE_EXTENDED
    assert path == [], "維持しているだけの日に遷移を記録している"


def test_extended_falling_back_into_the_pivot_zone_retests():
    """伸び切りから押してピボット帯に戻ったら、素通りせず RETESTING に落ちる。"""

    state, _ = _walk(lc.STATE_EXTENDED, {"extended": True, "retesting": True})
    assert state == lc.STATE_RETESTING


def test_confirmed_gapping_further_records_extended():
    state, _ = _walk(lc.STATE_CONFIRMED, {"holding": True, "extended": True})
    assert state == lc.STATE_EXTENDED


@pytest.mark.parametrize("current", lc.ALL_STATES)
def test_lifecycle_paths_are_all_legal(current):
    """全状態 × 全観測の組合せで、返す経路が必ず隣接表を歩けること。

    `resolve_path` が非合法な経路を作ると、途中で棄却されて状態が中途半端に
    止まる（まさに今回の不具合の形）。ここで網羅的に潰しておく。
    """

    for combo in itertools.product([False, True], repeat=len(OBSERVATION_KEYS)):
        observation = dict(zip(OBSERVATION_KEYS, combo))
        state = current
        for target, _reason in lc.resolve_path(current, observation):
            allowed = lc.ALLOWED_TRANSITIONS.get(state, frozenset())
            assert target in allowed, (
                f"{current} の観測 {observation} が非合法な遷移 {state} → {target} を要求"
            )
            state = target


def test_terminal_states_never_move():
    for terminal in (lc.STATE_FAILED, lc.STATE_EXPIRED):
        for combo in itertools.product([False, True], repeat=3):
            observation = dict(zip(("triggered", "holding", "extended"), combo))
            assert _walk(terminal, observation)[0] == terminal
