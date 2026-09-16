"""jp-core-v9 → v11 and jp-app-v2 → v3 keep existing rows."""

from __future__ import annotations

import sqlite3

from app.repositories.app_store import APP_SCHEMA_VERSION, AppStore
from app.repositories.base import utc_now_iso
from app.repositories.core import CoreRepository
from app.repositories.core_schema import CORE_DDL, CORE_SCHEMA_VERSION
from app.services.radar.t1_priority import T1_MET
from tests.support.a0_t1_fixtures import SESSION_ISO, init_repo


def _legacy_v9_db(path):
    # Build current DDL then rewind the version stamp to v9 without T1 tables
    # so initialize() must apply the v9→v10 migration.
    repo = CoreRepository(path)
    repo.initialize()
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE IF EXISTS radar_t1_evaluations")
        connection.execute("DROP TABLE IF EXISTS radar_t1_current")
        connection.execute("DROP TABLE IF EXISTS radar_t1_retry")
        connection.execute(
            "UPDATE jp_core_schema SET version=?, checksum=?, applied_at=? WHERE id=1",
            ("jp-core-v9", "old-checksum", utc_now_iso()),
        )
        connection.execute(
            "INSERT INTO securities (canonical_code, display_code, name_ja, market_code, as_of_date, updated_at) "
            "VALUES ('72030','7203','legacy','0111',?,?)",
            (SESSION_ISO, utc_now_iso()),
        )
        connection.commit()
    return path


def test_core_v9_to_v10_keeps_rows_and_is_idempotent(tmp_path):
    path = tmp_path / "jp-core.db"
    _legacy_v9_db(path)
    repo = CoreRepository(path)
    repo.initialize()
    assert repo.SCHEMA_VERSION == CORE_SCHEMA_VERSION
    with repo.read() as connection:
        version = connection.execute("SELECT version FROM jp_core_schema WHERE id=1").fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        security = connection.execute(
            "SELECT canonical_code FROM securities WHERE canonical_code='72030'"
        ).fetchone()
    assert version == "jp-core-v11"
    assert {"radar_t1_evaluations", "radar_t1_current", "radar_t1_retry", "radar_t1_anchors"} <= tables
    assert security[0] == "72030"
    repo.initialize()
    repo.persist_t1_evaluations(
        [{"event_id": "evt-mig", "t1_priority": {"status": T1_MET, "identity_hash": "x", "computed_at": "2026-03-16T09:00:00Z"}}]
    )


def test_core_v10_to_v11_keeps_t1_rows_and_adds_anchors(tmp_path):
    path = tmp_path / "jp-core.db"
    repo = CoreRepository(path)
    repo.initialize()
    repo.persist_t1_evaluations(
        [{"event_id": "evt-keep", "t1_priority": {"status": T1_MET, "identity_hash": "keep", "computed_at": "2026-03-16T09:00:00Z"}}]
    )
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE IF EXISTS radar_t1_anchors")
        connection.execute(
            "UPDATE jp_core_schema SET version=?, checksum=?, applied_at=? WHERE id=1",
            ("jp-core-v10", "old-checksum", utc_now_iso()),
        )
        connection.commit()
    again = CoreRepository(path)
    again.initialize()
    with again.read() as connection:
        version = connection.execute("SELECT version FROM jp_core_schema WHERE id=1").fetchone()[0]
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        kept = connection.execute("SELECT event_id FROM radar_t1_current WHERE event_id='evt-keep'").fetchone()
    assert version == "jp-core-v11"
    assert "radar_t1_anchors" in tables
    assert kept[0] == "evt-keep"


def test_app_v2_to_v3_adds_preferences(tmp_path):
    store = AppStore(tmp_path / "jp-app.db")
    store.initialize()
    with sqlite3.connect(tmp_path / "jp-app.db") as connection:
        connection.execute("DROP TABLE IF EXISTS view_preferences")
        connection.execute("DROP TABLE IF EXISTS algorithm_defaults")
        connection.execute(
            "UPDATE jp_app_schema SET version=?, checksum=? WHERE id=1",
            ("jp-app-v2", "old"),
        )
        connection.commit()
    again = AppStore(tmp_path / "jp-app.db")
    again.initialize()
    assert again.SCHEMA_VERSION == APP_SCHEMA_VERSION
    again.put_view_preferences("owner", screener_ranking_algorithm="follow_default", radar_sort_algorithm="follow_default")
    assert again.get_view_preferences("owner")["screener_ranking_algorithm"] == "follow_default"


def test_schema_guard_checksum_matches_current_ddl():
    from app.repositories.base import schema_checksum
    from tests.test_schema_version_guard import EXPECTED_CHECKSUM, EXPECTED_VERSION

    assert CORE_SCHEMA_VERSION == EXPECTED_VERSION
    assert schema_checksum(CORE_DDL) == EXPECTED_CHECKSUM
