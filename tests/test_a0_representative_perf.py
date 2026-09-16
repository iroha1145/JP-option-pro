"""Representative-pool A0/T1 timings. Not a 17-name 6ms toy."""

from __future__ import annotations

import json
import time
from pathlib import Path

from tests.support.a0_t1_fixtures import (
    api_client,
    init_repo,
    insert_radar_event,
    publish_strength_rows,
    strength_row,
)


def _large_pool(count: int = 400) -> list[dict]:
    rows = []
    for index in range(count):
        code = f"{1000 + index:04d}0"
        intrinsic = 90.0 - (index % 80)
        mid = 20.0 + (index % 70)
        long = 25.0 + ((index * 3) % 65)
        rows.append(strength_row(code, intrinsic=intrinsic, mid=mid, long=long, close=800 + index))
    rows[0] = strength_row("72030", intrinsic=99.0, mid=10.0, long=10.0, close=2000.0)
    rows[1] = strength_row("99840", intrinsic=11.0, mid=98.0, long=97.0, close=800.0)
    return rows


def test_representative_pool_champions_differ_and_records_timings(tmp_path, monkeypatch):
    repo = init_repo(tmp_path / "jp-core.db")
    rows = _large_pool(400)
    publish_strength_rows(repo, rows)
    for index in range(80):
        insert_radar_event(
            repo,
            event_id=f"evt-{index:03d}",
            code=rows[index]["canonical_code"],
            priority=80 - (index % 40),
        )
    client = api_client(tmp_path, monkeypatch)

    def timed(path, params):
        started = time.perf_counter()
        response = client.get(path, params=params)
        elapsed = (time.perf_counter() - started) * 1000
        assert response.status_code == 200
        return response.json(), elapsed

    cold_prod, cold_prod_ms = timed("/api/strength/scan", {"top": 50, "ranking_algorithm": "production"})
    cold_a0, cold_a0_ms = timed("/api/strength/scan", {"top": 50, "ranking_algorithm": "a0"})
    hot_a0, hot_a0_ms = timed("/api/strength/scan", {"top": 50, "ranking_algorithm": "a0"})
    radar_prod, radar_prod_ms = timed("/api/radar/current", {"sort_algorithm": "production", "limit": 40})
    radar_t1, radar_t1_ms = timed("/api/radar/current", {"sort_algorithm": "t1", "limit": 40})

    assert cold_prod["rows"][0]["canonical_code"] != cold_a0["rows"][0]["canonical_code"]
    assert cold_a0["effective_algorithm"] == "a0_mid_long"
    assert cold_prod["matched_count"] == 400
    assert radar_prod["matched_count"] == 80
    assert radar_t1["matched_count"] == 80

    payload = {
        "pool": 400,
        "radar_events": 80,
        "strength_production_cold_ms": round(cold_prod_ms, 3),
        "strength_a0_cold_ms": round(cold_a0_ms, 3),
        "strength_a0_hot_ms": round(hot_a0_ms, 3),
        "radar_production_ms": round(radar_prod_ms, 3),
        "radar_t1_ms": round(radar_t1_ms, 3),
        "production_champion": cold_prod["rows"][0]["canonical_code"],
        "a0_champion": cold_a0["rows"][0]["canonical_code"],
    }
    artifacts = Path("/opt/cursor/artifacts")
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "a0-t1-representative-perf.json").write_text(json.dumps(payload, indent=2))
    assert cold_a0_ms < 2500
    assert radar_t1_ms < 2500
