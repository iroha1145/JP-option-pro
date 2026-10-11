"""ニュース原文の同期・分類・フィード提供。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.data_paths import get_data_paths
from app.personal_config import get_personal_config
from app.repositories.core import CoreRepository
from app.repositories.news_store import NewsStore
from app.services import display_text
from app.services.news import classify
from app.services.news.entities import EntityMatcher, build_alias_rows
from app.services.news.fetcher import fetch_feed

NEWS_SERVICE_VERSION = "jp-news-service-v2"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def rebuild_entity_catalog(core: CoreRepository, store: NewsStore) -> int:
    securities = core.list_securities(active_only=True)
    rows = build_alias_rows(securities)
    return store.replace_entity_aliases(rows)


def sync_feeds_once(
    *,
    core: CoreRepository,
    store: NewsStore,
    watchlist_codes: set[str],
    radar_codes: set[str],
    transport=None,
) -> dict[str, Any]:
    """フィード取得 → 実体照合 → 分類 → 重複排除 → 保存。"""

    config = get_personal_config().news
    matcher = EntityMatcher(store.all_entity_aliases())
    now = datetime.now(timezone.utc)
    fetched = 0
    stored = 0
    duplicates = 0
    dropped_irrelevant = 0
    feed_errors: dict[str, str] = {}

    # 近接重複: 48h 以内の既存タイトル + 今回バッチ内タイトルと Jaccard 比較。
    import json as _json

    dedup_window_start = _iso(now - timedelta(hours=48))
    seen_titles: list[tuple[str, frozenset[str], set[str]]] = []
    for known_id, known_title, securities_json in store.recent_titles_since(dedup_window_start):
        try:
            known_codes = {
                str(entry.get("canonical_code"))
                for entry in _json.loads(securities_json)
            }
        except ValueError:
            known_codes = set()
        seen_titles.append((known_id, classify.title_bigrams(known_title), known_codes))

    for feed_url in config.feed_urls:
        state = store.feed_state(feed_url) or {}
        result = fetch_feed(
            feed_url,
            etag=state.get("etag"),
            last_modified=state.get("last_modified"),
            transport=transport,
        )
        if result.status == "error":
            feed_errors[feed_url] = result.error_code or "unknown"
            store.record_feed_fetch(
                feed_url, etag=state.get("etag"), last_modified=state.get("last_modified"),
                items_seen=0, error_code=result.error_code,
            )
            continue
        if result.status == "not_modified":
            store.record_feed_fetch(
                feed_url, etag=result.etag, last_modified=result.last_modified,
                items_seen=0, error_code=None,
            )
            continue
        if not result.items:
            # 空の 200 + 新 ETag を保存すると次回 304 で永久に空になる。
            feed_errors[feed_url] = "feed_empty_body"
            store.record_feed_fetch(
                feed_url, etag=state.get("etag"), last_modified=state.get("last_modified"),
                items_seen=0, error_code="feed_empty_body",
            )
            continue
        store.record_feed_fetch(
            feed_url, etag=result.etag, last_modified=result.last_modified,
            items_seen=len(result.items), error_code=None,
        )

        batch: list[dict[str, Any]] = []
        for item in result.items:
            fetched += 1
            news_id = classify.news_identity(feed_url, item.link, item.title)
            text = f"{item.title}\n{item.summary or ''}"
            matches = matcher.match(text)
            categories = classify.classify(item.title, item.summary)
            relevance = classify.market_relevance(categories, [m.__dict__ for m in matches])
            if relevance is None:
                dropped_irrelevant += 1
                continue  # 日本株と接点のない記事はフィードに入れない
            codes = sorted({m.canonical_code for m in matches})
            fingerprint = classify.content_fingerprint(item.title, item.published_at, codes)
            # 日付のない指紋は日をまたいで衝突するので、指紋照合は日付があるときだけ。
            duplicate_of = None
            if item.published_at:
                duplicate_of = store.fingerprint_exists_since(fingerprint, since_iso=dedup_window_start)
            if duplicate_of == news_id:
                duplicate_of = None
            bigrams = classify.title_bigrams(item.title)
            if duplicate_of is None:
                code_set = set(codes)
                for known_id, known_bigrams, known_codes in seen_titles:
                    if known_id == news_id:
                        continue
                    # Only a genuine shared ticker relaxes the similarity threshold.
                    # Treating "both have no codes" as shared over-deduped distinct
                    # macro headlines (BOJ/CPI/FX) that merely share common bigrams.
                    shared_entity = bool(code_set & known_codes)
                    threshold = 0.5 if shared_entity else 0.72
                    if classify.titles_similar(bigrams, known_bigrams, threshold=threshold):
                        duplicate_of = known_id
                        break
            if duplicate_of is None:
                seen_titles.append((news_id, bigrams, set(codes)))
            in_watchlist = any(code in watchlist_codes for code in codes)
            has_radar = any(code in radar_codes for code in codes)
            importance, components, reason_items = classify.importance_score(
                categories=categories,
                securities_count=len(codes),
                published_at=item.published_at,
                in_watchlist=in_watchlist,
                has_radar_event=has_radar,
                now=now,
            )
            if duplicate_of:
                duplicates += 1
            batch.append(
                {
                    "news_id": news_id,
                    "source": _source_label(feed_url),
                    "source_url": item.link,
                    "original_title": item.title,
                    "original_summary": item.summary,
                    "source_language": classify.detect_language(item.title, item.summary),
                    "published_at": item.published_at,
                    "fetched_at": _iso(now),
                    "content_fingerprint": fingerprint,
                    "duplicate_of": duplicate_of,
                    "categories": categories,
                    "securities": [
                        {"canonical_code": m.canonical_code, "alias": m.alias, "alias_type": m.alias_type}
                        for m in matches
                    ],
                    "market_relevance": relevance,
                    "importance": importance,
                    # `reasons` は中文で置換済み、`reason_items` は翻訳用の
                    # テンプレート形。既存行には後者が無いので、読み出し側は
                    # 前者へフォールバックする。
                    "importance_components": {
                        "components": components,
                        "reasons": display_text.rendered(reason_items),
                        "reason_items": reason_items,
                    },
                }
            )
        stored += store.insert_news_items(batch)

    return {
        "version": NEWS_SERVICE_VERSION,
        "feeds": len(config.feed_urls),
        "fetched": fetched,
        "stored": stored,
        "duplicates": duplicates,
        "dropped_irrelevant": dropped_irrelevant,
        "feed_errors": feed_errors,
    }


def _source_label(feed_url: str) -> str:
    try:
        host = feed_url.split("//", 1)[1].split("/", 1)[0]
        return host.removeprefix("www.")
    except IndexError:
        return feed_url[:40]


# ---------------------------------------------------------------------------
# API ビュー（米国版カタリストデスクの情報設計に対応）
# ---------------------------------------------------------------------------


def _security_names(codes: set[str]) -> dict[str, str | None]:
    if not codes:
        return {}
    core = CoreRepository(get_data_paths().core_db, read_only=True)
    if not core.exists():
        return {}
    names: dict[str, str | None] = {}
    for code in codes:
        security = core.get_security(code)
        names[code] = security.get("name_ja") if security else None
    return names


def _clamp_window_hours(hours: int) -> int:
    """Clamp the requested window to [6h, 14d] — the range actually queried."""

    return max(6, min(24 * 14, hours))


def _window_items(store: NewsStore, hours: int, *, limit: int = 300) -> list[dict[str, Any]]:
    since = _iso(datetime.now(timezone.utc) - timedelta(hours=_clamp_window_hours(hours)))
    return store.recent_items(since_iso=since, limit=limit)


def news_feed_view(
    *,
    hours: int = 72,
    category: str | None = None,
    only_securities: bool = False,
    min_importance: float | None = None,
) -> dict[str, Any]:
    config = get_personal_config()
    paths = get_data_paths()
    store = NewsStore(paths.news_db, read_only=True)
    if not store.exists():
        return {"mode": config.features.news_mode, "items": [], "note_ja": "ニュースデータベースは未作成です。"}
    items = _window_items(store, hours)
    if category:
        items = [item for item in items if category in (item.get("categories") or [])]
    if only_securities:
        items = [item for item in items if item.get("securities")]
    if min_importance is not None:
        items = [
            item for item in items
            if item.get("importance") is not None and item["importance"] >= min_importance
        ]
    codes = {
        str(entry.get("canonical_code"))
        for item in items
        for entry in (item.get("securities") or [])
    }
    names = _security_names(codes)
    return {
        "mode": config.features.news_mode,
        "window_hours": _clamp_window_hours(hours),
        "items": [_item_view(item, names) for item in items],
    }


def news_hotspots_view(*, hours: int = 72, limit: int = 8) -> dict[str, Any]:
    """銘柄別ホットスポット: 実体つきニュースを主銘柄でグルーピングし、
    (最大重要度, 件数) でランク付け。米国版 HotspotsStrip の簡易版。"""

    paths = get_data_paths()
    store = NewsStore(paths.news_db, read_only=True)
    if not store.exists():
        return {"groups": []}
    items = _window_items(store, hours)
    groups: dict[str, dict[str, Any]] = {}
    for item in items:
        securities = item.get("securities") or []
        if not securities:
            continue
        primary = str(securities[0].get("canonical_code"))
        group = groups.setdefault(
            primary,
            {"canonical_code": primary, "item_count": 0, "max_importance": None,
             "categories": [], "latest": None},
        )
        group["item_count"] += 1
        importance = item.get("importance")
        if importance is not None and (group["max_importance"] is None or importance > group["max_importance"]):
            group["max_importance"] = importance
        for cat in item.get("categories") or []:
            if cat not in group["categories"]:
                group["categories"].append(cat)
        if group["latest"] is None:
            group["latest"] = {
                "news_id": item["news_id"],
                "title": item.get("original_title"),
                "published_at": item.get("published_at"),
            }
    ranked = sorted(
        groups.values(),
        key=lambda g: (-(g["max_importance"] or 0.0), -g["item_count"], g["canonical_code"]),
    )[: max(1, int(limit))]
    names = _security_names({g["canonical_code"] for g in ranked})
    for group in ranked:
        code = group["canonical_code"]
        group["display_code"] = _display(code)
        group["name_ja"] = names.get(code)
        group["categories"] = group["categories"][:3]
    return {"window_hours": _clamp_window_hours(hours), "groups": ranked}


def news_securities_view(*, hours: int = 72, limit: int = 50) -> dict[str, Any]:
    """原文ニュースの銘柄別件数・重要度・分類。"""

    paths = get_data_paths()
    store = NewsStore(paths.news_db, read_only=True)
    if not store.exists():
        return {"rows": []}
    items = _window_items(store, hours)
    per_code: dict[str, dict[str, Any]] = {}
    for item in items:
        for entry in item.get("securities") or []:
            code = str(entry.get("canonical_code"))
            row = per_code.setdefault(
                code,
                {"canonical_code": code, "news_count": 0, "max_importance": None,
                 "categories": [], "latest": None},
            )
            row["news_count"] += 1
            importance = item.get("importance")
            if importance is not None and (row["max_importance"] is None or importance > row["max_importance"]):
                row["max_importance"] = importance
            for cat in item.get("categories") or []:
                if cat not in row["categories"]:
                    row["categories"].append(cat)
            if row["latest"] is None:
                row["latest"] = {
                    "title": item.get("original_title"),
                    "published_at": item.get("published_at"),
                }
    rows = sorted(
        per_code.values(),
        key=lambda r: (-(r["max_importance"] or 0.0), -r["news_count"], r["canonical_code"]),
    )[: max(1, int(limit))]
    names = _security_names({row["canonical_code"] for row in rows})
    for row in rows:
        code = row["canonical_code"]
        row["display_code"] = _display(code)
        row["name_ja"] = names.get(code)
        row["categories"] = row["categories"][:3]
    return {"window_hours": _clamp_window_hours(hours), "rows": rows}


def news_pipeline_status_view() -> dict[str, Any]:
    """原文フィードの同期状態とデータ源健全性。"""

    config = get_personal_config()
    paths = get_data_paths()
    store = NewsStore(paths.news_db, read_only=True)
    feeds: list[dict[str, Any]] = []
    alias_count = 0
    if store.exists():
        feeds = store.feed_states()
        alias_count = store.alias_count()
    configured = list(config.news.feed_urls)
    known = {feed["feed_url"] for feed in feeds}
    for url in configured:
        if url not in known:
            feeds.append({"feed_url": url, "last_fetched_at": None, "last_error_code": None, "items_seen": 0})
    return {
        "mode": config.features.news_mode,
        "sync_seconds": config.news.sync_seconds,
        "window_hours": config.news.window_hours,
        "entity_aliases": alias_count,
        "feeds": feeds,
    }


def _display(code: str) -> str:
    return code[:4] if len(code) == 5 and code.endswith("0") else code


def _item_view(item: dict[str, Any], names: dict[str, str | None] | None = None) -> dict[str, Any]:
    components = item.get("importance_components") or {}
    return {
        "news_id": item["news_id"],
        "source": item.get("source"),
        "source_url": item.get("source_url"),
        "published_at": item.get("published_at"),
        "source_language": item.get("source_language"),
        "original_title": item.get("original_title"),
        "original_summary": item.get("original_summary"),
        "categories": item.get("categories") or [],
        "securities": [
            {
                "canonical_code": entry.get("canonical_code"),
                "display_code": _display(str(entry.get("canonical_code", ""))),
                "name_ja": (names or {}).get(str(entry.get("canonical_code"))),
            }
            for entry in (item.get("securities") or [])
        ],
        "importance": item.get("importance"),
        "importance_reasons": (components.get("reasons") or [])[:4],
        "importance_reason_items": (components.get("reason_items") or [])[:4],
        "market_relevance": item.get("market_relevance"),
    }


__all__ = [
    "NEWS_SERVICE_VERSION",
    "news_feed_view",
    "rebuild_entity_catalog",
    "sync_feeds_once",
]
