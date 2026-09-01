"""データ状態 API。"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import core_repository, worker_state_read
from app.config import get_settings
from app.services.data_status import data_status, intraday_addon_status
from app.worker.tasks import DEFAULT_TASK_NAMES

router = APIRouter(prefix="/api/data-status", tags=["data-status"])


@router.get("")
def get_data_status() -> dict:
    settings = get_settings()
    repository = core_repository()
    payload: dict = {
        "core_database_ready": repository.exists(),
    }
    if repository.exists():
        payload.update(data_status(repository, jquants_configured=settings.jquants_configured()))
    else:
        payload.update(
            data_status_empty(jquants_configured=settings.jquants_configured())
        )
    worker_repo = worker_state_read()
    if worker_repo.exists():
        try:
            payload["worker"] = worker_repo.health(DEFAULT_TASK_NAMES)
        except Exception:  # noqa: BLE001 — 状態ページは常に応答する
            payload["worker"] = {"healthy": False, "error": "worker_state_unreadable"}
    else:
        payload["worker"] = None
    return payload


def data_status_empty(*, jquants_configured: bool) -> dict:
    from app.providers.jquants.capabilities import CAPABILITIES, SUBSCRIPTION_PLAN
    from app.services.data_status import DATA_STATUS_VERSION

    return {
        "version": DATA_STATUS_VERSION,
        "provider": "J-Quants API V2",
        "plan": SUBSCRIPTION_PLAN,
        "api_key_configured": jquants_configured,
        "market_timezone": "Asia/Tokyo",
        "datasets": [
            {
                "key": capability.key,
                "endpoint": capability.endpoint,
                "status": capability.status,
                "cadence": capability.cadence,
                "history_years": capability.history_years,
                "note_ja": capability.note_ja or None,
                "freshness": "never_synced" if capability.status == "enabled" else None,
            }
            for capability in CAPABILITIES
        ],
        "intraday": intraday_addon_status(),
    }
