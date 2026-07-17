from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import time
from typing import Any

from app.core.config import get_settings


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RedisRuntimeConfig:
    redis_url: str
    cache_backend: str
    redis_key_prefix: str
    redis_socket_timeout_seconds: float
    data_asset_cache_enabled: bool
    data_asset_cache_ttl_seconds: int
    default_cache_ttl_seconds: int
    data_asset_summary_ttl_seconds: int
    data_asset_daily_health_ttl_seconds: int
    source: str

    def ttl_for(self, snapshot_key: str) -> int:
        if snapshot_key == "summary":
            return self.data_asset_summary_ttl_seconds
        if snapshot_key == "daily_health" or snapshot_key.startswith("daily_health:"):
            return self.data_asset_daily_health_ttl_seconds
        return self.default_cache_ttl_seconds


class RedisClient:
    def __init__(self) -> None:
        self._client: Any | None = None
        self._client_signature: tuple[str, float] | None = None
        self._available = True
        self._runtime_config: RedisRuntimeConfig | None = None
        self._runtime_config_expires_at = 0.0
        self._memory_cache: dict[str, tuple[float, dict | list]] = {}

    async def runtime_config(self) -> RedisRuntimeConfig:
        now = time.time()
        if self._runtime_config and self._runtime_config_expires_at > now:
            return self._runtime_config
        settings = get_settings()
        config = RedisRuntimeConfig(
            redis_url=settings.redis_url,
            cache_backend=settings.cache_backend,
            redis_key_prefix=settings.redis_key_prefix,
            redis_socket_timeout_seconds=settings.redis_socket_timeout_seconds,
            data_asset_cache_enabled=settings.data_asset_cache_enabled,
            data_asset_cache_ttl_seconds=settings.data_asset_cache_ttl_seconds,
            default_cache_ttl_seconds=settings.data_asset_cache_ttl_seconds,
            data_asset_summary_ttl_seconds=settings.data_asset_cache_ttl_seconds,
            data_asset_daily_health_ttl_seconds=settings.data_asset_cache_ttl_seconds,
            source="env",
        )
        db_config = await self._load_config_center_runtime_config()
        if db_config is not None:
            config = db_config
        self._runtime_config = config
        self._runtime_config_expires_at = now + max(5, settings.config_cache_ttl_seconds)
        return config

    async def get_json(self, key: str) -> dict | list | None:
        client = await self._get_client()
        if client is None:
            return self._memory_get(key)
        try:
            value = await client.get(key)
            if value is None:
                return None
            if isinstance(value, bytes):
                value = value.decode("utf-8")
            return json.loads(value)
        except Exception as exc:
            logger.warning("redis get_json failed: key=%s error=%s", key, exc)
            return self._memory_get(key)

    async def set_json(self, key: str, value: dict | list, *, ttl_seconds: int) -> bool:
        client = await self._get_client()
        if client is None:
            self._memory_set(key, value, ttl_seconds=ttl_seconds)
            return True
        try:
            await client.set(key, json.dumps(value, ensure_ascii=False), ex=max(1, ttl_seconds))
            return True
        except Exception as exc:
            logger.warning("redis set_json failed: key=%s error=%s", key, exc)
            self._memory_set(key, value, ttl_seconds=ttl_seconds)
            return True

    async def ttl(self, key: str) -> int | None:
        client = await self._get_client()
        if client is None:
            return self._memory_ttl(key)
        try:
            return int(await client.ttl(key))
        except Exception as exc:
            logger.warning("redis ttl failed: key=%s error=%s", key, exc)
            return self._memory_ttl(key)

    async def ping(self) -> bool:
        client = await self._get_client()
        if client is None:
            return True
        try:
            return bool(await client.ping())
        except Exception as exc:
            logger.warning("redis ping failed: %s", exc)
            return False

    async def test_url(self, redis_url: str, *, timeout_seconds: float | None = None) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            from redis import asyncio as redis_asyncio
        except ImportError as exc:
            return {
                "available": False,
                "error": "redis package is not installed",
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "error_type": type(exc).__name__,
            }
        settings = get_settings()
        timeout = timeout_seconds or settings.redis_socket_timeout_seconds
        try:
            client = redis_asyncio.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=False,
                socket_timeout=timeout,
                socket_connect_timeout=timeout,
            )
        except Exception as exc:
            return {
                "available": False,
                "error": str(exc),
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "error_type": type(exc).__name__,
            }
        try:
            pong = await client.ping()
            return {
                "available": bool(pong),
                "error": None,
                "latency_ms": int((time.perf_counter() - started) * 1000),
            }
        except Exception as exc:
            return {
                "available": False,
                "error": str(exc),
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "error_type": type(exc).__name__,
            }
        finally:
            await client.aclose()

    async def close(self) -> None:
        if self._client is None:
            return
        try:
            await self._client.aclose()
        except Exception:
            logger.exception("redis close failed")
        finally:
            self._client = None
            self._client_signature = None

    async def key(self, *parts: str) -> str:
        config = await self.runtime_config()
        cleaned = [str(part).strip(":") for part in parts if str(part).strip(":")]
        return ":".join([config.redis_key_prefix.strip(":"), *cleaned])

    async def _get_client(self) -> Any | None:
        config = await self.runtime_config()
        if config.cache_backend == "memory":
            return None
        if not config.redis_url or not self._available:
            if config.cache_backend == "redis" and not config.redis_url:
                logger.warning("CACHE_BACKEND=redis but REDIS_URL is empty; using memory fallback")
            return None
        signature = (config.redis_url, config.redis_socket_timeout_seconds)
        if self._client is not None and self._client_signature == signature:
            return self._client
        if self._client is not None:
            await self.close()
        try:
            from redis import asyncio as redis_asyncio
        except ImportError:
            self._available = False
            logger.warning("redis package is not installed; redis cache disabled")
            return None
        self._client = redis_asyncio.from_url(
            config.redis_url,
            encoding="utf-8",
            decode_responses=False,
            socket_timeout=config.redis_socket_timeout_seconds,
            socket_connect_timeout=config.redis_socket_timeout_seconds,
        )
        self._client_signature = signature
        return self._client

    async def _load_config_center_runtime_config(self) -> RedisRuntimeConfig | None:
        try:
            from app.core.security import SecretCipher
            from app.db.session import get_sessionmaker
            from app.modules.config_center.repository import ConfigCenterRepository

            settings = get_settings()
            sessionmaker = get_sessionmaker()
            async with sessionmaker() as session:
                repository = ConfigCenterRepository(session)
                config = await repository.find_config(category_code="market_data", config_code="redis_cache")
                if config is None or not config.is_enabled:
                    return None
                options = {
                    option.option_key: option.option_value
                    for option in await repository.list_options(config.id, only_enabled=True)
                }
                values = await repository.list_values(config.id, value_kind="redis_url", only_available=True)
                redis_url = settings.redis_url
                if values:
                    redis_url = SecretCipher(settings.config_master_key).decrypt(values[0].encrypted_value)
                data_asset_default_ttl = int(options.get("data_asset_cache_ttl_seconds") or settings.data_asset_cache_ttl_seconds)
                default_ttl = int(options.get("default_cache_ttl_seconds") or data_asset_default_ttl)
                summary_ttl = int(options.get("data_asset_summary_ttl_seconds") or data_asset_default_ttl)
                daily_health_ttl = int(options.get("data_asset_daily_health_ttl_seconds") or data_asset_default_ttl)
                return RedisRuntimeConfig(
                    redis_url=str(redis_url or ""),
                    cache_backend=str(options.get("cache_backend") or settings.cache_backend),
                    redis_key_prefix=str(options.get("redis_key_prefix") or settings.redis_key_prefix),
                    redis_socket_timeout_seconds=float(options.get("redis_socket_timeout_seconds") or settings.redis_socket_timeout_seconds),
                    data_asset_cache_enabled=_as_bool(options.get("data_asset_cache_enabled", settings.data_asset_cache_enabled)),
                    data_asset_cache_ttl_seconds=data_asset_default_ttl,
                    default_cache_ttl_seconds=default_ttl,
                    data_asset_summary_ttl_seconds=summary_ttl,
                    data_asset_daily_health_ttl_seconds=daily_health_ttl,
                    source="config_center",
                )
        except Exception as exc:
            logger.warning("load redis config center settings failed; using env fallback: %s", exc)
            return None

    def _memory_get(self, key: str) -> dict | list | None:
        item = self._memory_cache.get(key)
        if item is None:
            return None
        expires_at, value = item
        if expires_at <= time.time():
            self._memory_cache.pop(key, None)
            return None
        return value

    def _memory_set(self, key: str, value: dict | list, *, ttl_seconds: int) -> None:
        self._memory_cache[key] = (time.time() + max(1, ttl_seconds), value)

    def _memory_ttl(self, key: str) -> int | None:
        item = self._memory_cache.get(key)
        if item is None:
            return None
        expires_at, _ = item
        ttl = int(expires_at - time.time())
        if ttl <= 0:
            self._memory_cache.pop(key, None)
            return -2
        return ttl


redis_client = RedisClient()


def redis_key(*parts: str) -> str:
    settings = get_settings()
    cleaned = [str(part).strip(":") for part in parts if str(part).strip(":")]
    return ":".join([settings.redis_key_prefix.strip(":"), *cleaned])


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return bool(value)
