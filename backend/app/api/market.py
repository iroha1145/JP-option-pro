"""市場オーバービュー API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.deps import core_repository
from app.domain.constants import INDEX_CODES
from app.repositories.base import SchemaVersionError
from app.services.market import market_overview

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
