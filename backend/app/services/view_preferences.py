"""Per-principal view preferences stored in jp-app.db.

Owner personal choices never rewrite the global admin default. Writes are
a single UPSERT so a failed update cannot empty other principals.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.repositories.app_store import AppStore
from app.services.algorithm_modes import (
    FOLLOW_DEFAULT,
    PRODUCTION_ALGORITHM,
    canonicalize_radar_algorithm,
    canonicalize_screener_algorithm,
)


@dataclass(frozen=True)
class ViewPreferences:
    screener_ranking_algorithm: str = FOLLOW_DEFAULT
    radar_sort_algorithm: str = FOLLOW_DEFAULT

    def as_dict(self) -> dict[str, str]:
        return {
            "screener_ranking_algorithm": self.screener_ranking_algorithm,
            "radar_sort_algorithm": self.radar_sort_algorithm,
        }


def default_view_preferences() -> ViewPreferences:
    return ViewPreferences()


def _normalize_choice(family: str, value: Any) -> str:
    if family == "screener":
        parsed = canonicalize_screener_algorithm(value, allow_follow=True)
    else:
        parsed = canonicalize_radar_algorithm(value, allow_follow=True)
    return parsed or FOLLOW_DEFAULT


def normalize_view_preferences(value: Any) -> ViewPreferences:
    payload = value if isinstance(value, dict) else {}
    return ViewPreferences(
        screener_ranking_algorithm=_normalize_choice(
            "screener",
            payload.get("screener_ranking_algorithm"),
        ),
        radar_sort_algorithm=_normalize_choice(
            "radar",
            payload.get("radar_sort_algorithm"),
        ),
    )


def read_view_preferences(store: AppStore, principal: str) -> ViewPreferences:
    raw = store.get_view_preferences(principal)
    if raw is None:
        return default_view_preferences()
    return normalize_view_preferences(raw)


def write_view_preferences(store: AppStore, principal: str, value: Any) -> ViewPreferences:
    payload = value if isinstance(value, dict) else {}
    current = read_view_preferences(store, principal)
    merged = {
        "screener_ranking_algorithm": (
            payload["screener_ranking_algorithm"]
            if "screener_ranking_algorithm" in payload
            else current.screener_ranking_algorithm
        ),
        "radar_sort_algorithm": (
            payload["radar_sort_algorithm"]
            if "radar_sort_algorithm" in payload
            else current.radar_sort_algorithm
        ),
    }
    prefs = normalize_view_preferences(merged)
    store.put_view_preferences(
        principal,
        screener_ranking_algorithm=prefs.screener_ranking_algorithm,
        radar_sort_algorithm=prefs.radar_sort_algorithm,
    )
    return prefs


def read_admin_defaults(store: AppStore) -> dict[str, str]:
    raw = store.get_algorithm_defaults()
    screener = canonicalize_screener_algorithm(raw.get("screener_ranking_algorithm")) or PRODUCTION_ALGORITHM
    radar = canonicalize_radar_algorithm(raw.get("radar_sort_algorithm")) or PRODUCTION_ALGORITHM
    return {
        "screener_ranking_algorithm": screener,
        "radar_sort_algorithm": radar,
        "updated_at": raw.get("updated_at"),
    }


def write_admin_defaults(store: AppStore, value: Any) -> dict[str, str]:
    payload = value if isinstance(value, dict) else {}
    screener = canonicalize_screener_algorithm(payload.get("screener_ranking_algorithm")) or PRODUCTION_ALGORITHM
    radar = canonicalize_radar_algorithm(payload.get("radar_sort_algorithm")) or PRODUCTION_ALGORITHM
    return store.put_algorithm_defaults(
        screener_ranking_algorithm=screener,
        radar_sort_algorithm=radar,
    )


def preference_principal(kind: str, user_id: str | None) -> str | None:
    if kind == "account" and user_id:
        return f"account:{user_id}"
    if kind == "owner":
        return "owner"
    return None
