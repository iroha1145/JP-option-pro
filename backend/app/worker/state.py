"""Worker state: lease with fencing token, task status, owner action queue.

Ported design from the reference project:
- OS flock (worker/lock.py) proves no other live worker process; the SQLite
  lease with a monotonic ``fencing_token`` then rejects writes from any
  zombie that lost the lock race.
- ``recover_interrupted`` runs at startup under the new fence: crashed
  ``running`` rows become ``interrupted`` (tasks) or re-``queued``
  (actions) instead of wedging a slot forever.
- One active action per action type, enforced by a partial unique index —
  the DB, not politeness, guarantees no double-run.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from app.repositories.base import SQLiteRepository, utc_now_iso

WORKER_SCHEMA_VERSION = "jp-worker-v1"

WORKER_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS worker_lease (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        owner_id TEXT NOT NULL,
        fencing_token INTEGER NOT NULL,
        acquired_at TEXT NOT NULL,
        renewed_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS worker_task_status (
        task_name TEXT PRIMARY KEY,
        status TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        consecutive_failures INTEGER NOT NULL DEFAULT 0,
        last_started_at TEXT,
        last_completed_at TEXT,
        last_success_at TEXT,
        next_run_at TEXT,
        error_code TEXT,
        details_json TEXT NOT NULL DEFAULT '{}'
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE IF NOT EXISTS worker_action_requests (
        action_id INTEGER PRIMARY KEY AUTOINCREMENT,
        action_type TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        payload_json TEXT NOT NULL DEFAULT '{}',
        status TEXT NOT NULL DEFAULT 'queued',
        requested_at TEXT NOT NULL,
        started_at TEXT,
        completed_at TEXT,
        error_code TEXT,
        result_json TEXT,
        UNIQUE (action_type, idempotency_key)
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_worker_action_active
        ON worker_action_requests(action_type)
        WHERE status IN ('queued', 'running')
    """,
)

_LEASE_SECONDS = 60.0


class WorkerLeaseLost(RuntimeError):
    pass


class WorkerStateRepository(SQLiteRepository):
    SCHEMA_NAME = "jp_worker"
    SCHEMA_VERSION = WORKER_SCHEMA_VERSION
    DDL = WORKER_DDL

    def __init__(self, db_path: Path, *, read_only: bool = False) -> None:
        super().__init__(db_path, read_only=read_only)

    # -- lease ----------------------------------------------------------

    def acquire_lease(self, owner_id: str, *, force: bool = True) -> int:
        """Take the lease. ``force`` is safe because the OS flock already
        proved the previous owner process is dead; the fencing token still
        increments so any zombie writer gets rejected."""

        now = utc_now_iso()
        with self.write() as connection:
            row = connection.execute("SELECT fencing_token FROM worker_lease WHERE id = 1").fetchone()
            token = (int(row[0]) + 1) if row else 1
            if row and not force:
                raise WorkerLeaseLost("lease already held")
            connection.execute(
                "INSERT INTO worker_lease (id, owner_id, fencing_token, acquired_at, renewed_at, expires_at) "
                "VALUES (1, ?, ?, ?, ?, datetime('now', '+60 seconds')) "
                "ON CONFLICT (id) DO UPDATE SET owner_id=excluded.owner_id, "
                "fencing_token=excluded.fencing_token, acquired_at=excluded.acquired_at, "
                "renewed_at=excluded.renewed_at, expires_at=excluded.expires_at",
                (owner_id, token, now, now),
            )
        return token

    def renew_lease(self, owner_id: str, fencing_token: int) -> None:
        with self.write() as connection:
            cursor = connection.execute(
                "UPDATE worker_lease SET renewed_at = ?, expires_at = datetime('now', '+60 seconds') "
                "WHERE id = 1 AND owner_id = ? AND fencing_token = ?",
                (utc_now_iso(), owner_id, fencing_token),
            )
            if not cursor.rowcount:
                raise WorkerLeaseLost("fencing token moved")

    def _assert_fence(self, connection: sqlite3.Connection, owner_id: str, fencing_token: int) -> None:
        row = connection.execute(
            "SELECT owner_id, fencing_token FROM worker_lease WHERE id = 1"
        ).fetchone()
        if row is None or row[0] != owner_id or int(row[1]) != fencing_token:
            raise WorkerLeaseLost("fencing token moved")

    # -- startup recovery ------------------------------------------------

    def recover_interrupted(self, owner_id: str, fencing_token: int) -> None:
        with self.write() as connection:
            self._assert_fence(connection, owner_id, fencing_token)
            connection.execute(
                "UPDATE worker_task_status SET status='interrupted', error_code='worker_restarted' "
                "WHERE status IN ('starting', 'running', 'stopping')"
            )
            connection.execute(
                "UPDATE worker_action_requests SET status='queued', started_at=NULL, "
                "error_code='worker_restarted' WHERE status='running'"
            )

    def reconcile_task_inventory(self, task_names: tuple[str, ...]) -> None:
        """在庫を起動時に揃える。**消すだけでなく、足りない行を作る。**

        以前は削除しかしていなかったので、新しいタスクを 1 つ足すと、その
        タスクが初回に走るまで `task_inventory_complete` が false のまま
        —— つまり **コンテナが unhealthy** で、`deploy.sh --wait` が
        初回遅延より短ければデプロイが失敗する（実際そうなった）。
        まだ一度も走っていないことと、存在しないことは別。
        """

        placeholders = ", ".join("?" for _ in task_names) or "''"
        with self.write() as connection:
            connection.execute(
                f"DELETE FROM worker_task_status WHERE task_name NOT IN ({placeholders})",
                task_names,
            )
            connection.executemany(
                "INSERT INTO worker_task_status (task_name, status) VALUES (?, 'pending') "
                "ON CONFLICT (task_name) DO NOTHING",
                [(name,) for name in task_names],
            )

    # -- task status ------------------------------------------------------

    def record_task(
        self,
        owner_id: str,
        fencing_token: int,
        task_name: str,
        *,
        status: str,
        error_code: str | None = None,
        details: dict[str, Any] | None = None,
        next_run_at: str | None = None,
        success: bool | None = None,
    ) -> None:
        now = utc_now_iso()
        details_json = json.dumps(details or {}, ensure_ascii=False)[:16384]
        with self.write() as connection:
            self._assert_fence(connection, owner_id, fencing_token)
            row = connection.execute(
                "SELECT consecutive_failures FROM worker_task_status WHERE task_name = ?",
                (task_name,),
            ).fetchone()
            failures = int(row[0]) if row else 0
            if success is True:
                failures = 0
            elif success is False:
                failures += 1
            connection.execute(
                "INSERT INTO worker_task_status (task_name, status, enabled, consecutive_failures, "
                "last_started_at, last_completed_at, last_success_at, next_run_at, error_code, details_json) "
                "VALUES (?, ?, 1, ?, CASE WHEN ? = 'running' THEN ? ELSE NULL END, NULL, NULL, ?, ?, ?) "
                "ON CONFLICT (task_name) DO UPDATE SET "
                "status = excluded.status, "
                "consecutive_failures = ?, "
                "last_started_at = CASE WHEN excluded.status = 'running' THEN ? ELSE worker_task_status.last_started_at END, "
                "last_completed_at = CASE WHEN excluded.status IN ('completed', 'failed') THEN ? ELSE worker_task_status.last_completed_at END, "
                "last_success_at = CASE WHEN ? THEN ? ELSE worker_task_status.last_success_at END, "
                "next_run_at = excluded.next_run_at, "
                "error_code = excluded.error_code, "
                "details_json = excluded.details_json",
                (
                    task_name, status, failures, status, now, next_run_at, error_code, details_json,
                    failures, now, now, 1 if success is True else 0, now,
                ),
            )

    def task_statuses(self) -> list[dict[str, Any]]:
        with self.read() as connection:
            rows = connection.execute(
                "SELECT * FROM worker_task_status ORDER BY task_name"
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["details"] = json.loads(item.pop("details_json") or "{}")
            except ValueError:
                item["details"] = {}
            result.append(item)
        return result

    # -- action queue ------------------------------------------------------

    def request_action(
        self, action_type: str, *, idempotency_key: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        now = utc_now_iso()
        payload_json = json.dumps(payload or {}, ensure_ascii=False)[:8192]
        with self.write() as connection:
            try:
                cursor = connection.execute(
                    "INSERT INTO worker_action_requests (action_type, idempotency_key, payload_json, "
                    "status, requested_at) VALUES (?, ?, ?, 'queued', ?)",
                    (action_type, idempotency_key, payload_json, now),
                )
                return {"action_id": cursor.lastrowid, "status": "queued", "duplicate": False}
            except sqlite3.IntegrityError:
                row = connection.execute(
                    "SELECT action_id, status FROM worker_action_requests "
                    "WHERE action_type = ? AND status IN ('queued', 'running') "
                    "ORDER BY action_id DESC LIMIT 1",
                    (action_type,),
                ).fetchone()
                if row is not None:
                    return {"action_id": row[0], "status": row[1], "duplicate": True}
                row = connection.execute(
                    "SELECT action_id, status FROM worker_action_requests "
                    "WHERE action_type = ? AND idempotency_key = ?",
                    (action_type, idempotency_key),
                ).fetchone()
                return {
                    "action_id": row[0] if row else None,
                    "status": row[1] if row else "unknown",
                    "duplicate": True,
                }

    def claim_next_action(self, owner_id: str, fencing_token: int) -> dict[str, Any] | None:
        with self.write() as connection:
            self._assert_fence(connection, owner_id, fencing_token)
            row = connection.execute(
                "SELECT * FROM worker_action_requests WHERE status = 'queued' "
                "ORDER BY action_id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE worker_action_requests SET status = 'running', started_at = ? "
                "WHERE action_id = ?",
                (utc_now_iso(), row["action_id"]),
            )
            item = dict(row)
            try:
                item["payload"] = json.loads(item.pop("payload_json") or "{}")
            except ValueError:
                item["payload"] = {}
            return item

    def complete_action(
        self,
        owner_id: str,
        fencing_token: int,
        action_id: int,
        *,
        status: str,
        error_code: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> None:
        with self.write() as connection:
            self._assert_fence(connection, owner_id, fencing_token)
            connection.execute(
                "UPDATE worker_action_requests SET status = ?, completed_at = ?, error_code = ?, "
                "result_json = ? WHERE action_id = ?",
                (
                    status, utc_now_iso(), error_code,
                    json.dumps(result or {}, ensure_ascii=False)[:16384], action_id,
                ),
            )

    def recent_actions(self, *, limit: int = 20) -> list[dict[str, Any]]:
        with self.read() as connection:
            rows = connection.execute(
                "SELECT action_id, action_type, status, requested_at, started_at, completed_at, error_code "
                "FROM worker_action_requests ORDER BY action_id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [dict(row) for row in rows]

    def has_pending_actions(self) -> bool:
        with self.read() as connection:
            row = connection.execute(
                "SELECT 1 FROM worker_action_requests WHERE status = 'queued' LIMIT 1"
            ).fetchone()
        return row is not None

    # -- health ------------------------------------------------------------

    def health(self, expected_tasks: tuple[str, ...]) -> dict[str, Any]:
        statuses = {item["task_name"]: item for item in self.task_statuses()}
        degraded = [
            name
            for name, item in statuses.items()
            if item.get("status") in {"failed", "interrupted", "degraded"}
        ]
        missing = [name for name in expected_tasks if name not in statuses]
        with self.read() as connection:
            lease = connection.execute("SELECT * FROM worker_lease WHERE id = 1").fetchone()
        return {
            "healthy": not degraded and not missing and lease is not None,
            "schema_version": WORKER_SCHEMA_VERSION,
            "task_inventory_complete": not missing,
            "missing_tasks": missing,
            "degraded_tasks": degraded,
            "lease": dict(lease) if lease else None,
            "tasks": statuses,
        }


__all__ = ["WORKER_SCHEMA_VERSION", "WorkerLeaseLost", "WorkerStateRepository"]
