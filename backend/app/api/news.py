"""ニュース API — 米国版カタリストデスクの情報設計に対応。

/feed        情報流（カテゴリ/実体/重要度フィルタ + AI 分析状態つき）
/hotspots    銘柄別ホットスポット
/securities  銘柄別インパクト集計（AI 方向サマリは分析済みのみ）
/status      データ源健全性 + AI パイプライン状態
/econ-calendar 日本の経済指標カレンダー（官公庁公表スケジュール由来）
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.domain.econ_calendar import COVERAGE_NOTE_JA, econ_events_between
from app.domain.timeutil import add_days, iso_date, today_jst
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


@router.get("/econ-calendar")
def econ_calendar(
    start: str | None = Query(default=None, pattern="^\\d{4}-\\d{2}-\\d{2}$"),
    end: str | None = Query(default=None, pattern="^\\d{4}-\\d{2}-\\d{2}$"),
) -> dict:
    today = iso_date(today_jst())
    start_date = start or add_days(today, -7)
    end_date = end or add_days(today, 120)
    return {
        "coverage_note_ja": COVERAGE_NOTE_JA,
        "start_date": start_date,
        "end_date": end_date,
        "events": econ_events_between(start_date, end_date),
    }
