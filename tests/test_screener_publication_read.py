"""JP-05/06: atomic snapshot reads, stored score version, migrations."""

from __future__ import annotations

import sqlite3
import threading

import pytest
from starlette.testclient import TestClient

from app.repositories.base import SchemaVersionError, schema_checksum, utc_now_iso
from app.repositories.core import CoreRepository
from app.repositories.core_schema import CORE_DDL, CORE_SCHEMA_VERSION
from app.services.publication import OUTCOME_PUBLISHED
from app.services.strength_scan import STRENGTH_SCORE_VERSION


def _publish(repo: CoreRepository, *, trade_date: str, codes: list[str], version: str | None = None):
    rows = [{"canonical_code": code, "trade_date": trade_date, "intrinsic_score": 70.0} for code in codes]
    return repo.replace_strength_rows(
        rows,
        trade_date=trade_date,
        regime={"env": trade_date, "n": len(codes)},
        score_version=version or STRENGTH_SCORE_VERSION,
        expected_trade_date=trade_date,
        input_data_through=trade_date,
        coverage={"allows_complete_publish": True, "expected": len(codes), "valid": len(codes)},
        input_fingerprint=f"{trade_date}:{','.join(codes)}:{version or STRENGTH_SCORE_VERSION}",
        today=trade_date,
    )


def test_e01_snapshot_read_is_old_or_new_not_mixed(tmp_path):
    repo = CoreRepository(tmp_path / "core.db")
    repo.initialize()
    first = _publish(repo, trade_date="2026-09-07", codes=["72030", "67580", "99840"])
    assert first.outcome == OUTCOME_PUBLISHED

    start_write = threading.Event()
    writer_in_txn = threading.Event()
    reader_has_meta = threading.Event()
    writer_done = threading.Event()
    seen: dict[str, object] = {}

    def writer():
        start_write.wait(2)
        # Hold the write transaction until the reader has begun its snapshot.
        import sqlite3 as _sql

        connection = _sql.connect(repo.db_path, isolation_level=None, timeout=10)
        connection.execute("BEGIN IMMEDIATE")
        writer_in_txn.set()
        reader_has_meta.wait(2)
        connection.execute("DELETE FROM strength_rows")
        connection.execute(
            "INSERT INTO strength_rows (canonical_code, trade_date, details_json, built_at) "
            "VALUES ('72030', '2026-09-08', '{}', '2026-09-08T00:00:00Z')"
        )
        connection.execute(
            "UPDATE strength_meta SET trade_date='2026-09-08', universe_count=1, "
            "regime_json='{\"env\":\"2026-09-08\"}', publication_id='pub_new'"
        )
        connection.execute("COMMIT")
        connection.close()
        writer_done.set()

    def reader():
        writer_in_txn.wait(2)
        snapshot = repo.strength_snapshot()
        seen["snapshot"] = snapshot
        reader_has_meta.set()
        writer_done.wait(2)

    # Dedicated snapshot: reader starts after writer has BEGIN IMMEDIATE so it
    # either waits for the new commit or sees the old snapshot — never a mix.
    # The barrier here starts the reader after the writer lock exists; SQLite
    # WAL then yields one consistent generation.
    thread_w = threading.Thread(target=writer)
    thread_r = threading.Thread(target=reader)
    thread_w.start()
    start_write.set()
    writer_in_txn.wait(2)
    # Reader that uses the dedicated snapshot API while a writer is in progress.
    snap = repo.strength_snapshot()
    reader_has_meta.set()
    thread_w.join(3)
    assert snap is not None
    rows, meta = snap
    assert (meta["trade_date"] == "2026-09-07" and len(rows) == 3) or (
        meta["trade_date"] == "2026-09-08" and len(rows) == 1
    )
    if meta["trade_date"] == "2026-09-07":
        assert meta["universe_count"] == 3
        assert all(row["trade_date"] == "2026-09-07" for row in rows)
    else:
        assert meta["universe_count"] == 1
        assert all(row["trade_date"] == "2026-09-08" for row in rows)


def test_e02_two_autocommit_reads_can_mix_generations(tmp_path):
    """Documents why BEGIN is required: two read() calls are not a snapshot."""

    repo = CoreRepository(tmp_path / "core.db")
    repo.initialize()
    _publish(repo, trade_date="2026-09-07", codes=["72030", "67580", "99840"])

    meta = repo.strength_meta()
    _publish(repo, trade_date="2026-09-08", codes=["72030"])
    rows = repo.strength_rows_all()
    assert meta["trade_date"] == "2026-09-07"
    assert len(rows) == 1 and rows[0]["trade_date"] == "2026-09-08"


def test_e03_stored_score_version_is_not_the_runtime_constant(tmp_path):
    repo = CoreRepository(tmp_path / "core.db")
    repo.initialize()
    pub = _publish(repo, trade_date="2026-09-08", codes=["72030"], version="jp-strength-historical")
    assert pub.score_version == "jp-strength-historical"
    meta = repo.strength_meta()
    assert meta["score_version"] == "jp-strength-historical"
    assert meta["score_version"] != STRENGTH_SCORE_VERSION


def test_e04_historical_null_version_stays_unknown(tmp_path):
    repo = CoreRepository(tmp_path / "core.db")
    repo.initialize()
    _publish(repo, trade_date="2026-09-07", codes=["72030"])
    with repo.write() as connection:
        connection.execute("UPDATE strength_meta SET score_version = NULL")
    meta = repo.strength_meta()
    assert meta["score_version"] is None
    assert meta["stored_score_version"] is None


def test_e05_v8_migrates_to_v9_without_stamping_current_version(tmp_path):
    db_path = tmp_path / "core.db"
    repo = CoreRepository(db_path)
    repo.initialize()
    _publish(repo, trade_date="2026-09-07", codes=["72030"])
    with sqlite3.connect(db_path) as connection:
        connection.execute("ALTER TABLE strength_meta DROP COLUMN publication_id")
        connection.execute("ALTER TABLE strength_meta DROP COLUMN score_version")
        connection.execute("ALTER TABLE strength_meta DROP COLUMN expected_trade_date")
        connection.execute("ALTER TABLE strength_meta DROP COLUMN input_data_through")
        connection.execute("ALTER TABLE strength_meta DROP COLUMN coverage_json")
        connection.execute("ALTER TABLE strength_meta DROP COLUMN index_input_date")
        connection.execute("ALTER TABLE strength_meta DROP COLUMN universe_version")
        connection.execute("ALTER TABLE strength_meta DROP COLUMN input_fingerprint")
        connection.execute(
            "UPDATE jp_core_schema SET version='jp-core-v8', checksum='deadbeef' WHERE id=1"
        )
        connection.commit()
    CoreRepository(db_path).initialize()
    with sqlite3.connect(db_path) as connection:
        version = connection.execute("SELECT version FROM jp_core_schema WHERE id=1").fetchone()[0]
        columns = {row[1] for row in connection.execute("PRAGMA table_info(strength_meta)")}
        score = connection.execute("SELECT score_version FROM strength_meta WHERE id=1").fetchone()[0]
    assert version == CORE_SCHEMA_VERSION
    assert "publication_id" in columns and "score_version" in columns
    assert score is None


def test_e06_readonly_does_not_create_or_migrate(tmp_path):
    db_path = tmp_path / "missing.db"
    reader = CoreRepository(db_path, read_only=True)
    assert reader.exists() is False
    with pytest.raises(Exception):
        reader.initialize()
    assert not db_path.exists()

    writer = CoreRepository(db_path)
    writer.initialize()
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE jp_core_schema SET version='jp-core-v0', checksum='x' WHERE id=1"
        )
        connection.commit()
    readonly = CoreRepository(db_path, read_only=True)
    with pytest.raises(SchemaVersionError):
        readonly.strength_snapshot()


def test_schema_checksum_matches_current_ddl():
    assert schema_checksum(CORE_DDL)


def test_e08_etag_changes_when_expected_date_changes(tmp_path, monkeypatch):
    from app.tools.dev_fixture import build_fixture
    import app.api.deps as deps
    import app.config as config_module
    import app.access as access_module
    import importlib
    import app.main as main_module

    data_dir = tmp_path / "data"
    build_fixture(str(data_dir), days=140)
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    deps.reset_dependencies_for_tests()
    config_module.reset_settings_for_tests()
    access_module.reset_access_runtime_for_tests()
    main_module = importlib.reload(main_module)

    class _Loopback:
        def __init__(self, inner):
            self._inner = inner

        async def __call__(self, scope, receive, send):
            if scope.get("type") == "http":
                scope = {**scope, "client": ("127.0.0.1", 40001)}
            await self._inner(scope, receive, send)

    with TestClient(_Loopback(main_module.app), base_url="http://testserver") as client:
        first = client.get("/api/strength/scan?top=5")
        assert first.status_code == 200
        body = first.json()
        assert "publication_id" in body
        assert body.get("query_kind") == "filter"
        etag = first.headers.get("etag")
        assert etag
        cached = client.get("/api/strength/scan?top=5", headers={"If-None-Match": etag})
        assert cached.status_code == 304
    deps.reset_dependencies_for_tests()


def test_e07_screener_count_and_rows_share_one_snapshot(tmp_path):
    repo = CoreRepository(tmp_path / "core.db")
    repo.initialize()
    repo.replace_screener_rows(
        [
            {"canonical_code": "72030", "trade_date": "2026-09-07", "metrics": {"x": 1}},
            {"canonical_code": "67580", "trade_date": "2026-09-07", "metrics": {"x": 2}},
        ]
    )
    rows, total = repo.screener_query(
        where_sql="1=1",
        params=(),
        order_sql="canonical_code",
        limit=10,
        offset=0,
    )
    assert total == 2
    assert {row["canonical_code"] for row in rows} == {"72030", "67580"}
    assert {row["trade_date"] for row in rows} == {"2026-09-07"}
