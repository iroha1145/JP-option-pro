"""原文ニュース・銘柄集計・フィード状態 API。"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.personal_config import get_personal_config

router = APIRouter(prefix="/api/news", tags=["news"])

_OFF_NOTE = "ニュース機能は無効です（config/personal.toml [features] news_mode）。"


def _mode_off() -> dict:
    return {"mode": "off", "items": [], "note_ja": _OFF_NOTE}


@router.get("/feed")
def news_feed(
    hours: int = Query(default=72, ge=6, le=336),
    category: str | None = Query(default=None, max_length=20),
    only_securities: bool = False,
    min_importance: float | None = Query(default=None, ge=0, le=100),
) -> dict:
    if get_personal_config().features.news_mode == "off":
        return _mode_off()
    from app.services.news.service import news_feed_view

    return news_feed_view(
        hours=hours, category=category,
        only_securities=only_securities, min_importance=min_importance,
    )


@router.get("/hotspots")
def news_hotspots(hours: int = Query(default=72, ge=6, le=336)) -> dict:
    if get_personal_config().features.news_mode == "off":
        return {"groups": [], "note_ja": _OFF_NOTE}
    from app.services.news.service import news_hotspots_view

    return news_hotspots_view(hours=hours)


@router.get("/securities")
def news_securities(hours: int = Query(default=72, ge=6, le=336)) -> dict:
    if get_personal_config().features.news_mode == "off":
        return {"rows": [], "note_ja": _OFF_NOTE}
    from app.services.news.service import news_securities_view

    return news_securities_view(hours=hours)


@router.get("/status")
def news_status() -> dict:
    from app.services.news.service import news_pipeline_status_view

    return news_pipeline_status_view()
