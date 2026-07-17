from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = Field(default="stock-center", alias="APP_NAME")
    app_env: str = Field(default="local", alias="APP_ENV")
    database_url: str = Field(alias="DATABASE_URL")
    database_pool_size: int = Field(default=10, alias="DATABASE_POOL_SIZE")
    database_max_overflow: int = Field(default=20, alias="DATABASE_MAX_OVERFLOW")
    database_pool_timeout_seconds: int = Field(default=30, alias="DATABASE_POOL_TIMEOUT_SECONDS")
    database_pool_recycle_seconds: int = Field(default=1800, alias="DATABASE_POOL_RECYCLE_SECONDS")
    database_echo_pool: bool = Field(default=False, alias="DATABASE_ECHO_POOL")
    database_connect_timeout_seconds: int = Field(default=10, alias="DATABASE_CONNECT_TIMEOUT_SECONDS")
    database_ssl: Literal["auto", "disable", "require"] = Field(default="auto", alias="DATABASE_SSL")
    config_master_key: str = Field(default="", alias="CONFIG_MASTER_KEY")
    config_cache_ttl_seconds: int = Field(default=60, alias="CONFIG_CACHE_TTL_SECONDS")
    redis_url: str = Field(default="", alias="REDIS_URL")
    cache_backend: Literal["auto", "redis", "memory"] = Field(default="auto", alias="CACHE_BACKEND")
    redis_key_prefix: str = Field(default="stock-center", alias="REDIS_KEY_PREFIX")
    redis_socket_timeout_seconds: float = Field(default=3.0, alias="REDIS_SOCKET_TIMEOUT_SECONDS")
    data_asset_cache_enabled: bool = Field(default=True, alias="DATA_ASSET_CACHE_ENABLED")
    data_asset_cache_ttl_seconds: int = Field(default=1800, alias="DATA_ASSET_CACHE_TTL_SECONDS")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    skill_root: str = Field(default="./resources/skills", alias="SKILL_ROOT")
    skill_output_dir: str = Field(default="./data/skill_outputs", alias="SKILL_OUTPUT_DIR")
    skill_default_timeout_seconds: int = Field(default=60, alias="SKILL_DEFAULT_TIMEOUT_SECONDS")
    scheduler_enabled: bool = Field(default=False, alias="SCHEDULER_ENABLED")
    scheduler_max_concurrent_jobs: int = Field(default=2, alias="SCHEDULER_MAX_CONCURRENT_JOBS")
    market_data_no_proxy_domains: str = Field(
        default=(
            "eastmoney.com,.eastmoney.com,"
            "10jqka.com.cn,.10jqka.com.cn,"
            "iwencai.com,.iwencai.com,"
            "sina.com.cn,.sina.com.cn,"
            "tdx.com.cn,.tdx.com.cn,"
            "tushare.pro,.tushare.pro"
        ),
        alias="MARKET_DATA_NO_PROXY_DOMAINS",
    )
    cors_allow_origins: str = Field(
        default="http://127.0.0.1:8080,http://localhost:8080",
        alias="CORS_ALLOW_ORIGINS",
    )

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]

    @property
    def market_data_no_proxy_list(self) -> list[str]:
        return [domain.strip() for domain in self.market_data_no_proxy_domains.split(",") if domain.strip()]

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
