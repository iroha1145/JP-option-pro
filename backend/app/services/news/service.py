"""ニュース同期・AI ジョブ投入・フィード提供のオーケストレーション。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from app.data_paths import get_data_paths
from app.personal_config import get_personal_config
from app.repositories.core import CoreRepository
from app.repositories.news_store import NewsStore
from app.services.ai_jobs.store import AIJobStore, request_hash  # noqa: F401 — request_hash は enqueue 用
from app.services.ai_jobs import runtime as ai
from app.services import display_text
from app.services.news import classify
from app.services.news.entities import EntityMatcher, build_alias_rows
from app.services.news.fetcher import fetch_feed

NEWS_SERVICE_VERSION = "jp-news-service-v1"
SUBMITTED_STALE_SECONDS = 30 * 60


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


def enqueue_ai_jobs(
    *, store: NewsStore, jobs: AIJobStore, daily_token_limit: int, max_items: int,
) -> dict[str, Any]:
    """重要度上位の未処理ニュースに翻訳/分析ジョブを積む（予算内で）。"""

    config = get_personal_config()
    since = _iso(datetime.now(timezone.utc) - timedelta(hours=config.news.window_hours))
    candidates = store.pending_ai_candidates(
        since_iso=since,
        limit=max_items,
        translation_version=ai.TRANSLATION_PROMPT_VERSION,
        analysis_version=ai.ANALYSIS_PROMPT_VERSION,
    )
    created = 0
    skipped_budget = 0
    skipped_queue = 0
    for item in candidates:
        # Enforce the configured queue cap (previously declared but never checked;
        # the queue was only implicitly bounded by the daily token budget).
        if jobs.queued_count() >= config.ai.max_queued:
            skipped_queue += 1
            continue
        committed = jobs.tokens_committed_today()
        if committed >= daily_token_limit:
            skipped_budget += 1
            continue
        news_id = item["news_id"]
        # 翻訳: 原文が日本語でない場合のみ。日本語原文の再翻訳はしない。
        # 版が上がったら（prompt/schema）既訳でも再投入する（サイレントに旧結果を使い続けない）。
        translation_stale = item.get("translation_version") != ai.TRANSLATION_PROMPT_VERSION
        if (
            item.get("source_language") != "ja"
            and (item.get("translated_title_ja") is None or translation_stale)
        ):
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
        analysis_stale = item.get("analysis_version") != ai.ANALYSIS_PROMPT_VERSION
        # Re-check the cap before the second job of the item so one candidate can't
        # push the queue past max_queued (the top-of-loop check only gates entry).
        if (
            item.get("securities")
            and (item.get("analysis_zh") is None or analysis_stale)
            and jobs.queued_count() < config.ai.max_queued
        ):
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
    return {
        "candidates": len(candidates),
        "jobs_created": created,
        "skipped_budget": skipped_budget,
        "skipped_queue": skipped_queue,
    }


def _submission_stale(submitted: Mapping[str, Any]) -> bool:
    """True when a submitted job has been in flight past SUBMITTED_STALE_SECONDS."""

    submitted_at = submitted.get("submitted_at")
    if not submitted_at:
        return False
    try:
        started = datetime.fromisoformat(str(submitted_at).replace("Z", "+00:00"))
    except ValueError:
        return False
    return (datetime.now(timezone.utc) - started).total_seconds() > SUBMITTED_STALE_SECONDS


def process_ai_jobs_once(*, store: NewsStore, jobs: AIJobStore, runtime: ai.OpenAIRuntime) -> dict[str, Any]:
    """送信 1 回 + 回収 1 回。並行度 1・予算はジョブ表が守る。"""

    outcome: dict[str, Any] = {"submitted": 0, "settled": 0, "pending": 0}

    # 1) 回収
    submitted = jobs.submitted_job()
    if submitted is not None:
        # Always poll first so a background response that actually completed is
        # captured even past the staleness window. Only time out when the response
        # is STILL pending beyond the deadline — never discard finished work.
        # If poll itself throws (network / 404), still release a stale slot so an
        # outage cannot pin concurrency-1 forever; a live job stays submitted.
        try:
            poll = runtime.poll(str(submitted.get("openai_response_id")))
        except Exception:  # noqa: BLE001 — 回収失敗はジョブ表が所有する
            if _submission_stale(submitted):
                jobs.settle(
                    submitted["job_id"], status="failed", result=None,
                    tokens_used=None, error_code="model_poll_error",
                )
                outcome["settled"] = 1
            else:
                outcome["pending"] = 1
        else:
            if poll["status"] == "pending":
                if _submission_stale(submitted):
                    jobs.settle(
                        submitted["job_id"], status="failed", result=None,
                        tokens_used=None, error_code="model_poll_timeout",
                    )
                    outcome["settled"] = 1
                else:
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


def _analysis_states(items: list[dict[str, Any]]) -> dict[str, str]:
    """news_id → none|pending|completed|failed（AI ジョブ表と結果から判定）。"""

    config = get_personal_config()
    paths = get_data_paths()
    states: dict[str, str] = {}
    jobs_map: dict[str, dict[str, str]] = {}
    store = AIJobStore(paths.ai_jobs_db, read_only=True)
    if store.exists():
        try:
            jobs_map = store.jobs_for_news([item["news_id"] for item in items])
        except Exception:  # noqa: BLE001 — 状態表示は本文配信を壊さない
            jobs_map = {}
    ai_enabled = config.features.news_mode == "scheduled"
    for item in items:
        if item.get("analysis_zh"):
            states[item["news_id"]] = "completed"
            continue
        job_status = (jobs_map.get(item["news_id"]) or {}).get("news_analysis_zh")
        if job_status in ("queued", "submitted", "unknown"):
            states[item["news_id"]] = "pending"
        elif job_status == "failed":
            states[item["news_id"]] = "failed"
        else:
            states[item["news_id"]] = "disabled" if not ai_enabled else "none"
    return states


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
    states = _analysis_states(items)
    return {
        "mode": config.features.news_mode,
        "window_hours": _clamp_window_hours(hours),
        "items": [
            {**_item_view(item, names), "analysis_state": states.get(item["news_id"], "none")}
            for item in items
        ],
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
                "title": item.get("translated_title_ja") or item.get("original_title"),
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
    """銘柄別インパクト集計（米国版 StocksPanel 対応）。

    決定論部分（件数・重要度・分類）は常に出る。AI サマリは分析済み件数のみ
    （方向予測は v2 で製品から削除）。分析ゼロ件は null — 0 で偽装しない。"""

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
                 "categories": [], "latest": None, "analyzed_count": 0},
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
                    "title": item.get("translated_title_ja") or item.get("original_title"),
                    "published_at": item.get("published_at"),
                }
            analysis = item.get("analysis_zh") or {}
            for affected in analysis.get("affected") or []:
                if str(affected.get("code")) != code:
                    continue
                row["analyzed_count"] += 1
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
        analyzed = row.pop("analyzed_count")
        row["ai"] = {"analyzed": analyzed} if analyzed else None
    return {"window_hours": _clamp_window_hours(hours), "rows": rows}


def news_pipeline_status_view() -> dict[str, Any]:
    """データ源健全性 + AI パイプライン状態（米国版 SourcesPanel/StatusHero 対応）。"""

    from app.config import get_settings

    config = get_personal_config()
    settings = get_settings()
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
    ai_queue: dict[str, int] = {}
    jobs = AIJobStore(paths.ai_jobs_db, read_only=True)
    if jobs.exists():
        try:
            ai_queue = jobs.status_counts()
        except Exception:  # noqa: BLE001
            ai_queue = {}
    ai_ready = config.features.news_mode == "scheduled" and settings.openai_configured()
    return {
        "mode": config.features.news_mode,
        "sync_seconds": config.news.sync_seconds,
        "window_hours": config.news.window_hours,
        "entity_aliases": alias_count,
        "feeds": feeds,
        "ai": {
            "enabled": ai_ready,
            "openai_configured": settings.openai_configured(),
            "translation_target": "ja-JP",
            "analysis_language": "zh-CN",
            "queue": ai_queue,
            "note_ja": (
                None
                if ai_ready
                else "AI 翻訳・影響分析は OPENAI_API_KEY を設定し news_mode を scheduled にすると有効になります。"
            ),
        },
    }


def _display(code: str) -> str:
    return code[:4] if len(code) == 5 and code.endswith("0") else code


def _item_view(item: dict[str, Any], names: dict[str, str | None] | None = None) -> dict[str, Any]:
    analysis = item.get("analysis_zh")
    components = item.get("importance_components") or {}
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
    "enqueue_ai_jobs",
    "news_feed_view",
    "process_ai_jobs_once",
    "rebuild_entity_catalog",
    "sync_feeds_once",
]
