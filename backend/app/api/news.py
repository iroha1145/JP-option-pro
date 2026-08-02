"""ニュース API（フェーズ5で本実装; 現在はモード宣言のみ返す）。"""

from __future__ import annotations

from fastapi import APIRouter

from app.personal_config import get_personal_config

router = APIRouter(prefix="/api/news", tags=["news"])


@router.get("/feed")
def news_feed(hours: int = 72) -> dict:
    config = get_personal_config()
    if config.features.news_mode == "off":
        return {
            "mode": "off",
            "items": [],
            "note_ja": "ニュース機能は無効です（config/personal.toml [features] news_mode）。",
        }
    from app.services.news.service import news_feed_view

    return news_feed_view(hours=hours)
