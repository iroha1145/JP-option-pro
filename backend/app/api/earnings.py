"""決算カレンダー API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import app_store, core_repository
from app.domain.timeutil import add_days, iso_date, today_jst
from app.services.earnings_service import recent_disclosures, upcoming_calendar

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
