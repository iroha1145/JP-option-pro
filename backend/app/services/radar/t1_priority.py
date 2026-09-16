"""Japan T1 evaluation and stable boost sort.

T1 never changes detector output, lifecycle, or event identity. It only
annotates daily-condition status and, when selected, reorders an already
qualified result set. Applicable setup is first-trigger ``base_breakout``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timezone
from typing import Any, Callable, Mapping, Sequence

from app.domain.timeutil import JST
from app.services.algorithm_modes import T1_ALGORITHM, T1_VERSION
from app.services.radar.daily_confirmation import (
    T1_SETTINGS,
    compute_atr,
    daily_bar_location,
    rvol_daily_20med,
    t1_checks,
    valid_daily_ohlc,
    valid_session_volume,
)
from app.services.radar.engine import SIGNAL_BASE_BREAK


T1_MET = "met"
T1_UNMET = "unmet"
T1_PENDING = "pending_close"
T1_UNAVAILABLE = "unavailable"
T1_NOT_APPLICABLE = "not_applicable"
T1_DAILY_SETUP = SIGNAL_BASE_BREAK
T1_TERMINAL_STATUSES = {T1_MET, T1_UNMET}
T1_EXPIRED_LIFECYCLES = {"failed", "expired"}
T1_RETRYABLE_REASONS = {
    "daily_unavailable",
    "missing_event_bar",
    "missing_event_volume",
    "no_completed_daily_bars",
    "daily_fetch_failed",
    "price_adapter_unavailable",
    "waiting_vendor_publish",
}
T1_DATA_CONVENTION = "jp_adj_ohlcv_v1"
T1_SETTLED_STATUSES = {T1_MET, T1_UNMET}
REGULAR_CLOSE = time(15, 30)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return number


def _as_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.astimezone(JST).date()
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _aware(as_of: datetime) -> datetime:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("T1 evaluation requires a timezone-aware as_of")
    return as_of


def session_daily_complete(session_date: date, *, as_of: datetime) -> bool:
    """True only after that session's regular 15:30 JST close.

    Exchange close is not the same as J-Quants publish. Callers must still
    treat a missing T bar as unavailable / retryable.
    """

    moment = _aware(as_of).astimezone(JST)
    close_at = datetime.combine(session_date, REGULAR_CLOSE, tzinfo=JST)
    return moment >= close_at


def vendor_publish_ready(
    session_date: date,
    *,
    as_of: datetime,
    first_fetch_hhmm: str = "17:00",
) -> bool:
    """Do not start the eight-attempt fetch budget at 15:30."""

    if not session_daily_complete(session_date, as_of=as_of):
        return False
    hours, minutes = first_fetch_hhmm.split(":", 1)
    gate = datetime.combine(
        session_date, time(int(hours), int(minutes)), tzinfo=JST
    )
    return _aware(as_of).astimezone(JST) >= gate


def t1_setup_applicable(event: Mapping[str, Any] | None) -> bool:
    payload = dict(event or {})
    setup = str(payload.get("signal_type") or payload.get("setup_type") or "").strip()
    return setup == T1_DAILY_SETUP


def event_t1_status(event: Mapping[str, Any]) -> str:
    features = event.get("features") if isinstance(event.get("features"), Mapping) else {}
    payload = event.get("t1_priority")
    if not isinstance(payload, Mapping):
        payload = features.get("t1_priority") if isinstance(features, Mapping) else None
    if not isinstance(payload, Mapping):
        return T1_UNAVAILABLE
    status = str(payload.get("status") or "").strip()
    if status == "pending":
        return T1_PENDING
    if status in {T1_MET, T1_UNMET, T1_PENDING, T1_UNAVAILABLE, T1_NOT_APPLICABLE}:
        return status
    return T1_UNAVAILABLE


def t1_boost_eligible(event: Mapping[str, Any]) -> bool:
    lifecycle = str(event.get("state") or event.get("lifecycle_state") or "").strip()
    if lifecycle in T1_EXPIRED_LIFECYCLES:
        return False
    return event_t1_status(event) == T1_MET


def t1_needs_close_eval(event: Mapping[str, Any]) -> bool:
    if not t1_setup_applicable(event):
        return False
    status = event_t1_status(event)
    if status in {T1_MET, T1_UNMET, T1_NOT_APPLICABLE}:
        return False
    if status == T1_PENDING:
        return True
    features = event.get("features") if isinstance(event.get("features"), Mapping) else {}
    payload = event.get("t1_priority")
    if not isinstance(payload, Mapping):
        payload = features.get("t1_priority") if isinstance(features, Mapping) else None
    if not isinstance(payload, Mapping):
        return True
    reason = str(payload.get("reason") or "")
    return status == T1_UNAVAILABLE and (reason in T1_RETRYABLE_REASONS or reason == "")


def _identity_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(payload),
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def t1_identity_complete(payload: Mapping[str, Any] | None) -> bool:
    """True only for a hashable *and* decision-complete settled conclusion.

    A hash that includes null resistance or volume is not proof that the
    inputs were complete. Unavailable / pending attempts are never complete.
    Storage must not trust a caller-supplied identity_complete=True.
    """

    body = dict(payload or {})
    status = str(body.get("status") or "").strip()
    if status not in T1_SETTLED_STATUSES:
        return False
    if not str(body.get("identity_hash") or "").strip():
        return False
    if body.get("identity_complete") is False:
        return False
    # A caller-supplied identity_complete=True is not enough. Settled
    # conclusions must carry the four decision metrics; missing resistance
    # or volume hashed as null is not a complete identity.
    for key in ("clv", "rvol_daily_20med", "upper_shadow_ratio", "breakout_distance_atr"):
        if _finite(body.get(key)) is None:
            return False
    return True


def t1_input_identity(
    *,
    event_id: str | None,
    session_date: date,
    resistance_high: Any,
    session_bar: Mapping[str, Any],
    prior_bars: Sequence[Mapping[str, Any]],
    settings: Mapping[str, Any] | None = None,
) -> str:
    """Fingerprint every causal T-window input, including ATR history."""

    cfg = {**T1_SETTINGS, **dict(settings or {})}
    return _identity_hash(
        {
            "event_id": event_id or "",
            "session_date": session_date.isoformat(),
            "version": T1_VERSION,
            "variant": T1_ALGORITHM,
            "data_convention": T1_DATA_CONVENTION,
            "resistance": _finite(resistance_high),
            "session_bar": {
                "open": _finite(session_bar.get("open")),
                "high": _finite(session_bar.get("high")),
                "low": _finite(session_bar.get("low")),
                "close": _finite(session_bar.get("close")),
                "volume": _finite(session_bar.get("volume")),
            },
            "prior_bars": [
                {
                    "session_date": str(item.get("session_date") or ""),
                    "open": _finite(item.get("open")),
                    "high": _finite(item.get("high")),
                    "low": _finite(item.get("low")),
                    "close": _finite(item.get("close")),
                    "volume": _finite(item.get("volume")),
                }
                for item in prior_bars
            ],
            "settings": {
                "clv_min": cfg.get("clv_min"),
                "rvol_min": cfg.get("rvol_min"),
                "upper_shadow_max": cfg.get("upper_shadow_max"),
                "distance_atr_min": cfg.get("distance_atr_min"),
                "rvol_lookback": cfg.get("rvol_lookback"),
                "atr_period": cfg.get("atr_period"),
            },
        }
    )


def t1_view_token(
    scan_date: str,
    sort_algorithm: str,
    events: Sequence[Mapping[str, Any]],
) -> str:
    items = []
    for event in events:
        payload = event.get("t1_priority")
        if not isinstance(payload, Mapping):
            features = event.get("features") if isinstance(event.get("features"), Mapping) else {}
            payload = features.get("t1_priority") if isinstance(features, Mapping) else {}
        body = dict(payload or {})
        items.append(
            {
                "event_id": str(event.get("event_id") or ""),
                "status": str(body.get("status") or ""),
                "eval_version": int(body.get("eval_version") or 0),
                "identity_hash": str(body.get("identity_hash") or ""),
            }
        )
    items.sort(key=lambda item: item["event_id"])
    return _identity_hash(
        {
            "scan_date": scan_date,
            "sort_algorithm": sort_algorithm,
            "items": items,
        }
    )[:24]


def t1_anchor_payload(event: Mapping[str, Any]) -> dict[str, Any] | None:
    """Dedicated first-publish T1 anchor. Live daily structure is not an anchor."""

    features = event.get("features") if isinstance(event.get("features"), Mapping) else {}
    for source in (
        event.get("t1_anchor"),
        features.get("t1_anchor") if isinstance(features, Mapping) else None,
    ):
        if isinstance(source, Mapping) and source.get("resistance_high") is not None:
            return dict(source)
    return None


def _legacy_pivot_recovery(event: Mapping[str, Any]) -> Any:
    """Recover resistance from frozen pivot only with explicit then-resistance proof.

    Production ``pivot_price`` from the base detector is resistance mid. Do not
    treat a bare pivot as T1 resistance without a recorded convention match.
    """

    features = event.get("features") if isinstance(event.get("features"), Mapping) else {}
    recovery = event.get("t1_anchor_recovery")
    if not isinstance(recovery, Mapping):
        recovery = features.get("t1_anchor_recovery") if isinstance(features, Mapping) else None
    if not isinstance(recovery, Mapping):
        return None
    if recovery.get("pivot_was_resistance_high") is not True:
        return None
    convention = str(recovery.get("data_convention") or "").strip()
    if convention and convention != T1_DATA_CONVENTION:
        return None
    return event.get("pivot_price")


def t1_resistance_high(event: Mapping[str, Any]) -> Any:
    """Frozen first-publish platform high. Never read today's live structure."""

    anchor = t1_anchor_payload(event)
    if anchor is not None:
        return anchor.get("resistance_high")
    return _legacy_pivot_recovery(event)


def frozen_platform_evidence(event: Mapping[str, Any]) -> bool:
    resistance = _finite(t1_resistance_high(event))
    return resistance is not None and resistance > 0


def evaluate_t1_from_daily(
    daily: Sequence[Mapping[str, Any]] | None,
    *,
    session_date: date,
    resistance_high: Any,
    as_of: datetime,
    previous: Mapping[str, Any] | None = None,
    settings: Mapping[str, Any] | None = None,
    event_id: str | None = None,
    is_trading_day: Callable[[str], bool | None] | None = None,
    prior_trading_sessions: Callable[[date, int], list[str] | None] | None = None,
) -> dict[str, Any]:
    """Evaluate T1 from completed daily bars only.

    Inputs are always trimmed to the event session. A later trading day must
    not change a settled conclusion for the same event and input identity.
    ``known_at`` is the first time this identity became met/unmet.
    """

    cfg = {**T1_SETTINGS, **dict(settings or {})}
    computed_at = _aware(as_of).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    prior = dict(previous or {})
    prior_known = prior.get("known_at") if prior.get("status") in T1_TERMINAL_STATUSES else None
    first_known = prior.get("first_known_at") or prior_known
    base = {
        "version": T1_VERSION,
        "variant": T1_ALGORITHM,
        "status": T1_UNAVAILABLE,
        "session_date": session_date.isoformat(),
        "data_through": None,
        "session_complete": False,
        "computed_at": computed_at,
        "known_at": None,
        "first_known_at": first_known,
        "eval_version": int(prior.get("eval_version") or 0) or 1,
        "identity_hash": None,
        "identity_complete": False,
        "revisions": list(prior.get("revisions") or []),
        "event_id": event_id or prior.get("event_id"),
        "checks": {
            "clv": False,
            "rvol": False,
            "upper_shadow": False,
            "distance_atr": False,
        },
        "clv": None,
        "rvol_daily_20med": None,
        "upper_shadow_ratio": None,
        "breakout_distance_atr": None,
        "reason": None,
    }
    trading = None if is_trading_day is None else is_trading_day(session_date.isoformat())
    if trading is None and is_trading_day is not None:
        return {**base, "reason": "calendar_unknown"}
    if trading is False:
        return {**base, "reason": "not_a_trading_day"}
    if not session_daily_complete(session_date, as_of=as_of):
        return {**base, "status": T1_PENDING, "reason": "session_incomplete"}
    if daily is None:
        return {**base, "session_complete": True, "reason": "daily_unavailable"}

    lookback = int(cfg["rvol_lookback"])
    if prior_trading_sessions is None:
        return {**base, "session_complete": True, "reason": "trading_calendar_unavailable"}
    try:
        prior_sessions = prior_trading_sessions(session_date, lookback)
    except (RuntimeError, ValueError, TypeError):
        return {**base, "session_complete": True, "reason": "trading_calendar_unavailable"}
    if prior_sessions is None:
        return {**base, "session_complete": True, "reason": "trading_calendar_unavailable"}
    if len(prior_sessions) != lookback:
        return {**base, "session_complete": True, "reason": "insufficient_calendar_history"}

    bars_by_date: dict[str, list[Mapping[str, Any]]] = {}
    for bar in daily:
        day = str(bar.get("trade_date") or bar.get("session_date") or "")[:10]
        if not day:
            return {**base, "session_complete": True, "reason": "unordered_daily_bars"}
        if day > session_date.isoformat():
            continue
        bars_by_date.setdefault(day, []).append(bar)
    if any(len(rows) > 1 for rows in bars_by_date.values()):
        return {**base, "session_complete": True, "reason": "duplicate_session_bar"}

    session_rows = bars_by_date.get(session_date.isoformat()) or []
    if not session_rows:
        return {**base, "session_complete": True, "reason": "missing_event_bar"}
    ohlc = session_rows[-1]
    if valid_daily_ohlc(ohlc.get("open"), ohlc.get("high"), ohlc.get("low"), ohlc.get("close")) is None:
        return {**base, "session_complete": True, "reason": "invalid_ohlc"}
    location = daily_bar_location(ohlc.get("open"), ohlc.get("high"), ohlc.get("low"), ohlc.get("close"))
    prior_volumes: list[Any] = []
    prior_bars: list[dict[str, Any]] = []
    atr_window: list[dict[str, Any]] = []
    for day in prior_sessions:
        rows = bars_by_date.get(day)
        if not rows:
            return {**base, "session_complete": True, "reason": "missing_prior_session"}
        prior_ohlc = rows[-1]
        if valid_daily_ohlc(
            prior_ohlc.get("open"), prior_ohlc.get("high"), prior_ohlc.get("low"), prior_ohlc.get("close")
        ) is None:
            return {**base, "session_complete": True, "reason": "invalid_prior_ohlc"}
        if valid_session_volume(prior_ohlc.get("volume")) is None:
            return {**base, "session_complete": True, "reason": "missing_prior_volume"}
        prior_volumes.append(prior_ohlc.get("volume"))
        packed = {
            "session_date": day,
            "open": _finite(prior_ohlc.get("open")),
            "high": _finite(prior_ohlc.get("high")),
            "low": _finite(prior_ohlc.get("low")),
            "close": _finite(prior_ohlc.get("close")),
            "volume": _finite(prior_ohlc.get("volume")),
        }
        prior_bars.append(packed)
        atr_window.append(packed)
    session_packed = {
        "session_date": session_date.isoformat(),
        "open": _finite(ohlc.get("open")),
        "high": _finite(ohlc.get("high")),
        "low": _finite(ohlc.get("low")),
        "close": _finite(ohlc.get("close")),
        "volume": _finite(ohlc.get("volume")),
    }
    atr_window.append(session_packed)
    identity = t1_input_identity(
        event_id=event_id or prior.get("event_id") or "",
        session_date=session_date,
        resistance_high=resistance_high,
        session_bar=session_packed,
        prior_bars=prior_bars,
        settings=cfg,
    )
    if (
        prior.get("identity_hash") == identity
        and prior.get("status") in T1_TERMINAL_STATUSES
        and prior.get("version") == T1_VERSION
    ):
        reused = dict(prior)
        reused.update(
            {
                "computed_at": computed_at,
                "session_complete": True,
                "identity_hash": identity,
                "identity_complete": True,
                "reused": True,
                "first_known_at": first_known or prior.get("known_at"),
                "event_id": event_id or prior.get("event_id"),
            }
        )
        reused.pop("latest_attempt", None)
        return reused
    rvol = rvol_daily_20med(ohlc.get("volume"), prior_volumes, lookback=lookback)
    atr = compute_atr(atr_window, period=int(cfg["atr_period"]))
    close_v = _finite(ohlc.get("close"))
    resistance = _finite(resistance_high)
    if resistance is None:
        return {
            **base,
            "session_complete": True,
            "data_through": session_date.isoformat(),
            "identity_hash": identity,
            "identity_complete": False,
            "reason": "missing_resistance",
        }
    if atr is None or atr <= 0:
        return {
            **base,
            "session_complete": True,
            "data_through": session_date.isoformat(),
            "identity_hash": identity,
            "identity_complete": False,
            "reason": "atr_unavailable",
            "rvol_daily_20med": rvol.get("rvol_daily_20med"),
            "rvol_detail": rvol,
        }
    distance = (close_v - resistance) / atr if close_v is not None else None
    checks = t1_checks(
        clv=location["clv"],
        rvol=rvol.get("rvol_daily_20med"),
        upper_shadow=location["upper_shadow_ratio"],
        distance_atr=distance,
        settings=cfg,
    )
    detail = {
        "status": rvol.get("status"),
        "reason": rvol.get("reason"),
        "lookback_used": rvol.get("lookback_used"),
        "denominator": rvol.get("denominator"),
    }
    if not checks["available"]:
        reason = rvol.get("reason") or (
            "invalid_ohlc" if location.get("invalid_ohlc")
            else "zero_range" if location.get("zero_range")
            else "t1_inputs_unavailable"
        )
        return {
            **base,
            "status": T1_UNAVAILABLE,
            "session_complete": True,
            "data_through": session_date.isoformat(),
            "identity_hash": identity,
            "identity_complete": False,
            "reason": reason,
            "checks": checks["checks"],
            "clv": checks["clv"],
            "rvol_daily_20med": checks["rvol"],
            "upper_shadow_ratio": checks["upper_shadow_ratio"],
            "breakout_distance_atr": checks["breakout_distance_atr"],
            "rvol_detail": detail,
        }
    status = T1_MET if checks["satisfied"] else T1_UNMET
    reason = None if status == T1_MET else "conditions_not_met"
    known_at = computed_at
    revisions = list(prior.get("revisions") or [])
    eval_version = int(prior.get("eval_version") or 0) or 1
    if (
        prior.get("status") in T1_TERMINAL_STATUSES
        and prior.get("identity_hash")
        and prior.get("identity_hash") != identity
    ):
        revisions.append(
            {
                "eval_version": eval_version,
                "identity_hash": prior.get("identity_hash"),
                "status": prior.get("status"),
                "known_at": prior.get("known_at"),
                "computed_at": prior.get("computed_at"),
            }
        )
        eval_version += 1
        first_known = prior.get("first_known_at") or prior.get("known_at") or known_at
    return {
        **base,
        "status": status,
        "session_complete": True,
        "data_through": session_date.isoformat(),
        "known_at": known_at,
        "first_known_at": first_known or known_at,
        "eval_version": eval_version,
        "identity_hash": identity,
        "identity_complete": True,
        "revisions": revisions,
        "reused": False,
        "event_id": event_id or prior.get("event_id"),
        "checks": checks["checks"],
        "clv": checks["clv"],
        "rvol_daily_20med": checks["rvol"],
        "upper_shadow_ratio": checks["upper_shadow_ratio"],
        "breakout_distance_atr": checks["breakout_distance_atr"],
        "reason": reason,
        "rvol_detail": detail,
    }


def production_event_sort_key(event: Mapping[str, Any]) -> tuple[Any, ...]:
    """Match repository list order: usable priority first, then event_id ASC.

    SQL is ``ORDER BY alert_priority IS NULL, alert_priority DESC, event_id``.
    Reverse=True therefore puts a *low* event_id last in the tuple so we invert
    the code with a leading unusable-priority flag only.
    """

    priority = _finite(event.get("alert_priority"))
    return (
        priority is not None,
        priority if priority is not None else -1.0,
        str(event.get("event_id") or ""),
    )


def event_group_key(event: Mapping[str, Any]) -> str:
    trading = _as_date(event.get("discovered_date") or event.get("trading_date"))
    return trading.isoformat() if trading is not None else ""


def apply_t1_stable_boost(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Boost T1-met events inside each trading-date group's original slots.

    Incoming order is the production order. Zero boostable events returns that
    sequence item-for-item — dates are not regrouped. When at least one event
    is boostable, each discovered-date group is stably partitioned into met /
    rest and written back into the group's original index slots so interleaved
    dates (A T / B T-1 / C T) do not collapse into A,C,B.
    """

    items = [dict(item) for item in events]
    if not any(t1_boost_eligible(item) for item in items):
        return items
    groups: dict[str, list[int]] = {}
    group_order: list[str] = []
    for index, item in enumerate(items):
        key = event_group_key(item)
        if key not in groups:
            group_order.append(key)
            groups[key] = []
        groups[key].append(index)
    boosted = list(items)
    for key in group_order:
        slots = groups[key]
        bucket = [items[index] for index in slots]
        met = [item for item in bucket if t1_boost_eligible(item)]
        rest = [item for item in bucket if not t1_boost_eligible(item)]
        for slot, item in zip(slots, met + rest):
            boosted[slot] = item
    return boosted


def attach_t1_features(
    event: Mapping[str, Any],
    daily: Sequence[Mapping[str, Any]] | None,
    *,
    as_of: datetime,
    previous: Mapping[str, Any] | None = None,
    is_trading_day: Callable[[str], bool | None] | None = None,
    prior_trading_sessions: Callable[[date, int], list[str] | None] | None = None,
) -> dict[str, Any]:
    payload = dict(event)
    features = dict(payload.get("features") or {})
    computed_at = _aware(as_of).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    session_date = _as_date(payload.get("discovered_date") or payload.get("trading_date"))
    if not t1_setup_applicable(payload):
        evaluation = {
            "version": T1_VERSION,
            "variant": T1_ALGORITHM,
            "status": T1_NOT_APPLICABLE,
            "reason": "setup_not_in_t1_universe",
            "setup_type": str(payload.get("signal_type") or ""),
            "session_date": session_date.isoformat() if session_date else None,
            "computed_at": computed_at,
            "known_at": None,
            "identity_complete": False,
        }
    elif session_date is None:
        evaluation = {
            "version": T1_VERSION,
            "variant": T1_ALGORITHM,
            "status": T1_UNAVAILABLE,
            "reason": "missing_trading_date",
            "computed_at": computed_at,
            "identity_complete": False,
        }
    elif not frozen_platform_evidence(payload):
        evaluation = {
            "version": T1_VERSION,
            "variant": T1_ALGORITHM,
            "status": T1_NOT_APPLICABLE,
            "reason": "missing_frozen_platform",
            "session_date": session_date.isoformat(),
            "computed_at": computed_at,
            "known_at": None,
            "identity_complete": False,
        }
    else:
        evaluation = evaluate_t1_from_daily(
            daily,
            session_date=session_date,
            resistance_high=t1_resistance_high(payload),
            as_of=as_of,
            previous=previous if previous is not None else (
                features.get("t1_priority")
                if isinstance(features.get("t1_priority"), Mapping)
                else payload.get("t1_priority")
                if isinstance(payload.get("t1_priority"), Mapping)
                else None
            ),
            event_id=str(payload.get("event_id") or "") or None,
            is_trading_day=is_trading_day,
            prior_trading_sessions=prior_trading_sessions,
        )
    features["t1_priority"] = evaluation
    payload["features"] = features
    payload["t1_priority"] = evaluation
    return payload
