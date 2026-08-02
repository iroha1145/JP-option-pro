"""自選株 API — 主体解決型（オーナー / 訪客アカウント）。

- オーナーセッション → 従来の watchlist テーブル（jp-app.db）
- 訪客アカウント cookie → account_watchlist（jp-app.db、身元は共有 accounts.db）
- 匿名 → 401 account_login_required

訪客 cookie が同時に存在する場合は訪客リストを優先する（米国版と同じ:
画面に見えているのは自分のリストであるべき）。書き込みは同一オリジン
ガード必須。オーナー権限はここでは何も付与しない。
"""

from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Request

from app.access import (
    request_is_owner_session,
    require_same_origin_json,
    require_same_origin_request,
)
from app.api.account import current_account
from app.api.deps import app_store, core_repository
from app.domain.symbols import display_code, normalize_input_code

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


def _principal(request: Request) -> tuple[str, str | None]:
    """(kind, user_id): kind は 'account' か 'owner'。匿名は 401。"""

    account = current_account(request)
    if account is not None:
        return "account", account.user_id
    if request_is_owner_session(request):
        return "owner", None
    raise HTTPException(
        status_code=401,
        detail={"code": "account_login_required", "message": "请先登录"},
    )


def _entries(kind: str, user_id: str | None) -> list[dict]:
    store = app_store()
    if kind == "account" and user_id:
        return store.account_watchlist(user_id)
    return store.watchlist()


@router.get("")
def get_watchlist(request: Request) -> dict:
    kind, user_id = _principal(request)
    repository = core_repository()
    items = []
    core_ready = repository.exists()
    for entry in _entries(kind, user_id):
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
    return {
        "items": items,
        "principal": kind,
        "max_items": app_store().ACCOUNT_WATCHLIST_MAX if kind == "account" else None,
    }


def _normalize_or_422(code: str) -> str:
    canonical = normalize_input_code(code)
    if canonical is None:
        raise HTTPException(status_code=422, detail={"code": "invalid_code_format"})
    return canonical


@router.post("/{code}", status_code=201)
def add_watchlist(code: str, request: Request) -> dict:
    # POST はボディ無し運用（既存クライアント互換）なので JSON 要求はしない。
    require_same_origin_request(request)
    kind, user_id = _principal(request)
    canonical = _normalize_or_422(code)
    repository = core_repository()
    if repository.exists() and repository.get_security(canonical) is None:
        raise HTTPException(status_code=404, detail={"code": "unknown_security"})
    store = app_store()
    if kind == "account" and user_id:
        try:
            created = store.account_add_to_watchlist(user_id, canonical)
        except ValueError:
            raise HTTPException(
                status_code=409,
                detail={"code": "watchlist_full", "message": f"自选最多 {store.ACCOUNT_WATCHLIST_MAX} 只"},
            ) from None
    else:
        created = store.add_to_watchlist(canonical)
    return {"canonical_code": canonical, "created": created}


@router.patch("/{code}")
def update_watchlist(
    code: str,
    request: Request,
    note: str | None = Body(default=None, embed=True, max_length=2000),
    marked_important: bool | None = Body(default=None, embed=True),
) -> dict:
    require_same_origin_json(request)
    kind, user_id = _principal(request)
    canonical = _normalize_or_422(code)
    store = app_store()
    if kind == "account" and user_id:
        updated = store.account_update_watchlist_item(
            user_id, canonical, note=note, marked_important=marked_important
        )
    else:
        updated = store.update_watchlist_item(
            canonical, note=note, marked_important=marked_important
        )
    if not updated:
        raise HTTPException(status_code=404, detail={"code": "not_in_watchlist"})
    return {"canonical_code": canonical, "updated": True}


@router.delete("/{code}")
def remove_watchlist(code: str, request: Request) -> dict:
    require_same_origin_request(request)
    kind, user_id = _principal(request)
    canonical = _normalize_or_422(code)
    store = app_store()
    if kind == "account" and user_id:
        removed = store.account_remove_from_watchlist(user_id, canonical)
    else:
        removed = store.remove_from_watchlist(canonical)
    if not removed:
        raise HTTPException(status_code=404, detail={"code": "not_in_watchlist"})
    return {"canonical_code": canonical, "removed": True}
