"""アクセス API — オーナー + 訪客アカウントの二主体（米国版 /api/access 対応）。

/login はユーザー名で分岐する: ``admin`` はオーナー（APP_PASSWORD_HASH、
プロセス内単一セッション）、それ以外は共有 accounts.db の訪客アカウント。
訪客セッションはオーナー権限を一切満たさない。後方互換のため username
省略時は owner 扱い（旧クライアントはパスワードのみ送る）。
"""

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
from app.api.account import (
    ACCOUNT_COOKIE_NAME,
    account_http_error,
    attach_account_cookie,
    check_login_cooldown,
    clear_account_cookie,
    clear_login_failures,
    current_account,
    record_login_failure,
)
from app.services.accounts import AccountError, get_account_store
from app.services.request_security import request_client_ip

OWNER_USERNAME = "admin"

router = APIRouter(prefix="/api/access", tags=["access"])


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(default=OWNER_USERNAME, min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


@router.get("/status")
def access_status(request: Request) -> dict:
    runtime = get_access_runtime()
    account = current_account(request)
    return {
        "mode": runtime.mode,
        "is_owner": request_is_owner_session(request),
        "password_configured": runtime.password_configured,
        "account": (
            {"logged_in": True, "username": account.username}
            if account is not None
            else {"logged_in": False, "username": None}
        ),
    }


def _customer_login(request: Request, body: LoginBody) -> Response:
    """訪客ログイン: account cookie のみ発行、オーナー権限には触れない。"""

    import time

    from fastapi.responses import JSONResponse

    if not request_uses_https(request):
        raise HTTPException(
            status_code=status.HTTP_426_UPGRADE_REQUIRED,
            detail={"code": "https_required", "message": "Login requires HTTPS"},
        )
    check_login_cooldown(request)
    try:
        result = get_account_store().authenticate(body.username, body.password)
    except AccountError as exc:
        record_login_failure(request)
        raise account_http_error(exc) from exc
    clear_login_failures(request)
    response = JSONResponse(
        {
            "logged_in": False,
            "account": {"logged_in": True, "username": result.account.username},
        },
        headers={"Cache-Control": "no-store"},
    )
    attach_account_cookie(response, result.token, int(max(1, result.expires_at - time.time())))
    return response


@router.post("/login", response_model=None)
def login(request: Request, body: LoginBody, response: Response) -> Response | dict:
    require_same_origin_json(request)
    if body.username.strip().casefold() != OWNER_USERNAME:
        return _customer_login(request, body)
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
    # サインアウトは一つ: 保持している方のセッションをどちらも失効させる。
    get_account_store().revoke_session(request.cookies.get(ACCOUNT_COOKIE_NAME, ""))
    response.delete_cookie(OWNER_COOKIE_NAME, path="/")
    clear_account_cookie(response)
    return {"logged_in": False}
