"""Completed tasks retain full diagnostics, including market-wide input lists."""

import json

import pytest

from app.worker.state import WorkerStateRepository


@pytest.mark.parametrize("input_count", [0, 2, 4000])
def test_task_and_action_details_round_trip(tmp_path, input_count):
    repository = WorkerStateRepository(tmp_path / "worker.db")
    repository.initialize()
    token = repository.acquire_lease("worker")
    diagnostics = {
        "valid_inputs": [
            {
                "canonical_code": f"{10000 + index}",
                "trade_date": "2026-10-09",
                "source": "日线行情",
                "rows": 320,
            }
            for index in range(input_count)
        ],
        "summary": {"accepted": input_count, "rejected": 0},
        "last_detail": "完整结尾",
    } if input_count else None
    expected = diagnostics or {}
    if input_count == 4000:
        assert len(json.dumps(expected, ensure_ascii=False)) > 16384

    repository.record_task("worker", token, "post_close", status="running")
    action = repository.request_action("post_close_batch", idempotency_key="roundtrip")
    claimed = repository.claim_next_action("worker", token)
    assert claimed["action_id"] == action["action_id"]
    repository.record_task(
        "worker", token, "post_close", status="completed", success=True,
        details=diagnostics,
    )
    repository.complete_action(
        "worker", token, action["action_id"], status="completed", result=diagnostics,
    )

    with repository.read() as connection:
        task_json = connection.execute(
            "SELECT details_json FROM worker_task_status WHERE task_name = 'post_close'"
        ).fetchone()[0]
        action_json = connection.execute(
            "SELECT result_json FROM worker_action_requests WHERE action_id = ?",
            (action["action_id"],),
        ).fetchone()[0]
    # Read the actual stored JSON as well as the forgiving public accessors:
    # neither truncation nor their invalid-JSON fallback may hide a loss.
    assert json.loads(task_json) == expected
    assert json.loads(action_json) == expected
    task = repository.task_statuses()[0]
    result = repository.get_action(action["action_id"])
    assert task["details"] == expected
    assert result["result"] == expected
    assert task["status"] == result["status"] == "completed"
    assert task["error_code"] is result["error_code"] is None
    assert task["consecutive_failures"] == 0
    assert task["last_completed_at"] and result["completed_at"]
