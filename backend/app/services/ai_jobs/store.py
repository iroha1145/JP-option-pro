"""jp-ai-jobs.db — モデルジョブの永続キュー。

参照プロジェクトから移植した規律:
- request_hash は payload + model + prompt/schema 版を畳み込む → 同一入力の
  重複支払いを DB の UNIQUE 制約で防ぐ。
- 日次トークン予算: 確定 usage + 未確定ジョブの予約分を UTC 日で合算。
- unknown（送信結果不明）は再試行しない。response_id が残っていれば 24h、
  無ければ 15 分だけ同時実行スロットを塞ぐ（旧プロジェクトの事故対策）。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from app.repositories.base import SQLiteRepository, utc_now_iso

AI_SCHEMA_VERSION = "jp-ai-jobs-v1"

JOB_TYPES = ("news_translation_ja", "news_analysis_zh")

UNKNOWN_HOLD_WITH_RESPONSE_SECONDS = 24 * 3600
UNKNOWN_HOLD_NO_RESPONSE_SECONDS = 15 * 60
CLAIMING_MARKER = "claiming"
CLAIMING_STALE_SECONDS = 120

AI_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS ai_jobs (
        job_id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_type TEXT NOT NULL CHECK (job_type IN ('news_translation_ja', 'news_analysis_zh')),
        request_hash TEXT NOT NULL,
        news_id TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        prompt_version TEXT NOT NULL,
        schema_version TEXT NOT NULL,
        model TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'queued'
            CHECK (status IN ('queued', 'submitted', 'completed', 'failed', 'cancelled', 'unknown')),
        openai_response_id TEXT,
        token_reservation INTEGER NOT NULL DEFAULT 0,
        tokens_used INTEGER,
        error_code TEXT,
        result_json TEXT,
        created_at TEXT NOT NULL,
        submitted_at TEXT,
        completed_at TEXT,
        updated_at TEXT NOT NULL,
        UNIQUE (job_type, request_hash)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ai_jobs_status ON ai_jobs(status, job_id)",
    "CREATE INDEX IF NOT EXISTS idx_ai_jobs_news ON ai_jobs(news_id)",
)


def request_hash(
    job_type: str, payload: Mapping[str, Any], *, model: str,
    prompt_version: str, schema_version: str, schema_sha256: str,
) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    blob = "\n".join((job_type, canonical, model, prompt_version, schema_version, schema_sha256))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _utc_day(now_iso: str) -> str:
    return now_iso[:10]


class AIJobStore(SQLiteRepository):
    SCHEMA_NAME = "jp_ai"
    SCHEMA_VERSION = AI_SCHEMA_VERSION
    DDL = AI_DDL

    def __init__(self, db_path: Path, *, read_only: bool = False) -> None:
        super().__init__(db_path, read_only=read_only)

    def create_job(
        self, *, job_type: str, news_id: str, payload: Mapping[str, Any],
        prompt_version: str, schema_version: str, model: str,
        request_hash_value: str, token_reservation: int,
    ) -> dict[str, Any]:
        now = utc_now_iso()
        with self.write() as connection:
            existing = connection.execute(
                "SELECT job_id, status FROM ai_jobs WHERE job_type = ? AND request_hash = ?",
                (job_type, request_hash_value),
            ).fetchone()
            if existing is not None:
                return {"job_id": existing[0], "status": existing[1], "created": False}
            cursor = connection.execute(
                "INSERT INTO ai_jobs (job_type, request_hash, news_id, payload_json, prompt_version, "
                "schema_version, model, status, token_reservation, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?)",
                (
                    job_type, request_hash_value, news_id,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    prompt_version, schema_version, model, int(token_reservation), now, now,
                ),
            )
            return {"job_id": cursor.lastrowid, "status": "queued", "created": True}

    def queued_count(self) -> int:
        with self.read() as connection:
            return int(connection.execute(
                "SELECT COUNT(*) FROM ai_jobs WHERE status = 'queued'"
            ).fetchone()[0])

    def tokens_committed_today(self) -> int:
        """確定 usage + 未確定の予約分（UTC 日）。"""

        day = _utc_day(utc_now_iso())
        with self.read() as connection:
            settled = connection.execute(
                "SELECT COALESCE(SUM(tokens_used), 0) FROM ai_jobs "
                "WHERE completed_at LIKE ? AND tokens_used IS NOT NULL",
                (f"{day}%",),
            ).fetchone()[0]
            # In-flight reservations count regardless of creation day: a job created
            # just before UTC midnight but still queued/submitted/unknown today will
            # spend its tokens today, so filtering reservations by created_at let the
            # daily budget be overspent by stale carryover.
            reserved = connection.execute(
                "SELECT COALESCE(SUM(token_reservation), 0) FROM ai_jobs "
                "WHERE status IN ('queued', 'submitted', 'unknown')",
            ).fetchone()[0]
        return int(settled) + int(reserved)

    def slot_blocked(self) -> bool:
        """同時実行 1 の規律: submitted / 進行中の claim / 有効な unknown が残っていれば塞がる。"""

        now = datetime.now(timezone.utc)
        with self.read() as connection:
            submitted = connection.execute(
                "SELECT COUNT(*) FROM ai_jobs WHERE status = 'submitted'"
            ).fetchone()[0]
            if submitted:
                return True
            claiming_rows = connection.execute(
                "SELECT updated_at FROM ai_jobs WHERE status = 'queued' AND error_code = ?",
                (CLAIMING_MARKER,),
            ).fetchall()
            for row in claiming_rows:
                try:
                    updated = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
                except ValueError:
                    return True
                if (now - updated).total_seconds() < CLAIMING_STALE_SECONDS:
                    return True
            unknown_rows = connection.execute(
                "SELECT openai_response_id, updated_at FROM ai_jobs WHERE status = 'unknown'"
            ).fetchall()
        for row in unknown_rows:
            hold = (
                UNKNOWN_HOLD_WITH_RESPONSE_SECONDS if row[0] else UNKNOWN_HOLD_NO_RESPONSE_SECONDS
            )
            try:
                updated = datetime.fromisoformat(str(row[1]).replace("Z", "+00:00"))
            except ValueError:
                continue
            if (now - updated).total_seconds() < hold:
                return True
        return False

    def claim_next(self) -> dict[str, Any] | None:
        now = utc_now_iso()
        now_dt = datetime.now(timezone.utc)
        with self.write() as connection:
            rows = connection.execute(
                "SELECT * FROM ai_jobs WHERE status = 'queued' ORDER BY job_id"
            ).fetchall()
            chosen = None
            for row in rows:
                if row["error_code"] == CLAIMING_MARKER:
                    try:
                        updated = datetime.fromisoformat(str(row["updated_at"]).replace("Z", "+00:00"))
                    except ValueError:
                        chosen = row
                        break
                    if (now_dt - updated).total_seconds() < CLAIMING_STALE_SECONDS:
                        continue
                chosen = row
                break
            if chosen is None:
                return None
            connection.execute(
                "UPDATE ai_jobs SET error_code = ?, updated_at = ? "
                "WHERE job_id = ? AND status = 'queued'",
                (CLAIMING_MARKER, now, chosen["job_id"]),
            )
            item = dict(chosen)
            try:
                item["payload"] = json.loads(item.pop("payload_json"))
            except ValueError:
                item["payload"] = {}
            return item

    def submitted_job(self) -> dict[str, Any] | None:
        with self.read() as connection:
            row = connection.execute(
                "SELECT * FROM ai_jobs WHERE status = 'submitted' ORDER BY job_id LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        try:
            item["payload"] = json.loads(item.pop("payload_json"))
        except ValueError:
            item["payload"] = {}
        return item

    def mark_submitted(self, job_id: int, response_id: str) -> None:
        now = utc_now_iso()
        with self.write() as connection:
            connection.execute(
                # Clear the transient CLAIMING_MARKER stored in error_code so a
                # submitted row isn't left with a misleading 'claiming' diagnostic.
                "UPDATE ai_jobs SET status = 'submitted', openai_response_id = ?, "
                "submitted_at = ?, updated_at = ?, error_code = NULL "
                "WHERE job_id = ? AND status = 'queued'",
                (response_id, now, now, job_id),
            )

    def mark_unknown(self, job_id: int, *, error_code: str) -> None:
        now = utc_now_iso()
        with self.write() as connection:
            connection.execute(
                "UPDATE ai_jobs SET status = 'unknown', error_code = ?, updated_at = ? "
                "WHERE job_id = ?",
                (error_code[:120], now, job_id),
            )

    def settle(
        self, job_id: int, *, status: str, result: Mapping[str, Any] | None,
        tokens_used: int | None, error_code: str | None,
    ) -> None:
        now = utc_now_iso()
        with self.write() as connection:
            connection.execute(
                "UPDATE ai_jobs SET status = ?, result_json = ?, tokens_used = ?, error_code = ?, "
                "completed_at = ?, updated_at = ?, token_reservation = 0 WHERE job_id = ?",
                (
                    status,
                    json.dumps(result, ensure_ascii=False, sort_keys=True) if result is not None else None,
                    tokens_used, error_code, now, now, job_id,
                ),
            )

    def jobs_for_news(self, news_ids: list[str]) -> dict[str, dict[str, str]]:
        """news_id → {job_type: status}（フィードの分析状態表示用）。"""

        if not news_ids:
            return {}
        placeholders = ", ".join("?" for _ in news_ids)
        with self.read() as connection:
            rows = connection.execute(
                f"SELECT news_id, job_type, status FROM ai_jobs WHERE news_id IN ({placeholders})",
                news_ids,
            ).fetchall()
        result: dict[str, dict[str, str]] = {}
        for row in rows:
            result.setdefault(row[0], {})[row[1]] = row[2]
        return result

    def status_counts(self) -> dict[str, int]:
        with self.read() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) FROM ai_jobs GROUP BY status"
            ).fetchall()
        return {row[0]: int(row[1]) for row in rows}


__all__ = ["AIJobStore", "AI_SCHEMA_VERSION", "JOB_TYPES", "request_hash"]
