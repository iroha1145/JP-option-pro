"""Owner-editable configuration from ``config/personal.toml``.

Strict models: unknown keys are rejected so a typo fails at startup instead
of silently doing nothing. Values that changing would break paid-request
dedup or the deployment boundary are pinned with ``Literal``.
"""

from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.runtime_environment import REPOSITORY_ROOT

PERSONAL_CONFIG_PATH = REPOSITORY_ROOT / "config" / "personal.toml"


class StrictConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AccessConfig(StrictConfigModel):
    mode: Literal["private_network", "password"] = "private_network"
    allowed_private_cidrs: tuple[str, ...] = (
        "127.0.0.0/8",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "::1/128",
    )


class FeatureConfig(StrictConfigModel):
    radar_enabled: bool = True
    news_mode: Literal["off", "read", "scheduled"] = "off"


class AIConfig(StrictConfigModel):
    # Pinned: the AI job dedup hash folds model+reasoning in; a config-level
    # change would silently orphan every cached result.
    model: Literal["gpt-5.6-terra"] = "gpt-5.6-terra"
    reasoning: Literal["max"] = "max"
    execution_mode: Literal["background"] = "background"
    max_concurrency: Literal[1] = 1
    daily_token_limit: int = Field(default=8_000_000, ge=100_000, le=50_000_000)
    cooldown_seconds: int = Field(default=20, ge=0, le=3600)
    max_queued: int = Field(default=200, ge=10, le=2000)


class SyncConfig(StrictConfigModel):
    # 歴史回填の年数（Standard は最大 10 年）
    backfill_years: int = Field(default=10, ge=1, le=10)
    # 引け後バッチの起動時刻（JST, "HH:MM"）。公式更新 ~16:30 の後。
    daily_batch_time_jst: str = "17:00"
    # 財務速報バッチ（開示 18:00 の後）と確報補完（~24:30 の後 → 翌 01:10）
    fins_evening_time_jst: str = "18:40"
    fins_late_time_jst: str = "01:10"
    # 週次: 信用残（第2営業日 16:30 の後）
    margin_weekly_time_jst: str = "17:40"
    request_timeout_seconds: int = Field(default=30, ge=5, le=120)


class RadarConfig(StrictConfigModel):
    enabled: bool = True
    # 対象市場（プライム/スタンダード/グロース）
    market_codes: tuple[str, ...] = ("0111", "0112", "0113")
    # 流動性フロア: 20日平均売買代金（円）
    min_avg_turnover_jpy: float = Field(default=100_000_000.0, ge=0.0)
    # 上場からの最低営業日数
    min_listed_days: int = Field(default=120, ge=20, le=1000)
    lookback_days: int = Field(default=320, ge=120, le=520)
    expiry_days: int = Field(default=40, ge=5, le=200)
    max_events_per_scan: int = Field(default=400, ge=50, le=2000)


class NewsConfig(StrictConfigModel):
    sync_seconds: int = Field(default=900, ge=120, le=86400)
    window_hours: int = Field(default=72, ge=24, le=336)
    max_ai_items_per_run: int = Field(default=12, ge=1, le=50)
    # RSS/Atom フィード（日本株関連のみを実体マッチで残す）
    feed_urls: tuple[str, ...] = ()


class StorageConfig(StrictConfigModel):
    backup_keep: int = Field(default=7, ge=1, le=60)
    news_retention_days: int = Field(default=30, ge=8, le=365)


class PersonalConfig(StrictConfigModel):
    access: AccessConfig = AccessConfig()
    features: FeatureConfig = FeatureConfig()
    ai: AIConfig = AIConfig()
    sync: SyncConfig = SyncConfig()
    radar: RadarConfig = RadarConfig()
    news: NewsConfig = NewsConfig()
    storage: StorageConfig = StorageConfig()


def load_personal_config(path: Path | None = None) -> PersonalConfig:
    config_path = path or PERSONAL_CONFIG_PATH
    if not config_path.is_file():
        return PersonalConfig()
    with config_path.open("rb") as handle:
        data = tomllib.load(handle)
    return PersonalConfig.model_validate(data)


@lru_cache(maxsize=1)
def get_personal_config() -> PersonalConfig:
    return load_personal_config()


def reset_personal_config_for_tests() -> None:
    get_personal_config.cache_clear()


__all__ = [
    "AIConfig",
    "AccessConfig",
    "FeatureConfig",
    "NewsConfig",
    "PERSONAL_CONFIG_PATH",
    "PersonalConfig",
    "RadarConfig",
    "StorageConfig",
    "SyncConfig",
    "get_personal_config",
    "load_personal_config",
    "reset_personal_config_for_tests",
]
