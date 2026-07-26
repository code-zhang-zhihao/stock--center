from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Callable
from urllib.parse import urlparse
from uuid import uuid4

from app.core.config import get_settings
from app.core.security import SecretCipher
from app.modules.config_center.models import ConfigValue, SystemConfig
from app.modules.config_center.repository import ConfigCenterRepository
from app.modules.market_data.providers import json_safe, normalize_symbol, safe_float, safe_int


class TickflowRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class TickflowCredentials:
    system_config_id: int
    value_id: int
    fingerprint: str
    api_key: str = field(repr=False)
    endpoint_url: str | None = None
    timeout_seconds: float = 10.0


@dataclass(frozen=True)
class TickflowProbeResult:
    available: bool
    error: str | None
    details: dict[str, Any]


def tickflow_symbol(stock_code: str) -> str:
    code = normalize_symbol(stock_code)
    if code.startswith("6"):
        return f"{code}.SH"
    if code.startswith(("0", "3")):
        return f"{code}.SZ"
    if code.startswith(("4", "8")):
        return f"{code}.BJ"
    raise TickflowRuntimeError(f"unsupported TickFlow A-share symbol: {stock_code}")


def _as_utc_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


class TickflowQuoteProvider:
    """TickFlow realtime quote adapter.

    TickFlow is used only for quote capability in this phase. MooTDX remains
    the realtime minute-bar provider, so this adapter deliberately has no
    minute-bar API.
    """

    source = "tickflow"

    def __init__(
        self,
        credentials: TickflowCredentials,
        *,
        client_factory: Callable[[TickflowCredentials], Any] | None = None,
    ) -> None:
        self.credentials = credentials
        self._client_factory = client_factory or self._default_client
        self._client: Any | None = None

    async def quote(self, stock_code: str) -> tuple[dict | None, list[dict]]:
        symbol = tickflow_symbol(stock_code)
        rows = await asyncio.to_thread(self._quote_sync, [symbol], False)
        return (rows[0] if rows else None), rows

    async def quote_batch(self, stock_codes: list[str]) -> tuple[list[dict], list[dict]]:
        symbols = [tickflow_symbol(code) for code in stock_codes if normalize_symbol(code)]
        if not symbols:
            return [], []
        rows = await asyncio.to_thread(self._quote_sync, symbols, True)
        return rows, rows

    async def probe(self, *, symbol: str = "600519.SH") -> TickflowProbeResult:
        started = perf_counter()
        try:
            single_rows = await asyncio.to_thread(self._quote_sync, [symbol], False)
            batch_rows = await asyncio.to_thread(self._quote_sync, [symbol], True)
        except Exception as exc:
            return TickflowProbeResult(False, str(exc), {"symbol": symbol})
        if not single_rows:
            return TickflowProbeResult(False, "TickFlow returned no quote data", {"symbol": symbol})
        latest = single_rows[0]
        return TickflowProbeResult(
            True,
            None,
            {
                "symbol": symbol,
                "quote_by_symbol": True,
                "quote_batch": bool(batch_rows),
                "row_count": len(single_rows),
                "quote_time": latest.get("quote_time").isoformat() if isinstance(latest.get("quote_time"), datetime) else None,
                "latency_ms": int((perf_counter() - started) * 1000),
            },
        )

    def close(self) -> None:
        client = self._client
        self._client = None
        close = getattr(client, "close", None)
        if callable(close):
            close()

    def _default_client(self, credentials: TickflowCredentials):
        try:
            from tickflow import TickFlow
        except ImportError as exc:  # pragma: no cover - dependency is declared, retained for deployment diagnostics.
            raise TickflowRuntimeError("TickFlow SDK is not installed") from exc
        kwargs: dict[str, Any] = {
            "api_key": credentials.api_key,
            "timeout": credentials.timeout_seconds,
            "max_retries": 1,
        }
        if credentials.endpoint_url:
            kwargs["base_url"] = credentials.endpoint_url
        return TickFlow(**kwargs)

    def _quote_sync(self, symbols: list[str], force_batch: bool) -> list[dict]:
        client = self._client
        if client is None:
            client = self._client_factory(self.credentials)
            self._client = client
        try:
            if force_batch:
                response = client.quotes.get_by_symbols(symbols, as_dataframe=False)
            else:
                response = client.quotes.get(symbols=symbols, as_dataframe=False)
        except Exception as exc:
            raise TickflowRuntimeError(f"TickFlow quote request failed: {exc}") from exc
        if not isinstance(response, list):
            raise TickflowRuntimeError("TickFlow quote response is not a list")
        rows = []
        for item in response:
            if not isinstance(item, dict):
                continue
            row = self._normalize_quote(item)
            if row is not None:
                rows.append(row)
        return rows

    @staticmethod
    def _normalize_quote(item: dict) -> dict | None:
        symbol = str(item.get("symbol") or "")
        stock_code = normalize_symbol(symbol)
        if not stock_code:
            return None
        ext = item.get("ext") if isinstance(item.get("ext"), dict) else {}
        last_price = safe_float(item.get("last_price"))
        pre_close = safe_float(item.get("prev_close"))
        change_amount = safe_float(ext.get("change_amount"))
        if change_amount is None and last_price is not None and pre_close not in (None, 0):
            change_amount = last_price - pre_close
        change_pct = (
            round(change_amount / pre_close * 100, 6)
            if change_amount is not None and pre_close not in (None, 0)
            else None
        )
        return {
            "stock_code": stock_code,
            "stock_name": str(item.get("name") or ext.get("name") or "").strip() or None,
            "quote_time": _as_utc_datetime(item.get("timestamp")),
            "source": "tickflow",
            "source_symbol": symbol,
            "session": item.get("session"),
            "last_price": last_price,
            "pre_close_price": pre_close,
            "change_amount": change_amount,
            "change_pct": change_pct,
            "open_price": safe_float(item.get("open")),
            "high_price": safe_float(item.get("high")),
            "low_price": safe_float(item.get("low")),
            # TickFlow's SDK declares these as realtime trading volume/amount.
            # They are retained separately from the MooTDX hand-unit fields.
            "volume_share": safe_int(item.get("volume")),
            "amount_yuan": safe_float(item.get("amount")),
            "metadata_json": {"source": "tickflow:quotes", "session": item.get("session"), "ext": json_safe(ext)},
        }


class TickflowProviderFactory:
    """Loads one active TickFlow credential from Config Center v2."""

    category_code = "market_data"
    config_code = "tickflow"

    def __init__(self, repository: ConfigCenterRepository) -> None:
        self.repository = repository
        self.cipher = SecretCipher(get_settings().config_master_key)

    async def resolve_credentials(self) -> TickflowCredentials:
        config, options, values = await self._load_candidates()
        value = values[0]
        endpoint = self._endpoint_url(value, options)
        return TickflowCredentials(
            system_config_id=config.id,
            value_id=value.id,
            fingerprint=value.fingerprint,
            api_key=self.cipher.decrypt(value.encrypted_value),
            endpoint_url=endpoint,
            timeout_seconds=max(float(options.get("timeout_seconds") or 10), 1),
        )

    async def probe_value(self, value_id: int) -> TickflowProbeResult:
        value = await self.repository.get_value(value_id)
        if value is None:
            return TickflowProbeResult(False, "config value not found", {})
        config = await self.repository.get_config(value.system_config_id)
        if config is None or config.category_code != self.category_code or config.config_code != self.config_code:
            return TickflowProbeResult(False, "value is not a TickFlow API key", {})
        options = await self._options(config)
        started = perf_counter()
        provider: TickflowQuoteProvider | None = None
        try:
            credentials = TickflowCredentials(
                system_config_id=config.id,
                value_id=value.id,
                fingerprint=value.fingerprint,
                api_key=self.cipher.decrypt(value.encrypted_value),
                endpoint_url=self._endpoint_url(value, options),
                timeout_seconds=max(float(options.get("timeout_seconds") or 10), 1),
            )
            provider = TickflowQuoteProvider(credentials)
            result = await provider.probe()
            await self._record_probe(config, value, result, int((perf_counter() - started) * 1000))
            return result
        except Exception as exc:
            result = TickflowProbeResult(False, str(exc), {})
            await self._record_probe(config, value, result, int((perf_counter() - started) * 1000))
            return result
        finally:
            if provider is not None:
                try:
                    provider.close()
                except Exception:
                    pass

    async def _load_candidates(self) -> tuple[SystemConfig, dict, list[ConfigValue]]:
        config = await self.repository.find_config(category_code=self.category_code, config_code=self.config_code)
        if config is None:
            raise TickflowRuntimeError("TickFlow configuration is missing or disabled")
        await self.repository.release_expired_cooldowns()
        await self.repository.commit()
        options = await self._options(config)
        values = await self.repository.list_values(config.id, value_kind="api_key", only_available=True)
        if not values:
            raise TickflowRuntimeError("No active TickFlow API key is configured")
        return config, options, values

    async def _options(self, config: SystemConfig) -> dict:
        rows = await self.repository.list_options(config.id, only_enabled=True)
        return {row.option_key: row.option_value for row in rows}

    @staticmethod
    def _endpoint_url(value: ConfigValue, options: dict) -> str | None:
        endpoint = str(getattr(value, "endpoint_url", None) or options.get("api_url") or "").strip()
        if not endpoint:
            return None
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise TickflowRuntimeError("TickFlow endpoint URL is invalid for this API key")
        return endpoint.rstrip("/")

    async def _record_probe(
        self,
        config: SystemConfig,
        value: ConfigValue,
        result: TickflowProbeResult,
        latency_ms: int,
    ) -> None:
        if not result.available:
            error_text = str(result.error or "")
            if any(token in error_text.lower() for token in ("401", "403", "unauthorized", "forbidden", "invalid api key")):
                await self.repository.mark_value_invalid(value.id)
            else:
                await self.repository.mark_value_failure(value.id)
        else:
            await self.repository.mark_value_used(value.id)
        await self.repository.record_call(
            {
                "trace_id": uuid4().hex,
                "domain": "market_data",
                "system_config_id": config.id,
                "config_value_id": value.id,
                "capability": "tickflow_quote_connectivity_test",
                "call_type": "test_value",
                "status": "success" if result.available else "failed",
                "request_summary": {"symbol": "600519.SH"},
                "response_summary": {"fingerprint": value.fingerprint, **json_safe(result.details)},
                "error_code": None if result.available else "tickflow_quote_connectivity_failed",
                "error_message": result.error,
                "latency_ms": latency_ms,
                "finished_at": datetime.now(timezone.utc),
                "metadata_json": {"provider": "tickflow"},
            }
        )
        await self.repository.commit()
