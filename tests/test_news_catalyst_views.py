"""カタリストデスク・ビュー: 経済カレンダー・境界照合・銘柄別集計。"""

from datetime import datetime, timedelta, timezone

from app.domain.econ_calendar import ECON_EVENTS, econ_events_between
from app.repositories.news_store import NewsStore
from app.services.news.classify import classify, market_relevance
from app.services.news.entities import EntityMatcher, build_alias_rows


def test_market_overview_keywords_do_not_swallow_us_summaries():
    assert market_relevance(classify("日経平均は続伸", None), []) == "market"
    assert market_relevance(classify("NY市場サマリー 米国株は続伸", "米国株式市場の概況。"), []) is None


def test_econ_calendar_range_and_ordering():
    events = econ_events_between("2026-09-01", "2026-10-31")
    assert events, "9-10月には日銀会合・短観・CPIがあるはず"
    dates = [event["date"] for event in events]
    assert dates == sorted(dates)
    assert all("2026-09-01" <= date <= "2026-10-31" for date in dates)
    mpm = [event for event in events if "金融政策決定会合" in event["name_ja"]]
    assert any(event["date"] == "2026-09-18" for event in mpm)
    # 展望レポート回（10/30）が含まれる
    assert any("展望レポート" in event["name_ja"] for event in events)


def test_econ_calendar_derived_dates_are_flagged():
    for event in ECON_EVENTS:
        assert event["importance"] in ("high", "medium", "low")
        assert event["source_url"].startswith("https://")
        if not event["confirmed"]:
            # 導出値には必ず根拠メモがある（UI の「目安」バッジの説明責任）
            assert event.get("note"), event["name_ja"]


def _matcher():
    rows = build_alias_rows(
        [
            {"canonical_code": "81180", "name_ja": "キング", "name_en": "KING CO."},
            {"canonical_code": "67850", "name_ja": "鈴木", "name_en": "SUZUKI CO."},
            {"canonical_code": "67580", "name_ja": "ソニーグループ", "name_en": "Sony Group"},
            {"canonical_code": "72030", "name_ja": "トヨタ自動車", "name_en": "TOYOTA MOTOR"},
        ]
    )
    return EntityMatcher([
        {"alias": alias, "canonical_code": code, "alias_type": alias_type}
        for alias, code, alias_type in rows
    ])


def test_katakana_alias_requires_katakana_boundary():
    matcher = _matcher()
    # 「ステーキング」の中の「キング」は誤爆 → 拒否
    assert not any(m.canonical_code == "81180" for m in matcher.match("ETFのステーキングプロバイダーを選定"))
    # 独立した「キング」は正当
    assert any(m.canonical_code == "81180" for m in matcher.match("キングが新製品を発表"))


def test_short_kanji_alias_requires_boundary():
    matcher = _matcher()
    # 人名「鈴木潤一」の中の「鈴木」→ 拒否（後続が漢字）
    assert not any(m.canonical_code == "67850" for m in matcher.match("WEDGE編集部・鈴木潤一 著"))
    # 「鈴木は増配を発表」→ 正当（後続がひらがな）
    assert any(m.canonical_code == "67850" for m in matcher.match("鈴木は増配を発表"))


def test_long_aliases_unaffected_by_boundary_rule():
    matcher = _matcher()
    assert any(m.canonical_code == "72030" for m in matcher.match("トヨタ自動車株式会社の決算"))
    assert any(m.canonical_code == "67580" for m in matcher.match("ソニーグループが上方修正"))


def test_securities_view_aggregates_and_ai_null_without_analysis(tmp_path, monkeypatch, data_dir):
    from datetime import datetime, timedelta, timezone

    # ビューは wall-clock の N 時間窓。固定日を書くと日付が転がった瞬間に 0 件になる。
    now = datetime.now(timezone.utc)
    published_1 = (now - timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%SZ")
    published_2 = (now - timedelta(hours=11)).strftime("%Y-%m-%dT%H:%M:%SZ")

    store = NewsStore(tmp_path / "news.db")
    store.initialize()
    store.insert_news_items(
        [
            {
                "news_id": "n1", "source": "test", "original_title": "トヨタ、上方修正",
                "source_language": "ja", "published_at": published_1,
                "fetched_at": published_1, "content_fingerprint": "f1",
                "categories": ["業績予想修正"],
                "securities": [{"canonical_code": "72030", "alias": "トヨタ自動車", "alias_type": "name_ja"}],
                "importance": 88.0, "market_relevance": "security",
            },
            {
                "news_id": "n2", "source": "test", "original_title": "トヨタ、新工場",
                "source_language": "ja", "published_at": published_2,
                "fetched_at": published_2, "content_fingerprint": "f2",
                "categories": ["製品・技術"],
                "securities": [{"canonical_code": "72030", "alias": "トヨタ自動車", "alias_type": "name_ja"}],
                "importance": 60.0, "market_relevance": "security",
            },
        ]
    )
    import app.services.news.service as service_module

    monkeypatch.setattr(service_module, "get_data_paths", lambda: type(
        "P", (), {"news_db": tmp_path / "news.db", "ai_jobs_db": tmp_path / "ai.db",
                  "core_db": tmp_path / "core.db"},
    )())
    view = service_module.news_securities_view(hours=72)
    assert len(view["rows"]) == 1
    row = view["rows"][0]
    assert row["display_code"] == "7203"
    assert row["news_count"] == 2
    assert row["max_importance"] == 88.0
    assert row["ai"] is None  # 分析ゼロ件は null — 0 件を偽装しない

    hotspots = service_module.news_hotspots_view(hours=72)
    assert hotspots["groups"][0]["canonical_code"] == "72030"
    assert hotspots["groups"][0]["item_count"] == 2
