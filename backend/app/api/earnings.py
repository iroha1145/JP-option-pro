"""決算カレンダー API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import app_store, core_repository
from app.domain.timeutil import add_days, iso_date, today_jst
from app.services.earnings_service import recent_disclosures, upcoming_calendar, upcoming_view
from app.services.radar.lifecycle import TERMINAL_STATES

router = APIRouter(prefix="/api/earnings", tags=["earnings"])

_DATE_PATTERN = "^\\d{4}-\\d{2}-\\d{2}$"


@router.get("/calendar")
def earnings_calendar(
    start: str | None = Query(default=None, pattern=_DATE_PATTERN),
    end: str | None = Query(default=None, pattern=_DATE_PATTERN),
) -> dict:
    repository = core_repository()
    if not repository.exists():
        raise HTTPException(status_code=503, detail={"code": "data_not_initialized"})
    today = iso_date(today_jst())
    start_date = start or today
    end_date = end or add_days(today, 14)
    if end_date < start_date:
        raise HTTPException(status_code=422, detail={"code": "invalid_date_range"})
    watchlist = set(app_store().watchlist_codes())
    return upcoming_calendar(
        repository, start_date=start_date, end_date=end_date, watchlist_codes=watchlist
    )


@router.get("/upcoming")
def earnings_upcoming(
    days_back: int = Query(default=3, ge=0, le=14),
    days_ahead: int = Query(default=35, ge=7, le=60),
) -> dict:
    """高密度カレンダービュー: released / confirmed / estimated / tbd の四態。"""

    repository = core_repository()
    if not repository.exists():
        raise HTTPException(status_code=503, detail={"code": "data_not_initialized"})
    today = iso_date(today_jst())
    radar_states = {
        event["canonical_code"]: event["state"]
        for event in repository.open_radar_events(terminal_states=sorted(TERMINAL_STATES))
    }
    return upcoming_view(
        repository,
        today=today,
        days_back=days_back,
        days_ahead=days_ahead,
        watchlist_codes=set(app_store().watchlist_codes()),
        radar_state_by_code=radar_states,
    )


@router.get("/recent")
def earnings_recent(days: int = Query(default=7, ge=1, le=45)) -> dict:
    repository = core_repository()
    if not repository.exists():
        raise HTTPException(status_code=503, detail={"code": "data_not_initialized"})
    today = iso_date(today_jst())
    start_date = add_days(today, -days)
    watchlist = set(app_store().watchlist_codes())
    return recent_disclosures(
        repository, start_date=start_date, end_date=today, watchlist_codes=watchlist
    )
