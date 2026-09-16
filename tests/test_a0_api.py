"""Real FastAPI A0 ranking against a saved publication. No mock scan body."""

from __future__ import annotations

from tests.support.a0_t1_fixtures import (
    A0_ALGORITHM,
    PRODUCTION_ALGORITHM,
    api_client,
    diverging_pool,
    init_repo,
    publish_strength_rows,
    strength_row,
)


def _open(tmp_path, monkeypatch, rows=None):
    repo = init_repo(tmp_path / "jp-core.db")
    publish_strength_rows(repo, rows or diverging_pool())
    client = api_client(tmp_path, monkeypatch)
    return repo, client


def test_a0_api_changes_champion_and_does_not_pollute_original(tmp_path, monkeypatch):
    _repo, client = _open(tmp_path, monkeypatch)
    original = client.get("/api/strength/scan", params={"top": 5, "ranking_algorithm": "production"})
    assert original.status_code == 200
    prod = original.json()
    assert prod["effective_algorithm"] == PRODUCTION_ALGORITHM
    assert prod["a0_status"] is None
    assert prod["rows"][0]["canonical_code"] == "72030"

    a0 = client.get("/api/strength/scan", params={"top": 5, "ranking_algorithm": "a0"}).json()
    assert a0["effective_algorithm"] == A0_ALGORITHM
    assert a0["a0_status"] == "active"
    assert a0["algorithm_version"] == "jp-a0-mid-long-v1"
    assert a0["rows"][0]["canonical_code"] == "99840"
    assert a0["rows"][0]["a0_score"] == 95.0
    assert a0["publication_id"] == prod["publication_id"]

    again = client.get("/api/strength/scan", params={"top": 5, "ranking_algorithm": "production"}).json()
    assert [row["canonical_code"] for row in again["rows"]] == [
        row["canonical_code"] for row in prod["rows"]
    ]
    assert again["rows"][0]["ranking_score"] == prod["rows"][0]["ranking_score"]


def test_a0_filters_full_pool_before_top_n(tmp_path, monkeypatch):
    _repo, client = _open(tmp_path, monkeypatch)
    prod = client.get("/api/strength/scan", params={"top": 2, "ranking_algorithm": "production"}).json()
    assert [row["canonical_code"] for row in prod["rows"]] == ["72030", "67580"]

    a0 = client.get(
        "/api/strength/scan",
        params={"top": 2, "max_price": 900, "ranking_algorithm": A0_ALGORITHM},
    ).json()
    codes = [row["canonical_code"] for row in a0["rows"]]
    assert "72030" not in codes
    assert codes[0] == "99840"
    assert a0["screened_count"] >= a0["matched_count"] >= 2


def test_a0_all_missing_is_not_labeled_active(tmp_path, monkeypatch):
    rows = [
        strength_row("11110", intrinsic=90, mid=None, long=None),
        strength_row("22220", intrinsic=80, mid=None, long=float("nan")),
    ]
    _repo, client = _open(tmp_path, monkeypatch, rows=rows)
    body = client.get("/api/strength/scan", params={"top": 10, "ranking_algorithm": "a0"}).json()
    assert body["effective_algorithm"] == A0_ALGORITHM
    assert body["a0_status"] == "a0_scores_unavailable"
    assert all(row["a0_available"] is False for row in body["rows"])


def test_a0_unsupported_combo_is_structured_error(tmp_path, monkeypatch):
    _repo, client = _open(tmp_path, monkeypatch)
    response = client.get(
        "/api/strength/scan",
        params={"timeframe": "mid", "profile": "balanced", "ranking_algorithm": "a0_mid_long"},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "algorithm_view_conflict"


def test_unknown_algorithm_is_structured_error(tmp_path, monkeypatch):
    _repo, client = _open(tmp_path, monkeypatch)
    response = client.get("/api/strength/scan", params={"ranking_algorithm": "c0_soft_sat"})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "unknown_algorithm"


def test_etag_differs_across_algorithm_and_max_price(tmp_path, monkeypatch):
    _repo, client = _open(tmp_path, monkeypatch)
    prod = client.get("/api/strength/scan", params={"top": 5, "ranking_algorithm": "production"})
    a0 = client.get("/api/strength/scan", params={"top": 5, "ranking_algorithm": "a0"})
    priced = client.get(
        "/api/strength/scan",
        params={"top": 5, "max_price": 900, "ranking_algorithm": "a0"},
    )
    assert prod.headers["etag"] != a0.headers["etag"]
    assert a0.headers["etag"] != priced.headers["etag"]
    cached = client.get(
        "/api/strength/scan",
        params={"top": 5, "ranking_algorithm": "a0"},
        headers={"If-None-Match": a0.headers["etag"]},
    )
    assert cached.status_code == 304


def test_profiles_advertise_optional_a0(tmp_path, monkeypatch):
    _repo, client = _open(tmp_path, monkeypatch)
    body = client.get("/api/strength/profiles").json()
    ids = [item["id"] for item in body["algorithms"]]
    assert ids == ["production", "a0_mid_long"]
    assert body["algorithms"][0]["default"] is True
    assert body["algorithms"][1]["default"] is False
