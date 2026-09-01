"""ブレイクアウトレーダー API（日足・引け後スキャンの結果を提供）。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import core_repository
from app.domain.symbols import display_code, normalize_input_code
from app.services.radar.engine import ALL_SIGNAL_TYPES
from app.services.radar.lifecycle import ALL_STATES
from app.services.short_monitor import radar_link
from app.services.short_monitor.states import ORDERED_STATES as SHORT_STATES

router = APIRouter(prefix="/api/radar", tags=["radar"])


@router.get("/current")
def radar_current(
    states: str | None = Query(default=None),
    signals: str | None = Query(default=None),
    min_priority: float | None = Query(default=None, ge=0, le=100),
    limit: int = Query(default=120, ge=1, le=400),
    short_states: str | None = Query(default=None),
    short_flags: str | None = Query(default=None),
    exclude_short_flags: str | None = Query(default=None),
    min_short_confidence: float | None = Query(default=None, ge=0.0, le=1.0),
) -> dict:
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
        return {"scan_date": None, "events": [], "note": "レーダー未実行"}
    state_filter = _csv_filter(states, ALL_STATES)
    signal_filter = _csv_filter(signals, ALL_SIGNAL_TYPES)
    events = repository.radar_events_scanned_on(
        scan_date,
        states=state_filter,
        signal_types=signal_filter,
        min_priority=min_priority,
        limit=limit,
    )
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
    return {
        "scan_date": scan_date,
        "granularity": "daily",
        "events": views,
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
    return _event_view(repository, event, include_transitions=True)


@router.get("/securities/{code}")
def radar_for_security(code: str) -> dict:
    canonical = normalize_input_code(code)
    if canonical is None:
        raise HTTPException(status_code=422, detail={"code": "invalid_code_format"})
    repository = core_repository()
    events = repository.radar_events_for_code(canonical, limit=40)
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
    }
    if include_transitions:
        view["transitions"] = event.get("transitions") or []
    return view
