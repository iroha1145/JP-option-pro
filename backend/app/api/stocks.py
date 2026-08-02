"""個別銘柄 API: 検索・概要・チャート。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import core_repository
from app.domain.symbols import display_code, normalize_input_code
from app.services.stock_research import resolve_code, stock_chart, stock_overview

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


@router.get("/search")
def search(q: str = Query(min_length=1, max_length=40), limit: int = 20) -> dict:
    repository = core_repository()
    if not repository.exists():
        return {"query": q, "results": []}
    results = repository.search_securities(q, limit=max(1, min(50, limit)))
    return {
        "query": q,
        "results": [
            {
                "canonical_code": row["canonical_code"],
                "display_code": row["display_code"],
                "name_ja": row.get("name_ja"),
                "name_en": row.get("name_en"),
                "market_name": row.get("market_name"),
                "sector33_name": row.get("sector33_name"),
            }
            for row in results
        ],
    }


def _resolve_or_404(raw_code: str) -> str:
    repository = core_repository()
    if not repository.exists():
        raise HTTPException(status_code=503, detail={"code": "data_not_initialized"})
    security = resolve_code(repository, raw_code)
    if security is None:
        raise HTTPException(status_code=404, detail={"code": "unknown_security"})
    return security["canonical_code"]


@router.get("/{code}")
def get_stock(code: str) -> dict:
    canonical = _resolve_or_404(code)
    overview = stock_overview(core_repository(), canonical)
    if overview is None:
        raise HTTPException(status_code=404, detail={"code": "unknown_security"})
    return overview


@router.get("/{code}/chart")
def get_chart(
    code: str,
    range: str = Query(default="1y", pattern="^(3m|6m|1y|3y|5y|10y)$"),
    interval: str = Query(default="1d", pattern="^(1d|60m|5m|1m)$"),
) -> dict:
    canonical = _resolve_or_404(code)
    if interval == "1d":
        return stock_chart(core_repository(), canonical, range_key=range)
    from app.data_paths import get_data_paths
    from app.domain.symbols import display_code as to_display
    from app.repositories.intraday_store import IntradayStore
    from app.services.intraday import intraday_chart

    store = IntradayStore(get_data_paths().intraday_db, read_only=True)
    view = intraday_chart(store, canonical, interval=interval)
    return {
        "canonical_code": canonical,
        "display_code": to_display(canonical),
        "range": "5d",
        "interval": interval,
        "data_through": view["bars"][-1]["trade_date"] if view.get("bars") else None,
        **view,
    }


@router.get("/{code}/resolve")
def resolve(code: str) -> dict:
    canonical = normalize_input_code(code)
    if canonical is None:
        raise HTTPException(status_code=422, detail={"code": "invalid_code_format"})
    return {"canonical_code": canonical, "display_code": display_code(canonical)}
