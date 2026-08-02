"""Optix Japan API process.

Single ASGI gateway (auth gate + rate limit + cache policy + security
headers in one pass), SPA static serving with commit stamping, fail-closed
deployment boundary validation at import time — the process refuses to
bind with an unsafe configuration.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from collections import deque
from pathlib import Path

from app.runtime_environment import load_runtime_environment

load_runtime_environment()

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, Response  # noqa: E402
from starlette.middleware.gzip import GZipMiddleware  # noqa: E402
from starlette.staticfiles import StaticFiles  # noqa: E402
from starlette.types import ASGIApp, Receive, Scope, Send  # noqa: E402

from app.access import (  # noqa: E402
    get_access_runtime,
    request_owner_access_context,
    require_public_read_or_owner_access,
    require_same_origin_action,
)
from app.api import (  # noqa: E402
    access as access_api,
    data_status as data_status_api,
    earnings as earnings_api,
    market as market_api,
    news as news_api,
    radar as radar_api,
    screener as screener_api,
    settings as settings_api,
    stocks as stocks_api,
    watchlist as watchlist_api,
    worker_actions as worker_api,
)
from app.config import get_settings  # noqa: E402
from app.services.request_security import client_ip_from_scope  # noqa: E402
from fastapi import Depends  # noqa: E402

APP_NAME = "Optix Japan"

_settings = get_settings()
_ACCESS_RUNTIME = get_access_runtime()
_BOUNDARY = _ACCESS_RUNTIME.validate_startup(
    os.environ.get("HOST_BIND", _settings.HOST_BIND),
    allowed_hosts=_settings.ALLOWED_HOSTS,
    trust_proxy_headers=_settings.TRUST_PROXY_HEADERS,
    trusted_proxy_cidrs=_settings.TRUSTED_PROXY_CIDRS,
)

app = FastAPI(title=APP_NAME, docs_url=None, redoc_url=None, openapi_url=None)
app.state.access_runtime = _ACCESS_RUNTIME

# ---------------------------------------------------------------------------
# frontend location & integrity
# ---------------------------------------------------------------------------

_FRONTEND_ENV = os.environ.get("FRONTEND_DIR", "").strip()
if _FRONTEND_ENV:
    FRONTEND_DIR = Path(_FRONTEND_ENV)
else:
    _candidates = [
        Path(__file__).resolve().parents[2] / "frontend",
        Path(__file__).resolve().parents[1] / "frontend",
    ]
    FRONTEND_DIR = next((c for c in _candidates if c.is_dir()), _candidates[0])

_INDEX_PATH = FRONTEND_DIR / "index.html"
_integrity_lock = threading.Lock()
_integrity_cache: tuple[tuple[int, int], dict] | None = None


def _frontend_integrity() -> dict:
    global _integrity_cache
    try:
        stat = _INDEX_PATH.stat()
        signature = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        return {"ready": False, "sha256": None}
    with _integrity_lock:
        if _integrity_cache and _integrity_cache[0] == signature:
            return _integrity_cache[1]
        digest = hashlib.sha256(_INDEX_PATH.read_bytes()).hexdigest()
        payload = {"ready": True, "sha256": digest}
        _integrity_cache = (signature, payload)
        return payload


# ---------------------------------------------------------------------------
# gateway middleware
# ---------------------------------------------------------------------------

_RL_WINDOW_SECONDS = 60.0
_RL_LIGHT_LIMIT = 240
_RL_HEAVY_LIMIT = 40
_RL_MAX_KEYS = 10_000
_rl_lock = threading.Lock()
_rl_buckets: dict[str, deque] = {}

_HEAVY_PREFIXES = ("/api/screener/query", "/api/worker/actions")
_PUBLIC_PATHS = {"/health", "/ready"}

_CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
    "form-action 'self'"
)


def _rate_limited(key: str, *, heavy: bool) -> bool:
    limit = _RL_HEAVY_LIMIT if heavy else _RL_LIGHT_LIMIT
    now = time.monotonic()
    with _rl_lock:
        if len(_rl_buckets) > _RL_MAX_KEYS:
            cutoff = now - _RL_WINDOW_SECONDS
            for bucket_key in [k for k, v in _rl_buckets.items() if not v or v[-1] <= cutoff]:
                _rl_buckets.pop(bucket_key, None)
        bucket = _rl_buckets.setdefault(key, deque())
        while bucket and bucket[0] <= now - _RL_WINDOW_SECONDS:
            bucket.popleft()
        if len(bucket) >= limit:
            return True
        bucket.append(now)
        return False


class _GatewayMiddleware:
    """Pure-ASGI: security headers, cache policy, rate limit, owner binding."""

    def __init__(self, inner: ASGIApp) -> None:
        self._inner = inner

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._inner(scope, receive, send)
            return
        path = scope.get("path", "")
        is_api = path.startswith("/api/")
        client_ip = client_ip_from_scope(scope)
        if is_api and _rate_limited(
            f"{client_ip}:{'h' if path.startswith(_HEAVY_PREFIXES) else 'l'}",
            heavy=path.startswith(_HEAVY_PREFIXES),
        ):
            response = JSONResponse(
                {"detail": {"code": "rate_limited"}}, status_code=429,
                headers={"Retry-After": "30", "Cache-Control": "no-store"},
            )
            await response(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                existing = {key.lower() for key, _ in headers}

                def add(name: bytes, value: bytes) -> None:
                    if name.lower() not in existing:
                        headers.append((name, value))

                add(b"x-content-type-options", b"nosniff")
                add(b"x-frame-options", b"DENY")
                add(b"referrer-policy", b"no-referrer")
                add(b"cross-origin-opener-policy", b"same-origin")
                add(b"x-app-version", _settings.APP_VERSION.encode())
                add(b"x-app-commit", _settings.APP_COMMIT.encode())
                if scope.get("scheme") == "https":
                    add(b"strict-transport-security", b"max-age=31536000")
                if path.startswith("/assets/"):
                    add(b"cache-control", b"public, max-age=31536000, immutable")
                elif is_api or path in _PUBLIC_PATHS:
                    # default-deny: routes opt in by setting their own header
                    add(b"cache-control", b"private, no-store")
                else:
                    add(b"cache-control", b"no-cache, no-store, must-revalidate")
                    add(b"content-security-policy", _CSP.encode())
            await send(message)

        await self._inner(scope, receive, send_with_headers)


app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)
app.add_middleware(_GatewayMiddleware)

# ---------------------------------------------------------------------------
# routers
# ---------------------------------------------------------------------------

_PUBLIC_READ = [Depends(require_public_read_or_owner_access)]
_OWNER_ACTION = [Depends(require_public_read_or_owner_access), Depends(require_same_origin_action)]

app.include_router(market_api.router, dependencies=_PUBLIC_READ)
app.include_router(stocks_api.router, dependencies=_PUBLIC_READ)
app.include_router(screener_api.router, dependencies=_PUBLIC_READ)
app.include_router(earnings_api.router, dependencies=_PUBLIC_READ)
app.include_router(radar_api.router, dependencies=_PUBLIC_READ)
app.include_router(news_api.router, dependencies=_PUBLIC_READ)
app.include_router(data_status_api.router, dependencies=_PUBLIC_READ)
app.include_router(settings_api.router, dependencies=_PUBLIC_READ)
app.include_router(watchlist_api.router, dependencies=_OWNER_ACTION)
app.include_router(worker_api.router, dependencies=_OWNER_ACTION)
app.include_router(access_api.router)

# ---------------------------------------------------------------------------
# health / readiness
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict:
    integrity = _frontend_integrity()
    return {
        "status": "ok" if integrity["ready"] else "degraded",
        "app": APP_NAME,
        "app_version": _settings.APP_VERSION,
        "app_commit": _settings.APP_COMMIT,
        "frontend": integrity,
    }


@app.get("/ready")
def ready() -> Response:
    integrity = _frontend_integrity()
    payload = {
        "status": "ready" if integrity["ready"] else "not_ready",
        "app_version": _settings.APP_VERSION,
        "app_commit": _settings.APP_COMMIT,
        "frontend": integrity,
    }
    return JSONResponse(payload, status_code=200 if integrity["ready"] else 503)


# ---------------------------------------------------------------------------
# SPA static serving
# ---------------------------------------------------------------------------

_COMMIT_META_MARKER = "</head>"
_index_html_lock = threading.Lock()
_index_html_cache: tuple[tuple[int, int], bytes] | None = None


def _index_html_bytes() -> bytes | None:
    global _index_html_cache
    try:
        stat = _INDEX_PATH.stat()
        signature = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        return None
    with _index_html_lock:
        if _index_html_cache and _index_html_cache[0] == signature:
            return _index_html_cache[1]
        raw = _INDEX_PATH.read_text(encoding="utf-8")
        meta = f'<meta name="x-app-commit" content="{_settings.APP_COMMIT}">{_COMMIT_META_MARKER}'
        stamped = raw.replace(_COMMIT_META_MARKER, meta, 1).encode("utf-8")
        _index_html_cache = (signature, stamped)
        return stamped


def _is_spa_document_path(path: str) -> bool:
    if path.startswith(("/api/", "/assets/")) or path in _PUBLIC_PATHS:
        return False
    tail = path.rsplit("/", 1)[-1]
    return "." not in tail


@app.middleware("http")
async def _spa_fallback(request: Request, call_next):
    path = request.url.path
    if request.method in {"GET", "HEAD"} and (path == "/" or _is_spa_document_path(path)):
        body = _index_html_bytes()
        if body is not None:
            return Response(content=body, media_type="text/html")
    return await call_next(request)


if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=False), name="static")
