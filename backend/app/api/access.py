"""アクセス API: 状態確認・ログイン・ログアウト（オーナー単一プリンシパル）。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.access import (
    LoginRejected,
    OWNER_COOKIE_NAME,
    OWNER_SESSION_SECONDS,
    get_access_runtime,
    request_is_owner_session,
    request_uses_https,
    require_same_origin_json,
    require_same_origin_request,
)
from app.services.request_security import request_client_ip

router = APIRouter(prefix="/api/access", tags=["access"])


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=256)


@router.get("/status")
def access_status(request: Request) -> dict:
    runtime = get_access_runtime()
    return {
        "mode": runtime.mode,
        "is_owner": request_is_owner_session(request),
        "password_configured": runtime.password_configured,
    }


@router.post("/login")
def login(request: Request, body: LoginBody, response: Response) -> dict:
    require_same_origin_json(request)
    runtime = get_access_runtime()
    if runtime.mode != "password":
        raise HTTPException(status_code=400, detail={"code": "login_not_required"})
    if not request_uses_https(request):
        raise HTTPException(
            status_code=status.HTTP_426_UPGRADE_REQUIRED,
            detail={"code": "https_required", "message": "Login requires HTTPS"},
        )
    try:
        result = runtime.login(body.password, client_key=request_client_ip(request))
    except LoginRejected as exc:
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        raise HTTPException(
            status_code=(429 if exc.code == "login_cooldown" else 401),
            detail={"code": exc.code},
            headers=headers,
        ) from exc
    response.set_cookie(
        OWNER_COOKIE_NAME,
        result.session_token,
        max_age=OWNER_SESSION_SECONDS,
        secure=True,
        httponly=True,
        samesite="strict",
        path="/",
    )
    return {"logged_in": True}


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    require_same_origin_request(request)
    runtime = get_access_runtime()
    runtime.logout(request.cookies.get(OWNER_COOKIE_NAME, ""))
    response.delete_cookie(OWNER_COOKIE_NAME, path="/")
    return {"logged_in": False}
