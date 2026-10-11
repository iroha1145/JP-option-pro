"""Owner-editable configuration from ``config/personal.toml``.

Access settings remain strict; retired or unknown feature settings are
ignored with a field-name warning. Values still receive type/range validation.
"""

from __future__ import annotations

import logging
import os
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from app.runtime_environment import REPOSITORY_ROOT

PERSONAL_CONFIG_PATH = REPOSITORY_ROOT / "config" / "personal.toml"


def resolved_personal_config_path() -> Path:
    """本番はイメージ内の既定 toml を差し替えず、環境変数で別ファイルを指す。

    ``PERSONAL_CONFIG_PATH``（例: /data/personal.toml）が設定されていれば
    それを使う。読み込みは従来通り fail-closed（未知キーで起動失敗）。"""

    raw = os.environ.get("PERSONAL_CONFIG_PATH", "").strip()
    return Path(raw) if raw else PERSONAL_CONFIG_PATH


class StrictConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FlexibleConfigModel(StrictConfigModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    @model_validator(mode="before")
    @classmethod
    def _warn_unknown_fields(cls, value):
        if isinstance(value, dict):
            known = set(cls.model_fields)
            for field in cls.model_fields.values():
                alias = field.validation_alias
                if isinstance(alias, AliasChoices):
                    known.update(alias.choices)
            for name in sorted(set(value) - known):
                logging.getLogger(__name__).warning("Ignoring unknown %s field: %s", cls.__name__, name)
        return value


class AccessConfig(StrictConfigModel):
    mode: Literal["private_network", "password"] = "private_network"
    allowed_private_cidrs: tuple[str, ...] = (
        "127.0.0.0/8",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "::1/128",
    )


class FeatureConfig(FlexibleConfigModel):
    radar_enabled: bool = True
    news_mode: Literal["off", "read"] = "off"
    # 遅延ザラ場気配（Yahoo・非公式）。表示専用でスコアには一切入らない。
    intraday_quotes: bool = True

    @model_validator(mode="before")
    @classmethod
    def _normalize_retired_schedule(cls, value):
        if isinstance(value, dict) and value.get("news_mode") == "scheduled":
            return {**value, "news_mode": "read"}
        return value


class SyncConfig(FlexibleConfigModel):
    # 歴史回填の年数（Standard は最大 10 年）
    backfill_years: int = Field(default=10, ge=1, le=10)
    # 引け後バッチの起動時刻（JST, "HH:MM"）。公式更新 ~16:30 の後。
    daily_batch_time_jst: str = "17:00"
    # 財務速報バッチ（開示 18:00 の後）と確報補完（~24:30 の後 → 翌 01:10）
    fins_evening_time_jst: str = "18:40"
    fins_late_time_jst: str = "01:10"
    request_timeout_seconds: int = Field(default=30, ge=5, le=120)


class RadarConfig(FlexibleConfigModel):
    enabled: bool = True
    # 対象市場（プライム/スタンダード/グロース）
    market_codes: tuple[str, ...] = ("0111", "0112", "0113")
    # 流動性フロア: 20日平均売買代金（円）
    min_avg_turnover_jpy: float = Field(default=100_000_000.0, ge=0.0)
    # 上場からの最低営業日数
    min_listed_days: int = Field(default=120, ge=20, le=1000)
    lookback_days: int = Field(default=320, ge=120, le=520)
    # 未確認イベントの寿命。**営業日**で数える（暦日 40 日 ≒ 営業日 28 日で、
    # 従来と同じ「観測回数」になるように既定値を移した）。連休で老化しない。
    # 旧キー `expiry_days` は本番 toml に残っているので別名で受ける。
    expiry_trading_days: int = Field(
        default=28, ge=5, le=200,
        validation_alias=AliasChoices("expiry_trading_days", "expiry_days"),
    )
    # 1 スキャンで **新規に作る** イベント数の上限（優先度順に採用）。
    # 既存イベントの更新・保存済みイベント総数・API の返却件数は別物。
    max_new_events_per_scan: int = Field(
        default=400, ge=50, le=2000,
        validation_alias=AliasChoices("max_new_events_per_scan", "max_events_per_scan"),
    )


class NewsConfig(FlexibleConfigModel):
    sync_seconds: int = Field(default=900, ge=120, le=86400)
    window_hours: int = Field(default=72, ge=24, le=336)

    @model_validator(mode="before")
    @classmethod
    def _ignore_retired_limit(cls, value):
        if isinstance(value, dict):
            return {key: item for key, item in value.items() if key != "max_ai_items_per_run"}
        return value

    # RSS/Atom フィード（日本株関連のみを実体マッチで残す）
    feed_urls: tuple[str, ...] = ()


class StorageConfig(FlexibleConfigModel):
    backup_keep: int = Field(default=7, ge=1, le=60)
    news_retention_days: int = Field(default=30, ge=8, le=365)


class PersonalConfig(StrictConfigModel):
    access: AccessConfig = AccessConfig()
    features: FeatureConfig = FeatureConfig()
    sync: SyncConfig = SyncConfig()
    radar: RadarConfig = RadarConfig()
    news: NewsConfig = NewsConfig()
    storage: StorageConfig = StorageConfig()

    @model_validator(mode="before")
    @classmethod
    def _ignore_retired_model_config(cls, value):
        # Existing owner files remain usable; old paid-request settings are inert.
        if isinstance(value, dict):
            return {key: item for key, item in value.items() if key != "ai"}
        return value


def load_personal_config(path: Path | None = None) -> PersonalConfig:
    config_path = path or resolved_personal_config_path()
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
