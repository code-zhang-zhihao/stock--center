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
from app.modules.strategy_center.realtime_service import StrategyRealtimeService


logger = logging.getLogger(__name__)
SHANGHAI = ZoneInfo("Asia/Shanghai")
CORE_INDEX_SYMBOLS: tuple[dict[str, str], ...] = (
    {"index_code": "000001", "index_name": "上证综指", "source_symbol": "000001.SH"},
    {"index_code": "399001", "index_name": "深证成指", "source_symbol": "399001.SZ"},
    {"index_code": "399006", "index_name": "创业板指", "source_symbol": "399006.SZ"},
    {"index_code": "000300", "index_name": "沪深300", "source_symbol": "000300.SH"},
    {"index_code": "000905", "index_name": "中证500", "source_symbol": "000905.SH"},
    {"index_code": "000852", "index_name": "中证1000", "source_symbol": "000852.SH"},
    {"index_code": "000016", "index_name": "上证50", "source_symbol": "000016.SH"},
)
ON_DEMAND_QUOTE_REQUEST_RESERVE = 5
MARKET_TIMELINE_MAX_ITEMS = 260
MARKET_EVENT_MAX_ITEMS = 120
MARKET_EVENT_PER_ROUND_LIMIT = 20
POST_CLOSE_STRUCTURE_CACHE_SECONDS = 300
POST_CLOSE_STRUCTURE_PENDING_CACHE_SECONDS = 60
POST_CLOSE_LADDER_STOCK_LIMIT = 500


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
        self._daily_factor_trade_date: date | None = None
        self._daily_factor_reference: dict[str, dict] = {}
        self._post_close_structure: dict = {"available": False, "reason": "post_close_structure_not_loaded"}
        self._post_close_structure_loaded_clock = 0.0
        self._post_close_structure_lock = asyncio.Lock()
        self._sector_info: dict[str, dict] = {}
        self._sector_members: dict[str, list[str]] = {}
        self._stock_sectors: dict[str, list[str]] = {}
        self._pools: dict[str, dict] = {}
        self._quotes: dict[str, dict] = {}
        self._minutes: dict[str, list[dict]] = {}
        self._minute_meta_by_stock: dict[str, dict] = {}
        self._minute_cached_rows: dict[str, dict[str, dict]] = {}
        self._market_round_quotes: dict[str, dict] = {}
        self._market_overview: dict = {"as_of": None, "items": {}, "round_id": None}
        self._sector_strength: dict[str, dict] = {}
        self._pool_summaries: dict[str, dict] = {}
        # These are deliberately short-lived intraday research artifacts.  A
        # full market Quote round is already held in memory; retaining one
        # compact point per minute makes the dashboard explain *changes*
        # without writing every quote/depth snapshot to PostgreSQL.
        self._market_history_trade_date: date | None = None
        self._market_timeline: list[dict] = []
        self._market_events: list[dict] = []
        self._previous_sector_ranks: dict[str, int] = {}
        self._previous_concept_leaders: dict[str, str] = {}
        self._previous_market_breadth: str | None = None
        self._core_index_quotes: dict[str, dict] = {}
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
            "strategy": RealtimeBlockMeta(block="strategy"),
        }
        self._strategy_runtime = StrategyRealtimeService()
        self._depth_by_stock: dict[str, dict] = {}
        self._depth_history_by_stock: dict[str, list[dict]] = {}
        self._decision_targets: list[dict] = []
        self._warm_targets: list[dict] = []
        self._last_market_refresh_clock = 0.0
        self._last_decision_refresh_clock = 0.0
        self._last_warm_refresh_clock = 0.0
        self._last_depth_refresh_clock = 0.0
        self._block_tasks: dict[str, asyncio.Task] = {}
        self._rate_budgets: dict[str, RealtimeRateBudget] = {}
        self._on_demand_budget = RealtimeRateBudget("on_demand_quote", ON_DEMAND_QUOTE_REQUEST_RESERVE, 1.0)
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
        block_tasks = [task for task in self._block_tasks.values() if not task.done()]
        for task in block_tasks:
            task.cancel()
        if block_tasks:
            await asyncio.gather(*block_tasks, return_exceptions=True)
        self._block_tasks.clear()
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
        block_status = {name: self._block_with_freshness(meta) for name, meta in self._blocks.items()}
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
            minute_guaranteed_count=int(self._last_minute_round.guaranteed_count),
            minute_guaranteed_overflow_count=int(self._last_minute_round.guaranteed_overflow_count),
            minute_unregistered_count=int(self._last_minute_round.unregistered_count),
            reference_loaded_at=self._reference_loaded_at,
            last_quote_round=self._last_quote_round,
            last_minute_round=self._last_minute_round,
            market=block_status["market"],
            decision_quote=block_status["decision_quote"],
            depth=block_status["depth"],
            minute=block_status["minute"],
            strategy=block_status["strategy"],
            rate_budgets=rate_budgets,
            leader_active=self._leader_active,
            depth_cache_count=len(self._depth_by_stock),
            decision_target_count=len(self._decision_targets),
            warm_target_count=len(self._warm_targets),
            error=self._error,
        ).model_dump(mode="json")

    @staticmethod
    def _block_with_freshness(meta: RealtimeBlockMeta) -> RealtimeBlockMeta:
        if meta.finished_at is None:
            return meta
        now = datetime.now(tz=ZoneInfo("UTC"))
        finished_at = meta.finished_at if meta.finished_at.tzinfo is not None else meta.finished_at.replace(tzinfo=ZoneInfo("UTC"))
        age = max(0, int((now - finished_at.astimezone(ZoneInfo("UTC"))).total_seconds()))
        return meta.model_copy(update={"cache_freshness_seconds": age})

    async def refresh_once(self, *, force: bool = False) -> dict:
        settings = await self._load_settings(force=True)
        if not settings.enabled and not force:
            raise RuntimeError("实时行情服务未启用，请先在数据源配置中启用 realtime_market")
        await self._refresh_round(settings, force=force)
        return await self.status()

    def invalidate_reference(self) -> None:
        """Make the next scheduler tick reload stock-pool runtime policies.

        Pool membership and policy edits are operator actions; waiting for the
        normal ten-minute reference refresh would make a successful save look
        ineffective on the realtime page.
        """
        self._reference_loaded_at = None
        self._reference_loaded_clock = 0.0

    async def market_overview(self) -> dict:
        await self._hydrate_shared_caches()
        return self._market_overview

    async def market_timeline(self, *, limit: int = 180) -> dict:
        await self._hydrate_market_history()
        return {
            "as_of": self._market_overview.get("as_of"),
            "round_id": self._market_overview.get("round_id"),
            "trade_date": self._market_history_trade_date.isoformat() if self._market_history_trade_date else None,
            "items": self._market_timeline[-limit:],
        }

    async def market_events(self, *, limit: int = 80) -> dict:
        await self._hydrate_market_history()
        return {
            "as_of": self._market_overview.get("as_of"),
            "round_id": self._market_overview.get("round_id"),
            "trade_date": self._market_history_trade_date.isoformat() if self._market_history_trade_date else None,
            "items": self._market_events[-limit:],
        }

    async def post_close_structure(self, *, trade_date: date | None = None) -> dict:
        """Return completed daily limit-event facts for the market dashboard.

        This path is intentionally read-only and does not depend on a live
        Quote round.  It is the factual input for later emotion/report logic,
        not an emotion score or a trading signal by itself.
        """
        # Historical reports are user-selected and are read directly.  Keeping
        # the small live/latest cache separate prevents a historical lookup
        # from evicting the dashboard's newest fact snapshot.
        if trade_date is not None:
            return await self._load_post_close_structure(trade_date=trade_date)
        if clock.monotonic() - self._post_close_structure_loaded_clock < self._post_close_structure_cache_seconds():
            return self._post_close_structure
        async with self._post_close_structure_lock:
            if clock.monotonic() - self._post_close_structure_loaded_clock < self._post_close_structure_cache_seconds():
                return self._post_close_structure
            self._post_close_structure = await self._load_post_close_structure()
            self._post_close_structure_loaded_clock = clock.monotonic()
            return self._post_close_structure

    async def _load_post_close_structure(self, *, trade_date: date | None = None) -> dict:
        try:
            sessionmaker = get_sessionmaker()
            async with sessionmaker() as session:
                repository = RealtimeMarketRepository(session)
                raw = await repository.latest_post_close_limit_events(trade_date=trade_date)
            return self._build_post_close_structure(raw)
        except Exception:
            logger.exception("post-close market structure load failed")
            return {
                "available": False,
                "reason": "post_close_structure_load_failed",
                "trade_date": trade_date.isoformat() if trade_date else None,
                "summary": None,
                "ladders": [],
                "limit_breaks": [],
            }

    def _post_close_structure_cache_seconds(self) -> int:
        return POST_CLOSE_STRUCTURE_CACHE_SECONDS if self._post_close_structure.get("available") else POST_CLOSE_STRUCTURE_PENDING_CACHE_SECONDS

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

    async def stock(self, stock_code: str, *, allow_on_demand: bool = True) -> dict:
        code = normalize_symbol(stock_code)
        self._page_targets[code] = clock.monotonic() + 120
        settings = await self._load_settings()
        now = datetime.now(tz=SHANGHAI)
        market_session = await self._is_open_market_session(now)
        await self._hydrate_stock_cache(code)
        if allow_on_demand and settings.enabled and market_session and self._stock_needs_on_demand_fetch(code):
            await self._fetch_stock_on_demand(code, settings)
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
            cached = await redis_client.hgetall_json(await redis_client.key("realtime", "minute-bars", code))
            if isinstance(cached, dict):
                meta = cached.pop("__meta__", None)
                items = [item for item in cached.values() if isinstance(item, dict) and item.get("bar_time")]
                items.sort(key=lambda item: str(item["bar_time"]))
                if items:
                    self._minutes[code] = items
                    self._minute_cached_rows[code] = {str(item["bar_time"]): item for item in items}
                if isinstance(meta, dict):
                    self._minute_meta_by_stock[code] = meta
            if code not in self._minutes and code not in self._minute_meta_by_stock:
                # Compatibility with a short-lived V1 full-series cache key.
                cached = await redis_client.get_json(await redis_client.key("realtime", "minutes", code))
                if isinstance(cached, dict):
                    items = cached.get("items")
                    meta = cached.get("meta")
                    if isinstance(items, list):
                        self._minutes[code] = items
                        self._minute_cached_rows[code] = {str(item.get("bar_time")): item for item in items if item.get("bar_time")}
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
            # A follower may serve the shared market/sector/pool caches but
            # must not spend a second instance's TickFlow or MooTDX quota for
            # a page-level miss.  A standalone instance can acquire the same
            # lease here before performing this exceptional direct fetch.
            if not self._leader_active and not await self._acquire_leader(settings):
                await self._hydrate_stock_cache(code)
                self._on_demand_errors[code] = "on_demand_shared_cache_miss: external fetch is owned by another runtime instance"
                return "shared_cache"
            now_clock = clock.monotonic()
            if now_clock - self._on_demand_attempted_at.get(code, 0.0) < 10:
                return "cooldown"
            self._on_demand_attempted_at[code] = now_clock
            self._on_demand_errors.pop(code, None)
            started = clock.monotonic()
            await self._ensure_provider_pools(settings)
            if "quote_symbols" not in self._rate_budgets:
                self._configure_rate_budgets({})
            await self._on_demand_budget.acquire()
            await self._rate_budgets["quote_symbols"].acquire()
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
        await self._hydrate_shared_caches()
        return self._pool_summaries.get(pool_code)

    async def pools(self, *, limit: int = 200) -> dict:
        await self._hydrate_shared_caches()
        items = list(self._pool_summaries.values())
        items.sort(
            key=lambda item: (
                item.get("average_change_pct") is None,
                -(item.get("heat_score") or 0),
                -(item.get("coverage_pct") or 0),
                str(item.get("pool_code") or ""),
            )
        )
        return {
            "as_of": self._market_overview.get("as_of"),
            "round_id": self._market_overview.get("round_id"),
            "items": items[:limit],
        }

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
        await self._hydrate_shared_caches()
        items = list(self._sector_strength.values())
        if sector_type:
            items = [item for item in items if item["sector_type"] == sector_type]
        items.sort(
            key=lambda item: (
                item.get("heat_score") is None,
                -(item.get("heat_score") or 0),
                -(item.get("coverage_pct") or 0),
                str(item.get("sector_code") or ""),
            )
        )
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
            scheduled: list[asyncio.Task] = []
            if force or now_clock - self._last_market_refresh_clock >= settings.full_market_interval_seconds:
                self._last_market_refresh_clock = clock.monotonic()
                scheduled.append(self._start_block("market", lambda: self._refresh_market_quotes(settings)))
            decision_due = force or now_clock - self._last_decision_refresh_clock >= settings.decision_quote_interval_seconds
            warm_due = force or now_clock - self._last_warm_refresh_clock >= settings.warm_quote_interval_seconds
            if decision_due:
                self._last_decision_refresh_clock = clock.monotonic()
                if warm_due:
                    self._last_warm_refresh_clock = clock.monotonic()
                scheduled.append(self._start_block("decision_quote", lambda: self._refresh_decision_quotes(settings, include_warm=warm_due)))
            depth_interval = settings.auction_depth_refresh_interval_seconds if self._is_opening_depth_session(now) else settings.depth_refresh_interval_seconds
            if force or now_clock - self._last_depth_refresh_clock >= depth_interval:
                self._last_depth_refresh_clock = clock.monotonic()
                scheduled.append(self._start_block("depth", lambda: self._refresh_depth(settings)))
            if self._is_continuous_market_session(now) and (force or clock.monotonic() - self._last_minute_refresh_clock >= settings.minute_refresh_interval_seconds):
                self._last_minute_refresh_clock = clock.monotonic()
                scheduled.append(self._start_block("minute", lambda: self._refresh_minutes(settings, uuid.uuid4().hex[:16])))
            if force and scheduled:
                await asyncio.gather(*scheduled, return_exceptions=True)

    def _start_block(self, name: str, operation_factory) -> asyncio.Task:
        current = self._block_tasks.get(name)
        if current is not None and not current.done():
            return current
        task = asyncio.create_task(self._run_block(name, operation_factory), name=f"realtime-{name}")
        self._block_tasks[name] = task
        return task

    async def _run_block(self, name: str, operation_factory) -> None:
        try:
            await operation_factory()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._error = f"{name}: {type(exc).__name__}: {exc}"
            logger.exception("realtime block failed: block=%s", name)
        finally:
            current = self._block_tasks.get(name)
            if current is asyncio.current_task():
                self._block_tasks.pop(name, None)

    async def _ensure_reference(self, settings: RealtimeSettings) -> None:
        if self._reference_loaded_at and clock.monotonic() - self._reference_loaded_clock < settings.reference_refresh_seconds:
            return
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            repository = RealtimeMarketRepository(session)
            active_codes, stock_names = await repository.active_stock_reference()
            factor_trade_date, daily_factor_reference = await repository.latest_daily_factor_reference()
            sector_info, sector_members, stock_sectors = await repository.sector_reference()
            industry_info, industry_members, stock_industries = await repository.industry_universe_reference()
            pools = await repository.pool_reference(active_codes)
        self._active_codes = active_codes
        self._stock_names = stock_names
        self._daily_factor_trade_date = factor_trade_date
        self._daily_factor_reference = daily_factor_reference
        self._sector_info = {**sector_info, **industry_info}
        self._sector_members = {**sector_members, **industry_members}
        self._stock_sectors = {**stock_sectors}
        for stock_code, codes in stock_industries.items():
            self._stock_sectors.setdefault(stock_code, []).extend(codes)
        self._pools = pools
        self._reference_loaded_at = datetime.now(tz=ZoneInfo("UTC"))
        self._reference_loaded_clock = clock.monotonic()
        logger.info(
            "realtime reference loaded: active=%s daily_factor_date=%s daily_factors=%s concepts=%s tickflow_industries=%s pools=%s",
            len(active_codes), factor_trade_date, len(daily_factor_reference), len(sector_info), len(industry_info), len(pools),
        )

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

    async def _hydrate_market_history(self) -> None:
        """Restore same-day dashboard history without issuing provider requests."""
        today = datetime.now(tz=SHANGHAI).date()
        if self._market_history_trade_date == today and (self._market_timeline or self._market_events):
            return
        timeline = await redis_client.get_json(await redis_client.key("realtime", "market-timeline", today.isoformat()))
        events = await redis_client.get_json(await redis_client.key("realtime", "market-events", today.isoformat()))
        if isinstance(timeline, list) or isinstance(events, list):
            self._market_history_trade_date = today
            self._market_timeline = [item for item in (timeline or []) if isinstance(item, dict)][-MARKET_TIMELINE_MAX_ITEMS:]
            self._market_events = [item for item in (events or []) if isinstance(item, dict)][-MARKET_EVENT_MAX_ITEMS:]

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

        core_indexes, index_errors, index_request_count = await self._refresh_core_index_quotes(settings)
        request_count += index_request_count
        self._core_index_quotes = core_indexes
        errors.extend(index_errors)

        received_codes = {item["stock_code"] for item in rows}
        market_coverage_ok = len(received_codes) >= max(1, math.ceil(len(self._active_codes) * 0.95))
        degraded = bool(errors) or not market_coverage_ok
        if rows and market_coverage_ok:
            # Aggregations must use one provider round only.  The broader
            # quote cache intentionally retains individual hot/page entries,
            # but it must never leak an older quote into the full-market,
            # topic, industry or pool statistics of this round.
            await self._hydrate_market_history()
            self._ensure_market_history_trade_date()
            round_quotes = {item["stock_code"]: item for item in rows}
            self._market_round_quotes = round_quotes
            self._quotes.update(round_quotes)
            self._market_overview = self._build_market_overview(round_id, round_quotes)
            self._sector_strength = self._build_sector_strength(round_id, round_quotes)
            self._pool_summaries = self._build_pool_summaries(round_id, round_quotes)
            self._record_market_history(round_id)
            await self._persist_quote_caches(settings)
            await self._publish("market_overview", self._market_overview)
            await self._publish("sectors", {"as_of": self._market_overview.get("as_of"), "round_id": round_id, "items": list(self._sector_strength.values())})
            await self._publish("pools", {"as_of": self._market_overview.get("as_of"), "round_id": round_id, "items": list(self._pool_summaries.values())})
            await self._publish("market_timeline", await self.market_timeline(limit=MARKET_TIMELINE_MAX_ITEMS))
            await self._publish("market_events", await self.market_events(limit=MARKET_EVENT_MAX_ITEMS))
            for pool_code, summary in self._pool_summaries.items():
                await self._publish(f"pool:{pool_code}", summary)

        meta = self._block_meta(
            "market", round_id, started, settings.quote_provider, len(self._active_codes), len(received_codes), len(errors), errors,
            request_count=request_count, degraded=degraded,
            degraded_reason=(
                "market_coverage_below_95_pct"
                if not market_coverage_ok
                else "core_index_quote_incomplete"
                if index_errors
                else "provider_error"
                if errors
                else None
            ),
        )
        self._blocks["market"] = meta
        self._last_quote_round = RealtimeRoundMeta(**meta.model_dump(exclude={"block", "request_count", "coverage_pct", "cache_freshness_seconds", "rate_limited_count", "network_error_count", "degraded_reason"}))
        if degraded:
            self._error = "全市场 TickFlow Quote 或核心指数不完整；全市场覆盖不足时已保留上一轮缓存"
        else:
            self._error = None

    async def _refresh_core_index_quotes(self, settings: RealtimeSettings) -> tuple[dict[str, dict], list[str], int]:
        errors: list[str] = []
        provider = self._quote_providers[0] if self._quote_providers else None
        if not isinstance(provider, TickflowQuoteProvider):
            return {}, ["core_indexes: TickFlow provider unavailable"], 0
        try:
            await self._rate_budgets["quote_symbols"].acquire()
            rows, _ = await provider.quote_source_symbols([item["source_symbol"] for item in CORE_INDEX_SYMBOLS])
        except Exception as exc:
            await self._record_rate_limit_if_needed("quote_symbols", exc)
            return {}, [f"core_indexes: {type(exc).__name__}: {exc}"], 1
        by_symbol = {str(item.get("source_symbol") or "").upper(): item for item in rows}
        result: dict[str, dict] = {}
        for definition in CORE_INDEX_SYMBOLS:
            quote = by_symbol.get(definition["source_symbol"])
            if quote is None:
                errors.append(f"core_indexes: missing {definition['source_symbol']}")
                continue
            result[definition["index_code"]] = {
                **definition,
                "quote": quote,
                "available": True,
            }
        return result, errors, 1

    @staticmethod
    def _quote_lane_rank(lane: str) -> int:
        return {"hot": 0, "warm": 1, "off": 2}.get(lane, 2)

    @staticmethod
    def _minute_lane_rank(lane: str) -> int:
        return {"guaranteed": 0, "rotating": 1, "off": 2}.get(lane, 2)

    def _realtime_targets(self, settings: RealtimeSettings) -> list[dict]:
        """Merge pool membership into an explainable effective realtime policy."""
        now = clock.monotonic()
        self._page_targets = {code: expires_at for code, expires_at in self._page_targets.items() if expires_at > now}
        active_set = set(self._active_codes)
        by_code: dict[str, list[dict]] = {}

        for pool in self._pools.values():
            policy = pool.get("realtime_policy") if isinstance(pool.get("realtime_policy"), dict) else {}
            if not policy.get("is_enabled"):
                continue
            quote_lane = str(policy.get("quote_lane") or "off")
            minute_lane = str(policy.get("minute_lane") or "off")
            if quote_lane == "off" and minute_lane == "off":
                continue
            try:
                priority = int(policy.get("priority", 1000))
            except (TypeError, ValueError, KeyError):
                priority = 1000
            for code in pool.get("stock_codes", []):
                if code not in active_set:
                    continue
                by_code.setdefault(code, []).append(
                    {
                        "kind": "pool",
                        "pool_code": pool["pool_code"],
                        "pool_name": pool["pool_name"],
                        "pool_type": pool["pool_type"],
                        "priority": priority,
                        "quote_lane": quote_lane,
                        "minute_lane": minute_lane,
                    }
                )

        for code in self._page_targets:
            if code in active_set:
                by_code.setdefault(code, []).append(
                    {
                        "kind": "page_watch",
                        "priority": 900,
                        "quote_lane": "hot",
                        "minute_lane": "guaranteed",
                    }
                )

        strong = sorted(
            (item for item in self._market_round_quotes.values() if item.get("stock_code") in active_set),
            key=lambda item: (abs(float(item.get("change_pct") or 0)), float(item.get("amount_yuan") or 0)),
            reverse=True,
        )[:settings.strong_candidate_limit]
        for item in strong:
            code = item["stock_code"]
            by_code.setdefault(code, []).append(
                {
                    "kind": "strong",
                    "priority": 1000,
                    "quote_lane": "warm",
                    "minute_lane": "rotating",
                }
            )

        targets: list[dict] = []
        for code, memberships in by_code.items():
            memberships.sort(key=lambda item: (int(item["priority"]), self._quote_lane_rank(str(item["quote_lane"])), item.get("pool_code") or item["kind"]))
            primary = memberships[0]
            quote_lane = min((str(item["quote_lane"]) for item in memberships), key=self._quote_lane_rank)
            minute_lane = min((str(item["minute_lane"]) for item in memberships), key=self._minute_lane_rank)
            quote = self._quotes.get(code, {})
            signal_score = abs(float(quote.get("change_pct") or 0)) + min(20.0, math.log10(max(1.0, float(quote.get("amount_yuan") or 0))) - 5.0)
            targets.append(
                {
                    "stock_code": code,
                    "stock_name": self._stock_names.get(code),
                    "reason": f"pool:{primary['pool_code']}" if primary["kind"] == "pool" else primary["kind"],
                    "priority": int(primary["priority"]),
                    "signal_score": round(signal_score, 4),
                    "promotion_reason": "pool_realtime_policy" if primary["kind"] == "pool" else primary["kind"],
                    "quote_lane": quote_lane,
                    "minute_lane": minute_lane,
                    "memberships": memberships,
                }
            )
        return sorted(
            targets,
            key=lambda item: (
                int(item["priority"]),
                self._quote_lane_rank(str(item["quote_lane"])),
                -float(item["signal_score"]),
                item["stock_code"],
            ),
        )

    def _build_decision_targets(self, settings: RealtimeSettings) -> tuple[list[dict], list[dict]]:
        targets = [item for item in self._realtime_targets(settings) if item["quote_lane"] != "off"]
        hot_candidates = [item for item in targets if item["quote_lane"] == "hot"]
        warm_candidates = [item for item in targets if item["quote_lane"] == "warm"]
        hot = hot_candidates[:settings.decision_target_limit]
        # Hot overflow remains observable and is refreshed with the warm pool;
        # it never silently disappears merely because the hot capacity is full.
        return hot, [*hot_candidates[settings.decision_target_limit:], *warm_candidates]

    async def _refresh_decision_quotes(self, settings: RealtimeSettings, *, include_warm: bool) -> None:
        started = clock.monotonic()
        round_id = uuid.uuid4().hex[:16]
        hot, warm = self._build_decision_targets(settings)
        self._decision_targets, self._warm_targets = hot, warm
        warm_capacity = self._warm_quote_symbol_capacity(settings) if include_warm else 0
        queried_warm = warm[:warm_capacity]
        targets = hot + queried_warm
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
                await self._publish(f"stock:{code}", await self.stock(code, allow_on_demand=False))
        expected = len(targets)
        meta = self._block_meta(
            "decision_quote", round_id, started, settings.quote_provider, expected, len({item["stock_code"] for item in rows}), len(errors), errors,
            request_count=request_count, degraded=bool(errors), degraded_reason="batch_request_error" if errors else None,
        )
        self._blocks["decision_quote"] = meta

    def _warm_quote_symbol_capacity(self, settings: RealtimeSettings) -> int:
        budget = self._rate_budgets.get("quote_symbols")
        if budget is None:
            return 0
        hot_requests = math.ceil(settings.decision_target_limit / max(1, settings.quote_batch_size))
        hot_per_minute = hot_requests * math.ceil(60 / max(1, settings.decision_quote_interval_seconds))
        # One symbols request is reserved for core indexes and five are retained
        # for page cache misses.  The remaining envelope is warm observation.
        remaining_requests = max(0, budget.safe_limit - hot_per_minute - 1 - ON_DEMAND_QUOTE_REQUEST_RESERVE)
        return remaining_requests * settings.quote_batch_size

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
        # Depth is an independent cadence: it must not wait for the preceding
        # 10-second Quote task to finish before it can determine the same hot
        # target set (notably on a manual forced refresh).
        hot, warm = self._build_decision_targets(settings)
        self._decision_targets, self._warm_targets = hot, warm
        codes = [item["stock_code"] for item in hot]
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
            snapshot = {
                **row,
                "depth_time": row.get("depth_time").isoformat() if isinstance(row.get("depth_time"), datetime) else str(row.get("depth_time") or ""),
                "features": self._depth_features(row),
            }
            history = [snapshot, *self._depth_history_by_stock.get(code, [])][:3]
            self._depth_by_stock[code] = snapshot
            self._depth_history_by_stock[code] = history
            changed.append((await redis_client.key("realtime", "depth", code), {"current": snapshot, "history": history}, settings.depth_cache_ttl_seconds))
        await redis_client.set_many_json(changed)
        self._blocks["depth"] = self._block_meta(
            "depth", round_id, started, "tickflow", len(codes), len({row["stock_code"] for row in rows}), len(errors), errors,
            request_count=requests, degraded=bool(errors), degraded_reason="depth_batch_error" if errors else None,
        )
        await self._refresh_strategy_runtime(settings)

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
        registered, selected, minute_plan = self._minute_target_plan(settings)
        await self._ensure_provider_pools(settings)
        queue: asyncio.Queue[dict] = asyncio.Queue()
        for target in selected:
            queue.put_nowait(target)
        updated = 0
        empty = 0
        errors: list[str] = []
        cache_queue: asyncio.Queue[tuple[str, list[dict], dict] | None] = asyncio.Queue(maxsize=max(16, len(selected)))

        async def cache_writer() -> None:
            """Consume completed network fetches while other MooTDX workers continue."""
            while True:
                item = await cache_queue.get()
                if item is None:
                    return
                batch = [item]
                finished = False
                while len(batch) < 50:
                    try:
                        queued = cache_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    if queued is None:
                        finished = True
                        break
                    batch.append(queued)
                ttl = self._minute_session_ttl()
                hash_items = []
                for stock_code, minute_rows, meta in batch:
                    fields = self._minute_cache_fields(stock_code, minute_rows, meta)
                    hash_items.append((await redis_client.key("realtime", "minute-bars", stock_code), fields, ttl))
                await redis_client.hset_many_hashes_json(hash_items)
                if finished:
                    return

        writer_task = asyncio.create_task(cache_writer(), name="realtime-minute-cache-writer")

        async def worker(provider: MootdxProvider) -> None:
            nonlocal updated, empty
            while True:
                try:
                    target = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                code = target["stock_code"]
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
                    await cache_queue.put((code, clean_rows, self._minute_meta_by_stock[code]))
                    await self._publish(f"stock:{code}", await self.stock(code, allow_on_demand=False))
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
            guaranteed_count=minute_plan["guaranteed_selected_count"],
            guaranteed_overflow_count=minute_plan["guaranteed_overflow_count"],
            rotating_selected_count=minute_plan["rotating_selected_count"],
            unregistered_count=minute_plan["unregistered_count"],
            duration_ms=int((clock.monotonic() - started) * 1000),
            error_samples=errors[:5],
        )
        self._blocks["minute"] = self._block_meta(
            "minute", round_id, started, "mootdx", len(selected), updated, len(errors), errors,
            request_count=len(selected), degraded=bool(errors), degraded_reason="per_symbol_errors" if errors else None,
        )
        await self._refresh_strategy_runtime(settings)

    async def _refresh_strategy_runtime(self, settings: RealtimeSettings) -> None:
        """Consume shared polling caches for paper confirmations/exits only."""
        started = clock.monotonic()
        round_id = uuid.uuid4().hex[:16]
        now = datetime.now(tz=SHANGHAI)
        try:
            summary = await self._strategy_runtime.process(
                now=now,
                quotes=self._quotes,
                depths=self._depth_by_stock,
                depth_history=self._depth_history_by_stock,
                minutes=self._minutes,
                blocks={name: meta.model_dump(mode="json") for name, meta in self._blocks.items()},
            )
            target_count = int(summary.get("candidate_count") or 0) + int(summary.get("open_trade_count") or 0)
            execution_count = int(summary.get("triggered_count") or 0) + int(summary.get("exit_count") or 0)
            degraded_count = int(summary.get("degraded_count") or 0)
            self._blocks["strategy"] = self._block_meta(
                "strategy", round_id, started, "shared_realtime_cache", target_count, execution_count, degraded_count,
                [], request_count=0, degraded=degraded_count > 0,
                degraded_reason="strategy_cache_degraded" if degraded_count else None,
            )
        except Exception as exc:
            logger.exception("strategy realtime process failed")
            self._blocks["strategy"] = self._block_meta(
                "strategy", round_id, started, "shared_realtime_cache", 0, 0, 1,
                [f"{type(exc).__name__}: {exc}"], request_count=0, degraded=True, degraded_reason="strategy_runtime_error",
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

    def _minute_target_plan(self, settings: RealtimeSettings) -> tuple[list[dict], list[dict], dict[str, int]]:
        candidates = [item for item in self._realtime_targets(settings) if item["minute_lane"] != "off"]
        guaranteed = [item for item in candidates if item["minute_lane"] == "guaranteed"]
        rotating = [item for item in candidates if item["minute_lane"] == "rotating"]
        registered = [*guaranteed, *rotating][:settings.minute_registered_target_limit]
        registered_guaranteed = [item for item in registered if item["minute_lane"] == "guaranteed"]
        registered_rotating = [item for item in registered if item["minute_lane"] == "rotating"]
        selected_guaranteed = registered_guaranteed[:settings.minute_guaranteed_target_count]
        overflow = [*registered_guaranteed[settings.minute_guaranteed_target_count:], *registered_rotating]
        remaining_slots = max(0, settings.minute_guaranteed_target_count - len(selected_guaranteed))
        rotating_selected: list[dict] = []
        if remaining_slots and overflow:
            offset = self._rotation_cursor % len(overflow)
            rotating_selected = (overflow[offset:] + overflow[:offset])[:remaining_slots]
            self._rotation_cursor += len(rotating_selected)
        selected = [*selected_guaranteed, *rotating_selected]
        return registered, selected, {
            "guaranteed_selected_count": len(selected_guaranteed),
            "guaranteed_overflow_count": max(0, len(guaranteed) - len(selected_guaranteed)),
            "rotating_selected_count": len(rotating_selected),
            "unregistered_count": max(0, len(candidates) - len(registered)),
        }

    def _build_market_overview(self, round_id: str, round_quotes: dict[str, dict]) -> dict:
        active_set = set(self._active_codes)
        values = [item for item in round_quotes.values() if item.get("stock_code") in active_set]
        change_values = [float(item["change_pct"]) for item in values if item.get("change_pct") is not None]
        up = sum(1 for value in change_values if value > 0)
        down = sum(1 for value in change_values if value < 0)
        flat = len(change_values) - up - down
        quoted_count = len(change_values)
        up_ratio = round(up / max(1, quoted_count) * 100, 2)
        down_ratio = round(down / max(1, quoted_count) * 100, 2)
        breadth_state = "broadly_up" if up_ratio >= 65 else "broadly_down" if down_ratio >= 65 else "mixed"
        verified_limit_quotes = [
            item
            for item in values
            if isinstance(item.get("metadata"), dict)
            and isinstance(item["metadata"].get("ext"), dict)
            and item["metadata"]["ext"].get("limit_up") is not None
            and item["metadata"]["ext"].get("limit_down") is not None
        ]
        limit_events = {
            "available": bool(verified_limit_quotes),
            "reason": None if verified_limit_quotes else "tickflow_quote_limit_prices_unavailable",
            "limit_up_count": sum(1 for item in verified_limit_quotes if self._is_limit_event(item, "up")) if verified_limit_quotes else None,
            "limit_down_count": sum(1 for item in verified_limit_quotes if self._is_limit_event(item, "down")) if verified_limit_quotes else None,
        }
        return {
            "as_of": datetime.now(tz=ZoneInfo("UTC")).isoformat(),
            "round_id": round_id,
            "provider": next((str(item.get("source")) for item in values if item.get("source")), self._settings.quote_provider),
            "items": {
                "quote_count": len(values),
                "expected_quote_count": len(self._active_codes),
                "coverage_pct": round(len(values) / max(1, len(self._active_codes)) * 100, 2),
                "up_count": up,
                "down_count": down,
                "flat_count": flat,
                "market_breadth": {
                    "state": breadth_state,
                    "up_ratio_pct": up_ratio,
                    "down_ratio_pct": down_ratio,
                    "flat_ratio_pct": round(flat / max(1, quoted_count) * 100, 2),
                },
                "average_change_pct": round(sum(change_values) / len(change_values), 4) if change_values else None,
                "median_change_pct": self._median(change_values),
                "total_amount_yuan": sum(float(item.get("amount_yuan") or 0) for item in values),
                "daily_factor_trend": self._build_daily_factor_trend(values),
                "intraday_structure": self._build_intraday_structure(values),
                "change_distribution": {
                    "up_5_pct": sum(1 for value in change_values if value >= 5),
                    "up_3_pct": sum(1 for value in change_values if 3 <= value < 5),
                    "up_0_to_3_pct": sum(1 for value in change_values if 0 < value < 3),
                    "flat": flat,
                    "down_0_to_3_pct": sum(1 for value in change_values if -3 < value < 0),
                    "down_3_pct": sum(1 for value in change_values if -5 < value <= -3),
                    "down_5_pct": sum(1 for value in change_values if value <= -5),
                },
                "limit_events": limit_events,
                "core_indexes": [
                    {
                        "index_code": definition["index_code"],
                        "index_name": definition["index_name"],
                        "source_symbol": definition["source_symbol"],
                        "available": definition["index_code"] in self._core_index_quotes,
                        "quote": self._core_index_quotes.get(definition["index_code"], {}).get("quote"),
                    }
                    for definition in CORE_INDEX_SYMBOLS
                ],
                "top_gainers": self._rank_quotes(values, reverse=True),
                "top_losers": self._rank_quotes(values, reverse=False),
                "top_amount": self._rank_quotes_by_metric(values, metric="amount_yuan"),
                "top_volume": self._rank_quotes_by_metric(values, metric="volume_hand"),
            },
        }

    def _build_daily_factor_trend(self, values: list[dict]) -> dict:
        """Compare current prices with the latest completed daily MA values.

        MA is deliberately a daily-factor reference, not a new intraday MA.
        That distinction keeps the dashboard useful during a session without
        accidentally treating a partial current-day candle as a completed bar.
        """
        if self._daily_factor_trade_date is None or not self._daily_factor_reference:
            return {
                "available": False,
                "reason": "daily_factor_reference_unavailable",
                "reference_trade_date": None,
                "quote_count": len(values),
                "factor_quote_count": 0,
                "ma5": None,
                "ma20": None,
                "ma60": None,
                "above_all": None,
            }

        counts: dict[str, dict[str, int]] = {
            "ma5": {"above_count": 0, "comparable_count": 0},
            "ma20": {"above_count": 0, "comparable_count": 0},
            "ma60": {"above_count": 0, "comparable_count": 0},
        }
        factor_quote_count = 0
        above_all_count = 0
        comparable_all_count = 0
        for quote in values:
            try:
                price = float(quote["last_price"])
            except (TypeError, ValueError, KeyError):
                continue
            factor = self._daily_factor_reference.get(str(quote.get("stock_code") or ""))
            if not factor:
                continue
            factor_quote_count += 1
            all_comparable = True
            all_above = True
            for key, bucket in counts.items():
                try:
                    moving_average = float(factor[key])
                except (TypeError, ValueError, KeyError):
                    all_comparable = False
                    continue
                bucket["comparable_count"] += 1
                if price >= moving_average:
                    bucket["above_count"] += 1
                else:
                    all_above = False
            if all_comparable:
                comparable_all_count += 1
                if all_above:
                    above_all_count += 1

        def result(bucket: dict[str, int]) -> dict:
            comparable_count = bucket["comparable_count"]
            return {
                **bucket,
                "above_pct": round(bucket["above_count"] / max(1, comparable_count) * 100, 2) if comparable_count else None,
            }

        return {
            "available": any(bucket["comparable_count"] for bucket in counts.values()),
            "reason": None,
            "reference_trade_date": self._daily_factor_trade_date.isoformat(),
            "quote_count": len(values),
            "factor_quote_count": factor_quote_count,
            "ma5": result(counts["ma5"]),
            "ma20": result(counts["ma20"]),
            "ma60": result(counts["ma60"]),
            "above_all": {
                "above_count": above_all_count,
                "comparable_count": comparable_all_count,
                "above_pct": round(above_all_count / max(1, comparable_all_count) * 100, 2) if comparable_all_count else None,
            },
        }

    @staticmethod
    def _build_intraday_structure(values: list[dict]) -> dict:
        above_open_count = 0
        below_open_count = 0
        open_comparable_count = 0
        at_high_count = 0
        at_low_count = 0
        range_comparable_count = 0
        for quote in values:
            try:
                price = float(quote["last_price"])
            except (TypeError, ValueError, KeyError):
                continue
            try:
                open_price = float(quote["open_price"])
                if open_price > 0:
                    open_comparable_count += 1
                    if price > open_price:
                        above_open_count += 1
                    elif price < open_price:
                        below_open_count += 1
            except (TypeError, ValueError, KeyError):
                pass
            try:
                high_price = float(quote["high_price"])
                low_price = float(quote["low_price"])
                if high_price > 0 and low_price > 0:
                    range_comparable_count += 1
                    tolerance = max(0.001, abs(price) * 0.0002)
                    if abs(price - high_price) <= tolerance:
                        at_high_count += 1
                    if abs(price - low_price) <= tolerance:
                        at_low_count += 1
            except (TypeError, ValueError, KeyError):
                pass
        return {
            "open_comparable_count": open_comparable_count,
            "above_open_count": above_open_count,
            "below_open_count": below_open_count,
            "range_comparable_count": range_comparable_count,
            "at_high_count": at_high_count,
            "at_low_count": at_low_count,
        }

    @staticmethod
    def _build_post_close_structure(raw: dict) -> dict:
        """Build a consecutive-limit-up ladder from canonical daily events.

        A board only advances when the same active, non-ST stock has a
        `limit_up` event on each previous open date.  ``limit_break`` is kept
        separate, so the seal rate is an explicit `limit_up / (limit_up +
        limit_break)` end-of-day measure rather than a synthetic price rule.
        """
        target_date = raw.get("trade_date")
        if not isinstance(target_date, date):
            return {
                "available": False,
                "reason": "daily_bar_unavailable",
                "trade_date": None,
                "daily_bar_coverage_pct": None,
                "summary": None,
                "ladders": [],
                "limit_breaks": [],
            }
        coverage_pct = round(
            int(raw.get("daily_bar_count") or 0) / max(1, int(raw.get("active_count") or 0)) * 100,
            2,
        )
        if not raw.get("daily_bar_count"):
            return {
                "available": False,
                "reason": "daily_bar_unavailable",
                "trade_date": target_date.isoformat(),
                "daily_bar_coverage_pct": coverage_pct,
                "summary": None,
                "ladders": [],
                "limit_breaks": [],
            }
        if not raw.get("limit_event_complete"):
            return {
                "available": False,
                "reason": "limit_event_ingest_incomplete",
                "trade_date": target_date.isoformat(),
                "daily_bar_coverage_pct": coverage_pct,
                "completion_capabilities": raw.get("completion_capabilities") or [],
                "summary": None,
                "ladders": [],
                "limit_breaks": [],
            }

        trade_dates = [item for item in raw.get("trade_dates") or [] if isinstance(item, date)]
        events = [item for item in raw.get("events") or [] if isinstance(item, dict)]
        limit_up_by_date: dict[date, set[str]] = {}
        for event in events:
            event_date = event.get("trade_date")
            if event.get("event_type") == "limit_up" and isinstance(event_date, date):
                limit_up_by_date.setdefault(event_date, set()).add(str(event.get("stock_code") or ""))

        current_events = [event for event in events if event.get("trade_date") == target_date]
        current_limit_ups = [event for event in current_events if event.get("event_type") == "limit_up"]
        current_limit_downs = [event for event in current_events if event.get("event_type") == "limit_down"]
        current_limit_breaks = [event for event in current_events if event.get("event_type") == "limit_break"]
        ladders: dict[int, list[dict]] = {}
        for event in current_limit_ups:
            stock_code = str(event.get("stock_code") or "")
            board_count = 0
            for trade_date in trade_dates:
                if stock_code not in limit_up_by_date.get(trade_date, set()):
                    break
                board_count += 1
            ladders.setdefault(max(1, board_count), []).append(
                RealtimeMarketService._post_close_stock_item(event, board_count=max(1, board_count))
            )
        ladder_items = []
        for board_count in sorted(ladders, reverse=True):
            stocks = sorted(
                ladders[board_count],
                key=lambda item: (
                    item.get("first_time") is None,
                    item.get("first_time") or "",
                    item.get("stock_code") or "",
                ),
            )
            ladder_items.append(
                {
                    "board_count": board_count,
                    "stock_count": len(stocks),
                    "stocks": stocks[:POST_CLOSE_LADDER_STOCK_LIMIT],
                    "truncated": len(stocks) > POST_CLOSE_LADDER_STOCK_LIMIT,
                }
            )
        limit_breaks = sorted(
            (RealtimeMarketService._post_close_stock_item(event) for event in current_limit_breaks),
            key=lambda item: (
                -(int(item.get("open_count") or 0)),
                -(float(item.get("turnover_amount") or 0)),
                item.get("stock_code") or "",
            ),
        )
        seal_denominator = len(current_limit_ups) + len(current_limit_breaks)
        highest_ladder = ladder_items[0] if ladder_items else None
        return {
            "available": True,
            "reason": None,
            "trade_date": target_date.isoformat(),
            "daily_bar_coverage_pct": coverage_pct,
            "completion_capabilities": raw.get("completion_capabilities") or [],
            "summary": {
                "limit_up_count": len(current_limit_ups),
                "limit_down_count": len(current_limit_downs),
                "limit_break_count": len(current_limit_breaks),
                "seal_rate_pct": round(len(current_limit_ups) / seal_denominator * 100, 2) if seal_denominator else None,
                "highest_board_count": highest_ladder.get("board_count") if highest_ladder else 0,
                "highest_board_stock_count": highest_ladder.get("stock_count") if highest_ladder else 0,
            },
            "ladders": ladder_items,
            "limit_breaks": limit_breaks[:POST_CLOSE_LADDER_STOCK_LIMIT],
            "limit_breaks_truncated": len(limit_breaks) > POST_CLOSE_LADDER_STOCK_LIMIT,
        }

    @staticmethod
    def _post_close_stock_item(event: dict, *, board_count: int | None = None) -> dict:
        def serialize_time(value: object) -> str | None:
            return value.isoformat() if isinstance(value, time) else None

        return {
            "stock_code": event.get("stock_code"),
            "stock_name": event.get("stock_name"),
            "board_count": board_count,
            "close_price": event.get("close_price"),
            "limit_price": event.get("limit_price"),
            "change_pct": event.get("change_pct"),
            "first_time": serialize_time(event.get("first_time")),
            "last_time": serialize_time(event.get("last_time")),
            "open_count": event.get("open_count"),
            "turnover_amount": event.get("turnover_amount"),
            "amount_yuan": event.get("amount_yuan"),
        }

    def _build_sector_strength(self, round_id: str, round_quotes: dict[str, dict]) -> dict[str, dict]:
        result: dict[str, dict] = {}
        for sector_code, members in self._sector_members.items():
            quotes = [round_quotes[code] for code in members if code in round_quotes and round_quotes[code].get("change_pct") is not None]
            if not quotes:
                continue
            changes = [float(item["change_pct"]) for item in quotes]
            leader = max(quotes, key=lambda item: float(item.get("change_pct") or 0))
            laggard = min(quotes, key=lambda item: float(item.get("change_pct") or 0))
            info = self._sector_info[sector_code]
            median_change = self._median(changes)
            verified_limit_quotes = [item for item in quotes if self._has_verified_limit_prices(item)]
            limit_up_count = sum(1 for item in verified_limit_quotes if self._is_limit_event(item, "up")) if verified_limit_quotes else None
            limit_down_count = sum(1 for item in verified_limit_quotes if self._is_limit_event(item, "down")) if verified_limit_quotes else None
            amount = sum(float(item.get("amount_yuan") or 0) for item in quotes)
            heat_breakdown = self._heat_breakdown(changes, limit_up_count or 0, limit_down_count or 0, len(members), amount)
            coverage_pct = round(len(quotes) / max(1, len(members)) * 100, 2)
            result[sector_code] = {
                **info,
                "as_of": self._market_overview.get("as_of"),
                "round_id": round_id,
                "member_count": len(members),
                "quote_count": len(quotes),
                "coverage_pct": coverage_pct,
                "confidence": self._coverage_confidence(coverage_pct),
                "change_pct": round(sum(changes) / len(changes), 4),
                "median_change_pct": median_change,
                "up_count": sum(1 for value in changes if value > 0),
                "down_count": sum(1 for value in changes if value < 0),
                "flat_count": sum(1 for value in changes if value == 0),
                "amount_yuan": amount,
                "limit_events_available": bool(verified_limit_quotes),
                "limit_up_count": limit_up_count,
                "limit_down_count": limit_down_count,
                "heat_breakdown": heat_breakdown,
                "heat_score": self._heat_score(changes, limit_up_count or 0, limit_down_count or 0, len(members), amount),
                "leader": {"stock_code": leader["stock_code"], "stock_name": leader.get("stock_name"), "change_pct": leader.get("change_pct"), "last_price": leader.get("last_price")},
                "laggard": {
                    "stock_code": laggard["stock_code"],
                    "stock_name": laggard.get("stock_name"),
                    "change_pct": laggard.get("change_pct"),
                    "last_price": laggard.get("last_price"),
                },
                "leaders": self._rank_quotes(quotes, reverse=True, limit=5),
                "laggards": self._rank_quotes(quotes, reverse=False, limit=5),
            }
        self._apply_sector_ranks(result)
        return result

    def _build_pool_summaries(self, round_id: str, round_quotes: dict[str, dict]) -> dict[str, dict]:
        result: dict[str, dict] = {}
        for pool_code, pool in self._pools.items():
            codes = pool["stock_codes"]
            quotes = [round_quotes[code] for code in codes if code in round_quotes and round_quotes[code].get("change_pct") is not None]
            changes = [float(item["change_pct"]) for item in quotes]
            verified_limit_quotes = [item for item in quotes if self._has_verified_limit_prices(item)]
            limit_up_count = sum(1 for item in verified_limit_quotes if self._is_limit_event(item, "up")) if verified_limit_quotes else None
            limit_down_count = sum(1 for item in verified_limit_quotes if self._is_limit_event(item, "down")) if verified_limit_quotes else None
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
                "limit_events_available": bool(verified_limit_quotes),
                "limit_up_count": limit_up_count,
                "limit_down_count": limit_down_count,
                "heat_score": self._heat_score(changes, limit_up_count or 0, limit_down_count or 0, len(codes), sum(float(item.get("amount_yuan") or 0) for item in quotes)),
                "leaders": self._rank_quotes(quotes, reverse=True, limit=5),
            }
        return result

    def _apply_sector_ranks(self, sectors: dict[str, dict]) -> None:
        """Attach a comparable heat rank within each independent taxonomy.

        Concepts and SW industries intentionally remain separate.  The rank
        delta is a purely intraday comparison with the preceding accepted
        full-market Quote round, not an EOD momentum or emotion signal.
        """
        next_ranks: dict[str, int] = {}
        grouped: dict[str, list[dict]] = {}
        for item in sectors.values():
            grouped.setdefault(str(item.get("sector_type") or "unknown"), []).append(item)
        for sector_type, items in grouped.items():
            items.sort(
                key=lambda item: (
                    -(item.get("heat_score") or 0),
                    -(item.get("coverage_pct") or 0),
                    str(item.get("sector_code") or ""),
                )
            )
            for position, item in enumerate(items, start=1):
                key = f"{sector_type}:{item['sector_code']}"
                previous_rank = self._previous_sector_ranks.get(key)
                item["rank"] = position
                item["previous_rank"] = previous_rank
                item["rank_change"] = previous_rank - position if previous_rank is not None else None
                next_ranks[key] = position
        self._previous_sector_ranks = next_ranks

    def _record_market_history(self, round_id: str) -> None:
        """Append one compact intraday dashboard point and meaningful changes.

        This function is called only after a >=95% full-market round is
        accepted.  A failed/degraded provider call therefore cannot create a
        fabricated trend or anomaly event.
        """
        trade_date = datetime.now(tz=SHANGHAI).date()
        if self._market_history_trade_date != trade_date:
            # The normal refresh path clears previous ranks *before* it builds
            # the current sector snapshot.  Keep the just-built rank map here
            # as a defensive fallback for direct/test callers.
            self._market_history_trade_date = trade_date
            self._market_timeline = []
            self._market_events = []
            self._previous_concept_leaders = {}
            self._previous_market_breadth = None

        overview_items = self._market_overview.get("items") if isinstance(self._market_overview.get("items"), dict) else {}
        concepts = sorted(
            (item for item in self._sector_strength.values() if item.get("sector_type") == "concept"),
            key=lambda item: (item.get("rank") or 10_000, str(item.get("sector_code") or "")),
        )
        top_concepts = concepts[:10]
        had_baseline = bool(self._market_timeline)
        timeline_point = {
            "as_of": self._market_overview.get("as_of"),
            "round_id": round_id,
            "up_count": overview_items.get("up_count"),
            "down_count": overview_items.get("down_count"),
            "flat_count": overview_items.get("flat_count"),
            "average_change_pct": overview_items.get("average_change_pct"),
            "median_change_pct": overview_items.get("median_change_pct"),
            "total_amount_yuan": overview_items.get("total_amount_yuan"),
            "breadth_state": (overview_items.get("market_breadth") or {}).get("state"),
            "top_concepts": [
                {
                    "sector_code": item.get("sector_code"),
                    "sector_name": item.get("sector_name"),
                    "rank": item.get("rank"),
                    "heat_score": item.get("heat_score"),
                    "change_pct": item.get("change_pct"),
                    "leader": item.get("leader"),
                }
                for item in top_concepts[:3]
            ],
        }
        self._market_timeline.append(timeline_point)
        self._market_timeline = self._market_timeline[-MARKET_TIMELINE_MAX_ITEMS:]

        if had_baseline:
            events = self._build_market_events(round_id, top_concepts, overview_items)
            self._market_events.extend(events[:MARKET_EVENT_PER_ROUND_LIMIT])
            self._market_events = self._market_events[-MARKET_EVENT_MAX_ITEMS:]
        self._previous_market_breadth = (overview_items.get("market_breadth") or {}).get("state")
        self._previous_concept_leaders = {
            str(item.get("sector_code")): str((item.get("leader") or {}).get("stock_code"))
            for item in top_concepts[:5]
            if (item.get("leader") or {}).get("stock_code")
        }

    def _ensure_market_history_trade_date(self) -> None:
        trade_date = datetime.now(tz=SHANGHAI).date()
        if self._market_history_trade_date == trade_date:
            return
        self._market_history_trade_date = trade_date
        self._market_timeline = []
        self._market_events = []
        self._previous_sector_ranks = {}
        self._previous_concept_leaders = {}
        self._previous_market_breadth = None

    def _build_market_events(self, round_id: str, top_concepts: list[dict], overview_items: dict) -> list[dict]:
        as_of = self._market_overview.get("as_of")
        events: list[dict] = []

        breadth_state = (overview_items.get("market_breadth") or {}).get("state")
        if breadth_state and breadth_state != self._previous_market_breadth:
            labels = {"broadly_up": "全市场上涨占优", "broadly_down": "全市场下跌占优", "mixed": "全市场涨跌回到均衡"}
            events.append(
                {
                    "event_type": "market_breadth_changed",
                    "severity": "positive" if breadth_state == "broadly_up" else "negative" if breadth_state == "broadly_down" else "neutral",
                    "title": labels.get(str(breadth_state), "市场宽度变化"),
                    "detail": f"上涨 {overview_items.get('up_count', 0)} 家，下跌 {overview_items.get('down_count', 0)} 家。",
                }
            )

        for item in top_concepts:
            rank_change = item.get("rank_change")
            rank = item.get("rank")
            previous_rank = item.get("previous_rank")
            sector_name = item.get("sector_name") or item.get("sector_code")
            if isinstance(rank_change, int) and rank_change >= 5:
                events.append(
                    {
                        "event_type": "concept_rank_up",
                        "severity": "positive",
                        "title": f"{sector_name} 热度上升",
                        "detail": f"概念热度排名由 #{previous_rank} 升至 #{rank}，上升 {rank_change} 位。",
                        "sector_code": item.get("sector_code"),
                        "sector_name": sector_name,
                    }
                )
            elif isinstance(rank_change, int) and rank_change <= -5:
                events.append(
                    {
                        "event_type": "concept_rank_down",
                        "severity": "negative",
                        "title": f"{sector_name} 热度回落",
                        "detail": f"概念热度排名由 #{previous_rank} 降至 #{rank}，回落 {abs(rank_change)} 位。",
                        "sector_code": item.get("sector_code"),
                        "sector_name": sector_name,
                    }
                )
            previous_leader = self._previous_concept_leaders.get(str(item.get("sector_code")))
            leader = item.get("leader") if isinstance(item.get("leader"), dict) else {}
            leader_code = leader.get("stock_code")
            if previous_leader and leader_code and leader_code != previous_leader and int(rank or 999) <= 5:
                events.append(
                    {
                        "event_type": "concept_leader_changed",
                        "severity": "neutral",
                        "title": f"{sector_name} 领涨股切换",
                        "detail": f"当前领涨为 {leader.get('stock_name') or leader_code}，涨跌幅 {leader.get('change_pct')}%。",
                        "sector_code": item.get("sector_code"),
                        "sector_name": sector_name,
                        "stock_code": leader_code,
                        "stock_name": leader.get("stock_name"),
                    }
                )

        for index, event in enumerate(events, start=1):
            event.update({"id": f"{round_id}:{index}", "as_of": as_of, "round_id": round_id})
        return events

    async def _persist_quote_caches(self, settings: RealtimeSettings) -> None:
        ttl = settings.cache_ttl_seconds
        history_ttl = self._market_history_ttl()
        trade_date = self._market_history_trade_date.isoformat() if self._market_history_trade_date else datetime.now(tz=SHANGHAI).date().isoformat()
        await redis_client.set_many_json(
            [
                (await redis_client.key("realtime", "market-overview"), self._market_overview, ttl),
                (await redis_client.key("realtime", "sectors"), list(self._sector_strength.values()), ttl),
                (await redis_client.key("realtime", "pools"), self._pool_summaries, ttl),
                (await redis_client.key("realtime", "market-timeline", trade_date), self._market_timeline, history_ttl),
                (await redis_client.key("realtime", "market-events", trade_date), self._market_events, history_ttl),
            ]
        )

    async def _persist_minute_cache(self, code: str, rows: list[dict], meta: dict) -> None:
        ttl = self._minute_session_ttl()
        changed = self._minute_cache_fields(code, rows, meta)
        await redis_client.hset_many_json(
            await redis_client.key("realtime", "minute-bars", code),
            changed,
            ttl_seconds=ttl,
        )

    def _minute_cache_fields(self, code: str, rows: list[dict], meta: dict) -> dict[str, dict]:
        cached_rows = self._minute_cached_rows.setdefault(code, {})
        changed = {
            str(row["bar_time"]): row
            for row in rows
            if row.get("bar_time") and cached_rows.get(str(row["bar_time"])) != row
        }
        cached_rows.update(changed)
        changed["__meta__"] = meta
        return changed

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
        safety_ratio = min(1.0, max(0.1, number("realtime_safety_ratio", 0.9)))
        signature = (quote_symbol_limit, universe_limit, depth_limit, safety_ratio)
        if signature == self._rate_signature:
            return
        self._rate_signature = signature
        self._rate_budgets = {
            "quote_symbols": RealtimeRateBudget("quote_symbols", quote_symbol_limit, safety_ratio),
            "quote_universe": RealtimeRateBudget("quote_universe", universe_limit, safety_ratio),
            "depth_batch": RealtimeRateBudget("depth_batch", depth_limit, safety_ratio),
            "on_demand_quote": self._on_demand_budget,
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
        return [RealtimeMarketService._rank_quote_item(item) for item in ranked[:limit]]

    @staticmethod
    def _rank_quotes_by_metric(items: list[dict], *, metric: str, limit: int = 10) -> list[dict]:
        ranked: list[dict] = []
        for item in items:
            try:
                value = float(item.get(metric))
            except (TypeError, ValueError):
                continue
            if value >= 0:
                ranked.append(item)
        ranked.sort(key=lambda item: float(item.get(metric) or 0), reverse=True)
        return [RealtimeMarketService._rank_quote_item(item) for item in ranked[:limit]]

    @staticmethod
    def _rank_quote_item(item: dict) -> dict:
        return {
            key: item.get(key)
            for key in ("stock_code", "stock_name", "last_price", "change_pct", "amount_yuan", "volume_hand")
        }

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
    def _has_verified_limit_prices(quote: dict) -> bool:
        metadata = quote.get("metadata") if isinstance(quote.get("metadata"), dict) else {}
        ext = metadata.get("ext") if isinstance(metadata.get("ext"), dict) else {}
        return ext.get("limit_up") is not None and ext.get("limit_down") is not None

    @staticmethod
    def _heat_breakdown(changes: list[float], limit_up: int, limit_down: int, member_count: int, amount: float) -> dict[str, float]:
        if not changes:
            return {"change": 0.0, "breadth": 0.0, "limit": 0.0, "liquidity": 0.0}
        up_ratio = sum(1 for value in changes if value > 0) / len(changes)
        mean_change = sum(changes) / len(changes)
        change_component = min(35.0, max(0.0, (mean_change + 3.0) / 6.0 * 35.0))
        breadth_component = up_ratio * 30.0
        limit_component = min(25.0, limit_up / max(1, member_count) * 250.0) - min(10.0, limit_down / max(1, member_count) * 100.0)
        liquidity_component = min(10.0, max(0.0, math.log10(max(1.0, amount)) - 6.0))
        return {
            "change": round(change_component, 2),
            "breadth": round(breadth_component, 2),
            "limit": round(limit_component, 2),
            "liquidity": round(liquidity_component, 2),
        }

    @classmethod
    def _heat_score(cls, changes: list[float], limit_up: int, limit_down: int, member_count: int, amount: float) -> float:
        breakdown = cls._heat_breakdown(changes, limit_up, limit_down, member_count, amount)
        return round(min(100.0, max(0.0, sum(breakdown.values()))), 2)

    @staticmethod
    def _coverage_confidence(coverage_pct: float) -> str:
        if coverage_pct >= 95:
            return "high"
        if coverage_pct >= 80:
            return "medium"
        return "low"

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
    def _market_history_ttl() -> int:
        now = datetime.now(tz=SHANGHAI)
        expiry = datetime.combine(now.date(), time(16, 30), tzinfo=SHANGHAI)
        return max(15 * 60, int((expiry - now).total_seconds()))

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
