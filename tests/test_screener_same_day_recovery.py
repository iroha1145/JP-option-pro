"""Recover the ordinary screener after a same-day strength publication changes.

All scans and database writes use production paths. Only the interrupted
write/receipt boundary is injected; checking the date alone cannot detect
these cases because both the old and new publications have the same date.
"""

from types import SimpleNamespace

import pytest

from app.services.publication import OUTCOME_ALREADY_CURRENT, OUTCOME_PUBLISHED
from app.worker.tasks import _run_radar_and_screener
from tests.test_screener_freshness import _bar, _config, _seed


DAY = "2026-09-08"


def _context(repository):
    return SimpleNamespace(
        repository=repository,
        config=SimpleNamespace(
            features=SimpleNamespace(radar_enabled=True), radar=_config()
        ),
    )


def _screener_rows(repository):
    rows, total = repository.screener_query(
        where_sql="1=1", params=(), order_sql="canonical_code", limit=100, offset=0
    )
    assert total == len(rows)
    return rows


@pytest.mark.parametrize("interruption", ["write_error", "empty_write", "receipt_error"])
def test_same_day_corrected_publication_repairs_interrupted_screener(
    tmp_path, monkeypatch, interruption
):
    repo = _seed(tmp_path, ["67580", "72030"], DAY)
    context = _context(repo)
    first = _run_radar_and_screener(context, DAY)
    assert first["outcome"] == OUTCOME_PUBLISHED
    first_id = first["publication"]["publication_id"]
    old_rows = _screener_rows(repo)

    # A vendor correction revises this session, without advancing the date.
    repo.upsert_daily_bars([_bar("72030", DAY, 105.0)])
    with monkeypatch.context() as fault:
        if interruption == "receipt_error":
            original_receipt = repo.record_sync_success

            def receipt(dataset, **kwargs):
                if dataset == "screener_snapshot":
                    raise RuntimeError("interrupted after ordinary rows committed")
                return original_receipt(dataset, **kwargs)

            fault.setattr(repo, "record_sync_success", receipt)
            with pytest.raises(RuntimeError, match="after ordinary rows committed"):
                _run_radar_and_screener(context, DAY)
        else:
            def write(_rows):
                if interruption == "write_error":
                    raise RuntimeError("ordinary screener unavailable")
                return 0

            fault.setattr(repo, "replace_screener_rows", write)
            failed = _run_radar_and_screener(context, DAY)
            assert failed["outcome"] == OUTCOME_PUBLISHED
            assert failed["status"] == "error"
            assert failed["screener_outcome"] == "failed"
            assert _screener_rows(repo) == old_rows

    corrected_id = repo.strength_meta()["publication_id"]
    assert corrected_id != first_id
    assert repo.screener_trade_date() == DAY
    assert repo.sync_state("screener_snapshot")["data_through"] == DAY
    if interruption == "receipt_error":
        assert _screener_rows(repo)[1]["close"] == 105.0

    # Simulate restart: no in-memory success flag may hide the unfinished table.
    from app.repositories.core import CoreRepository

    restarted = CoreRepository(repo.db_path)
    recovered = _run_radar_and_screener(_context(restarted), DAY)
    assert recovered["outcome"] == OUTCOME_ALREADY_CURRENT
    assert recovered["publication"]["publication_id"] == corrected_id
    assert recovered["status"] == "ok"
    assert recovered["screener_outcome"] == OUTCOME_PUBLISHED
    assert _screener_rows(restarted)[1]["close"] == 105.0
    assert restarted.sync_state("screener_snapshot")["checkpoint"]["publication_id"] == corrected_id

    # A fully completed replay remains idempotent and does not rewrite the table.
    def unexpected_write(_rows):
        pytest.fail("an intact publication should not rewrite screener rows")

    monkeypatch.setattr(restarted, "replace_screener_rows", unexpected_write)
    unchanged = _run_radar_and_screener(_context(restarted), DAY)
    assert unchanged["status"] == "ok"
    assert unchanged["screener_outcome"] == OUTCOME_ALREADY_CURRENT


@pytest.mark.parametrize("checkpoint", [{}, {"publication_id": "pub_other_snapshot"}])
def test_same_date_without_matching_publication_receipt_is_repaired(
    tmp_path, checkpoint
):
    repo = _seed(tmp_path, ["72030"], DAY)
    context = _context(repo)
    first = _run_radar_and_screener(context, DAY)
    publication_id = first["publication"]["publication_id"]

    # Covers an existing pre-receipt database as well as another same-day snapshot.
    import json

    with repo.write() as connection:
        connection.execute("UPDATE screener_rows SET close=1")
        connection.execute(
            "UPDATE sync_state SET checkpoint_json=? WHERE dataset='screener_snapshot'",
            (json.dumps(checkpoint),),
        )

    recovered = _run_radar_and_screener(context, DAY)
    assert recovered["outcome"] == OUTCOME_ALREADY_CURRENT
    assert recovered["screener_outcome"] == OUTCOME_PUBLISHED
    assert recovered["publication"]["publication_id"] == publication_id
    assert _screener_rows(repo)[0]["close"] == 100.0
    assert repo.sync_state("screener_snapshot")["checkpoint"]["publication_id"] == publication_id
