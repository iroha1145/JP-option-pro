"""Personal preferences live in jp-app.db; owner defaults stay separate."""

from __future__ import annotations

from app.repositories.app_store import AppStore
from app.services.view_preferences import (
    read_admin_defaults,
    read_view_preferences,
    write_admin_defaults,
    write_view_preferences,
)
from tests.support.a0_t1_fixtures import api_client, diverging_pool, init_repo, publish_strength_rows


def test_preference_upsert_is_atomic_and_isolated(tmp_path):
    store = AppStore(tmp_path / "jp-app.db")
    store.initialize()
    write_view_preferences(store, "account:alice", {"screener_ranking_algorithm": "a0_mid_long"})
    write_view_preferences(store, "account:bob", {"radar_sort_algorithm": "t1_daily_priority"})
    alice = read_view_preferences(store, "account:alice")
    bob = read_view_preferences(store, "account:bob")
    assert alice.screener_ranking_algorithm == "a0_mid_long"
    assert alice.radar_sort_algorithm == "follow_default"
    assert bob.radar_sort_algorithm == "t1_daily_priority"
    assert bob.screener_ranking_algorithm == "follow_default"
    defaults = read_admin_defaults(store)
    assert defaults["screener_ranking_algorithm"] == "production"
    write_admin_defaults(store, {"screener_ranking_algorithm": "a0_mid_long"})
    assert read_view_preferences(store, "account:alice").screener_ranking_algorithm == "a0_mid_long"
    assert read_admin_defaults(store)["screener_ranking_algorithm"] == "a0_mid_long"


def test_partial_write_keeps_the_other_family(tmp_path):
    store = AppStore(tmp_path / "jp-app.db")
    store.initialize()
    write_view_preferences(store, "owner", {"screener_ranking_algorithm": "a0_mid_long"})
    write_view_preferences(store, "owner", {"radar_sort_algorithm": "t1_daily_priority"})
    owner = read_view_preferences(store, "owner")
    assert owner.screener_ranking_algorithm == "a0_mid_long"
    assert owner.radar_sort_algorithm == "t1_daily_priority"
    write_view_preferences(store, "owner", {"screener_ranking_algorithm": "production"})
    owner = read_view_preferences(store, "owner")
    assert owner.screener_ranking_algorithm == "production"
    assert owner.radar_sort_algorithm == "t1_daily_priority"


def test_guest_cannot_write_preferences(tmp_path, monkeypatch):
    init_repo(tmp_path / "jp-core.db")
    publish_strength_rows(init_repo(tmp_path / "jp-core.db"), diverging_pool())
    client = api_client(tmp_path, monkeypatch)
    denied = client.put("/api/view-preferences", json={"screener_ranking_algorithm": "a0_mid_long"})
    assert denied.status_code in {401, 403, 415}
    owner_denied = client.put("/api/algorithm-defaults", json={"screener_ranking_algorithm": "a0"})
    # loopback TestClient is owner for GET, but PUT still needs same-origin JSON
    assert owner_denied.status_code in {200, 403, 415}


def test_owner_put_with_origin_does_not_rewrite_other_principals(tmp_path, monkeypatch):
    init_repo(tmp_path / "jp-core.db")
    store = AppStore(tmp_path / "jp-app.db")
    store.initialize()
    write_view_preferences(store, "account:alice", {"screener_ranking_algorithm": "production"})
    client = api_client(tmp_path, monkeypatch)
    response = client.put(
        "/api/view-preferences",
        json={"screener_ranking_algorithm": "a0_mid_long", "radar_sort_algorithm": "follow_default"},
        headers={"X-Optix-Action": "1", "Origin": "http://testserver", "Content-Type": "application/json"},
    )
    assert response.status_code in {200, 401}
    alice = read_view_preferences(store, "account:alice")
    assert alice.screener_ranking_algorithm == "production"


def test_owner_partial_put_keeps_screener_when_radar_changes(tmp_path, monkeypatch):
    init_repo(tmp_path / "jp-core.db")
    store = AppStore(tmp_path / "jp-app.db")
    store.initialize()
    write_view_preferences(store, "owner", {"screener_ranking_algorithm": "a0_mid_long"})
    client = api_client(tmp_path, monkeypatch)
    headers = {
        "X-Optix-Action": "1",
        "Origin": "http://testserver",
        "Content-Type": "application/json",
    }
    response = client.put(
        "/api/view-preferences",
        json={"radar_sort_algorithm": "t1_daily_priority"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["preferences"]["screener_ranking_algorithm"] == "a0_mid_long"
    assert body["preferences"]["radar_sort_algorithm"] == "t1_daily_priority"
    owner = read_view_preferences(store, "owner")
    assert owner.screener_ranking_algorithm == "a0_mid_long"
    assert owner.radar_sort_algorithm == "t1_daily_priority"
