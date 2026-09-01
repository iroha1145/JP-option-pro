"""ニュース: フィード解析 → 実体照合 → 重複排除 → 保存 → AI 契約検証。"""

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.repositories.core import CoreRepository
from app.repositories.news_store import NewsStore
from app.services.ai_jobs import runtime as ai
from app.services.ai_jobs.store import AIJobStore, request_hash
from app.services.news import classify
from app.services.news.fetcher import parse_feed_xml
from app.services.news import service as news_service
from app.services.news.service import (
    process_ai_jobs_once,
    rebuild_entity_catalog,
    sync_feeds_once,
)


class _FakePoll:
    """Minimal runtime stub exposing only poll() for process_ai_jobs_once."""

    def __init__(self, response: dict) -> None:
        self._response = response

    def poll(self, _response_id: str) -> dict:
        return self._response


def _submit_translation_job(jobs, news_id: str):
    payload = {"news_id": news_id, "title": "t"}
    hash_value = request_hash(
        "news_translation_ja", payload, model=ai.OFFICIAL_OPENAI_MODEL,
        prompt_version=ai.TRANSLATION_PROMPT_VERSION,
        schema_version=ai.TRANSLATION_SCHEMA_VERSION,
        schema_sha256=ai.schema_sha256(ai.TRANSLATION_SCHEMA),
    )
    job = jobs.create_job(
        job_type="news_translation_ja", news_id=news_id, payload=payload,
        prompt_version=ai.TRANSLATION_PROMPT_VERSION, schema_version=ai.TRANSLATION_SCHEMA_VERSION,
        model=ai.OFFICIAL_OPENAI_MODEL, request_hash_value=hash_value, token_reservation=6000,
    )
    jobs.mark_submitted(job["job_id"], "resp_1")
    return job


def test_stale_submitted_completed_poll_recovers_work(tmp_path, monkeypatch):
    """A background response that completed past the staleness window must be applied,
    not discarded as a timeout."""

    store = NewsStore(tmp_path / "news.db")
    store.initialize()
    store.insert_news_items([{
        "news_id": "n1", "source": "test", "original_title": "Toyota raises guidance",
        "source_language": "en", "content_fingerprint": "n1",
    }])
    jobs = AIJobStore(tmp_path / "ai.db")
    jobs.initialize()
    _submit_translation_job(jobs, "n1")
    monkeypatch.setattr(news_service, "SUBMITTED_STALE_SECONDS", -1)  # force "stale"
    runtime = _FakePoll({
        "status": "completed",
        "result": {"news_id": "n1", "title_ja": "トヨタが通期予想を上方修正", "summary_ja": None},
        "tokens_used": 100,
    })
    outcome = process_ai_jobs_once(store=store, jobs=jobs, runtime=runtime)
    assert outcome["settled"] == 1 and outcome["pending"] == 0
    # completed work is recovered rather than thrown away by the timeout path
    assert store.get_item("n1")["translated_title_ja"] == "トヨタが通期予想を上方修正"


def test_stale_submitted_pending_poll_times_out(tmp_path, monkeypatch):
    """A response that is STILL pending past the deadline is timed out (failed)."""

    store = NewsStore(tmp_path / "news.db")
    store.initialize()
    store.insert_news_items([{
        "news_id": "n1", "source": "test", "original_title": "Toyota raises guidance",
        "source_language": "en", "content_fingerprint": "n1",
    }])
    jobs = AIJobStore(tmp_path / "ai.db")
    jobs.initialize()
    _submit_translation_job(jobs, "n1")
    monkeypatch.setattr(news_service, "SUBMITTED_STALE_SECONDS", -1)
    outcome = process_ai_jobs_once(store=store, jobs=jobs, runtime=_FakePoll({"status": "pending"}))
    assert outcome["settled"] == 1  # timed out
    assert store.get_item("n1")["translated_title_ja"] is None
    assert jobs.jobs_for_news(["n1"])["n1"]["news_translation_ja"] == "failed"


class _BoomPoll:
    def poll(self, _response_id: str) -> dict:
        raise RuntimeError("openai_unreachable")


def test_stale_submitted_poll_error_releases_slot(tmp_path, monkeypatch):
    """A stale submitted job must not pin the concurrency-1 slot when poll throws."""

    store = NewsStore(tmp_path / "news.db")
    store.initialize()
    store.insert_news_items([{
        "news_id": "n1", "source": "test", "original_title": "Toyota raises guidance",
        "source_language": "en", "content_fingerprint": "n1",
    }])
    jobs = AIJobStore(tmp_path / "ai.db")
    jobs.initialize()
    _submit_translation_job(jobs, "n1")
    monkeypatch.setattr(news_service, "SUBMITTED_STALE_SECONDS", -1)
    outcome = process_ai_jobs_once(store=store, jobs=jobs, runtime=_BoomPoll())
    assert outcome["settled"] == 1 and outcome["pending"] == 0
    assert jobs.jobs_for_news(["n1"])["n1"]["news_translation_ja"] == "failed"
    assert jobs.slot_blocked() is False


def test_live_submitted_poll_error_stays_pending(tmp_path):
    """A still-fresh submitted job stays submitted when poll throws, so a later
    cycle can recover a completed background response."""

    store = NewsStore(tmp_path / "news.db")
    store.initialize()
    store.insert_news_items([{
        "news_id": "n1", "source": "test", "original_title": "Toyota raises guidance",
        "source_language": "en", "content_fingerprint": "n1",
    }])
    jobs = AIJobStore(tmp_path / "ai.db")
    jobs.initialize()
    _submit_translation_job(jobs, "n1")
    outcome = process_ai_jobs_once(store=store, jobs=jobs, runtime=_BoomPoll())
    assert outcome["settled"] == 0 and outcome["pending"] == 1
    assert jobs.jobs_for_news(["n1"])["n1"]["news_translation_ja"] == "submitted"
    assert jobs.slot_blocked() is True

RSS_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>テスト経済</title>
<item><title>トヨタ自動車、業績予想を上方修正 円安が追い風</title>
<link>https://news.example/a1</link>
<description>トヨタ自動車（7203）は通期営業利益予想を引き上げた。</description>
<pubDate>Fri, 31 Jul 2026 07:00:00 GMT</pubDate></item>
<item><title>Sony raises full-year guidance on strong game sales</title>
<link>https://news.example/a2</link>
<description>Sony Group said quarterly profit rose 20%.</description>
<pubDate>Fri, 31 Jul 2026 06:30:00 GMT</pubDate></item>
<item><title>トヨタ自動車が業績予想を上方修正、円安追い風で</title>
<link>https://other.example/dup</link>
<description>重複報道テスト（7203）。</description>
<pubDate>Fri, 31 Jul 2026 07:20:00 GMT</pubDate></item>
<item><title>NY市場サマリー 米国株は続伸</title>
<link>https://news.example/us</link>
<description>米国株式市場の概況。</description>
<pubDate>Fri, 31 Jul 2026 05:00:00 GMT</pubDate></item>
</channel></rss>"""


def _stores(tmp_path):
    core = CoreRepository(tmp_path / "core.db")
    core.initialize()
    core.replace_security_master(
        [
            {"canonical_code": "72030", "name_ja": "トヨタ自動車", "name_en": "TOYOTA MOTOR CORPORATION", "sector33_code": "3700", "market_code": "0111"},
            {"canonical_code": "67580", "name_ja": "ソニーグループ", "name_en": "Sony Group Corporation", "sector33_code": "3650", "market_code": "0111"},
        ],
        as_of_date="2026-07-31",
    )
    store = NewsStore(tmp_path / "news.db")
    store.initialize()
    rebuild_entity_catalog(core, store)
    return core, store


def test_parse_feed_xml_extracts_items():
    items = parse_feed_xml(RSS_FIXTURE.encode("utf-8"))
    assert len(items) == 4
    assert items[0].title.startswith("トヨタ自動車")
    assert items[0].published_at == "2026-07-31T07:00:00Z"


def test_sync_pipeline_dedup_and_relevance(tmp_path, monkeypatch, data_dir):
    core, store = _stores(tmp_path)
    from app import personal_config

    monkeypatch.setattr(
        personal_config,
        "get_personal_config",
        lambda: personal_config.PersonalConfig.model_validate(
            {"news": {"feed_urls": ["https://feeds.example/rss"]}, "features": {"news_mode": "read"}}
        ),
    )
    import app.services.news.service as service_module

    monkeypatch.setattr(service_module, "get_personal_config", personal_config.get_personal_config)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=RSS_FIXTURE.encode("utf-8"), headers={"ETag": 'W/"v1"'})

    summary = sync_feeds_once(
        core=core, store=store, watchlist_codes={"72030"}, radar_codes=set(),
        transport=httpx.MockTransport(handler),
    )
    assert summary["fetched"] == 4
    assert summary["dropped_irrelevant"] == 1  # 米国株サマリーは日本株フィードに入れない
    assert summary["stored"] == 3
    assert summary["duplicates"] == 1  # 同一イベントの別ソース報道

    items = store.recent_items(since_iso="2026-07-30T00:00:00Z")
    assert len(items) == 2  # 重複は duplicate_of で非表示
    toyota = next(item for item in items if any(s["canonical_code"] == "72030" for s in item["securities"]))
    assert "業績予想修正" in toyota["categories"]
    assert toyota["source_language"] == "ja"
    assert toyota["importance"] is not None and toyota["importance"] > 50


def test_nikkei_average_is_market_relevant_us_summary_is_not():
    nikkei = classify.classify("日経平均は続伸、東京株式市場は堅調", None)
    assert "市場概況" in nikkei
    assert classify.market_relevance(nikkei, []) == "market"
    us = classify.classify("NY市場サマリー 米国株は続伸", "米国株式市場の概況。")
    assert classify.market_relevance(us, []) is None


def test_empty_200_does_not_lock_etag(tmp_path, monkeypatch, data_dir):
    core, store = _stores(tmp_path)
    from app import personal_config

    monkeypatch.setattr(
        personal_config,
        "get_personal_config",
        lambda: personal_config.PersonalConfig.model_validate(
            {"news": {"feed_urls": ["https://feeds.example/rss"]}, "features": {"news_mode": "read"}}
        ),
    )
    import app.services.news.service as service_module

    monkeypatch.setattr(service_module, "get_personal_config", personal_config.get_personal_config)

    empty = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>x</title></channel></rss>"""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, content=empty, headers={"ETag": 'W/"empty"'})
        assert request.headers.get("If-None-Match") != 'W/"empty"'
        return httpx.Response(200, content=RSS_FIXTURE.encode("utf-8"), headers={"ETag": 'W/"v1"'})

    transport = httpx.MockTransport(handler)
    first = sync_feeds_once(
        core=core, store=store, watchlist_codes=set(), radar_codes=set(), transport=transport,
    )
    assert first["feed_errors"]["https://feeds.example/rss"] == "feed_empty_body"
    assert store.feed_state("https://feeds.example/rss")["etag"] is None

    second = sync_feeds_once(
        core=core, store=store, watchlist_codes={"72030"}, radar_codes=set(), transport=transport,
    )
    assert second["stored"] == 3
    assert second["feed_errors"] == {}


def test_undated_items_do_not_fingerprint_collide(tmp_path):
    store = NewsStore(tmp_path / "news.db")
    store.initialize()
    store.insert_news_items(
        [
            {
                "news_id": "a", "source": "t", "original_title": "同一見出し",
                "source_language": "ja", "published_at": None,
                "fetched_at": "2026-08-01T00:00:00Z",
                "content_fingerprint": classify.content_fingerprint("同一見出し", None, ["72030"]),
                "categories": ["市場概況"],
                "securities": [{"canonical_code": "72030"}],
                "importance": 50.0, "market_relevance": "security",
            }
        ]
    )
    fingerprint = classify.content_fingerprint("同一見出し", None, ["72030"])
    # 日付なし指紋は照合しない（service 側）。ストア関数自体は衝突し得る。
    assert store.fingerprint_exists_since(fingerprint, since_iso="2026-07-01T00:00:00Z") == "a"


def test_translation_contract_rejects_wrong_language():
    with pytest.raises(ai.ResultValidationError):
        ai.validate_translation_result(
            {"news_id": "n1", "title_ja": "丰田对业绩进行说明", "summary_ja": "", "already_japanese": False},
            news_id="n1",
        )
    valid = ai.validate_translation_result(
        {"news_id": "n1", "title_ja": "トヨタ、通期見通しを上方修正", "summary_ja": "円安が追い風。", "already_japanese": False},
        news_id="n1",
    )
    assert valid["title_ja"].startswith("トヨタ")


def test_analysis_contract_binds_codes_and_language():
    allowed = {"72030"}
    with pytest.raises(ai.ResultValidationError):
        ai.validate_analysis_result(
            {"news_id": "n1", "headline_zh": "利好丰田", "impact_zh": "对营业利润有正面影响，幅度取决于汇率走势与产量。",
             "affected": [{"code": "99840", "reason_zh": "x"}],
             "insufficient_context": False},
            news_id="n1", allowed_codes=allowed,
        )
    with pytest.raises(ai.ResultValidationError):
        ai.validate_analysis_result(
            {"news_id": "n1", "headline_zh": "トヨタに追い風", "impact_zh": "日本語の分析は契約違反です。",
             "affected": [], "insufficient_context": False},
            news_id="n1", allowed_codes=allowed,
        )
    valid = ai.validate_analysis_result(
        {"news_id": "n1", "headline_zh": "业绩上修利好丰田股价",
         "impact_zh": "公司上调全年营业利润预期，反映汇率与销量改善，对利润与现金流构成正面影响。",
         "affected": [{"code": "72030", "reason_zh": "业绩指引上调"}],
         "insufficient_context": False},
        news_id="n1", allowed_codes=allowed,
    )
    assert valid["affected"][0]["code"] == "72030"
    # v2: 方向・置信度は契約から削除済み — 出力に混ざっても保存されない。
    assert "direction" not in valid["affected"][0]
    assert "confidence" not in valid["affected"][0]


def test_poll_unknown_status_is_failed_not_pending():
    class _Resp:
        status = "mystery"
        output_text = ""
        usage = None

    class _Client:
        def __init__(self):
            self.responses = type("R", (), {"retrieve": staticmethod(lambda _id: _Resp())})()

    runtime = ai.OpenAIRuntime.__new__(ai.OpenAIRuntime)
    runtime._client = _Client()
    runtime._model = ai.OFFICIAL_OPENAI_MODEL
    assert runtime.poll("resp_x")["status"] == "failed"
    assert "unknown_status" in runtime.poll("resp_x")["error_code"]


def test_claim_next_marks_claiming_and_skips_fresh_claim(tmp_path):
    jobs = AIJobStore(tmp_path / "ai.db")
    jobs.initialize()
    payload = {"news_id": "n1", "title": "t"}
    hash_value = request_hash(
        "news_translation_ja", payload, model=ai.OFFICIAL_OPENAI_MODEL,
        prompt_version=ai.TRANSLATION_PROMPT_VERSION,
        schema_version=ai.TRANSLATION_SCHEMA_VERSION,
        schema_sha256=ai.schema_sha256(ai.TRANSLATION_SCHEMA),
    )
    jobs.create_job(
        job_type="news_translation_ja", news_id="n1", payload=payload,
        prompt_version=ai.TRANSLATION_PROMPT_VERSION, schema_version=ai.TRANSLATION_SCHEMA_VERSION,
        model=ai.OFFICIAL_OPENAI_MODEL, request_hash_value=hash_value, token_reservation=6000,
    )
    first = jobs.claim_next()
    assert first is not None
    assert jobs.slot_blocked()  # claim 中もスロットを塞ぐ
    second = jobs.claim_next()
    assert second is None  # claiming 中は二重に渡さない


def test_ai_job_dedup_and_budget(tmp_path):
    jobs = AIJobStore(tmp_path / "ai.db")
    jobs.initialize()
    payload = {"news_id": "n1", "title": "t"}
    hash_value = request_hash(
        "news_translation_ja", payload, model=ai.OFFICIAL_OPENAI_MODEL,
        prompt_version=ai.TRANSLATION_PROMPT_VERSION,
        schema_version=ai.TRANSLATION_SCHEMA_VERSION,
        schema_sha256=ai.schema_sha256(ai.TRANSLATION_SCHEMA),
    )
    first = jobs.create_job(
        job_type="news_translation_ja", news_id="n1", payload=payload,
        prompt_version=ai.TRANSLATION_PROMPT_VERSION, schema_version=ai.TRANSLATION_SCHEMA_VERSION,
        model=ai.OFFICIAL_OPENAI_MODEL, request_hash_value=hash_value, token_reservation=6000,
    )
    second = jobs.create_job(
        job_type="news_translation_ja", news_id="n1", payload=payload,
        prompt_version=ai.TRANSLATION_PROMPT_VERSION, schema_version=ai.TRANSLATION_SCHEMA_VERSION,
        model=ai.OFFICIAL_OPENAI_MODEL, request_hash_value=hash_value, token_reservation=6000,
    )
    assert first["created"] and not second["created"]
    assert first["job_id"] == second["job_id"]  # 同一入力は同一ジョブ
    assert jobs.tokens_committed_today() == 6000  # 予約分が予算を占有

    jobs.mark_submitted(first["job_id"], "resp_1")
    assert jobs.slot_blocked()  # 並行度 1
    jobs.settle(first["job_id"], status="completed", result={"ok": True}, tokens_used=1234, error_code=None)
    assert not jobs.slot_blocked()
    assert jobs.tokens_committed_today() == 1234  # 予約は実測 usage に置き換わる


def test_prompt_version_change_moves_request_hash():
    payload = {"news_id": "n1"}
    base = request_hash("news_translation_ja", payload, model="m", prompt_version="v1", schema_version="s1", schema_sha256="x")
    bumped = request_hash("news_translation_ja", payload, model="m", prompt_version="v2", schema_version="s1", schema_sha256="x")
    assert base != bumped  # プロンプト更新は古い結果を静かに再利用しない


def test_pending_ai_candidates_japanese_analyzed_does_not_starve(tmp_path):
    """日本語の既分析行（翻訳版なし）が limit を埋め、未分析を押し出してはいけない。"""

    store = NewsStore(tmp_path / "news.db")
    store.initialize()
    now = datetime.now(timezone.utc)
    recent = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    since = (now - timedelta(hours=72)).strftime("%Y-%m-%dT%H:%M:%SZ")
    analyzed = [
        {
            "news_id": f"ja-{index}",
            "source": "test",
            "original_title": f"トヨタ既分析{index}",
            "source_language": "ja",
            "published_at": recent,
            "fetched_at": recent,
            "content_fingerprint": f"ja-{index}",
            "categories": ["決算"],
            "securities": [{"canonical_code": "72030", "alias": "トヨタ", "alias_type": "name_ja"}],
            "importance": 90.0,
            "market_relevance": "security",
        }
        for index in range(20)
    ]
    pending = {
        "news_id": "needs-analysis",
        "source": "test",
        "original_title": "ソニー、未分析",
        "source_language": "ja",
        "published_at": recent,
        "fetched_at": recent,
        "content_fingerprint": "needs-analysis",
        "categories": ["決算"],
        "securities": [{"canonical_code": "67580", "alias": "ソニー", "alias_type": "name_ja"}],
        "importance": 10.0,
        "market_relevance": "security",
    }
    store.insert_news_items([*analyzed, pending])
    for index in range(20):
        store.attach_analysis(
            f"ja-{index}",
            analysis={"headline_zh": "已分析", "impact_zh": "无增量"},
            model="m",
            version="analysis-v2",
            fingerprint=f"a{index}",
        )

    found = store.pending_ai_candidates(
        since_iso=since,
        limit=10,
        translation_version="tr-v1",
        analysis_version="analysis-v2",
    )
    ids = [row["news_id"] for row in found]
    assert ids == ["needs-analysis"]

    store.attach_analysis(
        "needs-analysis",
        analysis={"headline_zh": "旧版", "impact_zh": "旧版"},
        model="m",
        version="analysis-v1",
        fingerprint="stale",
    )
    stale = store.pending_ai_candidates(
        since_iso=since,
        limit=10,
        translation_version="tr-v1",
        analysis_version="analysis-v2",
    )
    assert [row["news_id"] for row in stale] == ["needs-analysis"]
