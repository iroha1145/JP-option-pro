"""Worker アクション API: 手動更新はワーカーの同じタスクを起動する。"""

from __future__ import annotations

import secrets
import sqlite3

from fastapi import APIRouter, Body, HTTPException

from app.api.deps import worker_state_read, worker_state_write
from app.domain.symbols import normalize_input_code
from app.repositories.base import SchemaVersionError
from app.worker.tasks import DEFAULT_TASK_NAMES, MANUAL_ACTION_TYPES

router = APIRouter(prefix="/api/worker", tags=["worker"])


def _worker_unavailable() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={"code": "worker_unavailable"},
        headers={"Retry-After": "1", "Cache-Control": "no-store"},
    )


def _retryable_queue_error(error: Exception, schema_name: str) -> bool:
    # verify_schema wraps every OperationalError, including permanent I/O or
    # malformed-schema errors. Only a missing initial schema and native lock
    # errors are a temporary unavailable worker, not arbitrary schema drift.
    cause = error.__cause__ if isinstance(error, SchemaVersionError) else error
    if not isinstance(cause, sqlite3.OperationalError):
        return False
    code = getattr(cause, "sqlite_errorcode", None)
    if not isinstance(code, int):
        return False
    if (code & 0xFF) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
        return True
    return (
        isinstance(error, SchemaVersionError)
        and code == sqlite3.SQLITE_ERROR
        and str(cause) == f"no such table: {schema_name}_schema"
    )


@router.get("/status")
def worker_status() -> dict:
    repository = worker_state_read()
    if not repository.exists():
        return {"available": False, "healthy": False, "tasks": {}}
    health = repository.health(DEFAULT_TASK_NAMES)
    health["available"] = True
    health["recent_actions"] = repository.recent_actions(limit=10)
    return health


@router.post("/actions/{action_type}", status_code=202)
def request_action(
    action_type: str,
    code: str | None = Body(default=None, embed=True, max_length=8),
) -> dict:
    if action_type not in MANUAL_ACTION_TYPES:
        raise HTTPException(status_code=404, detail={"code": "unknown_action"})
    payload: dict = {}
    if action_type in ("intraday_fetch", "tick_fetch"):
        canonical = normalize_input_code(code or "")
        if canonical is None:
            raise HTTPException(status_code=422, detail={"code": "invalid_code_format"})
        payload["code"] = canonical
        if action_type == "tick_fetch":
            # ランタイムは action_type を payload から剥がすため、dataset は自前で運ぶ
            payload["dataset"] = "tick"
    repository = worker_state_write()
    if not repository.exists():
        # The worker owns schema creation/migration. File existence also does
        # not prove its first schema transaction has committed yet.
        raise _worker_unavailable()
    try:
        outcome = repository.request_action(
            action_type, idempotency_key=secrets.token_hex(8), payload=payload
        )
    except (SchemaVersionError, sqlite3.OperationalError) as exc:
        if not _retryable_queue_error(exc, repository.SCHEMA_NAME):
            raise
        # request_action returns only after its transaction commits; failures
        # inside that transaction roll back. Never retry here with a new key,
        # or relabel unknown/possibly post-commit errors as a safe retry.
        raise _worker_unavailable() from exc
    return {"action_type": action_type, **outcome}


@router.get("/actions/{action_id}")
def get_action(action_id: int) -> dict:
    repository = worker_state_read()
    if not repository.exists():
        raise HTTPException(status_code=404, detail={"code": "action_not_found"})
    item = repository.get_action(action_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "action_not_found"})
    return item
