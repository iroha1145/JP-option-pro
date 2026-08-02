"""Single-root filesystem layout for the Optix Japan runtime.

Write-ownership contract (enforced by connection mode, not convention):

- ``core_db``      — worker-only writer: securities master, trading calendar,
                     daily bars, indices, financial summaries, earnings
                     calendar, margin/short data, radar events, sync state.
- ``news_db``      — worker-only writer: news items, entity links,
                     translations (ja-JP) and impact analyses (zh-CN).
- ``ai_jobs_db``   — dual writer: API creates jobs, worker processes them.
- ``worker_db``    — dual writer: task status + owner action queue.
- ``app_db``       — API-only writer: watchlist, owner marks, runtime settings.
- ``snapshots``    — worker publishes atomic JSON documents, API reads them
                     through the fingerprinted file cache.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_DATA_DIR = Path("/data")


def _absolute_path(value: str | Path, *, name: str) -> Path:
    path = Path(value).expanduser()
    if str(value).startswith("file:") or not path.is_absolute() or ".." in path.parts:
        raise ValueError(
            f"{name} must be an absolute filesystem path without parent traversal"
        )
    return path


def data_dir(value: str | Path | None = None) -> Path:
    """Resolve the only runtime path setting without creating directories."""

    if value is None:
        raw = os.environ.get("DATA_DIR", "").strip()
        value = raw or DEFAULT_DATA_DIR
    return _absolute_path(value, name="DATA_DIR")


def explicit_data_path(value: str | Path, *, name: str) -> Path:
    """Validate a programmatic test override without making it an env setting."""

    return _absolute_path(value, name=name)


@dataclass(frozen=True)
class DataPaths:
    root: Path
    core_db: Path
    news_db: Path
    ai_jobs_db: Path
    worker_db: Path
    app_db: Path
    intraday_db: Path
    worker_lock: Path
    snapshots_dir: Path
    market_snapshot: Path
    radar_snapshot: Path
    screener_snapshot: Path
    watchlist_snapshot: Path
    backups_dir: Path
    runtime_settings: Path


def get_data_paths(value: str | Path | None = None) -> DataPaths:
    root = data_dir(value)
    snapshots = root / "snapshots"
    return DataPaths(
        root=root,
        core_db=root / "jp-core.db",
        news_db=root / "jp-news.db",
        ai_jobs_db=root / "jp-ai-jobs.db",
        worker_db=root / "jp-worker.db",
        app_db=root / "jp-app.db",
        intraday_db=root / "jp-intraday.db",
        worker_lock=root / "jp-worker.lock",
        snapshots_dir=snapshots,
        market_snapshot=snapshots / "market-snapshot-v1.json",
        radar_snapshot=snapshots / "radar-snapshot-v1.json",
        screener_snapshot=snapshots / "screener-snapshot-v1.json",
        watchlist_snapshot=snapshots / "watchlist-snapshot-v1.json",
        backups_dir=root / "backups",
        runtime_settings=root / "runtime-settings.json",
    )


__all__ = [
    "DEFAULT_DATA_DIR",
    "DataPaths",
    "data_dir",
    "explicit_data_path",
    "get_data_paths",
]
