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
from app.modules.realtime_market.rate_limit import RealtimeRateBudget
from app.modules.realtime_market.schemas import RealtimeBlockMeta, RealtimeMinuteMeta, RealtimeRoundMeta, RealtimeSettings, RealtimeStatus
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
        self._blocks: dict[str, RealtimeBlockMeta] = {
            "market": RealtimeBlockMeta(block="market"),
            "decision_quote": RealtimeBlockMeta(block="decision_quote"),
            "depth": RealtimeBlockMeta(block="depth"),
            "minute": RealtimeBlockMeta(block="minute"),
        }
        self._depth_by_stock: dict[str, dict] = {}
        self._depth_history_by_stock: dict[str, list[dict]] = {}
        self._decision_targets: list[dict] = []
        self._warm_targets: list[dict] = []
        self._last_market_refresh_clock = 0.0
        self._last_decision_refresh_clock = 0.0
        self._last_warm_refresh_clock = 0.0
        self._last_depth_refresh_clock = 0.0
        self._rate_budgets: dict[str, RealtimeRateBudget] = {}
        self._rate_signature: tuple[object, ...] | None = None
        self._leader_owner = f"{uuid.uuid4().hex}:{id(self)}"
        self._leader_active = False
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
        await redis_client.release_lease(await redis_client.key("realtime", "leader"), self._leader_owner)
        self._leader_active = False
        logger.info("realtime market runtime stopped")

    async def status(self) -> dict:
        settings = await self._load_settings()
        runtime_config = await redis_client.runtime_config()
        backend = "memory"
        if runtime_config.cache_backend != "memory" and runtime_config.redis_url:
            backend = "redis" if await redis_client.ping() else "memory_fallback"
        now = datetime.now(tz=SHANGHAI)
        stale_count = sum(1 for quote in self._quotes.values() if self._is_stale(quote, settings, now))
        rate_budgets = {name: await budget.snapshot() for name, budget in self._rate_budgets.items()}
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
            market=self._blocks["market"],
            decision_quote=self._blocks["decision_quote"],
            depth=self._blocks["depth"],
            minute=self._blocks["minute"],
            rate_budgets=rate_budgets,
            leader_active=self._leader_active,
            depth_cache_count=len(self._depth_by_stock),
            decision_target_count=len(self._decision_targets),
            warm_target_count=len(self._warm_targets),
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
            "depth": self._depth_by_stock.get(code),
            "depth_history": self._depth_history_by_stock.get(code, []),
            "meta": {
                "query_mode": "realtime_cache",
                "resolved_source": quote.get("source") if quote else (meta.get("source") if meta else None),
                "attempted_engines": list(dict.fromkeys([settings.quote_provider, "mootdx"])),
                "quote_source": quote.get("source") if quote else None,
                "minute_source": meta.get("source") if meta else None,
                "fallback_used": False,
                "persisted": False,
                "cache": "realtime_market",
                "runtime_enabled": settings.enabled,
                "market_session": market_session,
                "cache_status": "hit" if (quote or code in self._minutes) else "miss",
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
        if code not in self._depth_by_stock:
            cached_depth = await redis_client.get_json(await redis_client.key("realtime", "depth", code))
            if isinstance(cached_depth, dict):
                current = cached_depth.get("current")
                history = cached_depth.get("history")
                if isinstance(current, dict):
                    self._depth_by_stock[code] = current
                if isinstance(history, list):
                    self._depth_history_by_stock[code] = history

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

    async def decision_targets(self) -> dict:
        return {
            "as_of": self._blocks["decision_quote"].finished_at,
            "hot": self._decision_targets,
            "warm": self._warm_targets,
            "hot_limit": self._settings.decision_target_limit,
        }

    async def depth(self, stock_codes: list[str] | None = None) -> dict:
        codes = [normalize_symbol(code) for code in stock_codes] if stock_codes else list(self._depth_by_stock)
        return {
            "as_of": self._blocks["depth"].finished_at,
            "round_id": self._blocks["depth"].round_id,
            "items": [
                {"stock_code": code, "current": self._depth_by_stock.get(code), "history": self._depth_history_by_stock.get(code, [])}
                for code in codes
                if code in self._depth_by_stock
            ],
        }

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
                settings = await self._load_settings()
                now = datetime.now(tz=SHANGHAI)
                if settings.enabled and await self._is_open_market_session(now):
                    await self._refresh_round(settings)
                    # Each block has its own cadence (60s market, 10s decision
                    # Quote/depth, 60s warm, 60s minute).  A short scheduler
                    # tick prevents a full-market refresh from delaying a
                    # candidate's next 10-second snapshot.
                    await asyncio.sleep(1)
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
            if not await self._acquire_leader(settings):
                await self._hydrate_shared_caches()
                return
            await self._ensure_reference(settings)
            if not self._active_codes:
                self._error = "未加载到沪深 active 股票范围"
                return
            now_clock = clock.monotonic()
            if force or now_clock - self._last_market_refresh_clock >= settings.full_market_interval_seconds:
                await self._refresh_market_quotes(settings)
                self._last_market_refresh_clock = clock.monotonic()
            decision_due = force or now_clock - self._last_decision_refresh_clock >= settings.decision_quote_interval_seconds
            warm_due = force or now_clock - self._last_warm_refresh_clock >= settings.warm_quote_interval_seconds
            if decision_due:
                # When both clocks are due, one hot+warm pass avoids querying
                # the 200 hot symbols twice in the same second.
                await self._refresh_decision_quotes(settings, include_warm=warm_due)
                self._last_decision_refresh_clock = clock.monotonic()
                if warm_due:
                    self._last_warm_refresh_clock = clock.monotonic()
            elif warm_due:
                await self._refresh_decision_quotes(settings, include_warm=True)
                self._last_warm_refresh_clock = clock.monotonic()
            depth_interval = settings.auction_depth_refresh_interval_seconds if self._is_opening_depth_session(now) else settings.depth_refresh_interval_seconds
            if force or now_clock - self._last_depth_refresh_clock >= depth_interval:
                await self._refresh_depth(settings)
                self._last_depth_refresh_clock = clock.monotonic()
            if self._is_continuous_market_session(now) and (force or clock.monotonic() - self._last_minute_refresh_clock >= settings.minute_refresh_interval_seconds):
                await self._refresh_minutes(settings, uuid.uuid4().hex[:16])
                self._last_minute_refresh_clock = clock.monotonic()

    async def _ensure_reference(self, settings: RealtimeSettings) -> None:
        if self._reference_loaded_at and clock.monotonic() - self._reference_loaded_clock < settings.reference_refresh_seconds:
            return
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            repository = RealtimeMarketRepository(session)
            active_codes, stock_names = await repository.active_stock_reference()
            sector_info, sector_members, stock_sectors = await repository.sector_reference()
            industry_info, industry_members, stock_industries = await repository.industry_universe_reference()
            pools = await repository.pool_reference(active_codes)
        self._active_codes = active_codes
        self._stock_names = stock_names
        self._sector_info = {**sector_info, **industry_info}
        self._sector_members = {**sector_members, **industry_members}
        self._stock_sectors = {**stock_sectors}
        for stock_code, codes in stock_industries.items():
            self._stock_sectors.setdefault(stock_code, []).extend(codes)
        self._pools = pools
        self._reference_loaded_at = datetime.now(tz=ZoneInfo("UTC"))
        self._reference_loaded_clock = clock.monotonic()
        logger.info("realtime reference loaded: active=%s concepts=%s tickflow_industries=%s pools=%s", len(active_codes), len(sector_info), len(industry_info), len(pools))

    async def _acquire_leader(self, settings: RealtimeSettings) -> bool:
        self._leader_active = await redis_client.acquire_lease(
            await redis_client.key("realtime", "leader"), self._leader_owner, ttl_seconds=settings.leader_lease_seconds
        )
        return self._leader_active

    async def _hydrate_shared_caches(self) -> None:
        """A follower serves the current Redis snapshot but never spends provider quota."""
        if not self._market_overview.get("as_of"):
            overview = await redis_client.get_json(await redis_client.key("realtime", "market-overview"))
            if isinstance(overview, dict):
                self._market_overview = overview
        if not self._sector_strength:
            sectors = await redis_client.get_json(await redis_client.key("realtime", "sectors"))
            if isinstance(sectors, list):
                self._sector_strength = {str(item.get("sector_code")): item for item in sectors if isinstance(item, dict) and item.get("sector_code")}
        if not self._pool_summaries:
            pools = await redis_client.get_json(await redis_client.key("realtime", "pools"))
            if isinstance(pools, dict):
                self._pool_summaries = pools

    async def _refresh_market_quotes(self, settings: RealtimeSettings) -> None:
        started = clock.monotonic()
        round_id = uuid.uuid4().hex[:16]
        errors: list[str] = []
        rows: list[dict] = []
        request_count = 0
        try:
            await self._ensure_provider_pools(settings)
            if settings.quote_provider != "tickflow" or not self._quote_providers:
                raise RuntimeError("第一期全市场 Quote 仅支持已验证的 TickFlow 标的池接口")
            await self._rate_budgets["quote_universe"].acquire()
            request_count = 1
            result, _ = await self._quote_providers[0].universe_quotes("CN_Equity_A")
            active_set = set(self._active_codes)
            rows = [self._normalize_quote(item) for item in result if normalize_symbol(str(item.get("stock_code") or "")) in active_set]
            if not rows:
                errors.append("quote_universe: no eligible A-share quote data")
        except Exception as exc:
            errors.append(f"quote_universe: {type(exc).__name__}: {exc}")
            await self._record_rate_limit_if_needed("quote_universe", exc)

        received_codes = {item["stock_code"] for item in rows}
        degraded = bool(errors) or len(received_codes) < max(1, int(len(self._active_codes) * 0.95))
        if rows and not degraded:
            self._quotes.update({item["stock_code"]: item for item in rows})
            self._market_overview = self._build_market_overview(round_id)
            self._sector_strength = self._build_sector_strength(round_id)
            self._pool_summaries = self._build_pool_summaries(round_id)
            await self._persist_quote_caches(settings)
            await self._publish("market_overview", self._market_overview)
            await self._publish("sectors", {"as_of": self._market_overview.get("as_of"), "round_id": round_id, "items": list(self._sector_strength.values())})
            for pool_code, summary in self._pool_summaries.items():
                await self._publish(f"pool:{pool_code}", summary)

        meta = self._block_meta(
            "market", round_id, started, settings.quote_provider, len(self._active_codes), len(received_codes), len(errors), errors,
            request_count=request_count, degraded=degraded,
            degraded_reason="coverage_below_95_pct_or_provider_error" if degraded else None,
        )
        self._blocks["market"] = meta
        self._last_quote_round = RealtimeRoundMeta(**meta.model_dump(exclude={"block", "request_count", "coverage_pct", "cache_freshness_seconds", "rate_limited_count", "network_error_count", "degraded_reason"}))
        if degraded:
            self._error = "全市场 TickFlow 标的池 Quote 不完整，已保留上一轮缓存"
        else:
            self._error = None

    def _build_decision_targets(self, settings: RealtimeSettings) -> tuple[list[dict], list[dict]]:
        now = clock.monotonic()
        self._page_targets = {code: expires_at for code, expires_at in self._page_targets.items() if expires_at > now}
        active_set = set(self._active_codes)
        ranked: list[tuple[str, str, int, float]] = []
        priority_pools = (("holding", 0), ("focus", 1), ("candidate", 2), ("strategy", 3), ("breakout_retake", 3))
        for pool_code, priority in priority_pools:
            for code in self._pools.get(pool_code, {}).get("stock_codes", []):
                if code in active_set:
                    quote = self._quotes.get(code, {})
                    signal_score = abs(float(quote.get("change_pct") or 0)) + min(20.0, math.log10(max(1.0, float(quote.get("amount_yuan") or 0))) - 5.0)
                    ranked.append((code, f"pool:{pool_code}", priority, signal_score))
        for code in self._page_targets:
            if code in active_set:
                ranked.append((code, "page_watch", 4, 0.0))
        strong = sorted(
            (item for item in self._quotes.values() if item.get("stock_code") in active_set),
            key=lambda item: (abs(float(item.get("change_pct") or 0)), float(item.get("amount_yuan") or 0)),
            reverse=True,
        )[:settings.strong_candidate_limit]
        ranked.extend((item["stock_code"], "strong", 5, abs(float(item.get("change_pct") or 0))) for item in strong)
        deduped: list[dict] = []
        seen: set[str] = set()
        for code, reason, priority, signal_score in sorted(ranked, key=lambda item: (item[2], -item[3], item[0])):
            if code in seen:
                continue
            seen.add(code)
            deduped.append(
                {
                    "stock_code": code,
                    "stock_name": self._stock_names.get(code),
                    "reason": reason,
                    "priority": priority,
                    "signal_score": round(signal_score, 4),
                    "promotion_reason": "priority_pool" if priority <= 1 else "latest_quote_strength",
                }
            )
        return deduped[:settings.decision_target_limit], deduped[settings.decision_target_limit:]

    async def _refresh_decision_quotes(self, settings: RealtimeSettings, *, include_warm: bool) -> None:
        started = clock.monotonic()
        round_id = uuid.uuid4().hex[:16]
        hot, warm = self._build_decision_targets(settings)
        self._decision_targets, self._warm_targets = hot, warm
        targets = hot + (warm if include_warm else [])
        rows, errors, request_count = await self._fetch_quote_codes([item["stock_code"] for item in targets], settings)
        if rows:
            previous = {item["stock_code"]: self._quotes.get(item["stock_code"]) for item in rows}
            self._quotes.update({item["stock_code"]: item for item in rows})
            hot_codes = {item["stock_code"] for item in hot}
            changed = [
                (await redis_client.key("realtime", "quote", item["stock_code"]), item, settings.cache_ttl_seconds)
                for item in rows
                if item["stock_code"] in hot_codes and self._quote_changed(previous.get(item["stock_code"]), item)
            ]
            await redis_client.set_many_json(changed)
            for code in hot_codes.intersection({item["stock_code"] for item in rows}):
                await self._publish(f"stock:{code}", await self.stock(code))
        expected = len(targets)
        meta = self._block_meta(
            "decision_quote", round_id, started, settings.quote_provider, expected, len({item["stock_code"] for item in rows}), len(errors), errors,
            request_count=request_count, degraded=bool(errors), degraded_reason="batch_request_error" if errors else None,
        )
        self._blocks["decision_quote"] = meta

    async def _fetch_quote_codes(self, codes: list[str], settings: RealtimeSettings) -> tuple[list[dict], list[str], int]:
        await self._ensure_provider_pools(settings)
        rows: list[dict] = []
        errors: list[str] = []
        requests = 0
        provider = self._quote_providers[0] if self._quote_providers else None
        if provider is None:
            return rows, ["quote_batch: provider unavailable"], requests
        for offset in range(0, len(codes), settings.quote_batch_size):
            batch = codes[offset : offset + settings.quote_batch_size]
            if not batch:
                continue
            try:
                await self._rate_budgets["quote_symbols"].acquire()
                requests += 1
                result, _ = await provider.quote_batch(batch)
                normalized = [self._normalize_quote(item) for item in result if item.get("stock_code")]
                if not normalized:
                    errors.append(f"quote_batch[{batch[0]}..{batch[-1]}]: no_quote_data")
                else:
                    rows.extend(normalized)
            except Exception as exc:
                errors.append(f"quote_batch[{batch[0]}..{batch[-1]}]: {type(exc).__name__}: {exc}")
                await self._record_rate_limit_if_needed("quote_symbols", exc)
        return rows, errors, requests

    async def _refresh_depth(self, settings: RealtimeSettings) -> None:
        started = clock.monotonic()
        round_id = uuid.uuid4().hex[:16]
        codes = [item["stock_code"] for item in self._decision_targets[:settings.decision_target_limit]]
        rows: list[dict] = []
        errors: list[str] = []
        requests = 0
        if codes:
            try:
                await self._ensure_provider_pools(settings)
                provider = self._quote_providers[0] if self._quote_providers else None
                if not isinstance(provider, TickflowQuoteProvider):
                    raise RuntimeError("five-level depth requires TickFlow provider")
                await self._rate_budgets["depth_batch"].acquire()
                requests = 1
                rows = await provider.depth_batch(codes)
            except Exception as exc:
                errors.append(f"depth_batch: {type(exc).__name__}: {exc}")
                await self._record_rate_limit_if_needed("depth_batch", exc)
        changed: list[tuple[str, dict, int]] = []
        for row in rows:
            code = row["stock_code"]
            snapshot = {**row, "features": self._depth_features(row)}
            history = [snapshot, *self._depth_history_by_stock.get(code, [])][:3]
            self._depth_by_stock[code] = snapshot
            self._depth_history_by_stock[code] = history
            changed.append((await redis_client.key("realtime", "depth", code), {"current": snapshot, "history": history}, settings.depth_cache_ttl_seconds))
        await redis_client.set_many_json(changed)
        self._blocks["depth"] = self._block_meta(
            "depth", round_id, started, "tickflow", len(codes), len({row["stock_code"] for row in rows}), len(errors), errors,
            request_count=requests, degraded=bool(errors), degraded_reason="depth_batch_error" if errors else None,
        )

    def _block_meta(
        self,
        block: str,
        round_id: str,
        started: float,
        provider: str,
        expected_count: int,
        received_count: int,
        failed_count: int,
        errors: list[str],
        *,
        request_count: int,
        degraded: bool,
        degraded_reason: str | None,
    ) -> RealtimeBlockMeta:
        finished = datetime.now(tz=ZoneInfo("UTC"))
        return RealtimeBlockMeta(
            block=block,  # type: ignore[arg-type]
            round_id=round_id,
            started_at=finished - timedelta(milliseconds=int((clock.monotonic() - started) * 1000)),
            finished_at=finished,
            provider=provider,
            expected_count=expected_count,
            received_count=received_count,
            missing_count=max(0, expected_count - received_count),
            failed_batch_count=failed_count,
            duration_ms=int((clock.monotonic() - started) * 1000),
            degraded=degraded,
            error_samples=errors[:5],
            request_count=request_count,
            coverage_pct=round(received_count / max(1, expected_count) * 100, 2) if expected_count else None,
            cache_freshness_seconds=0,
            rate_limited_count=sum(1 for error in errors if "429" in error or "rate" in error.lower()),
            network_error_count=sum(1 for error in errors if "429" not in error),
            degraded_reason=degraded_reason,
        )

    @staticmethod
    def _depth_features(snapshot: dict) -> dict:
        bids = snapshot.get("bids") if isinstance(snapshot.get("bids"), list) else []
        asks = snapshot.get("asks") if isinstance(snapshot.get("asks"), list) else []
        bid_volume = sum(float(item.get("volume") or 0) for item in bids)
        ask_volume = sum(float(item.get("volume") or 0) for item in asks)
        bid1 = bids[0] if bids else {}
        ask1 = asks[0] if asks else {}
        bid_price = float(bid1.get("price")) if bid1.get("price") is not None else None
        ask_price = float(ask1.get("price")) if ask1.get("price") is not None else None
        return {
            "bid_volume_5": bid_volume,
            "ask_volume_5": ask_volume,
            "bid_ask_imbalance_5": round((bid_volume - ask_volume) / (bid_volume + ask_volume), 6) if bid_volume + ask_volume > 0 else None,
            "best_spread": round(ask_price - bid_price, 6) if ask_price is not None and bid_price is not None else None,
            "best_spread_pct": round((ask_price - bid_price) / ((ask_price + bid_price) / 2) * 100, 6) if ask_price is not None and bid_price is not None and ask_price + bid_price else None,
        }

    @staticmethod
    def _quote_changed(previous: dict | None, current: dict) -> bool:
        if previous is None:
            return True
        keys = ("quote_time", "last_price", "change_pct", "volume_share", "amount_yuan")
        return any(previous.get(key) != current.get(key) for key in keys)

    async def _record_rate_limit_if_needed(self, budget_name: str, exc: Exception) -> None:
        message = str(exc)
        if "429" not in message and "rate limit" not in message.lower() and "too many" not in message.lower():
            return
        cooldown_seconds = 300.0
        import re

        match = re.search(r"(?:retry[- ]after|cooldown)[^0-9]*(\d+(?:\.\d+)?)", message, flags=re.IGNORECASE)
        if match:
            cooldown_seconds = float(match.group(1))
        budget = self._rate_budgets.get(budget_name)
        if budget is not None:
            await budget.record_rate_limit(cooldown_seconds)

    async def _fetch_quotes(self, settings: RealtimeSettings) -> tuple[list[dict], list[str], bool]:
        await self._ensure_provider_pools(settings)
        batches = [self._active_codes[index:index + settings.quote_batch_size] for index in range(0, len(self._active_codes), settings.quote_batch_size)]
        queue: asyncio.Queue[list[str]] = asyncio.Queue()
        for batch in batches:
            queue.put_nowait(batch)
        rows: list[dict] = []
        errors: list[str] = []

        async def worker(provider: TickflowQuoteProvider | MootdxProvider) -> None:
            while True:
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

        await asyncio.gather(*(worker(provider) for provider in self._quote_providers))
        # A failed individual batch is isolated.  The caller decides whether
        # aggregate coverage is good enough; it must not stop the remaining
        # independent requests.
        return rows, errors, False

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
        cache_queue: asyncio.Queue[tuple[str, dict, int] | None] = asyncio.Queue(maxsize=max(16, len(selected)))

        async def cache_writer() -> None:
            """Consume completed network fetches while other MooTDX workers continue."""
            while True:
                item = await cache_queue.get()
                if item is None:
                    return
                batch = [item]
                while len(batch) < 50:
                    try:
                        queued = cache_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    if queued is None:
                        await redis_client.set_many_json(batch)
                        return
                    batch.append(queued)
                await redis_client.set_many_json(batch)

        writer_task = asyncio.create_task(cache_writer(), name="realtime-minute-cache-writer")

        async def worker(provider: MootdxProvider) -> None:
            nonlocal updated, empty
            while True:
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
                    await cache_queue.put((await redis_client.key("realtime", "minutes", code), {"items": clean_rows, "meta": self._minute_meta_by_stock[code]}, self._minute_session_ttl()))
                    await self._publish(f"stock:{code}", await self.stock(code))
                except Exception as exc:
                    errors.append(f"minute[{code}]: {type(exc).__name__}: {exc}")
                    self._minute_meta_by_stock[code] = {"status": "provider_error", "updated_at": datetime.now(tz=ZoneInfo("UTC")).isoformat(), "source": "mootdx"}

        try:
            await asyncio.gather(*(worker(provider) for provider in self._minute_providers))
        finally:
            await cache_queue.put(None)
            await writer_task
        self._last_minute_round = RealtimeMinuteMeta(
            selected_count=len(selected),
            registered_count=len(registered),
            updated_count=updated,
            no_intraday_data_count=empty,
            failed_count=len(errors),
            duration_ms=int((clock.monotonic() - started) * 1000),
            error_samples=errors[:5],
        )
        self._blocks["minute"] = self._block_meta(
            "minute", round_id, started, "mootdx", len(selected), updated, len(errors), errors,
            request_count=len(selected), degraded=bool(errors), degraded_reason="per_symbol_errors" if errors else None,
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
            median_change = self._median(changes)
            limit_up_count = sum(1 for item in quotes if self._is_limit_event(item, "up"))
            limit_down_count = sum(1 for item in quotes if self._is_limit_event(item, "down"))
            result[sector_code] = {
                **info,
                "as_of": self._market_overview.get("as_of"),
                "round_id": round_id,
                "member_count": len(members),
                "quote_count": len(quotes),
                "coverage_pct": round(len(quotes) / max(1, len(members)) * 100, 2),
                "change_pct": round(sum(changes) / len(changes), 4),
                "median_change_pct": median_change,
                "up_count": sum(1 for value in changes if value > 0),
                "down_count": sum(1 for value in changes if value < 0),
                "flat_count": sum(1 for value in changes if value == 0),
                "amount_yuan": sum(float(item.get("amount_yuan") or 0) for item in quotes),
                "limit_up_count": limit_up_count,
                "limit_down_count": limit_down_count,
                "heat_score": self._heat_score(changes, limit_up_count, limit_down_count, len(members), sum(float(item.get("amount_yuan") or 0) for item in quotes)),
                "leader": {"stock_code": leader["stock_code"], "stock_name": leader.get("stock_name"), "change_pct": leader.get("change_pct"), "last_price": leader.get("last_price")},
            }
        return result

    def _build_pool_summaries(self, round_id: str) -> dict[str, dict]:
        result: dict[str, dict] = {}
        for pool_code, pool in self._pools.items():
            codes = pool["stock_codes"]
            quotes = [self._quotes[code] for code in codes if code in self._quotes and self._quotes[code].get("change_pct") is not None]
            changes = [float(item["change_pct"]) for item in quotes]
            limit_up_count = sum(1 for item in quotes if self._is_limit_event(item, "up"))
            limit_down_count = sum(1 for item in quotes if self._is_limit_event(item, "down"))
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
                "median_change_pct": self._median(changes),
                "amount_yuan": sum(float(item.get("amount_yuan") or 0) for item in quotes),
                "limit_up_count": limit_up_count,
                "limit_down_count": limit_down_count,
                "heat_score": self._heat_score(changes, limit_up_count, limit_down_count, len(codes), sum(float(item.get("amount_yuan") or 0) for item in quotes)),
                "leaders": self._rank_quotes(quotes, reverse=True, limit=5),
            }
        return result

    async def _persist_quote_caches(self, settings: RealtimeSettings) -> None:
        ttl = settings.cache_ttl_seconds
        await redis_client.set_many_json(
            [
                (await redis_client.key("realtime", "quotes"), self._quotes, ttl),
                (await redis_client.key("realtime", "market-overview"), self._market_overview, ttl),
                (await redis_client.key("realtime", "sectors"), list(self._sector_strength.values()), ttl),
                (await redis_client.key("realtime", "pools"), self._pool_summaries, ttl),
            ]
        )

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
                credentials = await TickflowProviderFactory(ConfigCenterRepository(session)).resolve_realtime_credentials()
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
                    settings_fields = set(RealtimeSettings.model_fields)
                    # Existing deployments may still have V1's 80-symbol value
                    # before the owner-only migration is applied.  Enforce the
                    # purchased TickFlow maximum in process instead of letting
                    # a validation error disable the whole runtime config.
                    option_values = {key: value for key, value in options.items() if key != "enabled" and key in settings_fields}
                    try:
                        option_values["quote_batch_size"] = min(50, int(option_values.get("quote_batch_size", 50)))
                    except (TypeError, ValueError):
                        option_values["quote_batch_size"] = 50
                    self._settings = RealtimeSettings(
                        enabled=bool(config.is_enabled) and self._as_bool(options.get("enabled", False)),
                        **option_values,
                    )
                tickflow_config = await repository.find_config(category_code="market_data", config_code="tickflow")
                tickflow_options = (
                    {option.option_key: option.option_value for option in await repository.list_options(tickflow_config.id, only_enabled=True)}
                    if tickflow_config is not None
                    else {}
                )
                self._configure_rate_budgets(tickflow_options)
        except Exception as exc:
            self._error = f"realtime config load failed: {type(exc).__name__}: {exc}"
            logger.warning("realtime config load failed; preserving previous settings: %s", exc)
        self._settings_loaded_at = clock.monotonic()
        return self._settings

    def _configure_rate_budgets(self, options: dict) -> None:
        def number(name: str, default: float) -> float:
            value = options.get(name, default)
            try:
                return float(value)
            except (TypeError, ValueError):
                return default

        quote_symbol_limit = max(1, int(number("quote_symbol_requests_per_minute", 60)))
        universe_limit = max(1, int(number("quote_universe_requests_per_minute", 20)))
        depth_limit = max(1, int(number("depth_batch_requests_per_minute", 60)))
        safety_ratio = min(1.0, max(0.1, number("realtime_safety_ratio", 0.8)))
        signature = (quote_symbol_limit, universe_limit, depth_limit, safety_ratio)
        if signature == self._rate_signature:
            return
        self._rate_signature = signature
        self._rate_budgets = {
            "quote_symbols": RealtimeRateBudget("quote_symbols", quote_symbol_limit, safety_ratio),
            "quote_universe": RealtimeRateBudget("quote_universe", universe_limit, safety_ratio),
            "depth_batch": RealtimeRateBudget("depth_batch", depth_limit, safety_ratio),
        }

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
    def _median(values: list[float]) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        midpoint = len(ordered) // 2
        result = ordered[midpoint] if len(ordered) % 2 else (ordered[midpoint - 1] + ordered[midpoint]) / 2
        return round(result, 4)

    @staticmethod
    def _is_limit_event(quote: dict, direction: str) -> bool:
        metadata = quote.get("metadata") if isinstance(quote.get("metadata"), dict) else {}
        ext = metadata.get("ext") if isinstance(metadata.get("ext"), dict) else {}
        target = ext.get("limit_up") if direction == "up" else ext.get("limit_down")
        price = quote.get("last_price")
        try:
            return target is not None and price is not None and abs(float(target) - float(price)) <= max(0.001, abs(float(target)) * 0.0002)
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _heat_score(changes: list[float], limit_up: int, limit_down: int, member_count: int, amount: float) -> float:
        if not changes:
            return 0.0
        up_ratio = sum(1 for value in changes if value > 0) / len(changes)
        mean_change = sum(changes) / len(changes)
        change_component = min(35.0, max(0.0, (mean_change + 3.0) / 6.0 * 35.0))
        breadth_component = up_ratio * 30.0
        limit_component = min(25.0, limit_up / max(1, member_count) * 250.0) - min(10.0, limit_down / max(1, member_count) * 100.0)
        liquidity_component = min(10.0, math.log10(max(1.0, amount)) - 6.0)
        return round(min(100.0, max(0.0, change_component + breadth_component + limit_component + liquidity_component)), 2)

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
    def _is_opening_depth_session(now: datetime) -> bool:
        current = now.timetz().replace(tzinfo=None)
        return now.weekday() < 5 and time(9, 20) <= current <= time(9, 25)

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
