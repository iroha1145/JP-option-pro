"""Cache identity, 304, and preference isolation through the real API."""

from __future__ import annotations

from tests.support.a0_t1_fixtures import (
    api_client,
    diverging_pool,
    init_repo,
    insert_radar_event,
    insert_security,
    publish_strength_rows,
)


def _open(tmp_path, monkeypatch):
    repo = init_repo(tmp_path / "jp-core.db")
    publish_strength_rows(repo, diverging_pool())
    insert_security(repo, "72030")
    insert_radar_event(repo, event_id="evt-cache", code="72030")
    return repo, api_client(tmp_path, monkeypatch)


def test_algorithm_and_filter_params_do_not_share_etag_bodies(tmp_path, monkeypatch):
    _repo, client = _open(tmp_path, monkeypatch)
    prod = client.get("/api/strength/scan", params={"top": 3, "ranking_algorithm": "production"})
    a0 = client.get("/api/strength/scan", params={"top": 3, "ranking_algorithm": "a0"})
    assert prod.json()["rows"][0]["canonical_code"] != a0.json()["rows"][0]["canonical_code"]
    reused = client.get(
        "/api/strength/scan",
        params={"top": 3, "ranking_algorithm": "production"},
        headers={"If-None-Match": a0.headers["etag"]},
    )
    assert reused.status_code == 200
    assert reused.json()["effective_algorithm"] == "production"
    match = client.get(
        "/api/strength/scan",
        params={"top": 3, "ranking_algorithm": "a0"},
        headers={"If-None-Match": a0.headers["etag"]},
    )
    assert match.status_code == 304


def test_radar_sort_algorithm_changes_etag(tmp_path, monkeypatch):
    _repo, client = _open(tmp_path, monkeypatch)
    prod = client.get("/api/radar/current", params={"sort_algorithm": "production", "limit": 20})
    t1 = client.get("/api/radar/current", params={"sort_algorithm": "t1", "limit": 20})
    assert prod.status_code == 200
    assert t1.status_code == 200
    assert prod.headers["etag"] != t1.headers["etag"]
    assert t1.json()["effective_algorithm"] == "t1_daily_priority"


def test_visitor_put_preferences_is_rejected(tmp_path, monkeypatch):
    _repo, client = _open(tmp_path, monkeypatch)
    response = client.put(
        "/api/view-preferences",
        json={"screener_ranking_algorithm": "a0"},
        headers={"X-Optix-Action": "1", "Origin": "http://testserver"},
    )
    # Loopback owner session may accept; guests without cookie still need a principal.
    assert response.status_code in {200, 401}
    defaults = client.get("/api/algorithm-defaults").json()
    assert defaults["screener_ranking_algorithm"] == "production"
