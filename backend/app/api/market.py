"""市場オーバービュー API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import core_repository
from app.domain.constants import INDEX_CODES
from app.repositories.base import SchemaVersionError
from app.services.market import SECTOR_MEMBER_SORTS, market_overview, sector_members

router = APIRouter(prefix="/api/market", tags=["market"])


@router.get("/overview")
def get_market_overview() -> dict:
    repository = core_repository()
    if not repository.exists():
        raise HTTPException(status_code=503, detail={"code": "data_not_initialized"})
    try:
        return market_overview(repository)
    except SchemaVersionError as exc:
        raise HTTPException(status_code=503, detail={"code": "schema_mismatch"}) from exc


@router.get("/sectors/{sector33_code}/members")
def get_sector_members(
    sector33_code: str,
    sort: str = Query(default="turnover"),
    limit: int = Query(default=12, ge=1, le=50),
) -> dict:
    """業種の人気銘柄断面（売買代金 / 出来高倍率 / 騰落率で並べ替え）。"""

    if sort not in SECTOR_MEMBER_SORTS:
        raise HTTPException(status_code=422, detail={"code": "unknown_sort"})
    repository = core_repository()
    if not repository.exists():
        raise HTTPException(status_code=503, detail={"code": "data_not_initialized"})
    view = sector_members(repository, sector33_code=sector33_code, sort=sort, limit=limit)
    if view is None:
        raise HTTPException(status_code=404, detail={"code": "unknown_sector"})
    return view


@router.get("/indices/{index_code}")
def get_index_series(index_code: str, limit: int = 250) -> dict:
    if index_code not in INDEX_CODES:
        raise HTTPException(status_code=404, detail={"code": "unknown_index"})
    repository = core_repository()
    series = repository.index_series(index_code, limit=max(10, min(2600, limit)))
    return {
        "index_code": index_code,
        "name": INDEX_CODES[index_code],
        "data_through": series[-1]["trade_date"] if series else None,
        "bars": series,
    }
