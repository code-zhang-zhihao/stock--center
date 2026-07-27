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

    async def universe_quotes(self, universe_id: str = "CN_Equity_A") -> tuple[list[dict], list[dict]]:
        """Fetch a provider universe in one request; never synthesize it locally."""
        rows = await asyncio.to_thread(self._universe_quote_sync, universe_id)
        return rows, rows

    async def depth_batch(self, stock_codes: list[str]) -> list[dict]:
        """Fetch visible five-level order books through TickFlow's batch endpoint."""
        symbols = [tickflow_symbol(code) for code in stock_codes if normalize_symbol(code)]
        if not symbols:
            return []
        return await asyncio.to_thread(self._depth_batch_sync, symbols)

    async def universe_catalog(self) -> list[dict]:
        return await asyncio.to_thread(self._universe_catalog_sync)

    async def universe_members(self, universe_id: str) -> list[str]:
        return await asyncio.to_thread(self._universe_members_sync, universe_id)

    async def universe_members_batch(self, universe_ids: list[str]) -> dict[str, list[str]]:
        return await asyncio.to_thread(self._universe_members_batch_sync, universe_ids)

    async def probe(self, *, symbol: str = "600519.SH") -> TickflowProbeResult:
        """Verify every capability the realtime runtime needs before enabling it.

        A successful single quote is deliberately insufficient: an old key can
        answer it while lacking all-market quote or five-level depth access.
        """
        started = perf_counter()
        details: dict[str, Any] = {"symbol": symbol, "capabilities": {}}
        try:
            single_rows = await asyncio.to_thread(self._quote_sync, [symbol], False)
            details["capabilities"]["quote_single"] = {"available": bool(single_rows), "row_count": len(single_rows)}
        except Exception as exc:
            details["capabilities"]["quote_single"] = {"available": False, "error": str(exc)}
            return TickflowProbeResult(False, str(exc), details)
        if not single_rows:
            return TickflowProbeResult(False, "TickFlow returned no quote data", details)

        try:
            probe_symbols = await asyncio.to_thread(self._probe_symbols_sync)
        except Exception as exc:
            details["capabilities"]["universe_catalog"] = {"available": False, "error": str(exc)}
            return TickflowProbeResult(False, str(exc), details)

        operations: list[tuple[str, Callable[[], Any], int]] = [
            ("quote_symbol_batch_50", lambda: self._quote_sync(probe_symbols[:50], True), 50),
            ("quote_universe", lambda: self._universe_quote_sync("CN_Equity_A"), 1),
            ("depth_batch_200", lambda: self._depth_batch_sync(probe_symbols[:200]), 200),
        ]
        errors: list[str] = []
        for capability, operation, expected in operations:
            stage_started = perf_counter()
            try:
                result = await asyncio.to_thread(operation)
                row_count = len(result) if hasattr(result, "__len__") else 0
                details["capabilities"][capability] = {
                    "available": bool(result),
                    "expected_symbols": expected,
                    "row_count": row_count,
                    "latency_ms": int((perf_counter() - stage_started) * 1000),
                }
                if not result:
                    errors.append(f"{capability}: no data returned")
            except Exception as exc:
                details["capabilities"][capability] = {
                    "available": False,
                    "expected_symbols": expected,
                    "error": str(exc),
                    "latency_ms": int((perf_counter() - stage_started) * 1000),
                }
                errors.append(f"{capability}: {exc}")

        latest = single_rows[0]
        return TickflowProbeResult(
            not errors,
            "; ".join(errors) if errors else None,
            {
                **details,
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

    def _universe_quote_sync(self, universe_id: str) -> list[dict]:
        client = self._get_client()
        try:
            response = client.quotes.get(universes=[universe_id], as_dataframe=False)
        except Exception as exc:
            raise TickflowRuntimeError(f"TickFlow universe quote request failed: {exc}") from exc
        if not isinstance(response, list):
            raise TickflowRuntimeError("TickFlow universe quote response is not a list")
        return [row for item in response if isinstance(item, dict) if (row := self._normalize_quote(item)) is not None]

    def _depth_batch_sync(self, symbols: list[str]) -> list[dict]:
        client = self._get_client()
        try:
            response = client.depth.batch(symbols, batch_size=min(200, len(symbols)), max_workers=1, show_progress=False)
        except Exception as exc:
            raise TickflowRuntimeError(f"TickFlow depth batch request failed: {exc}") from exc
        if not isinstance(response, dict):
            raise TickflowRuntimeError("TickFlow depth batch response is not a mapping")
        rows: list[dict] = []
        for source_symbol, item in response.items():
            normalized = self._normalize_depth(source_symbol, item)
            if normalized is not None:
                rows.append(normalized)
        return rows

    def _probe_symbols_sync(self) -> list[str]:
        client = self._get_client()
        try:
            detail = client.universes.get("CN_Equity_A")
        except Exception as exc:
            raise TickflowRuntimeError(f"TickFlow universe catalogue request failed: {exc}") from exc
        payload = _object_to_mapping(detail)
        raw_symbols = payload.get("symbols") or payload.get("members") or []
        symbols: list[str] = []
        for raw in raw_symbols:
            if isinstance(raw, str):
                value = raw
            else:
                item = _object_to_mapping(raw)
                value = str(item.get("symbol") or item.get("code") or "")
            if value:
                symbols.append(value)
            if len(symbols) >= 200:
                break
        if len(symbols) < 200:
            raise TickflowRuntimeError(f"TickFlow CN_Equity_A catalogue returned only {len(symbols)} symbols; 200 are required for depth probe")
        return symbols

    def _universe_catalog_sync(self) -> list[dict]:
        client = self._get_client()
        try:
            response = client.universes.list()
        except Exception as exc:
            raise TickflowRuntimeError(f"TickFlow universe list request failed: {exc}") from exc
        if not isinstance(response, list):
            raise TickflowRuntimeError("TickFlow universe catalogue response is not a list")
        rows: list[dict] = []
        for raw in response:
            item = _object_to_mapping(raw)
            universe_id = str(item.get("id") or item.get("universe_id") or "").strip()
            if not universe_id:
                continue
            name = str(item.get("name") or item.get("display_name") or universe_id).strip()
            level = _taxonomy_level(universe_id, name)
            rows.append(
                {
                    "universe_id": universe_id,
                    "universe_name": name,
                    "description": item.get("description"),
                    "region": item.get("region"),
                    "category": item.get("category") or item.get("type"),
                    "taxonomy_level": level,
                    "logical_group_key": f"{level}:{name}" if level else None,
                    "source_symbol_count": safe_int(item.get("symbol_count") or item.get("count")) or 0,
                    "raw": json_safe(item),
                }
            )
        return rows

    def _universe_members_sync(self, universe_id: str) -> list[str]:
        client = self._get_client()
        try:
            detail = client.universes.get(universe_id)
        except Exception as exc:
            raise TickflowRuntimeError(f"TickFlow universe member request failed ({universe_id}): {exc}") from exc
        payload = _object_to_mapping(detail)
        raw_symbols = payload.get("symbols") or payload.get("members") or []
        result: list[str] = []
        for raw in raw_symbols:
            if isinstance(raw, str):
                symbol = raw
            else:
                item = _object_to_mapping(raw)
                symbol = str(item.get("symbol") or item.get("code") or "")
            code = normalize_symbol(symbol)
            if code:
                result.append(code)
        return sorted(set(result))

    def _universe_members_batch_sync(self, universe_ids: list[str]) -> dict[str, list[str]]:
        client = self._get_client()
        if not universe_ids:
            return {}
        try:
            response = client.universes.batch(universe_ids)
        except Exception as exc:
            raise TickflowRuntimeError(f"TickFlow universe member batch request failed: {exc}") from exc
        if not isinstance(response, dict):
            raise TickflowRuntimeError("TickFlow universe member batch response is not a mapping")
        result: dict[str, list[str]] = {}
        for universe_id, detail in response.items():
            payload = _object_to_mapping(detail)
            members: list[str] = []
            for raw in payload.get("symbols") or payload.get("members") or []:
                if isinstance(raw, str):
                    symbol = raw
                else:
                    item = _object_to_mapping(raw)
                    symbol = str(item.get("symbol") or item.get("code") or "")
                code = normalize_symbol(symbol)
                if code:
                    members.append(code)
            result[str(universe_id)] = sorted(set(members))
        return result

    def _get_client(self) -> Any:
        client = self._client
        if client is None:
            client = self._client_factory(self.credentials)
            self._client = client
        return client

    @staticmethod
    def _normalize_depth(source_symbol: str, value: Any) -> dict | None:
        item = _object_to_mapping(value)
        symbol = str(item.get("symbol") or source_symbol or "")
        stock_code = normalize_symbol(symbol)
        if not stock_code:
            return None
        bids = _depth_levels(item.get("bids") or item.get("bid"))
        asks = _depth_levels(item.get("asks") or item.get("ask"))
        return {
            "stock_code": stock_code,
            "source": "tickflow",
            "source_symbol": symbol,
            "depth_time": _as_utc_datetime(item.get("timestamp") or item.get("datetime") or item.get("time")),
            "bids": bids,
            "asks": asks,
            "metadata_json": {"source": "tickflow:depth", "raw": json_safe(item)},
        }

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


def _object_to_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return dumped if isinstance(dumped, dict) else {}
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        dumped = to_dict()
        return dumped if isinstance(dumped, dict) else {}
    return vars(value) if hasattr(value, "__dict__") else {}


def _depth_levels(value: Any) -> list[dict]:
    if not isinstance(value, list):
        return []
    levels: list[dict] = []
    for index, raw in enumerate(value[:5], start=1):
        item = _object_to_mapping(raw)
        if not item and isinstance(raw, (list, tuple)):
            item = {"price": raw[0] if raw else None, "volume": raw[1] if len(raw) > 1 else None}
        price = safe_float(item.get("price"))
        volume = safe_int(item.get("volume") or item.get("size") or item.get("quantity"))
        if price is None and volume is None:
            continue
        levels.append({"level": index, "price": price, "volume": volume})
    return levels


def _taxonomy_level(universe_id: str, universe_name: str) -> str | None:
    marker = f"{universe_id} {universe_name}".upper().replace("_", " ")
    for level in ("SW1", "SW2", "SW3"):
        if level in marker:
            return level.lower()
    return None


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
        return self._credentials_for(config, options, value)

    async def resolve_realtime_credentials(self) -> TickflowCredentials:
        """Resolve only a Key that passed the complete realtime capability probe."""
        config, options, values = await self._load_candidates()
        for value in values:
            probe = (value.metadata_json or {}).get("tickflow_realtime_probe")
            if isinstance(probe, dict) and probe.get("available") is True:
                return self._credentials_for(config, options, value)
        details = []
        for value in values:
            probe = (value.metadata_json or {}).get("tickflow_realtime_probe")
            if isinstance(probe, dict):
                details.append(str(probe.get("error") or "未完成实时权限测试"))
        suffix = f"；最近测试：{details[0]}" if details else "；请先在数据源配置中测试全市场 Quote、50 标的 Quote 和 200 标的五档深度"
        raise TickflowRuntimeError("No TickFlow API key has passed the realtime capability probe" + suffix)

    def _credentials_for(self, config: SystemConfig, options: dict, value: ConfigValue) -> TickflowCredentials:
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
            # A capability 403 means this Key is genuine but missing a paid
            # entitlement.  Do not disable it as an invalid credential; the
            # settings UI must keep it visible for upgrade/retest.
            if any(token in error_text.lower() for token in ("401", "unauthorized", "invalid api key", "invalid_api_key")):
                await self.repository.mark_value_invalid(value.id)
            else:
                await self.repository.mark_value_failure(value.id)
        else:
            await self.repository.mark_value_used(value.id)
        metadata = dict(value.metadata_json or {})
        metadata["tickflow_realtime_probe"] = {
            "available": result.available,
            "error": result.error,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "capabilities": json_safe(result.details.get("capabilities", {})),
        }
        await self.repository.update_value(value.id, {"metadata_json": metadata})
        await self.repository.record_call(
            {
                "trace_id": uuid4().hex,
                "domain": "market_data",
                "system_config_id": config.id,
                "config_value_id": value.id,
                "capability": "tickflow_quote_connectivity_test",
                "call_type": "test_value",
                "status": "success" if result.available else "failed",
                "request_summary": {
                    "symbol": "600519.SH",
                    "required_capabilities": ["quote_universe", "quote_symbol_batch_50", "depth_batch_200"],
                },
                "response_summary": {"fingerprint": value.fingerprint, **json_safe(result.details)},
                "error_code": None if result.available else "tickflow_quote_connectivity_failed",
                "error_message": result.error,
                "latency_ms": latency_ms,
                "finished_at": datetime.now(timezone.utc),
                "metadata_json": {"provider": "tickflow"},
            }
        )
        await self.repository.commit()
