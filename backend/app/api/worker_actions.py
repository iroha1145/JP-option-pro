"""Worker アクション API: 手動更新はワーカーの同じタスクを起動する。"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Body, HTTPException

from app.api.deps import worker_state_read, worker_state_write
from app.domain.symbols import normalize_input_code
from app.worker.tasks import DEFAULT_TASK_NAMES, MANUAL_ACTION_TYPES

router = APIRouter(prefix="/api/worker", tags=["worker"])


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
    if action_type == "intraday_fetch":
        canonical = normalize_input_code(code or "")
        if canonical is None:
            raise HTTPException(status_code=422, detail={"code": "invalid_code_format"})
        payload["code"] = canonical
    repository = worker_state_write()
    if not repository.exists():
        repository.initialize()
    outcome = repository.request_action(
        action_type, idempotency_key=secrets.token_hex(8), payload=payload
    )
    return {"action_type": action_type, **outcome}
