"""Process settings for Optix Japan.

Secrets come from the environment (populated by ``secrets.env``); paths come
from :mod:`app.data_paths`; owner preferences from ``config/personal.toml``.
Secret values never appear in logs, reprs, or API responses — the settings
API may only report whether a key is configured.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.data_paths import DataPaths, get_data_paths
from app.providers.jquants.client import OFFICIAL_BASE_URL
from app.runtime_environment import load_runtime_environment

load_runtime_environment()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", frozen=True)

    APP_VERSION: str = "dev"
    APP_COMMIT: str = "unknown"

    JQUANTS_API_KEY: SecretStr = SecretStr("")
    JQUANTS_BASE_URL: str = OFFICIAL_BASE_URL

    OPENAI_API_KEY: SecretStr = SecretStr("")

    # Deployment boundary (validated by deployment_boundary at startup).
    ALLOWED_HOSTS: str = ""
    TRUST_PROXY_HEADERS: str = "false"
    TRUSTED_PROXY_CIDRS: str = ""
    HOST_BIND: str = "127.0.0.1"

    # Retired concepts from the reference project must fail loudly rather
    # than be silently ignored if an old env file is reused.
    MACROLENS_URL: str = ""
    FINNHUB_API_KEY: str = ""
    MASSIVE_API_KEY: str = ""

    JQUANTS_MAX_ATTEMPTS: int = Field(default=4, ge=1, le=8)
    JQUANTS_GLOBAL_PER_MINUTE: int = Field(default=100, ge=1, le=120)
    JQUANTS_FINS_PER_MINUTE: int = Field(default=50, ge=1, le=60)

    @model_validator(mode="after")
    def _reject_retired_environment(self) -> "Settings":
        retired = {
            "MACROLENS_URL": self.MACROLENS_URL,
            "FINNHUB_API_KEY": self.FINNHUB_API_KEY,
            "MASSIVE_API_KEY": self.MASSIVE_API_KEY,
        }
        configured = sorted(name for name, value in retired.items() if str(value).strip())
        if configured:
            raise RuntimeError(
                "retired environment keys from the US project are set and must be removed: "
                + ", ".join(configured)
            )
        return self

    def jquants_configured(self) -> bool:
        return bool(self.JQUANTS_API_KEY.get_secret_value().strip())

    def openai_configured(self) -> bool:
        return bool(self.OPENAI_API_KEY.get_secret_value().strip())

    @property
    def data_paths(self) -> DataPaths:
        return get_data_paths()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_for_tests() -> None:
    get_settings.cache_clear()


__all__ = ["Settings", "get_settings", "reset_settings_for_tests"]
