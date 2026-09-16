"""F2/F3: radar ETag is content-true; T1 sorts the full eligible set then paginates."""

from __future__ import annotations

from app.services.radar.t1_priority import T1_MET, T1_UNMET
from tests.support.a0_t1_fixtures import (
    api_client,
    diverging_pool,
    init_repo,
    insert_radar_event,
    insert_security,
    publish_strength_rows,
)


def _open(tmp_path, monkeypatch, *, events=1):
    repo = init_repo(tmp_path / "jp-core.db")
    publish_strength_rows(repo, diverging_pool())
    insert_security(repo, "72030")
    insert_security(repo, "67580")
    insert_security(repo, "99840")
    if events:
        insert_radar_event(repo, event_id="evt-cache", code="72030", priority=80)
    return repo, api_client(tmp_path, monkeypatch)


def _persist_t1(repo, event_id, status, **extra):
    payload = {
        "status": status,
        "identity_hash": extra.pop("identity_hash", f"hash-{event_id}-{status}"),
        "clv": 0.8,
        "rvol_daily_20med": 2.1,
        "upper_shadow_ratio": 0.1,
        "breakout_distance_atr": 2.4,
        "computed_at": "2026-03-16T09:00:00Z",
        "known_at": "2026-03-16T09:00:00Z",
        "eval_version": extra.pop("eval_version", 1),
    }
    payload.update(extra)
    repo.persist_t1_evaluations([{"event_id": event_id, "t1_priority": payload}])


def test_same_content_stays_304_priority_change_is_200(tmp_path, monkeypatch):
    repo, client = _open(tmp_path, monkeypatch)
    first = client.get("/api/radar/current", params={"sort_algorithm": "production", "limit": 20})
    assert first.status_code == 200
    etag = first.headers["etag"]
    assert first.json()["events"][0]["alert_priority"] == 80
    same = client.get(
        "/api/radar/current",
        params={"sort_algorithm": "production", "limit": 20},
        headers={"If-None-Match": etag},
    )
    assert same.status_code == 304
    repo.upsert_radar_events(
        [
            {
                **repo.radar_event("evt-cache"),
                "alert_priority": 35,
            }
        ]
    )
    changed = client.get(
        "/api/radar/current",
        params={"sort_algorithm": "production", "limit": 20},
        headers={"If-None-Match": etag},
    )
    assert changed.status_code == 200
    assert changed.json()["events"][0]["alert_priority"] == 35
    assert changed.headers["etag"] != etag


def test_short_filters_are_part_of_etag_identity(tmp_path, monkeypatch):
    _repo, client = _open(tmp_path, monkeypatch)
    base = client.get("/api/radar/current", params={"sort_algorithm": "production", "limit": 20})
    filtered = client.get(
        "/api/radar/current",
        params={"sort_algorithm": "production", "limit": 20, "short_states": "covering"},
    )
    assert base.status_code == 200
    assert filtered.status_code == 200
    assert base.headers["etag"] != filtered.headers["etag"]


def test_t1_state_change_breaks_etag(tmp_path, monkeypatch):
    repo, client = _open(tmp_path, monkeypatch)
    _persist_t1(repo, "evt-cache", T1_UNMET)
    first = client.get("/api/radar/current", params={"sort_algorithm": "t1", "limit": 20})
    etag = first.headers["etag"]
    _persist_t1(repo, "evt-cache", T1_MET, identity_hash="hash-evt-cache-met", eval_version=2)
    later = client.get(
        "/api/radar/current",
        params={"sort_algorithm": "t1", "limit": 20},
        headers={"If-None-Match": etag},
    )
    assert later.status_code == 200
    assert later.json()["events"][0]["t1_priority"]["status"] == T1_MET


def test_unique_met_outside_old_top_400_becomes_first_and_matched_is_real(tmp_path, monkeypatch):
    repo = init_repo(tmp_path / "jp-core.db")
    publish_strength_rows(repo, diverging_pool())
    codes = [f"{10000 + index}0" for index in range(400)] + ["72030"]
    existing = []
    with repo.read() as connection:
        existing = [dict(row) for row in connection.execute("SELECT * FROM securities WHERE active = 1")]
    by_code = {item["canonical_code"]: item for item in existing}
    for code in codes:
        by_code[code] = {
            "canonical_code": code,
            "name_ja": code,
            "market_code": "0111",
            "sector33_code": "3650",
            "sector33_name": "電気機器",
        }
    repo.replace_security_master(list(by_code.values()), as_of_date="2026-03-16")
    events = []
    payloads = []
    for index in range(400):
        code = codes[index]
        events.append({
            "event_id": f"E{index:03d}",
            "canonical_code": code,
            "signal_type": "base_breakout",
            "state": "triggered",
            "discovered_date": "2026-03-16",
            "pivot_price": 100,
            "trigger_price": 105,
            "state_changed_date": "2026-03-16",
            "last_scanned_date": "2026-03-16",
            "alert_priority": 900 - index,
            "scores": {"alert_priority": 900 - index},
            "features": {
                "t1_anchor": {
                    "event_id": f"E{index:03d}",
                    "session_date": "2026-03-16",
                    "resistance_high": 100,
                    "data_convention": "jp_adj_ohlcv_v1",
                    "version": 1,
                    "source": "first_publish",
                }
            },
        })
        payloads.append({
            "event_id": f"E{index:03d}",
            "t1_priority": {
                "status": T1_UNMET,
                "identity_hash": f"u-{index}",
                "clv": 0.8,
                "rvol_daily_20med": 2.1,
                "upper_shadow_ratio": 0.1,
                "breakout_distance_atr": 2.4,
                "computed_at": "2026-03-16T09:00:00Z",
                "known_at": "2026-03-16T09:00:00Z",
            },
        })
    events.append({
        "event_id": "E400",
        "canonical_code": "72030",
        "signal_type": "base_breakout",
        "state": "triggered",
        "discovered_date": "2026-03-16",
        "pivot_price": 100,
        "trigger_price": 105,
        "state_changed_date": "2026-03-16",
        "last_scanned_date": "2026-03-16",
        "alert_priority": 1,
        "scores": {"alert_priority": 1},
        "features": {
            "t1_anchor": {
                "event_id": "E400",
                "session_date": "2026-03-16",
                "resistance_high": 100,
                "data_convention": "jp_adj_ohlcv_v1",
                "version": 1,
                "source": "first_publish",
            }
        },
    })
    repo.upsert_radar_events(events)
    repo.save_t1_anchors(events)
    repo.persist_t1_evaluations(payloads)
    _persist_t1(repo, "E400", T1_MET, identity_hash="met-400")
    repo.record_sync_success("radar_scan", data_through="2026-03-16")
    client = api_client(tmp_path, monkeypatch)
    production = client.get("/api/radar/current", params={"sort_algorithm": "production", "limit": 20})
    t1 = client.get("/api/radar/current", params={"sort_algorithm": "t1", "limit": 20})
    assert production.status_code == 200
    assert t1.status_code == 200
    assert production.json()["events"][0]["event_id"] == "E000"
    assert production.json()["matched_count"] == 401
    assert t1.json()["matched_count"] == 401
    assert t1.json()["events"][0]["event_id"] == "E400"
    page_two = client.get("/api/radar/current", params={"sort_algorithm": "t1", "limit": 20, "offset": 20})
    assert page_two.json()["matched_count"] == 401
    assert page_two.json()["events"][0]["event_id"] != "E400"
    seen = {item["event_id"] for item in t1.json()["events"]} | {item["event_id"] for item in page_two.json()["events"]}
    assert "E400" in seen
    assert len(seen) == len(t1.json()["events"]) + len(page_two.json()["events"])


def test_zero_met_radar_order_equals_production(tmp_path, monkeypatch):
    repo, client = _open(tmp_path, monkeypatch, events=0)
    insert_radar_event(repo, event_id="A", code="72030", priority=90, discovered="2026-03-16")
    insert_radar_event(repo, event_id="B", code="67580", priority=80, discovered="2026-03-13")
    insert_radar_event(repo, event_id="C", code="99840", priority=70, discovered="2026-03-16")
    for event_id in ("A", "B", "C"):
        _persist_t1(repo, event_id, T1_UNMET, identity_hash=f"u-{event_id}")
    # last insert stamps scan_date to C's discovered date; force a shared scan day
    for event_id in ("A", "B", "C"):
        event = repo.radar_event(event_id)
        event["last_scanned_date"] = "2026-03-16"
        repo.upsert_radar_events([event])
    repo.record_sync_success("radar_scan", data_through="2026-03-16")
    production = client.get("/api/radar/current", params={"sort_algorithm": "production", "limit": 20})
    t1 = client.get("/api/radar/current", params={"sort_algorithm": "t1", "limit": 20})
    prod_ids = [item["event_id"] for item in production.json()["events"]]
    t1_ids = [item["event_id"] for item in t1.json()["events"]]
    assert prod_ids == t1_ids == ["A", "B", "C"]
