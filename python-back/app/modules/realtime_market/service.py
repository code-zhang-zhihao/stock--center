from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta
import logging
import math
import time as clock
import uuid
from zoneinfo import ZoneInfo

from app.core.redis_client import redis_client
from app.db.session import get_sessionmaker
from app.modules.config_center.repository import ConfigCenterRepository
from app.modules.market_data.providers import MootdxProvider, normalize_symbol
from app.modules.realtime_market.repository import RealtimeMarketRepository
from app.modules.realtime_market.schemas import RealtimeMinuteMeta, RealtimeRoundMeta, RealtimeSettings, RealtimeStatus
from app.modules.realtime_market.tickflow_runtime import (
    TickflowCredentials,
    TickflowProviderFactory,
    TickflowQuoteProvider,
)


logger = logging.getLogger(__name__)
SHANGHAI = ZoneInfo("Asia/Shanghai")


class RealtimeMarketService:
    def __init__(self) -> None:
        self._running = False
        self._task: asyncio.Task | None = None
        self._refresh_lock = asyncio.Lock()
        self._settings = RealtimeSettings()
        self._settings_loaded_at = 0.0
        self._reference_loaded_at: datetime | None = None
        self._reference_loaded_clock = 0.0
        self._active_codes: list[str] = []
        self._stock_names: dict[str, str] = {}
        self._sector_info: dict[str, dict] = {}
        self._sector_members: dict[str, list[str]] = {}
        self._stock_sectors: dict[str, list[str]] = {}
        self._pools: dict[str, dict] = {}
        self._quotes: dict[str, dict] = {}
        self._minutes: dict[str, list[dict]] = {}
        self._minute_meta_by_stock: dict[str, dict] = {}
        self._market_overview: dict = {"as_of": None, "items": {}, "round_id": None}
        self._sector_strength: dict[str, dict] = {}
        self._pool_summaries: dict[str, dict] = {}
        self._page_targets: dict[str, float] = {}
        self._rotation_cursor = 0
        self._last_minute_refresh_clock = 0.0
        self._trade_day_cache: dict[date, bool] = {}
        self._last_quote_round = RealtimeRoundMeta()
        self._last_minute_round = RealtimeMinuteMeta()
        self._error: str | None = None
        self._quote_providers: list[TickflowQuoteProvider | MootdxProvider] = []
        self._minute_providers: list[MootdxProvider] = []
        self._quote_provider_identity: tuple[object, ...] | None = None
        self._tickflow_credentials: TickflowCredentials | None = None
        self._subscribers: dict[str, tuple[set[str], asyncio.Queue]] = {}
        self._on_demand_locks: dict[str, asyncio.Lock] = {}
        self._on_demand_attempted_at: dict[str, float] = {}
        self._on_demand_errors: dict[str, str] = {}

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="realtime-market-runtime")
        logger.info("realtime market runtime started")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._close_providers([*self._quote_providers, *self._minute_providers])
        self._quote_providers = []
        self._minute_providers = []
        logger.info("realtime market runtime stopped")

    async def status(self) -> dict:
        settings = await self._load_settings()
        runtime_config = await redis_client.runtime_config()
        backend = "memory"
        if runtime_config.cache_backend != "memory" and runtime_config.redis_url:
            backend = "redis" if await redis_client.ping() else "memory_fallback"
        now = datetime.now(tz=SHANGHAI)
        stale_count = sum(1 for quote in self._quotes.values() if self._is_stale(quote, settings, now))
        return RealtimeStatus(
            running=self._running,
            enabled=settings.enabled,
            market_session=await self._is_open_market_session(now),
            quote_provider=settings.quote_provider,
            minute_provider="mootdx",
            cache_backend=backend,
            cache_prefix=runtime_config.redis_key_prefix,
            quote_cache_count=len(self._quotes),
            quote_stale_count=stale_count,
            minute_cache_count=len(self._minutes),
            minute_registered_count=int(self._last_minute_round.registered_count),
            minute_guaranteed_count=int(self._last_minute_round.selected_count),
            reference_loaded_at=self._reference_loaded_at,
            last_quote_round=self._last_quote_round,
            last_minute_round=self._last_minute_round,
            error=self._error,
        ).model_dump(mode="json")

    async def refresh_once(self, *, force: bool = False) -> dict:
        settings = await self._load_settings(force=True)
        if not settings.enabled and not force:
            raise RuntimeError("实时行情服务未启用，请先在数据源配置中启用 realtime_market")
        await self._refresh_round(settings, force=force)
        return await self.status()

    async def market_overview(self) -> dict:
        return self._market_overview

    async def quotes(self, stock_codes: list[str] | None = None) -> dict:
        settings = await self._load_settings()
        now = datetime.now(tz=SHANGHAI)
        codes = [normalize_symbol(code) for code in stock_codes or self._quotes.keys()]
        items = []
        for code in codes:
            quote = self._quotes.get(code)
            if quote is None:
                continue
            items.append({**quote, "stale": self._is_stale(quote, settings, now)})
        return {"as_of": self._market_overview.get("as_of"), "round_id": self._market_overview.get("round_id"), "items": items}

    async def stock(self, stock_code: str) -> dict:
        code = normalize_symbol(stock_code)
        self._page_targets[code] = clock.monotonic() + 120
        settings = await self._load_settings()
        now = datetime.now(tz=SHANGHAI)
        market_session = await self._is_open_market_session(now)
        await self._hydrate_stock_cache(code)
        fetch_mode = "cache"
        if market_session and self._stock_needs_on_demand_fetch(code):
            fetch_mode = await self._fetch_stock_on_demand(code, settings)
        quote = self._quotes.get(code)
        meta = self._minute_meta_by_stock.get(code, {})
        errors = self._stock_cache_errors(code, settings)
        if self._on_demand_errors.get(code):
            errors.append(self._on_demand_errors[code])
        return {
            "stock_code": code,
            "quote": {**quote, "stale": self._is_stale(quote, settings, now)} if quote else None,
            "minute_bars": self._minutes.get(code, []),
            "minute_meta": meta,
            "meta": {
                "query_mode": "realtime_on_demand" if fetch_mode == "on_demand" else "realtime_cache",
                "resolved_source": quote.get("source") if quote else (meta.get("source") if meta else None),
                "attempted_engines": list(dict.fromkeys([settings.quote_provider, "mootdx"])),
                "quote_source": quote.get("source") if quote else None,
                "minute_source": meta.get("source") if meta else None,
                "fallback_used": False,
                "persisted": False,
                "cache": "realtime_market",
                "runtime_enabled": settings.enabled,
                "market_session": market_session,
                "cache_status": "hit" if fetch_mode == "cache" and (quote or code in self._minutes) else fetch_mode,
                "errors": errors,
            },
        }

    async def _hydrate_stock_cache(self, code: str) -> None:
        """Restore a directly fetched stock from Redis after an app restart.

        Full-market quote data intentionally remains an in-process aggregation. A
        per-stock key is only written for an on-demand request, so this read does
        not turn each page load into a multi-megabyte full-market Redis fetch.
        """
        if code not in self._quotes:
            quote = await redis_client.get_json(await redis_client.key("realtime", "quote", code))
            if isinstance(quote, dict) and quote.get("stock_code"):
                self._quotes[code] = quote
        if code not in self._minutes and code not in self._minute_meta_by_stock:
            cached = await redis_client.get_json(await redis_client.key("realtime", "minutes", code))
            if isinstance(cached, dict):
                items = cached.get("items")
                meta = cached.get("meta")
                if isinstance(items, list):
                    self._minutes[code] = items
                if isinstance(meta, dict):
                    self._minute_meta_by_stock[code] = meta

    def _stock_needs_on_demand_fetch(self, code: str) -> bool:
        # A recorded no-data/provider-error result is a cache entry too. Retrying
        # it on every browser refresh would create a request storm for suspended
        # securities or a temporarily unhealthy TDX server.
        if self._minute_meta_by_stock.get(code, {}).get("status") == "not_available_before_continuous_session":
            return True
        return code not in self._quotes or (code not in self._minutes and code not in self._minute_meta_by_stock)

    async def _fetch_stock_on_demand(self, code: str, settings: RealtimeSettings) -> str:
        """Fill an individual intraday cache miss from the capability providers.

        TickFlow provides the quote; MooTDX continues to provide the 1-minute
        bars during continuous trading. This remains a display-path fallback:
        it only writes realtime cache and never lands rows in PostgreSQL or
        provider raw tables.
        """
        lock = self._on_demand_locks.setdefault(code, asyncio.Lock())
        async with lock:
            if not self._stock_needs_on_demand_fetch(code):
                return "hit"
            now_clock = clock.monotonic()
            if now_clock - self._on_demand_attempted_at.get(code, 0.0) < 10:
                return "cooldown"
            self._on_demand_attempted_at[code] = now_clock
            self._on_demand_errors.pop(code, None)
            started = clock.monotonic()
            await self._ensure_provider_pools(settings)
            quote_provider = self._new_quote_provider(settings.quote_provider)
            minute_provider = self._new_minute_provider()
            try:
                logger.info("realtime stock on-demand fetch started: stock_code=%s", code)
                minute_enabled = self._is_continuous_market_session(datetime.now(tz=SHANGHAI))
                requests = [quote_provider.quote(code)]
                if minute_enabled:
                    requests.append(minute_provider.minute_bars(code))
                results = await asyncio.gather(*requests, return_exceptions=True)
                quote_result = results[0]
                minute_result = results[1] if minute_enabled else None
                timestamp = datetime.now(tz=ZoneInfo("UTC"))
                error_parts: list[str] = []
                if isinstance(quote_result, Exception):
                    error_parts.append(f"quote: {type(quote_result).__name__}: {quote_result}")
                else:
                    quote_row, _ = quote_result
                    if quote_row is not None:
                        normalized_quote = self._normalize_quote(quote_row)
                        self._quotes[code] = normalized_quote
                        await redis_client.set_json(
                            await redis_client.key("realtime", "quote", code),
                            normalized_quote,
                            ttl_seconds=settings.cache_ttl_seconds,
                        )
                    else:
                        error_parts.append("quote: no_quote_data")

                if not minute_enabled:
                    self._minute_meta_by_stock[code] = {
                        "status": "not_available_before_continuous_session",
                        "updated_at": timestamp.isoformat(),
                        "fetch_mode": "on_demand",
                        "source": "mootdx",
                    }
                elif isinstance(minute_result, Exception):
                    error_parts.append(f"minute: {type(minute_result).__name__}: {minute_result}")
                    self._minute_meta_by_stock[code] = {
                        "status": "provider_error",
                        "updated_at": timestamp.isoformat(),
                        "fetch_mode": "on_demand",
                        "source": "mootdx",
                    }
                else:
                    rows, _ = minute_result
                    if rows:
                        clean_rows = [self._normalize_minute(row) for row in rows]
                        self._minutes[code] = clean_rows
                        self._minute_meta_by_stock[code] = {
                            "status": "available",
                            "updated_at": timestamp.isoformat(),
                            "bar_count": len(clean_rows),
                            "fetch_mode": "on_demand",
                            "source": "mootdx",
                            "features": self._minute_features(clean_rows),
                        }
                        await self._persist_minute_cache(code, clean_rows, self._minute_meta_by_stock[code])
                    else:
                        self._minute_meta_by_stock[code] = {
                            "status": "no_intraday_data",
                            "updated_at": timestamp.isoformat(),
                            "fetch_mode": "on_demand",
                            "source": "mootdx",
                        }
                        error_parts.append("minute: no_intraday_data")

                if error_parts:
                    self._on_demand_errors[code] = f"on_demand_{settings.quote_provider}_mootdx: " + " | ".join(error_parts[:2])
                else:
                    self._on_demand_errors.pop(code, None)
                logger.info(
                    "realtime stock on-demand fetch completed: stock_code=%s quote=%s minute=%s bars=%s duration_ms=%s errors=%s",
                    code,
                    code in self._quotes,
                    self._minute_meta_by_stock.get(code, {}).get("status"),
                    len(self._minutes.get(code, [])),
                    int((clock.monotonic() - started) * 1000),
                    len(error_parts),
                )
                return "on_demand"
            except Exception as exc:
                self._on_demand_errors[code] = f"on_demand_{settings.quote_provider}_mootdx: {type(exc).__name__}: {exc}"
                logger.warning("realtime stock on-demand fetch failed: stock_code=%s error=%s", code, exc)
                return "unavailable"
            finally:
                self._close_providers([quote_provider, minute_provider])

    async def pool(self, pool_code: str) -> dict | None:
        return self._pool_summaries.get(pool_code)

    async def sectors(self, *, sector_type: str | None = None, limit: int = 50) -> dict:
        items = list(self._sector_strength.values())
        if sector_type:
            items = [item for item in items if item["sector_type"] == sector_type]
        items.sort(key=lambda item: (item.get("change_pct") is None, -(item.get("change_pct") or 0), -(item.get("coverage_pct") or 0)))
        return {"as_of": self._market_overview.get("as_of"), "round_id": self._market_overview.get("round_id"), "items": items[:limit]}

    async def subscribe(self, topics: set[str]):
        subscriber_id = uuid.uuid4().hex
        queue: asyncio.Queue = asyncio.Queue(maxsize=16)
        self._subscribers[subscriber_id] = (topics or {"market_overview"}, queue)
        try:
            yield {"topic": "connected", "data": {"subscriber_id": subscriber_id, "topics": sorted(topics)}}
            while True:
                yield await queue.get()
        finally:
            self._subscribers.pop(subscriber_id, None)

    async def _run_loop(self) -> None:
        while self._running:
            try:
                settings = await self._load_settings(force=True)
                now = datetime.now(tz=SHANGHAI)
                if settings.enabled and await self._is_open_market_session(now):
                    started = clock.monotonic()
                    await self._refresh_round(settings)
                    await asyncio.sleep(max(1, settings.full_market_interval_seconds - (clock.monotonic() - started)))
                else:
                    await asyncio.sleep(10)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._error = f"{type(exc).__name__}: {exc}"
                logger.exception("realtime market runtime round failed")
                await asyncio.sleep(10)

    async def _refresh_round(self, settings: RealtimeSettings, *, force: bool = False) -> None:
        async with self._refresh_lock:
            now = datetime.now(tz=SHANGHAI)
            if not force and not await self._is_open_market_session(now):
                return
            await self._ensure_reference(settings)
            if not self._active_codes:
                self._error = "未加载到沪深 active 股票范围"
                return
            quote_started = clock.monotonic()
            round_id = uuid.uuid4().hex[:16]
            quotes, batch_errors, quote_transport_failed = await self._fetch_quotes(settings)
            expected_count = len(self._active_codes)
            received_codes = {item["stock_code"] for item in quotes}
            failure_ratio = len(batch_errors) / max(1, math.ceil(expected_count / settings.quote_batch_size))
            degraded = quote_transport_failed or failure_ratio > settings.round_failure_threshold
            if quotes and not degraded:
                for quote in quotes:
                    self._quotes[quote["stock_code"]] = quote
                self._market_overview = self._build_market_overview(round_id)
                self._sector_strength = self._build_sector_strength(round_id)
                self._pool_summaries = self._build_pool_summaries(round_id)
                await self._persist_quote_caches(settings)
                await self._publish("market_overview", self._market_overview)
                await self._publish("sectors", {"as_of": self._market_overview.get("as_of"), "round_id": round_id, "items": list(self._sector_strength.values())})
                for pool_code, summary in self._pool_summaries.items():
                    await self._publish(f"pool:{pool_code}", summary)
                for code in list(self._page_targets):
                    await self._publish(f"stock:{code}", await self.stock(code))
            self._last_quote_round = RealtimeRoundMeta(
                round_id=round_id,
                started_at=now.astimezone(ZoneInfo("UTC")),
                finished_at=datetime.now(tz=ZoneInfo("UTC")),
                provider=settings.quote_provider,
                expected_count=expected_count,
                received_count=len(received_codes),
                missing_count=max(0, expected_count - len(received_codes)),
                failed_batch_count=len(batch_errors),
                duration_ms=int((clock.monotonic() - quote_started) * 1000),
                degraded=degraded,
                error_samples=batch_errors[:5],
            )
            if degraded:
                self._error = "全市场 quote 失败批次比例超过阈值，已保留上一轮缓存"
                logger.warning("realtime quote round degraded: round_id=%s expected=%s received=%s errors=%s", round_id, expected_count, len(received_codes), len(batch_errors))
                # Minute-line guarantees are independent from the full-market quote feed.
                # Holding/focus/page targets still need their refresh when quote_batch is degraded.
                if self._is_continuous_market_session(now) and (force or clock.monotonic() - self._last_minute_refresh_clock >= settings.minute_refresh_interval_seconds):
                    await self._refresh_minutes(settings, round_id)
                    self._last_minute_refresh_clock = clock.monotonic()
                return
            self._error = None
            if self._is_continuous_market_session(now) and (force or clock.monotonic() - self._last_minute_refresh_clock >= settings.minute_refresh_interval_seconds):
                await self._refresh_minutes(settings, round_id)
                self._last_minute_refresh_clock = clock.monotonic()
            logger.info(
                "realtime market round completed: round_id=%s quote=%s/%s minute=%s/%s quote_ms=%s minute_ms=%s",
                round_id,
                len(received_codes),
                expected_count,
                self._last_minute_round.updated_count,
                self._last_minute_round.selected_count,
                self._last_quote_round.duration_ms,
                self._last_minute_round.duration_ms,
            )

    async def _ensure_reference(self, settings: RealtimeSettings) -> None:
        if self._reference_loaded_at and clock.monotonic() - self._reference_loaded_clock < settings.reference_refresh_seconds:
            return
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            repository = RealtimeMarketRepository(session)
            active_codes, stock_names = await repository.active_stock_reference()
            sector_info, sector_members, stock_sectors = await repository.sector_reference()
            pools = await repository.pool_reference(active_codes)
        self._active_codes = active_codes
        self._stock_names = stock_names
        self._sector_info = sector_info
        self._sector_members = sector_members
        self._stock_sectors = stock_sectors
        self._pools = pools
        self._reference_loaded_at = datetime.now(tz=ZoneInfo("UTC"))
        self._reference_loaded_clock = clock.monotonic()
        logger.info("realtime reference loaded: active=%s sectors=%s pools=%s", len(active_codes), len(sector_info), len(pools))

    async def _fetch_quotes(self, settings: RealtimeSettings) -> tuple[list[dict], list[str], bool]:
        await self._ensure_provider_pools(settings)
        batches = [self._active_codes[index:index + settings.quote_batch_size] for index in range(0, len(self._active_codes), settings.quote_batch_size)]
        queue: asyncio.Queue[list[str]] = asyncio.Queue()
        for batch in batches:
            queue.put_nowait(batch)
        rows: list[dict] = []
        errors: list[str] = []
        transport_failed = asyncio.Event()

        async def worker(provider: TickflowQuoteProvider | MootdxProvider) -> None:
            while True:
                if transport_failed.is_set():
                    return
                try:
                    batch = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    result, _ = await provider.quote_batch(batch)
                    normalized = [self._normalize_quote(item) for item in result if item.get("stock_code")]
                    if not normalized:
                        errors.append(f"quote_batch[{batch[0]}..{batch[-1]}]: no_quote_data")
                        continue
                    rows.extend(normalized)
                except Exception as exc:
                    errors.append(f"quote_batch[{batch[0]}..{batch[-1]}]: {type(exc).__name__}: {exc}")
                    transport_failed.set()

        await asyncio.gather(*(worker(provider) for provider in self._quote_providers))
        return rows, errors, transport_failed.is_set()

    async def _refresh_minutes(self, settings: RealtimeSettings, round_id: str) -> None:
        started = clock.monotonic()
        registered = self._registered_minute_targets(settings)
        selected = self._select_minute_targets(registered, settings)
        await self._ensure_provider_pools(settings)
        queue: asyncio.Queue[str] = asyncio.Queue()
        for code in selected:
            queue.put_nowait(code)
        updated = 0
        empty = 0
        errors: list[str] = []
        transport_failed = asyncio.Event()

        async def worker(provider: MootdxProvider) -> None:
            nonlocal updated, empty
            while True:
                if transport_failed.is_set():
                    return
                try:
                    code = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    rows, _ = await provider.minute_bars(code)
                    timestamp = datetime.now(tz=ZoneInfo("UTC"))
                    if not rows:
                        empty += 1
                        self._minute_meta_by_stock[code] = {"status": "no_intraday_data", "updated_at": timestamp.isoformat(), "round_id": round_id, "source": "mootdx"}
                        continue
                    clean_rows = [self._normalize_minute(row) for row in rows]
                    self._minutes[code] = clean_rows
                    self._minute_meta_by_stock[code] = {
                        "status": "available",
                        "updated_at": timestamp.isoformat(),
                        "bar_count": len(clean_rows),
                        "round_id": round_id,
                        "source": "mootdx",
                        "features": self._minute_features(clean_rows),
                    }
                    updated += 1
                    await self._persist_minute_cache(code, clean_rows, self._minute_meta_by_stock[code])
                    await self._publish(f"stock:{code}", await self.stock(code))
                except Exception as exc:
                    errors.append(f"minute[{code}]: {type(exc).__name__}: {exc}")
                    self._minute_meta_by_stock[code] = {"status": "provider_error", "updated_at": datetime.now(tz=ZoneInfo("UTC")).isoformat(), "source": "mootdx"}
                    transport_failed.set()

        await asyncio.gather(*(worker(provider) for provider in self._minute_providers))
        self._last_minute_round = RealtimeMinuteMeta(
            selected_count=len(selected),
            registered_count=len(registered),
            updated_count=updated,
            no_intraday_data_count=empty,
            failed_count=len(errors),
            duration_ms=int((clock.monotonic() - started) * 1000),
            error_samples=errors[:5],
        )

    async def _is_open_market_session(self, now: datetime) -> bool:
        if not self._is_market_session(now):
            return False
        trade_date = now.date()
        if trade_date in self._trade_day_cache:
            return self._trade_day_cache[trade_date]
        sessionmaker = get_sessionmaker()
        try:
            async with sessionmaker() as session:
                value = await RealtimeMarketRepository(session).is_open_trade_date(trade_date)
        except Exception as exc:
            self._error = f"trade calendar check failed: {type(exc).__name__}: {exc}"
            logger.warning("realtime trade calendar check failed: %s", exc)
            return False
        self._trade_day_cache = {trade_date: value}
        return value

    def _registered_minute_targets(self, settings: RealtimeSettings) -> list[str]:
        now = clock.monotonic()
        self._page_targets = {code: expires_at for code, expires_at in self._page_targets.items() if expires_at > now}
        priority_codes: list[str] = []
        for pool_code in ("holding", "focus"):
            priority_codes.extend(self._pools.get(pool_code, {}).get("stock_codes", []))
        priority_codes.extend(self._page_targets.keys())
        candidates = sorted(
            self._quotes.values(),
            key=lambda item: (abs(float(item.get("change_pct") or 0)), float(item.get("amount_yuan") or 0)),
            reverse=True,
        )[:settings.strong_candidate_limit]
        codes = list(dict.fromkeys([*priority_codes, *(item["stock_code"] for item in candidates)]))
        # Quote can be temporarily degraded while minute(symbol) remains healthy. Fill the
        # remaining watch capacity from the active universe so the 200-stock guarantee is
        # still meaningful instead of collapsing to an empty target set.
        if len(codes) < settings.minute_registered_target_limit:
            existing_codes = set(codes)
            codes.extend(code for code in self._active_codes if code not in existing_codes)
        return codes[:settings.minute_registered_target_limit]

    def _select_minute_targets(self, registered: list[str], settings: RealtimeSettings) -> list[str]:
        guaranteed = settings.minute_guaranteed_target_count
        if len(registered) <= guaranteed:
            return registered
        fixed = []
        for pool_code in ("holding", "focus"):
            fixed.extend(self._pools.get(pool_code, {}).get("stock_codes", []))
        fixed.extend(self._page_targets.keys())
        fixed = list(dict.fromkeys(code for code in fixed if code in registered))[:guaranteed]
        remaining_slots = max(0, guaranteed - len(fixed))
        rotating = [code for code in registered if code not in fixed]
        if remaining_slots and rotating:
            offset = self._rotation_cursor % len(rotating)
            selected_candidates = (rotating[offset:] + rotating[:offset])[:remaining_slots]
            self._rotation_cursor += remaining_slots
            return [*fixed, *selected_candidates]
        return fixed

    def _build_market_overview(self, round_id: str) -> dict:
        values = list(self._quotes.values())
        change_values = [float(item["change_pct"]) for item in values if item.get("change_pct") is not None]
        up = sum(1 for value in change_values if value > 0)
        down = sum(1 for value in change_values if value < 0)
        flat = len(change_values) - up - down
        return {
            "as_of": datetime.now(tz=ZoneInfo("UTC")).isoformat(),
            "round_id": round_id,
            "provider": next((str(item.get("source")) for item in values if item.get("source")), self._settings.quote_provider),
            "items": {
                "quote_count": len(values),
                "up_count": up,
                "down_count": down,
                "flat_count": flat,
                "average_change_pct": round(sum(change_values) / len(change_values), 4) if change_values else None,
                "total_amount_yuan": sum(float(item.get("amount_yuan") or 0) for item in values),
                "top_gainers": self._rank_quotes(values, reverse=True),
                "top_losers": self._rank_quotes(values, reverse=False),
            },
        }

    def _build_sector_strength(self, round_id: str) -> dict[str, dict]:
        result: dict[str, dict] = {}
        for sector_code, members in self._sector_members.items():
            quotes = [self._quotes[code] for code in members if code in self._quotes and self._quotes[code].get("change_pct") is not None]
            if not quotes:
                continue
            changes = [float(item["change_pct"]) for item in quotes]
            leader = max(quotes, key=lambda item: float(item.get("change_pct") or 0))
            info = self._sector_info[sector_code]
            result[sector_code] = {
                **info,
                "as_of": self._market_overview.get("as_of"),
                "round_id": round_id,
                "member_count": len(members),
                "quote_count": len(quotes),
                "coverage_pct": round(len(quotes) / max(1, len(members)) * 100, 2),
                "change_pct": round(sum(changes) / len(changes), 4),
                "up_count": sum(1 for value in changes if value > 0),
                "down_count": sum(1 for value in changes if value < 0),
                "flat_count": sum(1 for value in changes if value == 0),
                "amount_yuan": sum(float(item.get("amount_yuan") or 0) for item in quotes),
                "leader": {"stock_code": leader["stock_code"], "stock_name": leader.get("stock_name"), "change_pct": leader.get("change_pct"), "last_price": leader.get("last_price")},
            }
        return result

    def _build_pool_summaries(self, round_id: str) -> dict[str, dict]:
        result: dict[str, dict] = {}
        for pool_code, pool in self._pools.items():
            codes = pool["stock_codes"]
            quotes = [self._quotes[code] for code in codes if code in self._quotes and self._quotes[code].get("change_pct") is not None]
            changes = [float(item["change_pct"]) for item in quotes]
            result[pool_code] = {
                "pool_code": pool_code,
                "pool_name": pool["pool_name"],
                "as_of": self._market_overview.get("as_of"),
                "round_id": round_id,
                "member_count": len(codes),
                "quote_count": len(quotes),
                "coverage_pct": round(len(quotes) / max(1, len(codes)) * 100, 2),
                "up_count": sum(1 for value in changes if value > 0),
                "down_count": sum(1 for value in changes if value < 0),
                "average_change_pct": round(sum(changes) / len(changes), 4) if changes else None,
                "amount_yuan": sum(float(item.get("amount_yuan") or 0) for item in quotes),
                "leaders": self._rank_quotes(quotes, reverse=True, limit=5),
            }
        return result

    async def _persist_quote_caches(self, settings: RealtimeSettings) -> None:
        ttl = settings.cache_ttl_seconds
        await redis_client.set_json(await redis_client.key("realtime", "quotes"), self._quotes, ttl_seconds=ttl)
        await redis_client.set_json(await redis_client.key("realtime", "market-overview"), self._market_overview, ttl_seconds=ttl)
        await redis_client.set_json(await redis_client.key("realtime", "sectors"), list(self._sector_strength.values()), ttl_seconds=ttl)
        await redis_client.set_json(await redis_client.key("realtime", "pools"), self._pool_summaries, ttl_seconds=ttl)

    async def _persist_minute_cache(self, code: str, rows: list[dict], meta: dict) -> None:
        ttl = self._minute_session_ttl()
        await redis_client.set_json(await redis_client.key("realtime", "minutes", code), {"items": rows, "meta": meta}, ttl_seconds=ttl)

    async def _publish(self, topic: str, payload: dict) -> None:
        event = {"topic": topic, "data": payload}
        for topics, queue in list(self._subscribers.values()):
            if topic not in topics and "*" not in topics:
                continue
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    pass

    async def _ensure_provider_pools(self, settings: RealtimeSettings) -> None:
        if settings.quote_provider == "tickflow":
            sessionmaker = get_sessionmaker()
            async with sessionmaker() as session:
                credentials = await TickflowProviderFactory(ConfigCenterRepository(session)).resolve_credentials()
            identity = ("tickflow", credentials.fingerprint, credentials.endpoint_url, credentials.timeout_seconds)
            if identity != self._quote_provider_identity:
                self._close_providers(self._quote_providers)
                self._quote_providers = []
                self._quote_provider_identity = identity
            self._tickflow_credentials = credentials
        else:
            identity = ("mootdx", None)
            if identity != self._quote_provider_identity:
                self._close_providers(self._quote_providers)
                self._quote_providers = []
                self._quote_provider_identity = identity
            self._tickflow_credentials = None
        self._resize_quote_pool(settings.quote_provider_pool_size, settings.quote_provider)
        self._resize_minute_pool(settings.minute_provider_pool_size)

    def _resize_quote_pool(self, expected_size: int, provider_code: str) -> None:
        if len(self._quote_providers) == expected_size:
            return
        self._close_providers(self._quote_providers)
        self._quote_providers = [self._new_quote_provider(provider_code) for _ in range(expected_size)]

    def _resize_minute_pool(self, expected_size: int) -> None:
        if len(self._minute_providers) == expected_size:
            return
        self._close_providers(self._minute_providers)
        self._minute_providers = [self._new_minute_provider() for _ in range(expected_size)]

    def _new_quote_provider(self, provider_code: str) -> TickflowQuoteProvider | MootdxProvider:
        if provider_code == "mootdx":
            return self._new_minute_provider()
        if self._tickflow_credentials is None:
            raise RuntimeError("TickFlow quote credentials are not loaded")
        return TickflowQuoteProvider(self._tickflow_credentials)

    @staticmethod
    def _new_minute_provider() -> MootdxProvider:
        provider = MootdxProvider()
        provider.timeout_seconds = 5
        provider.auto_retry = 1
        provider.fallback_server_limit = 2
        return provider

    @staticmethod
    def _close_providers(providers: list[object]) -> None:
        for provider in providers:
            close = getattr(provider, "close", None)
            if callable(close):
                try:
                    close()
                except Exception as exc:  # pragma: no cover - defensive close only.
                    logger.debug("realtime provider close ignored: %s", exc)

    async def _load_settings(self, *, force: bool = False) -> RealtimeSettings:
        if not force and clock.monotonic() - self._settings_loaded_at < 30:
            return self._settings
        sessionmaker = get_sessionmaker()
        try:
            async with sessionmaker() as session:
                repository = ConfigCenterRepository(session)
                config = await repository.find_config(category_code="market_data", config_code="realtime_market")
                if config is None:
                    self._settings = RealtimeSettings(enabled=False)
                else:
                    options = {option.option_key: option.option_value for option in await repository.list_options(config.id, only_enabled=True)}
                    self._settings = RealtimeSettings(enabled=bool(config.is_enabled) and self._as_bool(options.get("enabled", False)), **{key: value for key, value in options.items() if key != "enabled"})
        except Exception as exc:
            self._error = f"realtime config load failed: {type(exc).__name__}: {exc}"
            logger.warning("realtime config load failed; preserving previous settings: %s", exc)
        self._settings_loaded_at = clock.monotonic()
        return self._settings

    def _normalize_quote(self, row: dict) -> dict:
        stock_code = normalize_symbol(str(row.get("stock_code") or ""))
        return {
            "stock_code": stock_code,
            "stock_name": row.get("stock_name") or self._stock_names.get(stock_code),
            "quote_time": row.get("quote_time").isoformat() if isinstance(row.get("quote_time"), datetime) else str(row.get("quote_time") or ""),
            "source": str(row.get("source") or "mootdx"),
            "source_symbol": row.get("source_symbol"),
            "session": row.get("session"),
            "last_price": row.get("last_price"),
            "pre_close_price": row.get("pre_close_price"),
            "change_amount": row.get("change_amount"),
            "change_pct": row.get("change_pct"),
            "open_price": row.get("open_price"),
            "high_price": row.get("high_price"),
            "low_price": row.get("low_price"),
            "volume_hand": row.get("volume_hand"),
            "volume_share": row.get("volume_share"),
            "amount_yuan": row.get("amount_yuan"),
            "metadata": row.get("metadata_json") if isinstance(row.get("metadata_json"), dict) else None,
        }

    @staticmethod
    def _normalize_minute(row: dict) -> dict:
        return {
            "stock_code": row.get("stock_code"),
            "trade_date": row.get("bar_time").date().isoformat() if isinstance(row.get("bar_time"), datetime) else None,
            "bar_time": row.get("bar_time").isoformat() if isinstance(row.get("bar_time"), datetime) else str(row.get("bar_time") or ""),
            "interval": "1m",
            "source": "mootdx",
            "price": row.get("price"),
            "avg_price": None,
            "volume_hand": row.get("volume_hand"),
            "volume_share": row.get("volume_share"),
            "amount_yuan": None,
        }

    @staticmethod
    def _minute_features(rows: list[dict]) -> dict:
        prices = [float(row["price"]) for row in rows if row.get("price") is not None]
        volumes = [float(row["volume_share"] or 0) for row in rows]
        if not prices:
            return {"available": False, "reason": "price_missing"}
        latest = prices[-1]
        def change(window: int) -> float | None:
            if len(prices) <= window or prices[-window - 1] == 0:
                return None
            return round((latest / prices[-window - 1] - 1) * 100, 4)
        recent = volumes[-5:]
        prior = volumes[-25:-5]
        recent_average = sum(recent) / max(1, len(recent))
        prior_average = sum(prior) / max(1, len(prior))
        return {
            "available": True,
            "minute_return_1m": change(1),
            "minute_return_5m": change(5),
            "minute_return_15m": change(15),
            "minute_volume": volumes[-1] if volumes else None,
            "volume_spike_ratio": round(recent_average / prior_average, 4) if prior_average > 0 else None,
            "intraday_trend": round((latest / prices[0] - 1) * 100, 4) if prices[0] else None,
            "intraday_high_breakout": latest >= max(prices),
            "intraday_strength": round((latest - min(prices)) / (max(prices) - min(prices)), 4) if max(prices) > min(prices) else None,
            "vwap": None,
            "amount_based_features_available": False,
        }

    @staticmethod
    def _rank_quotes(items: list[dict], *, reverse: bool, limit: int = 10) -> list[dict]:
        ranked = [item for item in items if item.get("change_pct") is not None]
        ranked.sort(key=lambda item: float(item.get("change_pct") or 0), reverse=reverse)
        return [
            {key: item.get(key) for key in ("stock_code", "stock_name", "last_price", "change_pct", "amount_yuan")}
            for item in ranked[:limit]
        ]

    @staticmethod
    def _is_market_session(now: datetime) -> bool:
        if now.weekday() >= 5:
            return False
        current = now.timetz().replace(tzinfo=None)
        # TickFlow quote polling also covers the opening auction. MooTDX minute
        # bars are deliberately gated by _is_continuous_market_session below.
        return time(9, 15) <= current <= time(11, 30) or time(12, 55) <= current <= time(15, 0)

    @staticmethod
    def _is_continuous_market_session(now: datetime) -> bool:
        if now.weekday() >= 5:
            return False
        current = now.timetz().replace(tzinfo=None)
        return time(9, 30) <= current <= time(11, 30) or time(13, 0) <= current <= time(15, 0)

    @staticmethod
    def _as_bool(value: object) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
        return bool(value)

    @staticmethod
    def _minute_session_ttl() -> int:
        now = datetime.now(tz=SHANGHAI)
        expiry = datetime.combine(now.date(), time(15, 20), tzinfo=SHANGHAI)
        return max(60, int((expiry - now).total_seconds()))

    @staticmethod
    def _is_stale(quote: dict | None, settings: RealtimeSettings, now: datetime) -> bool:
        if quote is None or not quote.get("quote_time"):
            return True
        try:
            quote_time = datetime.fromisoformat(str(quote["quote_time"]))
            if quote_time.tzinfo is None:
                quote_time = quote_time.replace(tzinfo=ZoneInfo("UTC"))
            return now.astimezone(ZoneInfo("UTC")) - quote_time.astimezone(ZoneInfo("UTC")) > timedelta(seconds=settings.stale_after_seconds)
        except ValueError:
            return True

    def _stock_cache_errors(self, code: str, settings: RealtimeSettings) -> list[str]:
        if not settings.enabled and code not in self._quotes and code not in self._minutes:
            return ["realtime_runtime_disabled"]
        if code not in self._quotes and code not in self._minutes:
            return ["realtime_cache_miss"]
        return []


realtime_market_service = RealtimeMarketService()
