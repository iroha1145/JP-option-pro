"""訪客アカウント API — 登録・身元・サインアウト（米国版 /api/account 対応）。

アカウントセッションはオーナーセッションと厳密に別物: ここで発行される
cookie はどのオーナー専用ルートも満たさない。ログインは /api/access/login
（ユーザー名で owner / customer に分岐）に一本化してある。
"""

from __future__ import annotations

import threading
import time
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.access import request_uses_https, require_same_origin_json, require_same_origin_request
from app.services.accounts import Account, AccountError, get_account_store
from app.services.request_security import request_client_ip

ACCOUNT_COOKIE_NAME = "optix_user_session"

router = APIRouter(prefix="/api/account", tags=["account"])

_REGISTER_WINDOW_SECONDS = 60 * 60
_REGISTER_MAX_PER_WINDOW = 5
_LOGIN_FAILURE_LIMIT = 10
_LOGIN_FAILURE_WINDOW_SECONDS = 15 * 60
_LOGIN_COOLDOWN_SECONDS = 5 * 60

_rate_lock = threading.Lock()
_register_hits: dict[str, list[float]] = {}
_login_failures: dict[str, tuple[int, float, float]] = {}


def _client_key(request: Request) -> str:
    return request_client_ip(request)


def enforce_registration_rate(request: Request) -> None:
    key = _client_key(request)
    now = time.time()
    with _rate_lock:
        hits = [
            stamp for stamp in _register_hits.get(key, [])
            if stamp > now - _REGISTER_WINDOW_SECONDS
        ]
        if len(hits) >= _REGISTER_MAX_PER_WINDOW:
            retry_after = int(hits[0] + _REGISTER_WINDOW_SECONDS - now) + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"code": "registration_rate_limited", "message": "注册过于频繁，请稍后再试"},
                headers={"Retry-After": str(max(1, retry_after))},
            )
        hits.append(now)
        _register_hits[key] = hits


def check_login_cooldown(request: Request) -> None:
    key = _client_key(request)
    now = time.time()
    with _rate_lock:
        _count, _started_at, blocked_until = _login_failures.get(key, (0, now, 0.0))
        if blocked_until > now:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"code": "login_cooldown", "message": "登录尝试过多，请稍后再试"},
                headers={"Retry-After": str(max(1, int(blocked_until - now) + 1))},
            )


def record_login_failure(request: Request) -> None:
    key = _client_key(request)
    now = time.time()
    with _rate_lock:
        count, started_at, _blocked = _login_failures.get(key, (0, now, 0.0))
        if started_at < now - _LOGIN_FAILURE_WINDOW_SECONDS:
            count, started_at = 0, now
        count += 1
        blocked_until = now + _LOGIN_COOLDOWN_SECONDS if count >= _LOGIN_FAILURE_LIMIT else 0.0
        _login_failures[key] = (count, started_at, blocked_until)


def clear_login_failures(request: Request) -> None:
    with _rate_lock:
        _login_failures.pop(_client_key(request), None)


def reset_rate_limits() -> None:
    """テスト継ぎ目。"""

    with _rate_lock:
        _register_hits.clear()
        _login_failures.clear()


class CredentialsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


_ERROR_STATUS = {
    "username_taken": status.HTTP_409_CONFLICT,
    "registration_closed": status.HTTP_503_SERVICE_UNAVAILABLE,
    "invalid_credentials": status.HTTP_401_UNAUTHORIZED,
}

_ERROR_MESSAGE = {
    "username_required": "请填写用户名",
    "username_too_long": "用户名过长",
    "username_invalid_characters": "用户名不能包含空格或控制字符",
    "username_reserved": "该用户名已被保留，请换一个",
    "username_taken": "该用户名已被占用",
    "password_required": "请填写密码",
    "password_too_long": "密码过长",
    "password_invalid_characters": "密码包含不支持的字符",
    "registration_closed": "注册名额已满",
    "invalid_credentials": "用户名或密码不正确",
}


def account_http_error(error: AccountError) -> HTTPException:
    return HTTPException(
        status_code=_ERROR_STATUS.get(error.code, status.HTTP_400_BAD_REQUEST),
        detail={"code": error.code, "message": _ERROR_MESSAGE.get(error.code, "请求无法完成")},
    )


def current_account(request: Request) -> Account | None:
    token = request.cookies.get(ACCOUNT_COOKIE_NAME, "")
    if not token:
        return None
    return get_account_store().resolve_session(token)


def attach_account_cookie(response: Response, token: str, max_age: int) -> None:
    response.set_cookie(
        ACCOUNT_COOKIE_NAME, token,
        max_age=max_age, expires=max_age, path="/",
        secure=True, httponly=True, samesite="strict",
    )


def clear_account_cookie(response: Response) -> None:
    response.delete_cookie(
        ACCOUNT_COOKIE_NAME, path="/", secure=True, httponly=True, samesite="strict"
    )


def _account_payload(account: Account) -> dict:
    return {"logged_in": True, "username": account.username, "created_at": account.created_at}


@router.post("/register", dependencies=[Depends(require_same_origin_json)])
def register(request: Request, payload: Annotated[CredentialsRequest, Body()]) -> Response:
    if not request_uses_https(request):
        raise HTTPException(
            status_code=status.HTTP_426_UPGRADE_REQUIRED,
            detail={"code": "https_required", "message": "注册需要 HTTPS"},
        )
    enforce_registration_rate(request)
    try:
        result = get_account_store().register(payload.username, payload.password)
    except AccountError as exc:
        raise account_http_error(exc) from exc
    response = JSONResponse(
        _account_payload(result.account),
        status_code=status.HTTP_201_CREATED,
        headers={"Cache-Control": "no-store"},
    )
    attach_account_cookie(response, result.token, int(max(1, result.expires_at - time.time())))
    return response


@router.get("/me")
def me(request: Request) -> Response:
    account = current_account(request)
    body = _account_payload(account) if account is not None else {"logged_in": False, "username": None}
    return JSONResponse(body, headers={"Cache-Control": "no-store"})


@router.post("/logout", dependencies=[Depends(require_same_origin_request)])
def logout(request: Request) -> Response:
    get_account_store().revoke_session(request.cookies.get(ACCOUNT_COOKIE_NAME, ""))
    response = JSONResponse(
        {"logged_in": False, "username": None}, headers={"Cache-Control": "no-store"}
    )
    clear_account_cookie(response)
    return response
