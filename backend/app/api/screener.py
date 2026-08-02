"""スクリーナー API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.deps import app_store, core_repository
from app.domain.constants import MARKET_SEGMENTS, SECTOR33
from app.services.screener import ScreenerFilters, run_screener

router = APIRouter(prefix="/api/screener", tags=["screener"])


@router.get("/options")
def screener_options() -> dict:
    return {
        "markets": [{"code": code, "name": name} for code, name in MARKET_SEGMENTS.items()],
        "sectors": [{"code": code, "name": name} for code, name in sorted(SECTOR33.items())],
        "sort_keys": [
            "rs_topix_63d", "rs_sector_63d", "turnover_ratio", "return_20d", "return_63d",
            "pct_from_high_252", "avg_turnover_20d", "volatility_contraction", "close",
        ],
    }


@router.post("/query")
def screener_query(filters: ScreenerFilters) -> dict:
    repository = core_repository()
    if not repository.exists():
        raise HTTPException(status_code=503, detail={"code": "data_not_initialized"})
    if filters.watchlist_codes == ["__watchlist__"]:
        filters = filters.model_copy(update={"watchlist_codes": app_store().watchlist_codes()})
    return run_screener(repository, filters)
