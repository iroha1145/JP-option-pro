"""API プロセスのリポジトリ依存。

書き込み権限の境界をここで固定する: API は jp-core.db / jp-worker.db を
読み取り専用で開き、jp-app.db だけ書ける。
"""

from __future__ import annotations

from functools import lru_cache

from app.data_paths import get_data_paths
from app.repositories.app_store import AppStore
from app.repositories.core import CoreRepository
from app.worker.state import WorkerStateRepository


@lru_cache(maxsize=1)
def core_repository() -> CoreRepository:
    return CoreRepository(get_data_paths().core_db, read_only=True)


@lru_cache(maxsize=1)
def app_store() -> AppStore:
    paths = get_data_paths()
    store = AppStore(paths.app_db)
    if not store.exists():
        store.initialize()
    return store


@lru_cache(maxsize=1)
def worker_state_read() -> WorkerStateRepository:
    return WorkerStateRepository(get_data_paths().worker_db, read_only=True)


@lru_cache(maxsize=1)
def worker_state_write() -> WorkerStateRepository:
    # アクション投入だけは API から書く（旧プロジェクトと同じ二重ライタ領域）。
    return WorkerStateRepository(get_data_paths().worker_db)


def reset_dependencies_for_tests() -> None:
    core_repository.cache_clear()
    app_store.cache_clear()
    worker_state_read.cache_clear()
    worker_state_write.cache_clear()


__all__ = [
    "app_store",
    "core_repository",
    "reset_dependencies_for_tests",
    "worker_state_read",
    "worker_state_write",
]
