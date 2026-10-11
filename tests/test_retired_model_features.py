"""Retiring paid model features must leave source news and old data intact."""

from datetime import datetime, timezone
from types import SimpleNamespace
import sqlite3

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.data_paths import get_data_paths
from app.personal_config import PersonalConfig
from app.repositories.core import CoreRepository
from app.repositories.news_store import NewsStore
from app.runtime_environment import load_runtime_environment
from app.services.news import service
from app.worker.tasks import DEFAULT_TASK_NAMES, MANUAL_ACTION_TYPES, build_default_tasks


def test_existing_owner_config_is_read_only_news(caplog):
    config = PersonalConfig.model_validate({
        "features": {"news_mode": "scheduled"},
        "ai": {"model": "retired-model", "daily_token_limit": 100000},
        "news": {"max_ai_items_per_run": 12},
    })
    assert config.features.news_mode == "read"
    assert "ai" not in config.model_dump()
    assert "max_ai_items_per_run" not in config.news.model_dump()
    compatible = PersonalConfig.model_validate({"news": {"sync_second": 1234}})
    assert compatible.news.sync_seconds == 900
    assert "sync_second" not in compatible.news.model_dump()
    assert "Ignoring unknown NewsConfig field: sync_second" in caplog.text
    with pytest.raises(ValidationError):
        PersonalConfig.model_validate({"news": {"sync_seconds": 1}})


def test_retired_key_is_never_loaded_from_runtime_files(tmp_path):
    paths = []
    for name in (".env", "machine.env", "secrets.env"):
        path = tmp_path / name
        path.write_text("OPENAI_API_KEY=unused-retired-value\n")
        paths.append(path)
    target = {}
    load_runtime_environment(paths, environ=target)
    assert "OPENAI_API_KEY" not in target
    assert "OPENAI_API_KEY" not in Settings.model_fields


def test_original_views_hide_but_preserve_historical_model_columns(data_dir, monkeypatch):
    paths = get_data_paths()
    store = NewsStore(paths.news_db)
    store.initialize()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    store.insert_news_items([{
        "news_id": "history", "source": "source", "original_title": "Original headline",
        "original_summary": "Original summary", "source_language": "en",
        "published_at": now, "fetched_at": now,
        "securities": [{"canonical_code": "72030"}], "importance": 80,
    }])
    with store.write() as db:
        db.execute("UPDATE news_items SET translated_title_ja = ?, translated_summary_ja = ?, analysis_zh_json = ? WHERE news_id = ?",
                   ("旧翻訳", "旧要約", '{"headline_zh":"旧分析"}', "history"))
    monkeypatch.setattr(service, "get_personal_config", lambda: PersonalConfig(features={"news_mode": "read"}))
    original = store.get_item("history")
    views = [service.news_feed_view(), service.news_hotspots_view(), service.news_securities_view(), service.news_pipeline_status_view()]
    feed = views[0]["items"][0]
    assert feed["original_title"] == "Original headline"
    assert feed["original_summary"] == "Original summary"
    assert not {"translated_title_ja", "summary_ja", "translation_version", "analysis_zh", "analysis_state"}.intersection(feed)
    assert views[1]["groups"][0]["latest"]["title"] == "Original headline"
    assert views[2]["rows"][0]["latest"]["title"] == "Original headline"
    assert "ai" not in views[2]["rows"][0]
    assert "ai" not in views[3]
    assert store.get_item("history") == original


def test_news_task_has_no_model_lane_and_keeps_old_queue(data_dir, monkeypatch):
    paths = get_data_paths()
    with sqlite3.connect(paths.ai_jobs_db) as db:
        db.execute("CREATE TABLE ai_jobs(job_id INTEGER PRIMARY KEY, status TEXT)")
        db.execute("INSERT INTO ai_jobs VALUES(1, 'queued')")
        db.execute("INSERT INTO ai_jobs VALUES(2, 'submitted')")
    legacy_bytes = paths.ai_jobs_db.read_bytes()
    core = CoreRepository(paths.core_db)
    core.initialize()
    core.replace_security_master([{"canonical_code": "72030", "name_ja": "トヨタ自動車"}], as_of_date="2026-10-09")
    config = PersonalConfig.model_validate({"features": {"news_mode": "scheduled"}, "ai": {"max_queued": 50}})
    context = SimpleNamespace(paths=paths, config=config, repository=core, settings=Settings())
    calls = []
    monkeypatch.setattr(service, "sync_feeds_once", lambda **kwargs: calls.append(kwargs) or {"feeds": 0, "feed_errors": {}})
    tasks = build_default_tasks(context)
    assert "ai_jobs" not in DEFAULT_TASK_NAMES
    assert "ai_jobs" not in MANUAL_ACTION_TYPES
    assert "ai_jobs" not in {task.name for task in tasks}
    result = next(task for task in tasks if task.name == "news_sync").run(None)
    assert result.status == "completed" and calls
    assert "ai_enqueue" not in result.details
    assert paths.ai_jobs_db.read_bytes() == legacy_bytes
    backup = next(task for task in tasks if task.name == "maintenance").run(None)
    assert backup.status == "completed"
    assert "backup" in backup.details["jp-ai-jobs"]
    assert paths.ai_jobs_db.read_bytes() == legacy_bytes


def test_failed_retired_task_does_not_affect_current_worker_health(tmp_path):
    from app.worker.state import WorkerStateRepository
    repo = WorkerStateRepository(tmp_path / "worker.db")
    repo.initialize()
    token = repo.acquire_lease("owner")
    repo.record_task("owner", token, "news_sync", status="completed", success=True)
    repo.record_task("owner", token, "ai_jobs", status="failed", error_code="old_failure")
    health = repo.health(("news_sync",))
    assert health["healthy"]
    assert set(health["tasks"]) == {"news_sync"}
    assert health["degraded_tasks"] == []
    assert any(row["task_name"] == "ai_jobs" for row in repo.task_statuses())
