"""設定 API: キーが構成済みかどうかの真偽のみ返す（値は決して返さない）。"""

from __future__ import annotations

from fastapi import APIRouter

from app.config import get_settings
from app.personal_config import get_personal_config

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
def get_settings_view() -> dict:
    settings = get_settings()
    personal = get_personal_config()
    return {
        "jquants_configured": settings.jquants_configured(),
        "openai_configured": settings.openai_configured(),
        "access_mode": personal.access.mode,
        "radar_enabled": personal.features.radar_enabled,
        "news_mode": personal.features.news_mode,
        "app_version": settings.APP_VERSION,
        "app_commit": settings.APP_COMMIT,
    }
