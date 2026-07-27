"""The daily close production pipeline.

This module coordinates providers and canonical persistence.  Providers remain
raw transport adapters; factor computation is delegated to ``indicator_engine``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import date, datetime, timezone
from time import perf_counter
from typing import Any, Awaitable, Callable, Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from app.db.session import get_sessionmaker
from app.modules.config_center.repository import ConfigCenterRepository
from app.modules.indicator_engine.repository import IndicatorRepository
from app.modules.indicator_engine.service import IndicatorEngineService
from app.modules.market_data.contracts import CanonicalMappingResult
from app.modules.market_data.providers import MootdxProvider, normalize_symbol, parse_date, safe_float, safe_int
from app.modules.market_data.partitioning import ensure_market_partitions
from app.modules.market_data.repository import MarketDataRepository
from app.modules.market_data.tushare.contracts import TushareApiRequest
from app.modules.market_data.tushare.adapters import TushareMarketAdapter, TushareStockDailyAdapter
from app.modules.market_data.tushare_runtime import TushareProviderFactory, TushareRuntimeError
from app.modules.realtime_market.tickflow_runtime import (
    TickflowKlineProvider,
    TickflowProviderFactory,
    TickflowRuntimeError,
)


logger = logging.getLogger(__name__)
SHANGHAI = ZoneInfo("Asia/Shanghai")


class DailyMarketCloseIngestError(RuntimeError):
    code = "daily_market_close_ingest_failed"


class DailyMarketCloseIngestRequest(BaseModel):
    trade_date: date | None = None
    sync_daily: bool = True
    sync_daily_basic: bool = True
    sync_stock_technical_factor_pro: bool = True
    enhancement_start_date: date | None = None
    enhancement_end_date: date | None = None
    sync_lhb_events: bool = True
    sync_lhb_seats: bool = True
    sync_stock_moneyflow: bool = True
    sync_stock_limit_status: bool = True
    sync_lhb: bool = True
    sync_index_bars: bool = True
    sync_index_daily_basic: bool = True
    sync_north_hold: bool = False
    sync_market_stats: bool = True
    sync_sector_bars: bool = True
    sync_sector_moneyflow: bool = True
    sync_minute: bool = True
    calculate_daily_factors: bool = True
    calculate_minute_factors: bool = True
    calculate_technical_snapshot: bool = True
    calculate_stock_fund_factors: bool = True
    calculate_external_technical_factors: bool = True
    merge_external_technical_factors: bool = False
    calculate_sector_factors: bool = True
    fail_on_enrichment_error: bool = False
    enrichment_block_concurrency: int = Field(default=4, ge=1, le=10)
    minute_retention_trade_days: int = Field(default=30, ge=1, le=60)
    minute_max_concurrency: int = Field(default=10, ge=1, le=10)
    minute_batch_size: int = Field(default=200, ge=20, le=1000)
    minute_factor_stock_batch_size: int = Field(default=200, ge=50, le=500)
    ingest_mode: Literal["append_safe", "rebuild"] = "append_safe"


class DailyMarketCloseIngestResult(BaseModel):
    status: Literal["success", "skipped", "partial"] = "success"
    trade_date: date
    universe_count: int = 0
    daily_rows: int = 0
    daily_basic_rows: int = 0
    stock_technical_factor_rows: int = 0
    stock_moneyflow_rows: int = 0
    stock_limit_rows: int = 0
    lhb_event_rows: int = 0
    lhb_seat_rows: int = 0
    index_bar_rows: int = 0
    index_daily_basic_rows: int = 0
    north_hold_rows: int = 0
    market_stat_rows: int = 0
    sector_bar_rows: int = 0
    sector_moneyflow_rows: int = 0
    minute_target_count: int = 0
    minute_complete_count: int = 0
    minute_partial_count: int = 0
    minute_failed_count: int = 0
    minute_batch_count: int = 0
    minute_batches: list[dict] = Field(default_factory=list)
    daily_factor_rows: int = 0
    minute_factor_rows: int = 0
    technical_snapshot_rows: int = 0
    sector_factor_rows: int = 0
    enrichment_blocks: list[dict] = Field(default_factory=list)
    stage_timings: dict[str, int] = Field(default_factory=dict)
    block_status: dict[str, dict] = Field(default_factory=dict)
    coverage: dict[str, float] = Field(default_factory=dict)
    core_ready: bool = False
    report_quality: Literal["complete", "degraded", "blocked", "not_applicable"] = "blocked"
    missing_blocks: list[str] = Field(default_factory=list)
    pruned_partitions: list[str] = Field(default_factory=list)
    rebuild_deleted: dict[str, int] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DailyMarketCloseIngestService:
    """Build one trading day's reusable market facts and derived indicators."""

    minute_complete_threshold = 230
    daily_minimum_floor = 3000
    core_index_tickflow_max_concurrency = 3
    core_index_codes = ("000001.SH", "399001.SZ", "399006.SZ", "000300.SH", "000905.SH", "000852.SH", "000016.SH")

    def __init__(self, repository: MarketDataRepository, config_repository: ConfigCenterRepository) -> None:
        self.repository = repository
        self.config_repository = config_repository
        self.tushare = TushareProviderFactory(config_repository)
        # This client is used only by the minute-ingest stage.  Core index
        # daily bars use TickFlow/Tushare and must never enter a TDX host scan.
        self.mootdx = MootdxProvider(
            timeout_seconds=2,
            auto_retry=0,
            fallback_server_limit=4,
        )
        self.tushare_daily_adapter = TushareStockDailyAdapter()
        self.tushare_market_adapter = TushareMarketAdapter()

    def close(self) -> None:
        self.mootdx.close()

    async def run_minute(self, payload: DailyMarketCloseIngestRequest) -> DailyMarketCloseIngestResult:
        """Persist current-day MooTDX minute bars and their reusable minute factors."""
        started = perf_counter()
        trade_date = payload.trade_date or datetime.now(SHANGHAI).date()
        result = DailyMarketCloseIngestResult(
            trade_date=trade_date,
            report_quality="not_applicable",
        )
        trade_day = await self.repository.get_trade_day(trade_date)
        if trade_day is None:
            raise DailyMarketCloseIngestError(f"交易日历缺少 {trade_date.isoformat()}，请先同步 t_trade_calendar")
        if not trade_day.is_open:
            result.status = "skipped"
            result.warnings.append(f"{trade_date.isoformat()} 为非交易日，未执行分钟沉淀")
            return result
        today = datetime.now(SHANGHAI).date()
        if trade_date != today:
            result.status = "skipped"
            result.warnings.append("MooTDX 分钟任务只处理当前交易日，不执行历史分钟补数")
            return result

        universe = [
            code
            for code in await self.repository.list_active_stock_codes()
            if self._supports_mootdx_intraday(code)
        ]
        result.universe_count = len(universe)
        result.minute_target_count = len(universe)
        if not universe:
            raise DailyMarketCloseIngestError("all_a_share 动态范围为空，未发现可获取分钟线的沪深 active 股票")

        partition_started = perf_counter()
        await ensure_market_partitions(
            self.repository.session,
            trade_date=trade_date,
            include_minute_bar=True,
            include_minute_factor=payload.calculate_minute_factors,
        )
        await self.repository.commit()
        result.stage_timings["partition_preflight"] = int((perf_counter() - partition_started) * 1000)

        if payload.ingest_mode == "rebuild":
            result.rebuild_deleted = await self.repository.clear_minute_ingest_data(trade_date)
            await self.repository.commit()

        minute_started = perf_counter()
        minute_result = await self._sync_intraday(
            universe,
            trade_date=trade_date,
            sync_minute=True,
            max_concurrency=payload.minute_max_concurrency,
            minute_batch_size=payload.minute_batch_size,
            append_safe=payload.ingest_mode == "append_safe",
        )
        result.minute_complete_count = minute_result["minute_complete_count"]
        result.minute_partial_count = minute_result["minute_partial_count"]
        result.minute_failed_count = minute_result["minute_failed_count"]
        result.minute_batch_count = minute_result["minute_batch_count"]
        result.minute_batches = minute_result["minute_batches"]
        result.errors.extend(minute_result["errors"])
        result.stage_timings["minute_bars"] = int((perf_counter() - minute_started) * 1000)

        minute_counts = await self.repository.minute_bar_counts(
            stock_codes=universe,
            trade_date=trade_date,
        )
        if payload.calculate_minute_factors:
            factor_started = perf_counter()
            indicator_repository = IndicatorRepository(self.repository.session)
            factor_rows = 0
            factor_counts_before = await self.repository.minute_factor_counts(
                stock_codes=universe,
                trade_date=trade_date,
            )
            factor_targets = [
                code
                for code in universe
                if (
                    payload.ingest_mode == "rebuild"
                    or factor_counts_before.get(code, 0) < minute_counts.get(code, 0)
                )
            ]
            for batch_no, codes in enumerate(
                self._chunks(factor_targets, payload.minute_factor_stock_batch_size),
                start=1,
            ):
                batch_started = perf_counter()
                try:
                    written = await indicator_repository.backfill_minute_factors_set_based(
                        codes,
                        trade_date=trade_date,
                    )
                    await self.repository.commit()
                    factor_rows += written
                    logger.info(
                        "minute factor SQL batch completed: trade_date=%s batch=%s stocks=%s rows=%s elapsed_ms=%s",
                        trade_date,
                        batch_no,
                        len(codes),
                        written,
                        int((perf_counter() - batch_started) * 1000),
                    )
                except Exception as exc:
                    await self.repository.rollback()
                    message = (
                        f"minute factor batch {batch_no} failed: "
                        f"{type(exc).__name__}: {exc}"
                    )
                    logger.exception(
                        "minute factor SQL batch failed: trade_date=%s batch=%s stocks=%s",
                        trade_date,
                        batch_no,
                        len(codes),
                    )
                    result.errors.append(message)
            result.minute_factor_rows = factor_rows
            result.stage_timings["minute_factors"] = int((perf_counter() - factor_started) * 1000)

        minute_coverage = result.minute_complete_count / max(1, result.minute_target_count)
        factor_counts_after = await self.repository.minute_factor_counts(
            stock_codes=universe,
            trade_date=trade_date,
        )
        minute_bar_rows = sum(minute_counts.values())
        minute_factor_rows = sum(
            min(count, minute_counts.get(code, 0))
            for code, count in factor_counts_after.items()
        )
        result.coverage["minute_bars"] = round(minute_coverage, 6)
        result.coverage["minute_factors"] = round(
            min(1.0, minute_factor_rows / max(1, minute_bar_rows)),
            6,
        )
        result.block_status["minute_bars"] = {
            "status": "complete" if minute_coverage >= 0.95 else "partial",
            "rows": int(minute_result.get("minute_row_count") or 0),
        }
        result.block_status["minute_factors"] = {
            "status": "complete" if result.coverage["minute_factors"] >= 0.95 else "partial",
            "rows": minute_factor_rows,
        }
        if minute_coverage >= 0.95:
            retention_started = perf_counter()
            try:
                result.pruned_partitions = await self._prune_minute_data(
                    trade_date,
                    payload.minute_retention_trade_days,
                )
                await self.repository.commit()
            except Exception as exc:
                await self.repository.rollback()
                result.warnings.append(f"分钟分区清理失败，已保留沉淀数据: {exc}")
            result.stage_timings["retention"] = int((perf_counter() - retention_started) * 1000)
        else:
            result.status = "partial"
            result.missing_blocks.append("minute_bars")
            result.warnings.append(f"分钟线完整覆盖率 {minute_coverage:.1%}，未执行历史分钟分区清理")
        if result.coverage["minute_factors"] < 0.95:
            result.status = "partial"
            result.missing_blocks.append("minute_factors")
        if result.errors and result.status == "success":
            result.status = "partial"
        result.stage_timings["total"] = int((perf_counter() - started) * 1000)
        return result

    async def run(self, payload: DailyMarketCloseIngestRequest) -> DailyMarketCloseIngestResult:
        run_started = perf_counter()
        trade_date = payload.trade_date or datetime.now(SHANGHAI).date()
        result = DailyMarketCloseIngestResult(trade_date=trade_date)
        trade_day = await self.repository.get_trade_day(trade_date)
        if trade_day is None:
            raise DailyMarketCloseIngestError(f"交易日历缺少 {trade_date.isoformat()}，请先同步 t_trade_calendar")
        if not trade_day.is_open:
            result.status = "skipped"
            result.warnings.append(f"{trade_date.isoformat()} 为非交易日，未执行收盘沉淀")
            return result

        universe = await self.repository.list_active_stock_codes()
        universe_set = set(universe)
        result.universe_count = len(universe)
        if not universe:
            raise DailyMarketCloseIngestError("all_a_share 动态范围为空，未发现 active 股票")

        logger.info(
            "daily close ingest started: trade_date=%s universe=%s mode=%s minute=%s",
            trade_date,
            len(universe),
            payload.ingest_mode,
            payload.sync_minute,
        )
        today = datetime.now(SHANGHAI).date()
        created_partitions = await ensure_market_partitions(
            self.repository.session,
            trade_date=trade_date,
            include_minute_bar=payload.sync_minute and trade_date == today,
            include_minute_factor=payload.calculate_minute_factors,
        )
        if created_partitions:
            logger.info("daily close ingest prepared partitions: %s", created_partitions)

        if payload.ingest_mode == "rebuild":
            result.rebuild_deleted = await self.repository.clear_daily_close_ingest_data(trade_date)
            await self.repository.commit()

        core_started = perf_counter()
        await self._run_parallel_core_blocks(
            trade_date=trade_date,
            payload=payload,
            result=result,
            universe_set=universe_set,
        )
        if any(
            (
                payload.sync_daily,
                payload.sync_daily_basic,
                payload.sync_stock_moneyflow,
                payload.sync_index_bars,
                payload.sync_north_hold,
            )
        ):
            result.stage_timings["core_fact_blocks"] = int((perf_counter() - core_started) * 1000)

        daily_codes = await self._daily_codes(trade_date)
        if not daily_codes:
            raise DailyMarketCloseIngestError(f"{trade_date.isoformat()} 没有 Canonical 日线，不能继续分钟和因子沉淀")
        daily_targets = sorted(set(daily_codes) & universe_set)

        enrichment_started = perf_counter()
        await self._run_parallel_enrichment_blocks(
            trade_date=trade_date,
            payload=payload,
            result=result,
            universe_set=universe_set,
        )
        if result.enrichment_blocks:
            result.stage_timings["enhancement_fact_blocks"] = int(
                (perf_counter() - enrichment_started) * 1000
            )

        minute_targets = list(daily_targets)
        if payload.sync_minute:
            if trade_date != today:
                result.minute_target_count = len(minute_targets)
                result.warnings.append("MooTDX 仅提供当前交易日分钟线，历史指定日期跳过分钟线")
            else:
                skipped_intraday_codes = [
                    stock_code for stock_code in minute_targets if not self._supports_mootdx_intraday(stock_code)
                ]
                if skipped_intraday_codes:
                    minute_targets = [
                        stock_code for stock_code in minute_targets if self._supports_mootdx_intraday(stock_code)
                    ]
                    result.warnings.append(
                        "MooTDX intraday 暂只沉淀沪深股票，已跳过非沪深/未知代码数: "
                        f"{len(skipped_intraday_codes)}"
                    )
                result.minute_target_count = len(minute_targets)
                minute_result = await self._sync_intraday(
                    minute_targets,
                    trade_date=trade_date,
                    sync_minute=payload.sync_minute,
                    max_concurrency=payload.minute_max_concurrency,
                    minute_batch_size=payload.minute_batch_size,
                    append_safe=payload.ingest_mode == "append_safe",
                )
                result.minute_complete_count = minute_result["minute_complete_count"]
                result.minute_partial_count = minute_result["minute_partial_count"]
                result.minute_failed_count = minute_result["minute_failed_count"]
                result.minute_batch_count = minute_result["minute_batch_count"]
                result.minute_batches = minute_result["minute_batches"]
                result.errors.extend(minute_result["errors"])
                await self.repository.commit()

        indicator_repository = IndicatorRepository(self.repository.session)
        if payload.calculate_daily_factors:
            factor_started = perf_counter()
            for codes in self._chunks(daily_targets, 500):
                written = await indicator_repository.backfill_daily_factors_set_based(
                    codes,
                    start_date=trade_date,
                    end_date=trade_date,
                    history_start=trade_date.fromordinal(trade_date.toordinal() - 100),
                    fund_history_start=trade_date.fromordinal(trade_date.toordinal() - 20),
                    only_missing=False,
                    calculate_stock_fund=payload.calculate_stock_fund_factors,
                    include_external_technical=payload.calculate_external_technical_factors,
                )
                result.daily_factor_rows += written.get(trade_date, 0)
                await self.repository.commit()
            result.stage_timings["daily_factors"] = int((perf_counter() - factor_started) * 1000)

        if payload.merge_external_technical_factors:
            merge_started = perf_counter()
            for codes in self._chunks(daily_targets, 1000):
                result.daily_factor_rows += await indicator_repository.merge_external_technical_features(
                    codes,
                    trade_date=trade_date,
                )
                await self.repository.commit()
            result.stage_timings["external_technical_merge"] = int(
                (perf_counter() - merge_started) * 1000
            )

        if payload.calculate_minute_factors and minute_targets:
            factor_started = perf_counter()
            for codes in self._chunks(minute_targets, payload.minute_factor_stock_batch_size):
                result.minute_factor_rows += await indicator_repository.backfill_minute_factors_set_based(
                    codes,
                    trade_date=trade_date,
                )
                await self.repository.commit()
            result.stage_timings["minute_factors"] = int((perf_counter() - factor_started) * 1000)

        if payload.calculate_technical_snapshot:
            snapshot_started = perf_counter()
            for codes in self._chunks(daily_targets, 500):
                written = await indicator_repository.backfill_technical_snapshots_set_based(
                    codes,
                    start_date=trade_date,
                    end_date=trade_date,
                    only_missing=False,
                )
                result.technical_snapshot_rows += written.get(trade_date, 0)
                await self.repository.commit()
            result.stage_timings["technical_snapshots"] = int(
                (perf_counter() - snapshot_started) * 1000
            )

        if payload.calculate_sector_factors:
            sector_factor_started = perf_counter()
            indicator = IndicatorEngineService(indicator_repository)
            result.sector_factor_rows = await indicator.calculate_sector_factors(trade_date=trade_date)
            result.stage_timings["sector_factors"] = int(
                (perf_counter() - sector_factor_started) * 1000
            )

        if payload.sync_minute and result.minute_target_count:
            coverage = result.minute_complete_count / result.minute_target_count
            if coverage >= 0.95:
                try:
                    result.pruned_partitions = await self._prune_minute_data(
                        trade_date,
                        payload.minute_retention_trade_days,
                    )
                    await self.repository.commit()
                except Exception as exc:
                    await self.repository.rollback()
                    logger.warning("minute partition retention failed but ingest facts are preserved: %s", exc)
                    result.warnings.append(f"分钟分区清理失败，已保留沉淀数据: {exc}")
            else:
                result.status = "partial"
                result.warnings.append(f"分钟线完整覆盖率 {coverage:.1%}，未执行历史分钟分区清理")
        elif payload.sync_minute:
            result.status = "partial"

        if result.errors and result.status == "success":
            result.status = "partial"
        await self._finalize_readiness(result, universe_count=len(universe))
        result.stage_timings["total"] = int((perf_counter() - run_started) * 1000)
        logger.info(
            "daily close ingest finished: trade_date=%s status=%s daily=%s minute_complete=%s/%s factors=%s/%s/%s",
            trade_date,
            result.status,
            result.daily_rows,
            result.minute_complete_count,
            result.minute_target_count,
            result.daily_factor_rows,
            result.minute_factor_rows,
            result.technical_snapshot_rows,
        )
        return result

    async def _run_parallel_core_blocks(
        self,
        *,
        trade_date: date,
        payload: DailyMarketCloseIngestRequest,
        result: DailyMarketCloseIngestResult,
        universe_set: set[str],
    ) -> None:
        specs: list[dict[str, Any]] = [
            {
                "label": "daily",
                "enabled": payload.sync_daily,
                "target": "daily_rows",
                "fail_on_error": True,
                "operation": lambda service: service._sync_daily_bars(trade_date, universe_set),
            },
            {
                "label": "daily basic",
                "enabled": payload.sync_daily_basic,
                "target": "daily_basic_rows",
                "fail_on_error": True,
                "operation": lambda service: service._sync_daily_basic(trade_date, universe_set),
            },
            {
                "label": "stock moneyflow",
                "enabled": payload.sync_stock_moneyflow,
                "target": "stock_moneyflow_rows",
                "fail_on_error": payload.fail_on_enrichment_error,
                "operation": lambda service: service._sync_stock_moneyflow(trade_date, universe_set),
            },
            {
                "label": "index bars",
                "enabled": payload.sync_index_bars,
                "target": "index_bar_rows",
                "fail_on_error": payload.fail_on_enrichment_error,
                "operation": lambda service: service._sync_index_bars(trade_date, result),
            },
            {
                "label": "north hold",
                "enabled": payload.sync_north_hold,
                "target": "north_hold_rows",
                "fail_on_error": payload.fail_on_enrichment_error,
                "operation": lambda service: service._sync_north_hold(trade_date, universe_set, result),
            },
        ]
        enabled_specs = [spec for spec in specs if spec["enabled"]]
        if not enabled_specs:
            return
        semaphore = asyncio.Semaphore(min(payload.enrichment_block_concurrency, len(enabled_specs)))

        async def guarded(spec: dict[str, Any]) -> dict[str, Any]:
            async with semaphore:
                return await self._run_parallel_enrichment_block(
                    spec["label"],
                    spec["operation"],
                    fail_on_error=bool(spec["fail_on_error"]),
                    mode="single_date",
                    range_start_date=trade_date,
                    range_end_date=trade_date,
                )

        tasks = [asyncio.create_task(guarded(spec)) for spec in enabled_specs]
        try:
            block_results = await asyncio.gather(*tasks)
        except Exception:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        target_by_label = {spec["label"]: spec["target"] for spec in enabled_specs}
        for block_result in block_results:
            label = str(block_result.get("label"))
            if block_result.get("status") == "success":
                self._apply_enrichment_value(result, target_by_label[label], block_result.get("value"))
            else:
                result.warnings.append(str(block_result.get("error") or f"{label} 沉淀失败"))
            block_result.pop("value", None)
            result.enrichment_blocks.append(block_result)

    def _log_mapping_summary(self, mapping: CanonicalMappingResult) -> None:
        logger.info(
            "provider canonical mapping: provider=%s api=%s capability=%s range=%s raw=%s mapped=%s missing=%s conversions=%s warnings=%s",
            mapping.provider_code,
            mapping.api_name,
            mapping.capability_code,
            mapping.request_range,
            mapping.raw_count,
            mapping.mapped_count,
            mapping.missing_count,
            mapping.unit_conversions,
            mapping.warnings[:5],
        )

    def _log_upsert_summary(self, mapping: CanonicalMappingResult, upserted_count: int, table_name: str) -> None:
        logger.info(
            "provider canonical upsert: provider=%s api=%s capability=%s table=%s range=%s raw=%s mapped=%s upserted=%s missing=%s warnings=%s",
            mapping.provider_code,
            mapping.api_name,
            mapping.capability_code,
            table_name,
            mapping.request_range,
            mapping.raw_count,
            mapping.mapped_count,
            upserted_count,
            mapping.missing_count,
            mapping.warnings[:5],
        )

    async def _run_parallel_enrichment_blocks(
        self,
        *,
        trade_date: date,
        payload: DailyMarketCloseIngestRequest,
        result: DailyMarketCloseIngestResult,
        universe_set: set[str],
    ) -> None:
        block_specs: list[dict[str, Any]] = [
            {
                "label": "stock limit/suspend",
                "enabled": payload.sync_stock_limit_status,
                "target": "stock_limit_rows",
                "mode": "single_date",
                "range_start_date": trade_date,
                "range_end_date": trade_date,
                "operation": lambda service: service._sync_stock_limit_status(trade_date, universe_set),
            },
            {
                "label": "sector bars",
                "enabled": payload.sync_sector_bars,
                "target": "sector_bar_rows",
                "mode": "single_date",
                "range_start_date": trade_date,
                "range_end_date": trade_date,
                "operation": lambda service: service._sync_sector_bars(trade_date, result),
            },
            {
                "label": "stock technical factor pro",
                "enabled": payload.sync_stock_technical_factor_pro,
                "target": "stock_technical_factor_rows",
                "mode": "single_date",
                "range_start_date": trade_date,
                "range_end_date": trade_date,
                "operation": lambda service: service._sync_stock_technical_factor_pro(trade_date, universe_set),
            },
            {
                "label": "lhb events",
                "enabled": payload.sync_lhb and payload.sync_lhb_events,
                "target": "lhb_event_rows",
                "mode": self._enhancement_mode(payload),
                "range_start_date": payload.enhancement_start_date or trade_date,
                "range_end_date": payload.enhancement_end_date or trade_date,
                "operation": lambda service: service._sync_lhb_events(
                    trade_date,
                    universe_set,
                    start_date=payload.enhancement_start_date,
                    end_date=payload.enhancement_end_date,
                ),
            },
            {
                "label": "lhb seats",
                "enabled": payload.sync_lhb and payload.sync_lhb_seats,
                "target": "lhb_seat_rows",
                "mode": "single_date",
                "range_start_date": trade_date,
                "range_end_date": trade_date,
                "operation": lambda service: service._sync_lhb_seats(trade_date, universe_set),
            },
            {
                "label": "index daily basic",
                "enabled": payload.sync_index_daily_basic,
                "target": "index_daily_basic_rows",
                "mode": self._enhancement_mode(payload),
                "range_start_date": payload.enhancement_start_date or trade_date,
                "range_end_date": payload.enhancement_end_date or trade_date,
                "operation": lambda service: service._sync_index_daily_basic(
                    trade_date,
                    start_date=payload.enhancement_start_date,
                    end_date=payload.enhancement_end_date,
                ),
            },
            {
                "label": "market stats",
                "enabled": payload.sync_market_stats,
                "target": "market_stat_rows",
                "mode": self._enhancement_mode(payload),
                "range_start_date": payload.enhancement_start_date or trade_date,
                "range_end_date": payload.enhancement_end_date or trade_date,
                "operation": lambda service: service._sync_market_stats(
                    trade_date,
                    start_date=payload.enhancement_start_date,
                    end_date=payload.enhancement_end_date,
                ),
            },
            {
                "label": "sector moneyflow",
                "enabled": payload.sync_sector_moneyflow,
                "target": "sector_moneyflow_rows",
                "mode": self._enhancement_mode(payload),
                "range_start_date": payload.enhancement_start_date or trade_date,
                "range_end_date": payload.enhancement_end_date or trade_date,
                "operation": lambda service: service._sync_sector_moneyflow(
                    trade_date,
                    start_date=payload.enhancement_start_date,
                    end_date=payload.enhancement_end_date,
                ),
            },
        ]
        enabled_specs = [spec for spec in block_specs if spec["enabled"]]
        if not enabled_specs:
            return

        logger.info(
            "daily close ingest enrichment parallel started: blocks=%s concurrency=%s",
            len(enabled_specs),
            payload.enrichment_block_concurrency,
        )
        semaphore = asyncio.Semaphore(payload.enrichment_block_concurrency)

        async def guarded(spec: dict[str, Any]) -> dict[str, Any]:
            async with semaphore:
                return await self._run_parallel_enrichment_block(
                    spec["label"],
                    spec["operation"],
                    fail_on_error=payload.fail_on_enrichment_error,
                    mode=str(spec.get("mode") or "single_date"),
                    range_start_date=spec.get("range_start_date"),
                    range_end_date=spec.get("range_end_date"),
                )

        tasks = [asyncio.create_task(guarded(spec)) for spec in enabled_specs]
        try:
            block_results = await asyncio.gather(*tasks)
        except Exception:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

        target_by_label = {spec["label"]: spec["target"] for spec in enabled_specs}
        for block_result in block_results:
            label = str(block_result.get("label"))
            if (
                label == "market stats"
                and block_result.get("status") == "success"
                and int(block_result.get("rows") or 0) == 0
            ):
                block_result["status"] = "deferred"
                block_result["reason"] = "daily_info_not_published"
            if block_result.get("status") == "success":
                self._apply_enrichment_value(result, target_by_label[label], block_result.get("value"))
            elif block_result.get("status") == "deferred":
                result.warnings.append(f"{label} 当日数据尚未发布，已延后到缺口修复任务")
            else:
                message = str(block_result.get("error") or f"{label} 沉淀失败")
                result.warnings.append(message)
            block_result.pop("value", None)
            result.enrichment_blocks.append(block_result)
        logger.info(
            "daily close ingest enrichment parallel finished: blocks=%s failed=%s",
            len(block_results),
            sum(1 for item in block_results if item.get("status") != "success"),
        )

    async def _run_parallel_enrichment_block(
        self,
        label: str,
        operation: Callable[["DailyMarketCloseIngestService"], Awaitable[Any]],
        *,
        fail_on_error: bool,
        mode: str,
        range_start_date: date | None,
        range_end_date: date | None,
    ) -> dict[str, Any]:
        started = perf_counter()
        logger.info(
            "daily close ingest enrichment block started: label=%s mode=%s start_date=%s end_date=%s",
            label,
            mode,
            range_start_date,
            range_end_date,
        )
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            service = DailyMarketCloseIngestService(
                MarketDataRepository(session),
                ConfigCenterRepository(session),
            )
            try:
                value = await operation(service)
                await service.repository.commit()
            except Exception as exc:
                await service.repository.rollback()
                elapsed_ms = int((perf_counter() - started) * 1000)
                message = f"{label} 沉淀失败: {type(exc).__name__}: {exc}"
                logger.warning(
                    "daily close ingest enrichment block failed: label=%s elapsed_ms=%s error=%s",
                    label,
                    elapsed_ms,
                    message,
                )
                if fail_on_error:
                    raise DailyMarketCloseIngestError(message) from exc
                return {
                    "label": label,
                    "status": "failed",
                    "mode": mode,
                    "range_start_date": range_start_date.isoformat() if range_start_date else None,
                    "range_end_date": range_end_date.isoformat() if range_end_date else None,
                    "duration_ms": elapsed_ms,
                    "rows": 0,
                    "error": message,
                }
            finally:
                await asyncio.to_thread(service.close)

        elapsed_ms = int((perf_counter() - started) * 1000)
        rows = self._enrichment_row_count(value)
        logger.info(
            "daily close ingest enrichment block finished: label=%s mode=%s start_date=%s end_date=%s rows=%s elapsed_ms=%s",
            label,
            mode,
            range_start_date,
            range_end_date,
            rows,
            elapsed_ms,
        )
        return {
            "label": label,
            "status": "success",
            "mode": mode,
            "range_start_date": range_start_date.isoformat() if range_start_date else None,
            "range_end_date": range_end_date.isoformat() if range_end_date else None,
            "duration_ms": elapsed_ms,
            "rows": rows,
            "value": value,
        }

    def _apply_enrichment_value(self, result: DailyMarketCloseIngestResult, target: str | tuple[str, ...], value: Any) -> None:
        if isinstance(value, dict):
            setattr(result, str(target), int(value.get("rows") or 0))
            return
        if isinstance(target, tuple):
            for name, item in zip(target, value or (), strict=False):
                setattr(result, name, int(item or 0))
            return
        setattr(result, target, int(value or 0))

    @staticmethod
    def _enrichment_row_count(value: Any) -> int:
        if isinstance(value, dict):
            return int(value.get("rows") or 0)
        if isinstance(value, tuple):
            return sum(int(item or 0) for item in value)
        return int(value or 0)

    @staticmethod
    def _enhancement_mode(payload: DailyMarketCloseIngestRequest) -> str:
        if payload.enhancement_start_date and payload.enhancement_end_date and payload.enhancement_start_date != payload.enhancement_end_date:
            return "date_range"
        return "single_date"

    async def _tushare_response(self, api_name: str, params: dict, *, capability: str):
        try:
            return await self.tushare.call(
                capability,
                lambda transport: transport.request(TushareApiRequest(api_name, params)),
                request_summary={"api_name": api_name, **{key: self._json_value(value) for key, value in params.items()}},
                execution_mode="scheduler",
            )
        except TushareRuntimeError as exc:
            raise DailyMarketCloseIngestError(f"Tushare {api_name} 调用失败: {exc}") from exc

    async def _sync_daily_bars(self, trade_date: date, universe: set[str]) -> int:
        records, raw_payload = await self._tushare_records("daily", trade_date)
        mapping = self.tushare_daily_adapter.map_daily(
            records,
            trade_date=trade_date,
            universe=universe,
        )
        self._log_mapping_summary(mapping)
        min_expected = min(
            len(universe),
            max(self.daily_minimum_floor, int(len(universe) * 0.55)),
        )
        if len(mapping.rows) < min_expected:
            raise DailyMarketCloseIngestError(
                f"Tushare daily 返回 {len(mapping.rows)} 条，低于全市场保护阈值 {min_expected}；未降级为逐股请求"
            )
        upserted = await self.repository.upsert_daily_bars(mapping.rows)
        self._log_upsert_summary(mapping, upserted, "t_daily_bar")
        await self._capture_raw_summary(
            "daily_market_close_daily",
            trade_date,
            raw_payload,
            len(mapping.rows),
        )
        return upserted

    async def _sync_daily_basic(self, trade_date: date, universe: set[str]) -> int:
        records, raw_payload = await self._tushare_records("daily_basic", trade_date)
        mapping = self.tushare_daily_adapter.map_daily_basic(
            records,
            trade_date=trade_date,
            universe=universe,
        )
        self._log_mapping_summary(mapping)
        min_expected = max(1, int(len(universe) * 0.5))
        if len(mapping.rows) < min_expected:
            raise DailyMarketCloseIngestError(
                f"Tushare daily_basic 返回 {len(mapping.rows)} 条，低于沪深 active 范围的 50%"
            )
        upserted = await self.repository.upsert_daily_basic_rows(mapping.rows)
        self._log_upsert_summary(mapping, upserted, "t_stock_daily_basic")
        await self._capture_raw_summary(
            "daily_market_close_daily_basic",
            trade_date,
            raw_payload,
            len(mapping.rows),
            normalized_table="t_stock_daily_basic",
        )
        return upserted

    async def _sync_stock_technical_factor_pro(self, trade_date: date, universe: set[str]) -> int:
        response = await self._tushare_response(
            "stk_factor_pro",
            {"trade_date": trade_date},
            capability="daily_market_close_stock_technical_factor_pro",
        )
        rows = []
        for record in response.records:
            stock_code = normalize_symbol(str(record.get("ts_code") or ""))
            row_date = parse_date(record.get("trade_date"))
            if not stock_code or row_date is None or stock_code not in universe:
                continue
            factors = {
                key: value
                for key, value in record.items()
                if key not in {"ts_code", "trade_date"} and value is not None
            }
            rows.append(
                {
                    "stock_code": stock_code,
                    "trade_date": row_date,
                    "source": "tushare:stk_factor_pro",
                    "factors": factors,
                    "metadata_json": {"provider": "tushare", "api_name": "stk_factor_pro"},
                }
            )
        await self._capture_raw_summary(
            "daily_market_close_stock_technical_factor_pro",
            trade_date,
            response.raw_payload,
            len(rows),
            normalized_table="t_stock_technical_factor_daily",
        )
        return await self.repository.upsert_stock_technical_factor_rows(rows)

    async def _sync_stock_moneyflow(self, trade_date: date, universe: set[str]) -> int:
        response = await self._tushare_response("moneyflow", {"trade_date": trade_date}, capability="daily_market_close_stock_moneyflow")
        mapping = self.tushare_daily_adapter.map_moneyflow(response.records, trade_date=trade_date, universe=universe)
        self._log_mapping_summary(mapping)
        rows = mapping.rows
        await self._capture_raw_summary("daily_market_close_stock_moneyflow", trade_date, response.raw_payload, len(rows), normalized_table="t_stock_fund_flow_daily")
        upserted = await self.repository.upsert_stock_fund_flow_rows(rows)
        self._log_upsert_summary(mapping, upserted, "t_stock_fund_flow_daily")
        return upserted

    async def _sync_stock_limit_status(self, trade_date: date, universe: set[str]) -> int:
        limit_response = await self._tushare_response("limit_list_d", {"trade_date": trade_date}, capability="daily_market_close_stock_limit")
        suspend_response = await self._tushare_response("suspend_d", {"trade_date": trade_date}, capability="daily_market_close_stock_suspend")
        limit_mapping = self.tushare_daily_adapter.map_limit_events(
            limit_response.records,
            trade_date=trade_date,
            universe=universe,
        )
        suspend_mapping = self.tushare_daily_adapter.map_suspend_events(
            suspend_response.records,
            trade_date=trade_date,
            universe=universe,
        )
        self._log_mapping_summary(limit_mapping)
        self._log_mapping_summary(suspend_mapping)
        rows = [*limit_mapping.rows, *suspend_mapping.rows]
        await self._capture_raw_summary("daily_market_close_stock_limit", trade_date, limit_response.raw_payload, len(limit_response.records), normalized_table="t_limit_event_daily")
        await self._capture_raw_summary("daily_market_close_stock_suspend", trade_date, suspend_response.raw_payload, len(suspend_response.records), normalized_table="t_limit_event_daily")
        return await self.repository.upsert_limit_event_rows(rows)

    async def _sync_lhb(self, trade_date: date, universe: set[str]) -> tuple[int, int]:
        event_count = await self._sync_lhb_events(trade_date, universe)
        seat_count = await self._sync_lhb_seats(trade_date, universe)
        return event_count, seat_count

    async def _sync_lhb_events(
        self,
        trade_date: date,
        universe: set[str],
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> int:
        request_start_date = start_date or trade_date
        request_end_date = end_date or trade_date
        params = (
            {"start_date": request_start_date, "end_date": request_end_date}
            if request_start_date != request_end_date
            else {"trade_date": trade_date}
        )
        event_response = await self._tushare_response("top_list", params, capability="daily_market_close_lhb")
        mapping = self.tushare_market_adapter.map_top_list(
            event_response.records,
            start_date=request_start_date,
            end_date=request_end_date,
            universe=universe,
        )
        self._log_mapping_summary(mapping)
        events = mapping.rows
        await self._capture_raw_summary(
            "daily_market_close_lhb",
            trade_date,
            {
                "api_name": "top_list",
                "mode": "date_range" if request_start_date != request_end_date else "single_date",
                "start_date": request_start_date.isoformat(),
                "end_date": request_end_date.isoformat(),
                "raw_records": len(event_response.records),
            },
            len(events),
            normalized_table="t_lhb_event",
        )
        upserted = await self.repository.upsert_lhb_event_rows(events)
        self._log_upsert_summary(mapping, upserted, "t_lhb_event")
        return upserted

    async def _sync_lhb_seats(self, trade_date: date, universe: set[str]) -> int:
        seat_response = await self._tushare_response("top_inst", {"trade_date": trade_date}, capability="daily_market_close_lhb_seats")
        seats = []
        for record in seat_response.records:
            stock_code = normalize_symbol(str(record.get("ts_code") or ""))
            row_date = parse_date(record.get("trade_date"))
            seat_name = str(record.get("exalter") or record.get("seat_name") or record.get("name") or "")
            if stock_code and row_date and seat_name and stock_code in universe:
                buy = safe_float(record.get("buy"))
                sell = safe_float(record.get("sell"))
                seats.append(
                    {
                        "stock_code": stock_code,
                        "trade_date": row_date,
                        "source": "tushare:top_inst",
                        "side": "net",
                        "seat_name": seat_name,
                        "buy_amount": buy,
                        "sell_amount": sell,
                        "net_amount": safe_float(record.get("net_buy")) or self._net(buy, sell),
                        "rank": safe_int(record.get("rank")),
                        "metadata_json": {"provider": "tushare", "api_name": "top_inst", "raw": record},
                    }
                )
        await self._capture_raw_summary("daily_market_close_lhb_seats", trade_date, seat_response.raw_payload, len(seats), normalized_table="t_lhb_seat_detail")
        return await self.repository.upsert_lhb_seat_rows(seats)

    async def _sync_index_bars(self, trade_date: date, result: DailyMarketCloseIngestResult) -> int:
        core_codes = {
            normalize_symbol(index_code): index_code
            for index_code in self.core_index_codes
        }
        tickflow_rows, tickflow_errors = await self._tickflow_index_daily_rows(trade_date)
        rows_by_code = {
            normalize_symbol(str(row.get("index_code") or "")): row
            for row in tickflow_rows
            if normalize_symbol(str(row.get("index_code") or "")) in core_codes
        }
        tickflow_missing = [code for code in core_codes if code not in rows_by_code]
        tickflow_missing_set = set(tickflow_missing)
        tushare_rows: list[dict] = []
        tushare_raw_rows = 0
        tushare_error: str | None = None

        if tickflow_missing:
            try:
                response = await self._tushare_response(
                    "index_daily",
                    {"trade_date": trade_date},
                    capability="daily_market_close_index_bars_tushare_fallback",
                )
                tushare_raw_rows = len(response.records)
                fallback_records = [
                    record
                    for record in response.records
                    if normalize_symbol(str(record.get("ts_code") or "")) in tickflow_missing_set
                ]
                mapping = self.tushare_market_adapter.map_index_daily(
                    fallback_records,
                    trade_date=trade_date,
                    index_codes=tickflow_missing_set,
                )
                self._log_mapping_summary(mapping)
                result.warnings.extend(mapping.warnings)
                tushare_rows = mapping.rows
                rows_by_code.update(
                    {
                        normalize_symbol(str(row.get("index_code") or "")): row
                        for row in tushare_rows
                    }
                )
                await self._capture_raw_summary(
                    "daily_market_close_index_bars_tushare_fallback",
                    trade_date,
                    response.raw_payload,
                    len(tushare_rows),
                    normalized_table="t_index_bar",
                    provider_code="tushare",
                )
            except DailyMarketCloseIngestError as exc:
                tushare_error = str(exc)
                logger.warning(
                    "daily close ingest Tushare index fallback failed: missing=%s error=%s",
                    [core_codes[code] for code in tickflow_missing],
                    tushare_error,
                )

        rows = [rows_by_code[code] for code in core_codes if code in rows_by_code]
        missing_codes = [index_code for code, index_code in core_codes.items() if code not in rows_by_code]
        fallback_used = {
            code: "tushare:index_daily"
            for code in tickflow_missing
            if code in rows_by_code
        }
        await self._capture_raw_summary(
            "daily_market_close_index_bars",
            trade_date,
            {
                "api_name": "klines",
                "period": "1d",
                "adjust": "none",
                "index_codes": list(self.core_index_codes),
                "tickflow_request_count": len(self.core_index_codes),
                "tickflow_rows": len(tickflow_rows),
                "tickflow_errors": tickflow_errors,
                "tushare_fallback_requested": [core_codes[code] for code in tickflow_missing],
                "tushare_raw_rows": tushare_raw_rows,
                "tushare_error": tushare_error,
                "missing_codes": missing_codes,
                "fallback_used": fallback_used,
            },
            len(tickflow_rows),
            normalized_table="t_index_bar",
            provider_code="tickflow",
        )
        if fallback_used:
            result.warnings.append(
                "index_daily Tushare fallback_used: "
                + ", ".join(f"{core_codes[code]}->{source}" for code, source in sorted(fallback_used.items()))
            )
        if tickflow_errors:
            result.warnings.append(
                "TickFlow index daily unavailable: "
                + ", ".join(f"{core_codes[code]} ({error})" for code, error in sorted(tickflow_errors.items()))[:1000]
            )
        if tushare_error:
            result.warnings.append("Tushare index_daily fallback unavailable: " + tushare_error[:300])
        if missing_codes:
            result.warnings.append(f"index_daily 缺失指数: {', '.join(missing_codes)}")
        upserted = await self.repository.upsert_index_bar_rows(rows)
        logger.info(
            "provider canonical upsert: provider=%s api=%s capability=%s table=%s range=%s raw=%s mapped=%s upserted=%s missing=%s warnings=%s",
            "tickflow+tushare",
            "klines/index_daily",
            "index_daily",
            "t_index_bar",
            {"trade_date": trade_date.isoformat()},
            {"tickflow": len(tickflow_rows), "tushare": len(tushare_rows)},
            len(rows),
            upserted,
            len(missing_codes),
            [f"missing_codes={missing_codes[:10]}"] if missing_codes else [],
        )
        return upserted

    async def _tickflow_index_daily_rows(self, trade_date: date) -> tuple[list[dict], dict[str, str]]:
        """Fetch only same-day core-index K-lines; stale bars are intentionally rejected."""
        try:
            credentials = await TickflowProviderFactory(self.config_repository).resolve_realtime_credentials()
        except Exception as exc:  # A bad TickFlow configuration must not suppress the Tushare fallback.
            error = str(exc)
            return [], {normalize_symbol(index_code): error for index_code in self.core_index_codes}

        provider = TickflowKlineProvider(credentials)
        semaphore = asyncio.Semaphore(self.core_index_tickflow_max_concurrency)

        async def fetch(index_code: str) -> tuple[dict | None, str | None]:
            try:
                async with semaphore:
                    bars = await provider.daily_bars(index_code, count=2)
            except TickflowRuntimeError as exc:
                return None, str(exc)
            except Exception as exc:  # pragma: no cover - defensive SDK boundary.
                return None, f"{type(exc).__name__}: {exc}"
            row = self._tickflow_index_daily_row(index_code, trade_date, bars)
            if row is None:
                return None, f"no {trade_date.isoformat()} daily bar returned"
            return row, None

        try:
            fetched = await asyncio.gather(*(fetch(index_code) for index_code in self.core_index_codes))
        finally:
            await asyncio.to_thread(provider.close)

        rows: list[dict] = []
        errors: dict[str, str] = {}
        for index_code, (row, error) in zip(self.core_index_codes, fetched, strict=True):
            normalized = normalize_symbol(index_code)
            if row is not None:
                rows.append(row)
            elif error:
                errors[normalized] = error
        return rows, errors

    @staticmethod
    def _tickflow_index_daily_row(index_code: str, trade_date: date, bars: list[dict]) -> dict | None:
        target_bars = [
            bar
            for bar in bars
            if isinstance(bar.get("bar_time"), datetime)
            and bar["bar_time"].astimezone(SHANGHAI).date() == trade_date
        ]
        if not target_bars:
            return None
        current = max(target_bars, key=lambda bar: bar["bar_time"])
        current_time = current["bar_time"]
        previous_bars = [
            bar
            for bar in bars
            if isinstance(bar.get("bar_time"), datetime) and bar["bar_time"] < current_time
        ]
        previous_close = safe_float(current.get("previous_close_price"))
        if previous_close is None and previous_bars:
            previous_close = safe_float(max(previous_bars, key=lambda bar: bar["bar_time"]).get("close_price"))
        close_price = safe_float(current.get("close_price"))
        change_pct = (
            round((close_price - previous_close) / previous_close * 100, 6)
            if close_price is not None and previous_close not in (None, 0)
            else None
        )
        return {
            "index_code": normalize_symbol(index_code),
            "trade_date": trade_date,
            "source": "tickflow:klines",
            "open_price": safe_float(current.get("open_price")),
            "high_price": safe_float(current.get("high_price")),
            "low_price": safe_float(current.get("low_price")),
            "close_price": close_price,
            "change_pct": change_pct,
            "volume": safe_float(current.get("volume")),
            "amount_yuan": safe_float(current.get("amount_yuan")),
            "metadata_json": {
                "provider": "tickflow",
                "api_name": "klines",
                "source_symbol": current.get("source_symbol"),
                "period": "1d",
                "adjust": "none",
                "bar_time_utc": current_time.astimezone(timezone.utc).isoformat(),
                "amount_unit": "yuan",
            },
        }

    async def _sync_index_daily_basic(self, trade_date: date, *, start_date: date | None = None, end_date: date | None = None) -> int:
        request_start_date = start_date or trade_date
        request_end_date = end_date or trade_date
        params = (
            {"start_date": request_start_date, "end_date": request_end_date}
            if request_start_date != request_end_date
            else {"trade_date": trade_date}
        )
        response = await self._tushare_response("index_dailybasic", params, capability="daily_market_close_index_daily_basic")
        core_codes = {normalize_symbol(code) for code in self.core_index_codes}
        mapping = self.tushare_market_adapter.map_index_daily_basic(
            response.records,
            start_date=request_start_date,
            end_date=request_end_date,
            index_codes=core_codes,
        )
        self._log_mapping_summary(mapping)
        rows = mapping.rows
        await self._capture_raw_summary(
            "daily_market_close_index_daily_basic",
            trade_date,
            {
                "api_name": "index_dailybasic",
                "mode": "date_range" if request_start_date != request_end_date else "single_date",
                "start_date": request_start_date.isoformat(),
                "end_date": request_end_date.isoformat(),
                "raw_records": len(response.records),
            },
            len(rows),
            normalized_table="t_index_daily_basic",
        )
        upserted = await self.repository.upsert_index_daily_basic_rows(rows)
        self._log_upsert_summary(mapping, upserted, "t_index_daily_basic")
        return upserted

    async def _sync_north_hold(self, trade_date: date, universe: set[str], result: DailyMarketCloseIngestResult) -> int:
        response = await self._tushare_response("hk_hold", {"trade_date": trade_date}, capability="daily_market_close_north_hold")
        records = list(response.records)
        used_date = trade_date
        if not records:
            for fallback_date in await self.repository.recent_open_trade_dates(up_to=trade_date, limit=5):
                if fallback_date == trade_date:
                    continue
                fallback = await self._tushare_response("hk_hold", {"trade_date": fallback_date}, capability="daily_market_close_north_hold")
                if fallback.records:
                    records = list(fallback.records)
                    used_date = fallback_date
                    result.warnings.append(f"north_hold {trade_date.isoformat()} 无数据，已使用最近可用日 {fallback_date.isoformat()}")
                    break
        if not records:
            result.warnings.append(f"north_hold_unavailable_for_trade_date: {trade_date.isoformat()}")
        rows = []
        for record in records:
            stock_code = normalize_symbol(str(record.get("ts_code") or record.get("code") or ""))
            row_date = parse_date(record.get("trade_date"))
            exchange = str(record.get("exchange") or record.get("market") or "ALL")
            if stock_code and row_date and stock_code in universe:
                rows.append(
                    {
                        "stock_code": stock_code,
                        "stock_name": record.get("name"),
                        "trade_date": row_date,
                        "exchange": exchange,
                        "source": "tushare:hk_hold",
                        "hold_volume": safe_float(record.get("vol") or record.get("hold_vol")),
                        "hold_ratio": safe_float(record.get("ratio") or record.get("hold_ratio")),
                        "hold_market_value": safe_float(record.get("amount") or record.get("hold_amount")),
                        "hold_volume_change": safe_float(record.get("vol_change") or record.get("hold_vol_chg")),
                        "metadata_json": {"provider": "tushare", "api_name": "hk_hold", "raw": record},
                    }
                )
        await self._capture_raw_summary("daily_market_close_north_hold", trade_date, {"api_name": "hk_hold", "used_date": used_date.isoformat(), "row_count": len(records)}, len(rows), normalized_table="t_stock_north_hold_daily")
        return await self.repository.upsert_north_hold_rows(rows)

    async def _sync_market_stats(self, trade_date: date, *, start_date: date | None = None, end_date: date | None = None) -> int:
        request_start_date = start_date or trade_date
        request_end_date = end_date or trade_date
        rows = []
        for exchange in ("SH", "SZ"):
            params = {"exchange": exchange}
            if request_start_date != request_end_date:
                params.update({"start_date": request_start_date, "end_date": request_end_date})
            else:
                params["trade_date"] = trade_date
            response = await self._tushare_response("daily_info", params, capability="daily_market_close_market_stats")
            mapping = self.tushare_market_adapter.map_market_daily_stat(
                response.records,
                start_date=request_start_date,
                end_date=request_end_date,
                default_exchange=exchange,
            )
            self._log_mapping_summary(mapping)
            rows.extend(mapping.rows)
        await self._capture_raw_summary(
            "daily_market_close_market_stats",
            trade_date,
            {
                "api_name": "daily_info",
                "exchanges": ["SH", "SZ"],
                "mode": "date_range" if request_start_date != request_end_date else "single_date",
                "start_date": request_start_date.isoformat(),
                "end_date": request_end_date.isoformat(),
            },
            len(rows),
            normalized_table="t_market_daily_stat",
        )
        upserted = await self.repository.upsert_market_daily_stat_rows(rows)
        logger.info(
            "provider canonical upsert: provider=tushare api=daily_info capability=market_daily_stat table=t_market_daily_stat range=%s mapped=%s upserted=%s",
            {"start_date": request_start_date.isoformat(), "end_date": request_end_date.isoformat()},
            len(rows),
            upserted,
        )
        return upserted

    async def _sync_sector_bars(self, trade_date: date, result: DailyMarketCloseIngestResult) -> int:
        sector_map = await self.repository.tushare_ths_sector_map()
        raw_codes = sorted(sector_map)
        records: list[dict] = []
        request_count = 0
        for code_batch in self._chunks(raw_codes, 500):
            response = await self._tushare_response(
                "ths_daily",
                {"ts_code": ",".join(code_batch), "trade_date": trade_date},
                capability="daily_market_close_sector_bars",
            )
            request_count += 1
            records.extend(response.records)

        returned_codes = {
            str(record.get("ts_code") or "").strip()
            for record in records
            if parse_date(record.get("trade_date")) == trade_date
        }
        missing_codes = [code for code in raw_codes if code not in returned_codes]
        if missing_codes:
            retry = await self._tushare_response(
                "ths_daily",
                {"ts_code": ",".join(missing_codes), "trade_date": trade_date},
                capability="daily_market_close_sector_bars_retry_missing",
            )
            request_count += 1
            records.extend(retry.records)

        deduplicated: dict[tuple[str, date], dict] = {}
        for record in records:
            raw_code = str(record.get("ts_code") or "").strip()
            row_date = parse_date(record.get("trade_date"))
            if raw_code and row_date == trade_date:
                deduplicated[(raw_code, row_date)] = record
        records = list(deduplicated.values())
        final_codes = {key[0] for key in deduplicated}
        missing_codes = [code for code in raw_codes if code not in final_codes]
        if missing_codes:
            result.warnings.append(
                f"ths_daily 批量查询后仍缺少 {len(missing_codes)} 个板块当日行情"
            )
        mapping = self.tushare_market_adapter.map_ths_daily(records, trade_date=trade_date, sector_map=sector_map)
        self._log_mapping_summary(mapping)
        rows = mapping.rows
        await self._capture_raw_summary(
            "daily_market_close_sector_bars",
            trade_date,
            {
                "api_name": "ths_daily",
                "request_mode": "ts_code_batch",
                "batch_size": 500,
                "request_count": request_count,
                "target_codes": len(raw_codes),
                "raw_records": len(records),
                "missing_codes": missing_codes[:100],
            },
            len(rows),
            normalized_table="t_sector_bar",
        )
        upserted = await self.repository.upsert_sector_bar_rows(rows)
        self._log_upsert_summary(mapping, upserted, "t_sector_bar")
        return upserted

    async def _sync_sector_moneyflow(self, trade_date: date, *, start_date: date | None = None, end_date: date | None = None) -> int:
        request_start_date = start_date or trade_date
        request_end_date = end_date or trade_date
        sector_map = await self.repository.tushare_ths_sector_map()
        rows = []
        for api_name, sector_type in (("moneyflow_cnt_ths", "concept"), ("moneyflow_ind_ths", "industry")):
            params = (
                {"start_date": request_start_date, "end_date": request_end_date}
                if request_start_date != request_end_date
                else {"trade_date": trade_date}
            )
            response = await self._tushare_response(api_name, params, capability=f"daily_market_close_{api_name}")
            mapping = self.tushare_market_adapter.map_sector_moneyflow(
                response.records,
                api_name=api_name,
                sector_type=sector_type,
                start_date=request_start_date,
                end_date=request_end_date,
                sector_map=sector_map,
            )
            self._log_mapping_summary(mapping)
            rows.extend(mapping.rows)
            await self._capture_raw_summary(
                f"daily_market_close_{api_name}",
                trade_date,
                {
                    "api_name": api_name,
                    "mode": "date_range" if request_start_date != request_end_date else "single_date",
                    "start_date": request_start_date.isoformat(),
                    "end_date": request_end_date.isoformat(),
                    "raw_records": len(response.records),
                },
                len(response.records),
                normalized_table="t_sector_fund_flow_daily",
            )
        upserted = await self.repository.upsert_sector_fund_flow_rows(rows)
        logger.info(
            "provider canonical upsert: provider=tushare api=sector_moneyflow capability=sector_moneyflow table=t_sector_fund_flow_daily range=%s mapped=%s upserted=%s",
            {"start_date": request_start_date.isoformat(), "end_date": request_end_date.isoformat()},
            len(rows),
            upserted,
        )
        return upserted

    async def _tushare_records(self, api_name: str, trade_date: date) -> tuple[list[dict], dict]:
        try:
            response = await self.tushare.call(
                f"daily_market_close_{api_name}",
                lambda transport: transport.request(TushareApiRequest(api_name, {"trade_date": trade_date})),
                request_summary={"api_name": api_name, "trade_date": trade_date.isoformat()},
                execution_mode="scheduler",
            )
        except TushareRuntimeError as exc:
            raise DailyMarketCloseIngestError(f"Tushare {api_name} 调用失败: {exc}") from exc
        return response.records, response.raw_payload

    async def _daily_codes(self, trade_date: date) -> list[str]:
        from sqlalchemy import select
        from app.modules.market_data.models import DailyBar

        rows = await self.repository.session.execute(
            select(DailyBar.stock_code).where(DailyBar.trade_date == trade_date, DailyBar.source == "tushare:daily")
        )
        return list(rows.scalars().all())

    def _daily_rows(self, records: list[dict]) -> list[dict]:
        rows = []
        for record in records:
            stock_code = normalize_symbol(str(record.get("ts_code") or ""))
            trade_date = parse_date(record.get("trade_date"))
            if not stock_code or trade_date is None:
                continue
            amount = safe_float(record.get("amount"))
            volume = safe_int(record.get("vol"))
            rows.append(
                {
                    "stock_code": stock_code,
                    "trade_date": trade_date,
                    "source": "tushare:daily",
                    "adjust_mode": "none",
                    "open_price": safe_float(record.get("open")),
                    "high_price": safe_float(record.get("high")),
                    "low_price": safe_float(record.get("low")),
                    "close_price": safe_float(record.get("close")),
                    "pre_close_price": safe_float(record.get("pre_close")),
                    "change_amount": safe_float(record.get("change")),
                    "change_pct": safe_float(record.get("pct_chg")),
                    "volume_hand": volume,
                    "volume_share": volume * 100 if volume is not None else None,
                    "amount_yuan": amount * 1000 if amount is not None else None,
                    "turnover_rate": None,
                    "metadata_json": {"provider": "tushare", "api_name": "daily"},
                }
            )
        return rows

    def _daily_basic_rows(self, records: list[dict]) -> list[dict]:
        rows = []
        for record in records:
            stock_code = normalize_symbol(str(record.get("ts_code") or ""))
            trade_date = parse_date(record.get("trade_date"))
            if not stock_code or trade_date is None:
                continue
            rows.append(
                {
                    "stock_code": stock_code,
                    "trade_date": trade_date,
                    "source": "tushare:daily_basic",
                    "close_price": safe_float(record.get("close")),
                    "turnover_rate": safe_float(record.get("turnover_rate")),
                    "turnover_rate_f": safe_float(record.get("turnover_rate_f")),
                    "volume_ratio": safe_float(record.get("volume_ratio")),
                    "pe": safe_float(record.get("pe")),
                    "pe_ttm": safe_float(record.get("pe_ttm")),
                    "pb": safe_float(record.get("pb")),
                    "ps": safe_float(record.get("ps")),
                    "ps_ttm": safe_float(record.get("ps_ttm")),
                    "dv_ratio": safe_float(record.get("dv_ratio")),
                    "dv_ttm": safe_float(record.get("dv_ttm")),
                    "total_share": safe_float(record.get("total_share")),
                    "float_share": safe_float(record.get("float_share")),
                    "free_share": safe_float(record.get("free_share")),
                    "total_mv": safe_float(record.get("total_mv")),
                    "circ_mv": safe_float(record.get("circ_mv")),
                    "limit_status": safe_int(record.get("limit_status")),
                    "metadata_json": {"provider": "tushare", "api_name": "daily_basic", "raw": record},
                }
            )
        return rows

    @staticmethod
    def _to_ts_code(stock_code: str) -> str:
        code = normalize_symbol(stock_code)
        if code.startswith("6"):
            return f"{code}.SH"
        return f"{code}.SZ"

    async def _sync_intraday(
        self,
        stock_codes: list[str],
        *,
        trade_date: date,
        sync_minute: bool,
        max_concurrency: int,
        minute_batch_size: int,
        append_safe: bool,
    ) -> dict:
        minute_counts = await self.repository.minute_bar_counts(stock_codes=stock_codes, trade_date=trade_date)
        errors: list[str] = []
        minute_attempted: set[str] = set()
        minute_batches: list[dict] = []

        def append_error(message: str) -> None:
            if len(errors) < 50:
                errors.append(message)

        minute_needed = [
            stock_code
            for stock_code in stock_codes
            if sync_minute and (not append_safe or minute_counts.get(stock_code, 0) < self.minute_complete_threshold)
        ]
        if minute_needed:
            logger.info(
                "daily close ingest minute sync started: targets=%s batch_size=%s workers=%s",
                len(minute_needed),
                minute_batch_size,
                max_concurrency,
            )
        if minute_needed:
            fetch_queue: asyncio.Queue[str] = asyncio.Queue()
            write_queue: asyncio.Queue[tuple[str, list[dict], str | None] | None] = asyncio.Queue(
                maxsize=max_concurrency * 2
            )
            for stock_code in minute_needed:
                fetch_queue.put_nowait(stock_code)
            worker_count = min(max_concurrency, len(minute_needed))

            async def minute_worker(worker_id: int) -> None:
                provider = MootdxProvider()
                try:
                    while True:
                        try:
                            stock_code = fetch_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                        minute_attempted.add(stock_code)
                        try:
                            rows, _ = await provider.minute_bars(stock_code)
                            for row in rows:
                                row["trade_date"] = trade_date
                                row["metadata_json"] = {
                                    "provider": "mootdx",
                                    "api_name": "minute",
                                    "ingest": "daily_close_minute",
                                }
                            await write_queue.put((stock_code, rows, None))
                        except Exception as exc:  # provider failures are isolated per symbol
                            await write_queue.put(
                                (
                                    stock_code,
                                    [],
                                    f"minute {stock_code}: {type(exc).__name__}: {exc}",
                                )
                            )
                        finally:
                            fetch_queue.task_done()
                finally:
                    try:
                        await asyncio.to_thread(provider.close)
                    finally:
                        await write_queue.put(None)

            async def minute_writer() -> None:
                completed_workers = 0
                batch_no = 0
                batch_codes: list[str] = []
                batch_rows: list[dict] = []
                batch_fetched_codes: set[str] = set()
                batch_failed = 0

                async def flush() -> None:
                    nonlocal batch_no, batch_codes, batch_rows, batch_fetched_codes, batch_failed
                    if not batch_codes:
                        return
                    batch_no += 1
                    if batch_rows:
                        await self.repository.upsert_minute_bars(batch_rows)
                        await self.repository.commit()
                    minute_batches.append(
                        {
                            "batch_no": batch_no,
                            "target_count": len(batch_codes),
                            "fetched_stock_count": len(batch_fetched_codes),
                            "failed_stock_count": batch_failed,
                            "row_count": len(batch_rows),
                        }
                    )
                    logger.info(
                        "daily close ingest minute write batch completed: batch=%s targets=%s rows=%s failed=%s",
                        batch_no,
                        len(batch_codes),
                        len(batch_rows),
                        batch_failed,
                    )
                    batch_codes = []
                    batch_rows = []
                    batch_fetched_codes = set()
                    batch_failed = 0

                while completed_workers < worker_count:
                    item = await write_queue.get()
                    try:
                        if item is None:
                            completed_workers += 1
                            continue
                        stock_code, rows, error = item
                        batch_codes.append(stock_code)
                        if error:
                            batch_failed += 1
                            append_error(error)
                        elif rows:
                            batch_fetched_codes.add(stock_code)
                            batch_rows.extend(rows)
                        else:
                            batch_failed += 1
                        if len(batch_codes) >= minute_batch_size:
                            await flush()
                    finally:
                        write_queue.task_done()
                await flush()

            workers = [asyncio.create_task(minute_worker(worker_id)) for worker_id in range(worker_count)]
            writer = asyncio.create_task(minute_writer())
            tasks = [*workers, writer]
            try:
                await asyncio.gather(*tasks)
            except Exception:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise

        counts_after = await self.repository.minute_bar_counts(stock_codes=stock_codes, trade_date=trade_date)
        return {
            "minute_complete_count": sum(count >= self.minute_complete_threshold for count in counts_after.values()),
            "minute_partial_count": sum(0 < count < self.minute_complete_threshold for count in counts_after.values()),
            "minute_failed_count": sum(
                stock_code in minute_attempted and counts_after.get(stock_code, 0) == 0 for stock_code in stock_codes
            ),
            "minute_batch_count": len(minute_batches),
            "minute_row_count": sum(int(item.get("row_count") or 0) for item in minute_batches),
            "minute_batches": minute_batches[-20:],
            "errors": errors,
        }

    @staticmethod
    def _chunks(items: list[str], size: int) -> list[list[str]]:
        return [items[index : index + size] for index in range(0, len(items), size)]

    @staticmethod
    def _supports_mootdx_intraday(stock_code: str) -> bool:
        code = normalize_symbol(stock_code)
        return code.startswith(("0", "3", "6"))

    async def _capture_raw_summary(
        self,
        capability: str,
        trade_date: date,
        payload: dict,
        row_count: int,
        *,
        normalized_table: str | None = None,
        provider_code: str = "tushare",
    ) -> None:
        stored_payload = self._compact_raw_payload(payload, row_count=row_count)
        await self.repository.insert_raw(
            {
                "trace_id": uuid4().hex,
                "provider_code": provider_code,
                "capability": capability,
                "request_params": {"trade_date": trade_date.isoformat()},
                "record_key": trade_date.isoformat(),
                "payload": stored_payload,
                "payload_summary": {
                    "row_count": row_count,
                    "raw_payload_keys": sorted(payload.keys()),
                    "storage_mode": "summary" if stored_payload is not payload else "full",
                },
                "normalized_table": normalized_table or ("t_daily_bar" if capability.endswith("daily") else "t_stock_daily_basic"),
                "normalized_pk": trade_date.isoformat(),
                "status": "captured",
            }
        )

    @staticmethod
    def _compact_raw_payload(payload: dict, *, row_count: int) -> dict:
        """Keep audit metadata for large responses without duplicating canonical facts."""
        if row_count <= 500:
            return payload
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        data = payload.get("data")
        items = data.get("items") if isinstance(data, dict) else payload.get("items")
        fields = data.get("fields") if isinstance(data, dict) else payload.get("fields")
        sample: list[Any] = []
        if isinstance(items, list) and items:
            sample = [items[0]]
            if len(items) > 1:
                sample.append(items[-1])
        return {
            "row_count": row_count,
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "raw_payload_keys": sorted(payload.keys()),
            "fields": fields if isinstance(fields, list) else None,
            "sample_first_last": sample,
        }

    @staticmethod
    def _net(buy: float | None, sell: float | None) -> float | None:
        if buy is None or sell is None:
            return None
        return buy - sell

    @staticmethod
    def _float(value: object) -> float | None:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _json_value(value: object) -> object:
        return value.isoformat() if hasattr(value, "isoformat") else value

    async def _prune_minute_data(self, trade_date: date, retention_days: int) -> list[str]:
        retained = await self.repository.recent_open_trade_dates(up_to=trade_date, limit=retention_days)
        if len(retained) < retention_days:
            logger.info("minute retention skipped: only %s trade calendar days available", len(retained))
            return []
        cutoff = min(retained)
        dropped = await self.repository.drop_minute_partitions_before(cutoff)
        logger.info("minute partition retention completed: cutoff=%s dropped=%s", cutoff, dropped)
        return dropped

    async def assess_readiness(
        self,
        trade_date: date,
        *,
        universe_count: int | None = None,
    ) -> dict[str, Any]:
        counts = await self.repository.daily_close_asset_counts(trade_date)
        raw_capabilities = set(counts.pop("raw_capabilities", set()))
        active_count = int(universe_count or counts.get("active_stock") or 0)
        daily_count = int(counts.get("daily_bar") or 0)
        daily_denominator = max(1, daily_count)
        sector_denominator = max(1, int(counts.get("tushare_sector") or 0))

        coverage = {
            "daily_bars": min(1.0, daily_count / max(1, active_count)),
            "daily_basic": min(1.0, int(counts.get("daily_basic") or 0) / daily_denominator),
            "stock_moneyflow": min(1.0, int(counts.get("stock_moneyflow") or 0) / daily_denominator),
            "daily_factors": min(1.0, int(counts.get("daily_factor") or 0) / daily_denominator),
            "technical_snapshots": min(
                1.0,
                int(counts.get("technical_snapshot") or 0) / daily_denominator,
            ),
            "stock_technical": min(
                1.0,
                int(counts.get("stock_technical") or 0) / daily_denominator,
            ),
            "index_bars": min(
                1.0,
                int(counts.get("index_bar") or 0) / len(self.core_index_codes),
            ),
            "index_daily_basic": min(
                1.0,
                int(counts.get("index_daily_basic") or 0) / len(self.core_index_codes),
            ),
            "sector_bars": min(
                1.0,
                int(counts.get("sector_bar") or 0) / sector_denominator,
            ),
        }
        event_complete = {
            "daily_market_close_stock_limit",
            "daily_market_close_stock_suspend",
        }.issubset(raw_capabilities)
        lhb_complete = {
            "daily_market_close_lhb",
            "daily_market_close_lhb_seats",
        }.issubset(raw_capabilities)
        sector_moneyflow_complete = (
            int(counts.get("sector_moneyflow") or 0) > 0
            and {
                "daily_market_close_moneyflow_cnt_ths",
                "daily_market_close_moneyflow_ind_ths",
            }.issubset(raw_capabilities)
        )
        core_checks = {
            "daily_bars": coverage["daily_bars"] >= 0.95,
            "daily_basic": coverage["daily_basic"] >= 0.95,
            "stock_moneyflow": coverage["stock_moneyflow"] >= 0.95,
            "index_bars": coverage["index_bars"] >= 0.85,
            "daily_factors": coverage["daily_factors"] >= 0.95,
            "technical_snapshots": coverage["technical_snapshots"] >= 0.95,
        }
        enhancement_checks = {
            "stock_events": event_complete,
            "stock_technical": coverage["stock_technical"] >= 0.95,
            "lhb": lhb_complete,
            "index_daily_basic": coverage["index_daily_basic"] >= 0.85,
            "sector_bars": coverage["sector_bars"] >= 0.90,
            "sector_moneyflow": sector_moneyflow_complete,
            "sector_factors": int(counts.get("sector_factor") or 0) > 0,
        }
        optional_checks = {
            "market_stats": int(counts.get("market_stat") or 0) > 0,
        }
        block_status: dict[str, dict] = {}
        for name, complete in {**core_checks, **enhancement_checks}.items():
            block_status[name] = {
                "status": "complete" if complete else "missing",
                "rows": int(
                    counts.get(
                        {
                            "daily_bars": "daily_bar",
                            "daily_basic": "daily_basic",
                            "stock_moneyflow": "stock_moneyflow",
                            "stock_events": "limit_event",
                            "index_bars": "index_bar",
                            "daily_factors": "daily_factor",
                            "technical_snapshots": "technical_snapshot",
                            "stock_technical": "stock_technical",
                            "lhb": "lhb_event",
                            "index_daily_basic": "index_daily_basic",
                            "sector_bars": "sector_bar",
                            "sector_moneyflow": "sector_moneyflow",
                            "sector_factors": "sector_factor",
                        }.get(name, name),
                        0,
                    )
                    or 0
                ),
            }
        block_status["market_stats"] = {
            "status": "complete" if optional_checks["market_stats"] else "deferred",
            "rows": int(counts.get("market_stat") or 0),
        }
        core_ready = all(core_checks.values())
        enhancement_ready = all(enhancement_checks.values())
        missing_blocks = [
            name
            for name, complete in {**core_checks, **enhancement_checks, **optional_checks}.items()
            if not complete
        ]
        return {
            "counts": counts,
            "coverage": {key: round(value, 6) for key, value in coverage.items()},
            "block_status": block_status,
            "core_ready": core_ready,
            "enhancement_ready": enhancement_ready,
            "report_quality": (
                "complete"
                if core_ready and enhancement_ready
                else "degraded"
                if core_ready
                else "blocked"
            ),
            "missing_blocks": missing_blocks,
        }

    async def _finalize_readiness(
        self,
        result: DailyMarketCloseIngestResult,
        *,
        universe_count: int,
    ) -> None:
        readiness = await self.assess_readiness(
            result.trade_date,
            universe_count=universe_count,
        )
        result.coverage = readiness["coverage"]
        result.block_status = readiness["block_status"]
        result.core_ready = bool(readiness["core_ready"])
        result.report_quality = readiness["report_quality"]
        result.missing_blocks = list(readiness["missing_blocks"])
        if not result.core_ready and result.status == "success":
            result.status = "partial"
