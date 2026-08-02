"""ニュース同期・AI ジョブ投入・フィード提供のオーケストレーション。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.data_paths import get_data_paths
from app.personal_config import get_personal_config
from app.repositories.core import CoreRepository
from app.repositories.news_store import NewsStore
from app.services.ai_jobs.store import AIJobStore, request_hash
from app.services.ai_jobs import runtime as ai
from app.services.news import classify
from app.services.news.entities import EntityMatcher, build_alias_rows
from app.services.news.fetcher import fetch_feed

NEWS_SERVICE_VERSION = "jp-news-service-v1"


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
        store.record_feed_fetch(
            feed_url, etag=result.etag, last_modified=result.last_modified,
            items_seen=len(result.items), error_code=None,
        )
        if result.status == "not_modified":
            continue

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
            duplicate_of = store.fingerprint_exists_since(
                fingerprint, since_iso=_iso(now - timedelta(hours=48))
            )
            if duplicate_of == news_id:
                duplicate_of = None
            in_watchlist = any(code in watchlist_codes for code in codes)
            has_radar = any(code in radar_codes for code in codes)
            importance, components, reasons = classify.importance_score(
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
                    "importance_components": {"components": components, "reasons": reasons},
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


def enqueue_ai_jobs(
    *, store: NewsStore, jobs: AIJobStore, daily_token_limit: int, max_items: int,
) -> dict[str, Any]:
    """重要度上位の未処理ニュースに翻訳/分析ジョブを積む（予算内で）。"""

    config = get_personal_config()
    since = _iso(datetime.now(timezone.utc) - timedelta(hours=config.news.window_hours))
    candidates = store.pending_ai_candidates(since_iso=since, limit=max_items)
    created = 0
    skipped_budget = 0
    for item in candidates:
        committed = jobs.tokens_committed_today()
        if committed >= daily_token_limit:
            skipped_budget += 1
            continue
        news_id = item["news_id"]
        # 翻訳: 原文が日本語でない場合のみ。日本語原文の再翻訳はしない。
        if item.get("translated_title_ja") is None and item.get("source_language") != "ja":
            payload = ai.build_translation_payload(item)
            hash_value = request_hash(
                "news_translation_ja", payload,
                model=ai.OFFICIAL_OPENAI_MODEL,
                prompt_version=ai.TRANSLATION_PROMPT_VERSION,
                schema_version=ai.TRANSLATION_SCHEMA_VERSION,
                schema_sha256=ai.schema_sha256(ai.TRANSLATION_SCHEMA),
            )
            outcome = jobs.create_job(
                job_type="news_translation_ja", news_id=news_id, payload=payload,
                prompt_version=ai.TRANSLATION_PROMPT_VERSION,
                schema_version=ai.TRANSLATION_SCHEMA_VERSION,
                model=ai.OFFICIAL_OPENAI_MODEL,
                request_hash_value=hash_value,
                token_reservation=ai.TOKEN_RESERVATION_TRANSLATION,
            )
            created += 1 if outcome["created"] else 0
        if item.get("analysis_zh") is None and item.get("securities"):
            allowed = [entry["canonical_code"] for entry in item["securities"]]
            payload = ai.build_analysis_payload(item, allowed_codes=allowed)
            hash_value = request_hash(
                "news_analysis_zh", payload,
                model=ai.OFFICIAL_OPENAI_MODEL,
                prompt_version=ai.ANALYSIS_PROMPT_VERSION,
                schema_version=ai.ANALYSIS_SCHEMA_VERSION,
                schema_sha256=ai.schema_sha256(ai.ANALYSIS_SCHEMA),
            )
            outcome = jobs.create_job(
                job_type="news_analysis_zh", news_id=news_id, payload=payload,
                prompt_version=ai.ANALYSIS_PROMPT_VERSION,
                schema_version=ai.ANALYSIS_SCHEMA_VERSION,
                model=ai.OFFICIAL_OPENAI_MODEL,
                request_hash_value=hash_value,
                token_reservation=ai.TOKEN_RESERVATION_ANALYSIS,
            )
            created += 1 if outcome["created"] else 0
    return {"candidates": len(candidates), "jobs_created": created, "skipped_budget": skipped_budget}


def process_ai_jobs_once(*, store: NewsStore, jobs: AIJobStore, runtime: ai.OpenAIRuntime) -> dict[str, Any]:
    """送信 1 回 + 回収 1 回。並行度 1・予算はジョブ表が守る。"""

    outcome: dict[str, Any] = {"submitted": 0, "settled": 0, "pending": 0}

    # 1) 回収
    submitted = jobs.submitted_job()
    if submitted is not None:
        poll = runtime.poll(str(submitted.get("openai_response_id")))
        if poll["status"] == "pending":
            outcome["pending"] = 1
        elif poll["status"] == "failed":
            jobs.settle(
                submitted["job_id"], status="failed", result=None,
                tokens_used=poll.get("tokens_used"), error_code=poll.get("error_code"),
            )
            outcome["settled"] = 1
        else:
            settled = _apply_result(store, submitted, poll["result"])
            jobs.settle(
                submitted["job_id"],
                status="completed" if settled["accepted"] else "failed",
                result=poll["result"],
                tokens_used=poll.get("tokens_used"),
                error_code=settled.get("error_code"),
            )
            outcome["settled"] = 1

    # 2) 送信（スロットが空いていれば）
    if not jobs.slot_blocked():
        job = jobs.claim_next()
        if job is not None:
            instructions, schema_name, schema = _job_contract(job["job_type"])
            try:
                response_id = runtime.submit(
                    instructions=instructions, payload=job["payload"],
                    schema_name=schema_name, schema=schema,
                )
            except Exception as exc:  # noqa: BLE001 — 送信結果不明は unknown 隔離
                jobs.mark_unknown(job["job_id"], error_code=f"submit:{type(exc).__name__}")
            else:
                jobs.mark_submitted(job["job_id"], response_id)
                outcome["submitted"] = 1
    return outcome


def _job_contract(job_type: str):
    if job_type == "news_translation_ja":
        return ai.translation_instructions(), ai.TRANSLATION_SCHEMA_VERSION, ai.TRANSLATION_SCHEMA
    return ai.analysis_instructions(), ai.ANALYSIS_SCHEMA_VERSION, ai.ANALYSIS_SCHEMA


def _apply_result(store: NewsStore, job: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    news_id = str(job.get("news_id"))
    try:
        if job["job_type"] == "news_translation_ja":
            validated = ai.validate_translation_result(result, news_id=news_id)
            store.attach_translation(
                news_id,
                title_ja=validated["title_ja"],
                summary_ja=validated["summary_ja"],
                model=str(job.get("model")),
                version=str(job.get("prompt_version")),
                fingerprint=str(job.get("request_hash")),
            )
        else:
            allowed = {
                str(entry.get("canonical_code"))
                for entry in (store.get_item(news_id) or {}).get("securities", [])
            }
            validated = ai.validate_analysis_result(result, news_id=news_id, allowed_codes=allowed)
            store.attach_analysis(
                news_id,
                analysis=validated,
                model=str(job.get("model")),
                version=str(job.get("prompt_version")),
                fingerprint=str(job.get("request_hash")),
            )
    except ai.ResultValidationError as exc:
        return {"accepted": False, "error_code": exc.code}
    return {"accepted": True}


# ---------------------------------------------------------------------------
# API ビュー
# ---------------------------------------------------------------------------


def news_feed_view(*, hours: int = 72) -> dict[str, Any]:
    config = get_personal_config()
    paths = get_data_paths()
    store = NewsStore(paths.news_db, read_only=True)
    if not store.exists():
        return {"mode": config.features.news_mode, "items": [], "note_ja": "ニュースデータベースは未作成です。"}
    since = _iso(datetime.now(timezone.utc) - timedelta(hours=max(6, min(24 * 14, hours))))
    items = store.recent_items(since_iso=since, limit=200)
    return {
        "mode": config.features.news_mode,
        "window_hours": hours,
        "items": [_item_view(item) for item in items],
    }


def _item_view(item: dict[str, Any]) -> dict[str, Any]:
    analysis = item.get("analysis_zh")
    return {
        "news_id": item["news_id"],
        "source": item.get("source"),
        "source_url": item.get("source_url"),
        "published_at": item.get("published_at"),
        "source_language": item.get("source_language"),
        "original_title": item.get("original_title"),
        "original_summary": item.get("original_summary"),
        "translated_title_ja": item.get("translated_title_ja"),
        "summary_ja": item.get("translated_summary_ja"),
        "translation_version": item.get("translation_version"),
        "analysis_zh": (
            {
                "headline": analysis.get("headline_zh"),
                "impact": analysis.get("impact_zh"),
                "affected": analysis.get("affected"),
                "insufficient_context": analysis.get("insufficient_context"),
            }
            if analysis
            else None
        ),
        "categories": item.get("categories") or [],
        "securities": [
            {
                "canonical_code": entry.get("canonical_code"),
                "display_code": (
                    entry.get("canonical_code", "")[:4]
                    if str(entry.get("canonical_code", "")).endswith("0")
                    and len(str(entry.get("canonical_code", ""))) == 5
                    else entry.get("canonical_code")
                ),
                "name_ja": None,
            }
            for entry in (item.get("securities") or [])
        ],
        "importance": item.get("importance"),
    }


__all__ = [
    "NEWS_SERVICE_VERSION",
    "enqueue_ai_jobs",
    "news_feed_view",
    "process_ai_jobs_once",
    "rebuild_entity_catalog",
    "sync_feeds_once",
]
