"""GET/PUT personal algorithm preferences and owner-only admin defaults."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.access import (
    request_is_owner_session,
    require_same_origin_json,
)
from app.api.account import current_account
from app.api.deps import app_store
from app.services.algorithm_modes import UnknownAlgorithmError
from app.services.view_preferences import (
    preference_principal,
    read_admin_defaults,
    read_view_preferences,
    write_admin_defaults,
    write_view_preferences,
)

router = APIRouter(prefix="/api", tags=["view-preferences"])


def _signed_in_principal(request: Request) -> str | None:
    account = current_account(request)
    if account is not None:
        return preference_principal("account", account.user_id)
    if request_is_owner_session(request):
        return preference_principal("owner", None)
    return None


@router.get("/view-preferences")
def get_view_preferences(request: Request) -> dict:
    principal = _signed_in_principal(request)
    defaults = read_admin_defaults(app_store())
    if principal is None:
        return {
            "principal": None,
            "preferences": {"screener_ranking_algorithm": "follow_default", "radar_sort_algorithm": "follow_default"},
            "admin_defaults": {
                "screener_ranking_algorithm": defaults["screener_ranking_algorithm"],
                "radar_sort_algorithm": defaults["radar_sort_algorithm"],
            },
        }
    prefs = read_view_preferences(app_store(), principal)
    return {
        "principal": principal,
        "preferences": prefs.as_dict(),
        "admin_defaults": {
            "screener_ranking_algorithm": defaults["screener_ranking_algorithm"],
            "radar_sort_algorithm": defaults["radar_sort_algorithm"],
        },
    }


@router.put("/view-preferences")
def put_view_preferences(request: Request, body: dict) -> dict:
    require_same_origin_json(request)
    principal = _signed_in_principal(request)
    if principal is None:
        raise HTTPException(status_code=401, detail={"code": "account_login_required"})
    try:
        prefs = write_view_preferences(app_store(), principal, body)
    except UnknownAlgorithmError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "value": exc.value}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=500, detail={"code": "preference_write_failed", "message": str(exc)}) from exc
    return {"principal": principal, "preferences": prefs.as_dict()}


@router.get("/algorithm-defaults")
def get_algorithm_defaults() -> dict:
    return read_admin_defaults(app_store())


@router.put("/algorithm-defaults")
def put_algorithm_defaults(request: Request, body: dict) -> dict:
    require_same_origin_json(request)
    if not request_is_owner_session(request):
        raise HTTPException(status_code=403, detail={"code": "owner_required"})
    try:
        return write_admin_defaults(app_store(), body)
    except UnknownAlgorithmError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "value": exc.value}) from exc
