from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from time import perf_counter
from typing import Awaitable, Callable, Literal, TypeVar
from urllib.parse import urlparse
from uuid import uuid4

from app.core.config import get_settings
from app.core.security import SecretCipher
from app.modules.config_center.models import ConfigValue, SystemConfig
from app.modules.config_center.repository import ConfigCenterRepository
from app.modules.market_data.tushare.transport import TushareTransport, TushareTransportError
from app.modules.market_data.providers import json_safe
from app.modules.market_data.tushare.rate_limit import TushareRateLimitTimeout, tushare_rate_coordinator


T = TypeVar("T")


class TushareRuntimeError(RuntimeError):
    def __init__(self, message: str, *, retry_at: datetime | None = None) -> None:
        super().__init__(message)
        self.retry_at = retry_at


@dataclass(frozen=True)
class TushareProbeResult:
    available: bool
    error: str | None
    details: dict


class TushareProviderFactory:
    """Builds credential-injected Tushare clients from configuration center v2."""

    category_code = "market_data"
    config_code = "tushare_pro"

    def __init__(self, repository: ConfigCenterRepository) -> None:
        self.repository = repository
        self.cipher = SecretCipher(get_settings().config_master_key)

    async def call(
        self,
        capability: str,
        operation: Callable[[TushareTransport], Awaitable[T]],
        *,
        request_summary: dict | None = None,
        execution_mode: Literal["interactive", "scheduler"] = "interactive",
    ) -> T:
        config, options, values = await self._load_candidates()
        request_summary = json_safe(request_summary or {})
        errors: list[str] = []
        retry_count = max(int(options.get("retry_count", 1)), 0)
        retry_backoff_seconds = max(float(options.get("retry_backoff_seconds", 1)), 0)
        wait_budget = float(options.get("scheduler_max_wait_seconds" if execution_mode == "scheduler" else "interactive_max_wait_seconds", 1800 if execution_mode == "scheduler" else 3))
        candidates: list[tuple[ConfigValue, TushareTransport]] = []
        for value in values:
            try:
                candidates.append((value, self._provider(value, options)))
            except TushareTransportError as exc:
                await self._record_failure(config, value, capability, exc, 0, request_summary, 0)
                errors.append(f"{value.fingerprint}: {exc}")
        while candidates:
            try:
                reserved_id = await tushare_rate_coordinator.reserve(
                    [(value.id, provider.rate_limit_per_minute) for value, provider in candidates],
                    wait_budget,
                )
            except TushareRateLimitTimeout as exc:
                retry_at = datetime.now(timezone.utc) + timedelta(seconds=exc.retry_after_seconds)
                raise TushareRuntimeError(
                    "Tushare local rate limit reached; retry after " + retry_at.isoformat(),
                    retry_at=retry_at,
                ) from exc
            value, provider = next(item for item in candidates if item[0].id == reserved_id)
            for attempt in range(retry_count + 1):
                started = perf_counter()
                try:
                    result = await operation(provider)
                except TushareTransportError as exc:
                    elapsed = int((perf_counter() - started) * 1000)
                    await self._record_failure(config, value, capability, exc, elapsed, request_summary, attempt)
                    errors.append(f"{value.fingerprint}: {exc}")
                    if exc.kind == "transport" and attempt < retry_count:
                        if retry_backoff_seconds:
                            await asyncio.sleep(retry_backoff_seconds * (attempt + 1))
                        continue
                    break
                except Exception as exc:
                    elapsed = int((perf_counter() - started) * 1000)
                    wrapped = TushareTransportError(str(exc), kind="provider_error")
                    await self._record_failure(config, value, capability, wrapped, elapsed, request_summary, attempt)
                    errors.append(f"{value.fingerprint}: {exc}")
                    break
                elapsed = int((perf_counter() - started) * 1000)
                await self.repository.mark_value_used(value.id)
                await self.repository.record_call(
                    {
                        "trace_id": uuid4().hex,
                        "domain": "market_data",
                        "system_config_id": config.id,
                        "config_value_id": value.id,
                        "capability": capability,
                        "call_type": "tushare_provider",
                        "status": "success",
                        "request_summary": request_summary,
                        "response_summary": {"fingerprint": value.fingerprint},
                        "latency_ms": elapsed,
                        "finished_at": datetime.now(timezone.utc),
                        "metadata_json": {"provider": "tushare"},
                    }
                )
                await self.repository.commit()
                return result
            candidates = [item for item in candidates if item[0].id != value.id]
        raise TushareRuntimeError("Tushare all configured tokens failed: " + "; ".join(errors))

    async def probe_value(self, value_id: int) -> TushareProbeResult:
        value = await self.repository.get_value(value_id)
        if value is None:
            return TushareProbeResult(False, "config value not found", {})
        config = await self.repository.get_config(value.system_config_id)
        if config is None or config.category_code != self.category_code or config.config_code != self.config_code:
            return TushareProbeResult(False, "value is not a Tushare token", {})
        options = await self._options(config)
        end_date = date.today()
        start_date = end_date - timedelta(days=9)
        request_summary = {
            "api_name": "daily",
            "stock_code": "600519.SH",
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        }
        started = perf_counter()
        try:
            provider = self._provider(value, options)
            response = await provider.daily_connectivity(end_date=end_date)
            details = {**request_summary, "row_count": response.row_count}
            await self.repository.record_call(
                {
                    "trace_id": uuid4().hex,
                    "domain": "market_data",
                    "system_config_id": config.id,
                    "config_value_id": value.id,
                    "capability": "tushare_daily_connectivity_test",
                    "call_type": "test_value",
                    "status": "success",
                    "request_summary": request_summary,
                    "response_summary": {"fingerprint": value.fingerprint, **details},
                    "latency_ms": int((perf_counter() - started) * 1000),
                    "finished_at": datetime.now(timezone.utc),
                    "metadata_json": {"provider": "tushare"},
                }
            )
            await self.repository.commit()
            return TushareProbeResult(True, None, details)
        except TushareTransportError as exc:
            await self.repository.record_call(
                {
                    "trace_id": uuid4().hex,
                    "domain": "market_data",
                    "system_config_id": config.id,
                    "config_value_id": value.id,
                    "capability": "tushare_daily_connectivity_test",
                    "call_type": "test_value",
                    "status": "failed",
                    "request_summary": request_summary,
                    "response_summary": {"fingerprint": value.fingerprint, "error_kind": exc.kind},
                    "error_code": f"tushare_{exc.kind}",
                    "error_message": str(exc),
                    "latency_ms": int((perf_counter() - started) * 1000),
                    "finished_at": datetime.now(timezone.utc),
                    "metadata_json": {"provider": "tushare", "api_name": exc.api_name},
                }
            )
            await self.repository.commit()
            return TushareProbeResult(False, str(exc), request_summary)
        except Exception as exc:
            return TushareProbeResult(False, str(exc), {})

    async def _load_candidates(self) -> tuple[SystemConfig, dict, list[ConfigValue]]:
        config = await self.repository.find_config(category_code=self.category_code, config_code=self.config_code)
        if config is None:
            raise TushareRuntimeError("Tushare configuration is missing or disabled")
        await self.repository.release_expired_cooldowns()
        await self.repository.commit()
        options = await self._options(config)
        values = await self.repository.list_values(config.id, value_kind="token", only_available=True)
        if not values:
            raise TushareRuntimeError("No active Tushare token is configured")
        return config, options, values

    async def _options(self, config: SystemConfig) -> dict:
        rows = await self.repository.list_options(config.id, only_enabled=True)
        return {row.option_key: row.option_value for row in rows}

    def _provider(self, value: ConfigValue, options: dict) -> TushareTransport:
        endpoint = self._endpoint_url(value, options)
        return TushareTransport(
            token=self.cipher.decrypt(value.encrypted_value),
            api_url=endpoint,
            timeout_seconds=max(int(options.get("timeout_seconds") or 30), 1),
            rate_limit_per_minute=max(int(options.get("rate_limit_per_minute") or 60), 1),
            token_fingerprint=value.fingerprint,
        )

    @staticmethod
    def _endpoint_url(value: ConfigValue, options: dict) -> str:
        endpoint = str(getattr(value, "endpoint_url", None) or options.get("api_url") or "http://api.tushare.pro").strip()
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise TushareTransportError(
                "Tushare endpoint URL is invalid for this token",
                kind="endpoint_configuration_error",
            )
        return endpoint.rstrip("/")

    async def _record_failure(
        self,
        config: SystemConfig,
        value: ConfigValue,
        capability: str,
        error: TushareTransportError,
        latency_ms: int,
        request_summary: dict | None,
        attempt: int,
    ) -> None:
        if error.kind == "token_invalid":
            await self.repository.mark_value_invalid(value.id)
        elif error.kind == "rate_limit":
            options = await self._options(config)
            seconds = max(int(options.get("cooldown_seconds") or 60), 1)
            await self.repository.mark_value_cooldown(value.id, datetime.now(timezone.utc) + timedelta(seconds=seconds))
        elif error.kind not in {"permission", "endpoint_configuration_error"}:
            await self.repository.mark_value_failure(value.id)
        await self.repository.record_call(
            {
                "trace_id": uuid4().hex,
                "domain": "market_data",
                "system_config_id": config.id,
                "config_value_id": value.id,
                "capability": capability,
                "call_type": "tushare_provider",
                "status": "failed",
                "request_summary": {**(request_summary or {}), "attempt": attempt + 1},
                "response_summary": {"fingerprint": value.fingerprint, "error_kind": error.kind},
                "error_code": f"tushare_{error.kind}",
                "error_message": str(error),
                "latency_ms": latency_ms,
                "finished_at": datetime.now(timezone.utc),
                "metadata_json": {"provider": "tushare", "api_name": error.api_name},
            }
        )
        await self.repository.commit()
