"""ブレイクアウトレーダー API（日足・引け後スキャンの結果を提供）。"""

from __future__ import annotations

import hashlib

from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.access import request_is_owner_session
from app.api.account import current_account
from app.api.deps import app_store, core_repository
from app.domain.symbols import display_code, normalize_input_code
from app.services.algorithm_modes import (
    T1_ALGORITHM,
    UnknownAlgorithmError,
    resolve_radar_algorithm,
)
from app.services.radar.engine import ALL_SIGNAL_TYPES
from app.services.radar.lifecycle import ALL_STATES
from app.services.radar.t1_priority import apply_t1_stable_boost, t1_view_token
from app.services.short_monitor import radar_link
from app.services.short_monitor.states import ORDERED_STATES as SHORT_STATES
from app.services.view_preferences import (
    preference_principal,
    read_admin_defaults,
    read_view_preferences,
)

router = APIRouter(prefix="/api/radar", tags=["radar"])


def _request_radar_resolution(request: Request, sort_algorithm: str | None):
    store = app_store()
    defaults = read_admin_defaults(store)
    account = current_account(request)
    if account is not None:
        principal = preference_principal("account", account.user_id)
    elif request_is_owner_session(request):
        principal = preference_principal("owner", None)
    else:
        principal = None
    user_choice = None
    if principal:
        user_choice = read_view_preferences(store, principal).radar_sort_algorithm
    return resolve_radar_algorithm(
        requested=sort_algorithm,
        user_choice=user_choice,
        admin_default=defaults.get("radar_sort_algorithm"),
    )


def _maybe_304(request: Request, response: Response, etag: str) -> bool:
    response.headers["ETag"] = f'"{etag}"'
    response.headers["Cache-Control"] = "private, must-revalidate"
    incoming = request.headers.get("if-none-match")
    if incoming and incoming.strip() in {etag, f'"{etag}"'}:
        response.status_code = 304
        return True
    return False


@router.get("/current")
def radar_current(
    request: Request,
    response: Response,
    states: str | None = Query(default=None),
    signals: str | None = Query(default=None),
    min_priority: float | None = Query(default=None, ge=0, le=100),
    limit: int = Query(default=120, ge=1, le=400),
    offset: int = Query(default=0, ge=0),
    cursor: str | None = Query(default=None),
    short_states: str | None = Query(default=None),
    short_flags: str | None = Query(default=None),
    exclude_short_flags: str | None = Query(default=None),
    min_short_confidence: float | None = Query(default=None, ge=0.0, le=1.0),
    sort_algorithm: str | None = Query(default=None),
) -> dict:
    try:
        resolution = _request_radar_resolution(request, sort_algorithm)
    except UnknownAlgorithmError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "family": exc.family, "value": exc.value},
        ) from exc
    repository = core_repository()
    if not repository.exists():
        raise HTTPException(status_code=503, detail={"code": "data_not_initialized"})
    scan_date = None
    state = repository.sync_state("radar_scan")
    if state:
        scan_date = state.get("data_through")
    if not scan_date:
        scan_date = repository.latest_bar_date()
    if not scan_date:
        return {"scan_date": None, "events": [], "note": "レーダー未実行", **resolution.as_public_dict()}
    state_filter = _csv_filter(states, ALL_STATES)
    signal_filter = _csv_filter(signals, ALL_SIGNAL_TYPES)
    fetch_limit = 400 if resolution.effective == T1_ALGORITHM else limit + offset
    events = repository.radar_events_scanned_on(
        scan_date,
        states=state_filter,
        signal_types=signal_filter,
        min_priority=min_priority,
        limit=max(fetch_limit, limit),
    )
    events = repository.overlay_t1_evaluations(events)
    # 空売り行動は **重ねるだけ**。alert_priority だけを有界に動かし、
    # base_quality / breakout_confirmation / intrinsic_strength には触れない。
    snapshots = _short_behavior_map(repository, [e["canonical_code"] for e in events])
    views = [_event_view(repository, event) for event in events]
    views = radar_link.overlay(views, snapshots)
    state_filter_short = _csv_filter(short_states, tuple(SHORT_STATES))
    flag_filter = [f.strip() for f in (short_flags or "").split(",") if f.strip()] or None
    banned = [f.strip() for f in (exclude_short_flags or "").split(",") if f.strip()] or None
    if state_filter_short or flag_filter or banned or min_short_confidence is not None:
        views = [
            view for view in views
            if radar_link.matches(
                snapshots.get(view["canonical_code"]),
                states=state_filter_short, flags=flag_filter,
                exclude_flags=banned, min_confidence=min_short_confidence,
            )
        ]
    t1_view = None
    cursor_stale = False
    restart_required = False
    if resolution.effective == T1_ALGORITHM:
        views = apply_t1_stable_boost(views)
        t1_view = t1_view_token(scan_date, resolution.effective, views)
        if cursor and cursor != t1_view:
            cursor_stale = True
            restart_required = True
            offset = 0
    page = views[offset: offset + limit]
    etag = hashlib.sha256(
        "|".join(
            (
                scan_date,
                resolution.effective,
                resolution.version,
                t1_view or "",
                states or "",
                signals or "",
                str(min_priority or ""),
                str(limit),
                str(offset),
                str(len(views)),
            )
        ).encode("utf-8")
    ).hexdigest()[:32]
    if _maybe_304(request, response, etag):
        return {}
    return {
        "scan_date": scan_date,
        "granularity": "daily",
        "events": page,
        "matched_count": len(views),
        "offset": offset,
        "limit": limit,
        "t1_view": t1_view,
        "cursor_stale": cursor_stale,
        "restart_required": restart_required,
        **resolution.as_public_dict(),
    }


def _short_behavior_map(repository, codes: list[str]) -> dict[str, dict]:
    """当日の空売り行動スナップショットを 1 クエリで引く（N+1 にしない）。"""

    as_of = repository.latest_short_behavior_date()
    if not as_of or not codes:
        return {}
    import json as _json

    rows, _total = repository.short_behavior_rankings(
        as_of, codes=sorted(set(codes)), limit=len(set(codes)),
    )
    out: dict[str, dict] = {}
    for row in rows:
        try:
            flags = _json.loads(row.get("flags_json") or "[]")
        except ValueError:
            flags = []
        out[row["canonical_code"]] = {**row, "flags": flags}
    return out


@router.get("/events/{event_id}")
def radar_event(event_id: str) -> dict:
    repository = core_repository()
    event = repository.radar_event(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail={"code": "unknown_event"})
    event = repository.overlay_t1_evaluations([event])[0]
    return _event_view(repository, event, include_transitions=True)


@router.get("/securities/{code}")
def radar_for_security(code: str) -> dict:
    canonical = normalize_input_code(code)
    if canonical is None:
        raise HTTPException(status_code=422, detail={"code": "invalid_code_format"})
    repository = core_repository()
    events = repository.overlay_t1_evaluations(
        repository.radar_events_for_code(canonical, limit=40)
    )
    return {
        "canonical_code": canonical,
        "display_code": display_code(canonical),
        "events": [_event_view(repository, event, include_transitions=True) for event in events],
    }


def _csv_filter(raw: str | None, allowed: tuple[str, ...]) -> list[str] | None:
    if not raw:
        return None
    values = [item.strip() for item in raw.split(",") if item.strip()]
    filtered = [value for value in values if value in allowed]
    return filtered or None


def _event_view(repository, event: dict, *, include_transitions: bool = False) -> dict:
    code = event["canonical_code"]
    security = repository.get_security(code) or {}
    view = {
        "event_id": event["event_id"],
        "canonical_code": code,
        "display_code": display_code(code),
        "name_ja": security.get("name_ja"),
        "sector33_name": security.get("sector33_name"),
        "market_name": security.get("market_name"),
        "signal_type": event["signal_type"],
        "state": event["state"],
        "discovered_date": event["discovered_date"],
        "state_changed_date": event["state_changed_date"],
        "last_scanned_date": event["last_scanned_date"],
        "pivot_price": event.get("pivot_price"),
        "trigger_price": event.get("trigger_price"),
        "alert_priority": event.get("alert_priority"),
        "scores": event.get("scores") or {},
        "snapshot": (event.get("features") or {}).get("snapshot") or {},
        "structure": (event.get("features") or {}).get("structure") or None,
        "t1_priority": event.get("t1_priority") or (event.get("features") or {}).get("t1_priority"),
    }
    if include_transitions:
        view["transitions"] = event.get("transitions") or []
    return view
