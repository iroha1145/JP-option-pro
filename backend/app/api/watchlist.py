"""自選株 API（オーナー専用の書き込み、jp-app.db）。"""

from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException

from app.api.deps import app_store, core_repository
from app.domain.symbols import display_code, normalize_input_code

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


@router.get("")
def get_watchlist() -> dict:
    store = app_store()
    repository = core_repository()
    items = []
    core_ready = repository.exists()
    for entry in store.watchlist():
        code = entry["canonical_code"]
        security = repository.get_security(code) if core_ready else None
        row = {
            "canonical_code": code,
            "display_code": display_code(code),
            "note": entry.get("note"),
            "marked_important": bool(entry.get("marked_important")),
            "added_at": entry.get("added_at"),
            "name_ja": security.get("name_ja") if security else None,
            "sector33_name": security.get("sector33_name") if security else None,
            "market_name": security.get("market_name") if security else None,
            "quote": None,
        }
        if core_ready:
            bars = repository.bars_for_code(code, limit=2)
            if bars:
                last = bars[-1]
                prev = bars[-2] if len(bars) >= 2 else None
                change = None
                if prev and last.get("adj_close") and prev.get("adj_close"):
                    change = last["adj_close"] / prev["adj_close"] - 1.0
                row["quote"] = {
                    "trade_date": last.get("trade_date"),
                    "close": last.get("close"),
                    "change_pct": change,
                    "turnover_value": last.get("turnover_value"),
                }
        items.append(row)
    return {"items": items}


@router.post("/{code}", status_code=201)
def add_watchlist(code: str) -> dict:
    canonical = normalize_input_code(code)
    if canonical is None:
        raise HTTPException(status_code=422, detail={"code": "invalid_code_format"})
    repository = core_repository()
    if repository.exists() and repository.get_security(canonical) is None:
        raise HTTPException(status_code=404, detail={"code": "unknown_security"})
    created = app_store().add_to_watchlist(canonical)
    return {"canonical_code": canonical, "created": created}


@router.patch("/{code}")
def update_watchlist(
    code: str,
    note: str | None = Body(default=None, embed=True, max_length=2000),
    marked_important: bool | None = Body(default=None, embed=True),
) -> dict:
    canonical = normalize_input_code(code)
    if canonical is None:
        raise HTTPException(status_code=422, detail={"code": "invalid_code_format"})
    updated = app_store().update_watchlist_item(
        canonical, note=note, marked_important=marked_important
    )
    if not updated:
        raise HTTPException(status_code=404, detail={"code": "not_in_watchlist"})
    return {"canonical_code": canonical, "updated": True}


@router.delete("/{code}")
def remove_watchlist(code: str) -> dict:
    canonical = normalize_input_code(code)
    if canonical is None:
        raise HTTPException(status_code=422, detail={"code": "invalid_code_format"})
    removed = app_store().remove_from_watchlist(canonical)
    if not removed:
        raise HTTPException(status_code=404, detail={"code": "not_in_watchlist"})
    return {"canonical_code": canonical, "removed": True}
