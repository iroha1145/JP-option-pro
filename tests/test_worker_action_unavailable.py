"""Action admission during real SQLite initialization and writer contention.

The API must neither initialize the worker database nor retry an uncertain
write with a new idempotency key. A separate worker owns the startup fixture.
"""

from __future__ import annotations

import importlib
import sqlite3
import time
from contextlib import ExitStack
from datetime import date

import httpx
import pytest
from starlette.testclient import TestClient

from app.api import worker_actions
from app.repositories.base import SchemaVersionError
from app.worker.state import WorkerStateRepository

ACTION = "/api/worker/actions/post_close_batch"
ACTION_HEADERS = {"X-Optix-Action": "1", "Origin": "http://testserver"}


@pytest.fixture()
def clients(data_dir, monkeypatch):
    import app.access as access
    import app.api.deps as deps
    import app.config as config
    import app.main as main
    import app.personal_config as personal_config
    import app.services.accounts as accounts

    monkeypatch.delenv("ACCOUNTS_DB_PATH", raising=False)
    monkeypatch.delenv("PERSONAL_CONFIG_PATH", raising=False)
    monkeypatch.setattr(accounts, "_store", None)

    def reset():
        deps.reset_dependencies_for_tests()
        config.reset_settings_for_tests()
        personal_config.reset_personal_config_for_tests()
        access.reset_access_runtime_for_tests()

    reset()
    main = importlib.reload(main)

    class WithClientAddress:
        def __init__(self, address):
            self.address = address

        async def __call__(self, scope, receive, send):
            if scope.get("type") == "http":
                scope = {**scope, "client": (self.address, 40001)}
            await main.app(scope, receive, send)

    try:
        with ExitStack() as stack:
            owner = stack.enter_context(TestClient(
                WithClientAddress("127.0.0.1"), base_url="http://testserver",
                raise_server_exceptions=False,
            ))
            visitor = stack.enter_context(TestClient(
                WithClientAddress("203.0.113.8"), base_url="http://testserver",
                raise_server_exceptions=False,
            ))
            yield owner, visitor
    finally:
        reset()


def _assert_unavailable(response):
    assert response.status_code == 503, response.text
    assert response.json()["detail"]["code"] == "worker_unavailable"
    assert response.headers["retry-after"] == "1"
    assert "no-store" in response.headers["cache-control"]


def _post(client):
    return client.post(ACTION, json={}, headers=ACTION_HEADERS)


def test_absent_worker_database_is_not_created_by_api(clients, data_dir, monkeypatch):
    owner, _ = clients
    database = data_dir / "jp-worker.db"

    def forbidden_initialize(_self):
        raise AssertionError("API must not create or migrate the worker database")

    monkeypatch.setattr(WorkerStateRepository, "initialize", forbidden_initialize)
    _assert_unavailable(_post(owner))
    assert not database.exists()


@pytest.mark.parametrize("signed_in", [False, True])
def test_worker_unavailability_does_not_bypass_owner_or_origin(clients, data_dir, signed_in):
    from app.api.account import ACCOUNT_COOKIE_NAME
    from app.services.accounts import get_account_store

    owner, visitor = clients
    if signed_in:
        session = get_account_store().register("ordinary-user", "a sufficiently long test phrase")
        visitor.cookies.set(ACCOUNT_COOKIE_NAME, session.token)
        assert visitor.get("/api/account/me").json()["logged_in"] is True
    denied = _post(visitor)
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "private_network_required"
    assert "retry-after" not in denied.headers
    assert owner.post(ACTION, json={}).status_code == 403
    assert not (data_dir / "jp-worker.db").exists()


def test_real_writer_lock_returns_retryable_503_then_one_queued_action(clients, data_dir, monkeypatch):
    owner, _ = clients
    repository = WorkerStateRepository(data_dir / "jp-worker.db")
    repository.initialize()
    original_connect = repository._connect_rw

    def short_wait_connection():
        connection = original_connect()
        connection.execute("PRAGMA busy_timeout=25")
        return connection

    monkeypatch.setattr(repository, "_connect_rw", short_wait_connection)
    monkeypatch.setattr(worker_actions, "worker_state_write", lambda: repository)
    with sqlite3.connect(repository.db_path, isolation_level=None) as writer:
        writer.execute("BEGIN IMMEDIATE")
        try:
            _assert_unavailable(_post(owner))
            assert writer.execute("SELECT count(*) FROM worker_action_requests").fetchone()[0] == 0
        finally:
            writer.execute("ROLLBACK")

    accepted = _post(owner)
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["accepted"] is True
    action_id = accepted.json()["action_id"]
    duplicate = _post(owner)
    assert duplicate.status_code == 202
    assert duplicate.json()["action_id"] == action_id
    assert duplicate.json()["reason"] == "type_busy"
    assert len(repository.recent_actions()) == 1
    fence = repository.acquire_lease("test-worker")
    assert repository.claim_next_action("test-worker", fence)["action_id"] == action_id
    repository.complete_action("test-worker", fence, action_id, status="completed", result={"ok": True})
    assert repository.get_action(action_id)["status"] == "completed"


def test_incompatible_schema_is_not_migrated_or_reported_as_transient(clients, data_dir):
    owner, _ = clients
    repository = WorkerStateRepository(data_dir / "jp-worker.db")
    repository.initialize()
    with sqlite3.connect(repository.db_path) as connection:
        connection.execute("UPDATE jp_worker_schema SET version='jp-worker-v0'")
    response = _post(owner)
    assert response.status_code == 500
    assert "retry-after" not in response.headers
    with sqlite3.connect(repository.db_path) as connection:
        assert connection.execute("SELECT version FROM jp_worker_schema").fetchone()[0] == "jp-worker-v0"
        assert connection.execute("SELECT count(*) FROM worker_action_requests").fetchone()[0] == 0


@pytest.mark.parametrize("error_code", [sqlite3.SQLITE_IOERR, sqlite3.SQLITE_READONLY, sqlite3.SQLITE_FULL])
def test_wrapped_permanent_sqlite_errors_are_not_initialization_503s(clients, data_dir, monkeypatch, error_code):
    owner, _ = clients
    repository = WorkerStateRepository(data_dir / "jp-worker.db")
    repository.initialize()

    def fail_schema_read(_connection):
        cause = sqlite3.OperationalError("permanent database failure")
        cause.sqlite_errorcode = error_code
        raise SchemaVersionError("jp-worker.db: schema table missing") from cause

    monkeypatch.setattr(repository, "verify_schema", fail_schema_read)
    monkeypatch.setattr(worker_actions, "worker_state_write", lambda: repository)
    response = _post(owner)
    assert response.status_code == 500
    assert "retry-after" not in response.headers


def test_missing_action_table_is_not_misreported_as_startup(clients, data_dir):
    owner, _ = clients
    repository = WorkerStateRepository(data_dir / "jp-worker.db")
    repository.initialize()
    with sqlite3.connect(repository.db_path) as connection:
        connection.execute("DROP TABLE worker_action_requests")
    response = _post(owner)
    assert response.status_code == 500
    assert "retry-after" not in response.headers


def test_post_commit_failure_is_not_retried_or_declared_safe_to_retry(clients, data_dir, monkeypatch):
    owner, _ = clients
    repository = WorkerStateRepository(data_dir / "jp-worker.db")
    repository.initialize()
    request_action = repository.request_action
    calls = 0

    def fail_after_commit(*args, **kwargs):
        nonlocal calls
        calls += 1
        request_action(*args, **kwargs)
        error = sqlite3.OperationalError("disk I/O error after commit")
        error.sqlite_errorcode = sqlite3.SQLITE_IOERR
        raise error

    monkeypatch.setattr(repository, "request_action", fail_after_commit)
    monkeypatch.setattr(worker_actions, "worker_state_write", lambda: repository)
    response = _post(owner)
    assert response.status_code == 500
    assert "retry-after" not in response.headers
    assert calls == 1
    assert len(repository.recent_actions()) == 1


_PAUSED_WORKER = '''
import os
import runpy
import time
from pathlib import Path
from app.worker.state import WorkerStateRepository

original_connect = WorkerStateRepository._connect_rw
paused = False
def connect_with_pause(self):
    global paused
    connection = original_connect(self)
    if not paused:
        paused = True
        def trace(sql):
            if "CREATE TABLE IF NOT EXISTS jp_worker_schema" in sql:
                Path(os.environ["TEST_SCHEMA_PAUSED"]).write_text("initializing")
                deadline = time.monotonic() + 30
                while not Path(os.environ["TEST_SCHEMA_RELEASE"]).exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
        connection.set_trace_callback(trace)
    return connection
WorkerStateRepository._connect_rw = connect_with_pause
runpy.run_path(os.environ["TEST_REAL_WORKER"], run_name="__main__")
'''


def test_independent_worker_schema_window_is_503_then_202_and_processed(tmp_path, monkeypatch):
    from app.tools.dev_fixture import build_fixture
    from tests import test_screener_dual_process as dual

    data_dir = tmp_path / "data"
    build_fixture(str(data_dir), days=140, end_date=date(2026, 9, 8))
    wrapper = tmp_path / "paused_worker.py"
    wrapper.write_text(_PAUSED_WORKER)
    paused = tmp_path / "paused"
    release = tmp_path / "release"
    monkeypatch.setenv("TEST_SCHEMA_PAUSED", str(paused))
    monkeypatch.setenv("TEST_SCHEMA_RELEASE", str(release))
    monkeypatch.setenv("TEST_REAL_WORKER", str(dual.REPO / "tests/support/synthetic_worker.py"))
    original_popen = dual.subprocess.Popen
    with (tmp_path / "api.log").open("w+") as api_log, (tmp_path / "worker.log").open("w+") as worker_log:
        def spawn_with_paused_schema(command, **kwargs):
            is_worker = any(str(arg).endswith("tests/support/synthetic_worker.py") for arg in command)
            kwargs["stdout"] = worker_log if is_worker else api_log
            if is_worker:
                command = [command[0], str(wrapper)]
            return original_popen(command, **kwargs)

        monkeypatch.setattr(dual.subprocess, "Popen", spawn_with_paused_schema)
        bundle = dual._spawn(data_dir, engine="ok", wait_for_worker=False)
        try:
            deadline = time.monotonic() + 10
            while not paused.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert paused.exists(), "worker did not reach its uncommitted schema transaction"
            assert (data_dir / "jp-worker.db").is_file()
            with httpx.Client(base_url=bundle["base"], timeout=5) as client:
                assert client.get("/ready").status_code == 200
                assert client.get("/api/strength/scan?top=5").status_code == 200
                headers = {"X-Optix-Action": "1", "Origin": bundle["base"]}
                _assert_unavailable(client.post(ACTION, json={}, headers=headers))
                with sqlite3.connect(f"file:{data_dir / 'jp-worker.db'}?mode=ro", uri=True) as connection:
                    assert not connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                release.touch()
                dual._wait_worker_ready(data_dir, bundle["worker"])
                accepted = client.post(ACTION, json={}, headers=headers)
                assert accepted.status_code == 202, accepted.text
                finished = dual._poll_action(client, accepted.json()["action_id"])
                assert finished["status"] == "completed", finished
                assert finished["result"]["outcome"] in {"published", "already_current"}
            repository = WorkerStateRepository(data_dir / "jp-worker.db", read_only=True)
            assert len(repository.recent_actions()) == 1
        finally:
            release.touch()
            dual._stop(bundle)
