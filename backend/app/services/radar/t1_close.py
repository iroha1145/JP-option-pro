"""T1 batch evaluation after daily bars land, plus bounded close-completion.

Local bars are the primary input. A real upstream fetch is reserved only
when the T session bar is still missing after the vendor-ready gate.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Mapping, Sequence

from app.domain.timeutil import JST, now_jst
from app.services.algorithm_modes import T1_ALGORITHM
from app.services.radar.adjustment import adjust_series
from app.services.radar.t1_priority import (
    T1_MET,
    T1_NOT_APPLICABLE,
    T1_RETRYABLE_REASONS,
    T1_UNMET,
    attach_t1_features,
    t1_needs_close_eval,
    t1_setup_applicable,
    vendor_publish_ready,
)

T1_RETRY_MAX_ATTEMPTS = 8
T1_RETRY_BASE_SECONDS = 30.0
T1_RETRY_MAX_DELAY = 300.0

BarFetcher = Callable[[Sequence[str], str], Awaitable[Mapping[str, Sequence[Mapping[str, Any]]]]]


def _adjusted_through(repository, canonical_code: str, session_date: str) -> list[dict[str, Any]]:
    raw = repository.bars_for_code(canonical_code, end_date=session_date, limit=80)
    if not raw:
        return []
    return adjust_series(raw)


def _calendar_helpers(repository):
    def is_trading_day(value: str) -> bool | None:
        return repository.is_trading_day(value)

    def prior_trading_sessions(session: date, count: int) -> list[str] | None:
        return repository.prior_trading_sessions(session.isoformat(), count)

    return is_trading_day, prior_trading_sessions


def evaluate_t1_from_local_bars(
    repository,
    *,
    scan_date: str | None = None,
    as_of: datetime | None = None,
    events: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Score applicable events from bars already in jp-core.db. No N+1 fetch."""

    moment = as_of or now_jst()
    source = list(events) if events is not None else repository.applicable_t1_events(scan_date=scan_date)
    source = repository.overlay_t1_evaluations(source)
    is_trading_day, prior_sessions = _calendar_helpers(repository)
    updated: list[dict[str, Any]] = []
    for event in source:
        if not t1_setup_applicable(event):
            attached = attach_t1_features(
                event, None, as_of=moment,
                is_trading_day=is_trading_day,
                prior_trading_sessions=prior_sessions,
            )
            updated.append(attached)
            continue
        session = str(event.get("discovered_date") or "")[:10]
        bars = _adjusted_through(repository, str(event.get("canonical_code") or ""), session) if session else []
        previous = event.get("t1_priority") if isinstance(event.get("t1_priority"), Mapping) else None
        attached = attach_t1_features(
            event,
            bars,
            as_of=moment,
            previous=previous,
            is_trading_day=is_trading_day,
            prior_trading_sessions=prior_sessions,
        )
        updated.append(attached)
    written = repository.persist_t1_evaluations(updated)
    return {"attempted": len(updated), "written": written}


async def complete_pending_t1(
    repository,
    *,
    as_of: datetime | None = None,
    fetcher: BarFetcher | None = None,
    first_fetch_hhmm: str = "17:00",
    retry_base_seconds: float = T1_RETRY_BASE_SECONDS,
    persist_required_on_reserve: bool = True,
) -> dict[str, Any]:
    """Finish pending T1 after the close. Reservation happens before dispatch."""

    moment = as_of or now_jst()
    events = repository.overlay_t1_evaluations(repository.applicable_t1_events())
    pending = [item for item in events if t1_needs_close_eval(item)]
    if not pending:
        return {
            "attempted": 0,
            "completed": 0,
            "pending": 0,
            "retry": False,
            "reason": "no_pending",
        }

    def retry_identity(event: Mapping[str, Any]) -> tuple[str, str, str]:
        payload = event.get("t1_priority") if isinstance(event.get("t1_priority"), Mapping) else {}
        session_date = str((payload or {}).get("session_date") or event.get("discovered_date") or "")
        event_id = str(event.get("event_id") or "")
        return f"{event_id}|{session_date}|{T1_ALGORITHM}", event_id, session_date

    def parse_eligible(raw: Any) -> bool:
        if not raw:
            return True
        try:
            when = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return True
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return when <= moment.astimezone(timezone.utc)

    stored: dict[str, dict[str, Any]] = {}
    try:
        stored = repository.load_t1_retry_states([retry_identity(item)[0] for item in pending])
    except Exception:
        return {
            "attempted": 0,
            "completed": 0,
            "pending": len(pending),
            "retry": False,
            "reason": "retry_budget_unreadable",
        }

    eligible: list[dict[str, Any]] = []
    blocked_delays: list[float] = []
    exhausted_count = 0
    waiting_vendor = 0
    for event in pending:
        session_text = str(event.get("discovered_date") or "")[:10]
        try:
            session_date = date.fromisoformat(session_text)
        except ValueError:
            eligible.append(event)
            continue
        if not vendor_publish_ready(session_date, as_of=moment, first_fetch_hhmm=first_fetch_hhmm):
            waiting_vendor += 1
            continue
        key, _event_id, _session = retry_identity(event)
        state = dict(stored.get(key) or {})
        if state.get("exhausted"):
            exhausted_count += 1
            continue
        if not parse_eligible(state.get("next_eligible_at")):
            try:
                when = datetime.fromisoformat(str(state.get("next_eligible_at")).replace("Z", "+00:00"))
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
                blocked_delays.append(max(0.0, (when - moment.astimezone(timezone.utc)).total_seconds()))
            except (TypeError, ValueError):
                blocked_delays.append(retry_base_seconds)
            continue
        eligible.append(event)
    if not eligible:
        if waiting_vendor:
            return {
                "attempted": 0,
                "completed": 0,
                "pending": len(pending) - exhausted_count,
                "retry": True,
                "reason": "waiting_vendor_publish",
            }
        if blocked_delays:
            return {
                "attempted": 0,
                "completed": 0,
                "pending": len(pending) - exhausted_count,
                "retry": True,
                "reason": "t1_retry_not_due",
                "retry_after_seconds": min(blocked_delays),
            }
        return {
            "attempted": 0,
            "completed": 0,
            "pending": exhausted_count,
            "retry": False,
            "reason": "t1_retry_budget_exhausted",
        }

    def persist_states(states: list[dict[str, Any]], *, required: bool = False) -> None:
        if not states:
            return
        try:
            repository.save_t1_retry_states(states)
        except Exception:
            if required:
                raise

    def bump_states(
        items: Sequence[Mapping[str, Any]],
        reason: str,
        *,
        persist_required: bool = False,
    ) -> tuple[list[dict[str, Any]], float | None, int]:
        updates: list[dict[str, Any]] = []
        delays: list[float] = []
        max_attempt = 0
        for event in items:
            key, event_id, session_date = retry_identity(event)
            current = dict(stored.get(key) or {
                "retry_key": key,
                "event_id": event_id,
                "session_date": session_date,
                "algorithm": T1_ALGORITHM,
                "attempt": 0,
                "max_attempts": T1_RETRY_MAX_ATTEMPTS,
            })
            attempt = int(current.get("attempt") or 0) + 1
            cap = int(current.get("max_attempts") or T1_RETRY_MAX_ATTEMPTS)
            max_attempt = max(max_attempt, attempt)
            if attempt >= cap:
                current.update({
                    "retry_key": key, "event_id": event_id, "session_date": session_date,
                    "algorithm": T1_ALGORITHM, "attempt": attempt, "max_attempts": cap,
                    "next_eligible_at": None, "exhausted": True, "last_reason": reason,
                })
            else:
                delay = min(T1_RETRY_MAX_DELAY, retry_base_seconds * (2 ** min(attempt - 1, 3)))
                next_at = moment.astimezone(timezone.utc) + timedelta(seconds=delay)
                current.update({
                    "retry_key": key, "event_id": event_id, "session_date": session_date,
                    "algorithm": T1_ALGORITHM, "attempt": attempt, "max_attempts": cap,
                    "next_eligible_at": next_at.isoformat().replace("+00:00", "Z"),
                    "exhausted": False, "last_reason": reason,
                })
                delays.append(delay)
            stored[key] = current
            updates.append(current)
        persist_states(updates, required=persist_required)
        return updates, (min(delays) if delays else None), max_attempt

    needs_fetch: list[dict[str, Any]] = []
    local_ready: list[dict[str, Any]] = []
    is_trading_day, prior_sessions = _calendar_helpers(repository)
    for event in eligible:
        session = str(event.get("discovered_date") or "")[:10]
        bars = _adjusted_through(repository, str(event.get("canonical_code") or ""), session) if session else []
        has_t = any(str(bar.get("trade_date") or "")[:10] == session for bar in bars)
        if has_t:
            local_ready.append(event)
        else:
            needs_fetch.append(event)

    completed = 0
    finished_keys: list[str] = []
    updated_events: list[dict[str, Any]] = []
    for event in local_ready:
        session = str(event.get("discovered_date") or "")[:10]
        bars = _adjusted_through(repository, str(event.get("canonical_code") or ""), session)
        attached = attach_t1_features(
            event, bars, as_of=moment,
            previous=event.get("t1_priority") if isinstance(event.get("t1_priority"), Mapping) else None,
            is_trading_day=is_trading_day,
            prior_trading_sessions=prior_sessions,
        )
        updated_events.append(attached)
        status = str((attached.get("t1_priority") or {}).get("status") or "")
        reason = str((attached.get("t1_priority") or {}).get("reason") or "")
        if status in {T1_MET, T1_UNMET, T1_NOT_APPLICABLE} or (
            status == "unavailable" and reason not in T1_RETRYABLE_REASONS
        ):
            completed += 1
            finished_keys.append(retry_identity(event)[0])

    reserved_delay = None
    reserved_attempt = 0
    if needs_fetch:
        if fetcher is None:
            bump_states(needs_fetch, "price_adapter_unavailable")
        else:
            try:
                _, reserved_delay, reserved_attempt = bump_states(
                    needs_fetch, "t1_dispatch_reserved", persist_required=persist_required_on_reserve,
                )
            except Exception:
                return {
                    "attempted": len(eligible),
                    "completed": completed,
                    "pending": len(pending) - completed,
                    "retry": True,
                    "reason": "reservation_persist_failed",
                }
            codes = list(dict.fromkeys(str(item.get("canonical_code") or "") for item in needs_fetch if item.get("canonical_code")))
            session_dates = list(dict.fromkeys(str(item.get("discovered_date") or "")[:10] for item in needs_fetch))
            session_for_fetch = session_dates[0] if session_dates else ""
            try:
                fetched = await fetcher(codes, session_for_fetch)
            except (asyncio.CancelledError, KeyboardInterrupt):
                raise
            except Exception:
                return {
                    "attempted": len(eligible),
                    "completed": completed,
                    "pending": len(pending) - completed,
                    "retry": reserved_delay is not None,
                    "reason": "daily_fetch_failed",
                    "retry_after_seconds": reserved_delay,
                    "attempt": reserved_attempt,
                }
            fetched = fetched if isinstance(fetched, Mapping) else {}
            for event in needs_fetch:
                code = str(event.get("canonical_code") or "")
                session = str(event.get("discovered_date") or "")[:10]
                extra = list(fetched.get(code) or [])
                if extra:
                    repository.upsert_daily_bars(extra)
                bars = _adjusted_through(repository, code, session)
                attached = attach_t1_features(
                    event, bars, as_of=moment,
                    previous=event.get("t1_priority") if isinstance(event.get("t1_priority"), Mapping) else None,
                    is_trading_day=is_trading_day,
                    prior_trading_sessions=prior_sessions,
                )
                updated_events.append(attached)
                status = str((attached.get("t1_priority") or {}).get("status") or "")
                reason = str((attached.get("t1_priority") or {}).get("reason") or "")
                if status in {T1_MET, T1_UNMET, T1_NOT_APPLICABLE} or (
                    status == "unavailable" and reason not in T1_RETRYABLE_REASONS
                ):
                    completed += 1
                    finished_keys.append(retry_identity(event)[0])

    if updated_events:
        repository.persist_t1_evaluations(updated_events)
    if finished_keys:
        repository.clear_t1_retry_states(finished_keys)
    still_pending = len(pending) - completed
    retry = still_pending > 0 and (reserved_delay is not None or waiting_vendor > 0)
    return {
        "attempted": len(eligible),
        "completed": completed,
        "pending": still_pending,
        "retry": retry,
        "retry_after_seconds": reserved_delay,
        "attempt": reserved_attempt,
        "reason": None if completed else "t1_still_pending",
    }
