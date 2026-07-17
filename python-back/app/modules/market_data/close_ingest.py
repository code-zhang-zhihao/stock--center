"""The daily close production pipeline.

This module coordinates providers and canonical persistence.  Providers remain
raw transport adapters; factor computation is delegated to ``indicator_engine``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
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
from app.modules.market_data.providers import frame_records, first, MootdxProvider, normalize_symbol, parse_date, safe_float, safe_int
from app.modules.market_data.partitioning import ensure_market_partitions
from app.modules.market_data.repository import MarketDataRepository
from app.modules.market_data.tushare.contracts import TushareApiRequest
from app.modules.market_data.tushare.adapters import TushareMarketAdapter, TushareStockDailyAdapter
from app.modules.market_data.tushare_runtime import TushareProviderFactory, TushareRuntimeError


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
    calculate_sector_factors: bool = True
    fail_on_enrichment_error: bool = False
    enrichment_block_concurrency: int = Field(default=4, ge=1, le=10)
    minute_retention_trade_days: int = Field(default=10, ge=1, le=60)
    minute_max_concurrency: int = Field(default=4, ge=1, le=10)
    minute_batch_size: int = Field(default=200, ge=20, le=1000)
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
    pruned_partitions: list[str] = Field(default_factory=list)
    rebuild_deleted: dict[str, int] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DailyMarketCloseIngestService:
    """Build one trading day's reusable market facts and derived indicators."""

    minute_complete_threshold = 230
    daily_minimum_floor = 3000
    core_index_codes = ("000001.SH", "399001.SZ", "399006.SZ", "000300.SH", "000905.SH", "000852.SH", "000016.SH")

    def __init__(self, repository: MarketDataRepository, config_repository: ConfigCenterRepository) -> None:
        self.repository = repository
        self.config_repository = config_repository
        self.tushare = TushareProviderFactory(config_repository)
        self.mootdx = MootdxProvider()
        self.tushare_daily_adapter = TushareStockDailyAdapter()
        self.tushare_market_adapter = TushareMarketAdapter()

    async def run(self, payload: DailyMarketCloseIngestRequest) -> DailyMarketCloseIngestResult:
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

        if payload.sync_daily:
            daily_records, raw_payload = await self._tushare_records("daily", trade_date)
            daily_mapping = self.tushare_daily_adapter.map_daily(daily_records, trade_date=trade_date, universe=universe_set)
            daily_rows = daily_mapping.rows
            self._log_mapping_summary(daily_mapping)
            result.warnings.extend(daily_mapping.warnings)
            min_expected = min(len(universe), max(self.daily_minimum_floor, int(len(universe) * 0.55)))
            if len(daily_rows) < min_expected:
                raise DailyMarketCloseIngestError(
                    f"Tushare daily 返回 {len(daily_rows)} 条，低于全市场保护阈值 {min_expected}；未降级为逐股请求"
                )
            result.daily_rows = await self.repository.upsert_daily_bars(daily_rows)
            self._log_upsert_summary(daily_mapping, result.daily_rows, "t_daily_bar")
            await self._capture_raw_summary("daily_market_close_daily", trade_date, raw_payload, len(daily_rows))
            await self.repository.commit()

        daily_codes = await self._daily_codes(trade_date)
        if not daily_codes:
            raise DailyMarketCloseIngestError(f"{trade_date.isoformat()} 没有 Canonical 日线，不能继续分钟和因子沉淀")

        if payload.sync_daily_basic:
            daily_basic_records, raw_payload = await self._tushare_records("daily_basic", trade_date)
            daily_basic_mapping = self.tushare_daily_adapter.map_daily_basic(daily_basic_records, trade_date=trade_date, universe=universe_set)
            basic_rows = daily_basic_mapping.rows
            self._log_mapping_summary(daily_basic_mapping)
            result.warnings.extend(daily_basic_mapping.warnings)
            if len(basic_rows) < max(1, int(len(daily_codes) * 0.5)):
                raise DailyMarketCloseIngestError(
                    f"Tushare daily_basic 返回 {len(basic_rows)} 条，低于日线范围的 50%"
                )
            result.daily_basic_rows = await self.repository.upsert_daily_basic_rows(basic_rows)
            self._log_upsert_summary(daily_basic_mapping, result.daily_basic_rows, "t_stock_daily_basic")
            await self._capture_raw_summary("daily_market_close_daily_basic", trade_date, raw_payload, len(basic_rows))
            await self.repository.commit()

        daily_targets = sorted(set(daily_codes) & universe_set)
        await self._run_enrichment(
            "stock moneyflow",
            payload.sync_stock_moneyflow,
            payload.fail_on_enrichment_error,
            result,
            lambda: self._sync_stock_moneyflow(trade_date, universe_set),
            "stock_moneyflow_rows",
        )
        await self._run_enrichment(
            "stock limit/suspend",
            payload.sync_stock_limit_status,
            payload.fail_on_enrichment_error,
            result,
            lambda: self._sync_stock_limit_status(trade_date, universe_set),
            "stock_limit_rows",
        )
        await self._run_enrichment(
            "index bars",
            payload.sync_index_bars,
            payload.fail_on_enrichment_error,
            result,
            lambda: self._sync_index_bars(trade_date, result),
            "index_bar_rows",
        )
        await self._run_enrichment(
            "north hold",
            payload.sync_north_hold,
            payload.fail_on_enrichment_error,
            result,
            lambda: self._sync_north_hold(trade_date, universe_set, result),
            "north_hold_rows",
        )
        await self._run_enrichment(
            "sector bars",
            payload.sync_sector_bars,
            payload.fail_on_enrichment_error,
            result,
            lambda: self._sync_sector_bars(trade_date, result),
            "sector_bar_rows",
        )

        await self._run_parallel_enrichment_blocks(
            trade_date=trade_date,
            payload=payload,
            result=result,
            universe_set=universe_set,
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

        indicator = IndicatorEngineService(IndicatorRepository(self.repository.session))
        factors = await indicator.calculate_market_close(
            daily_targets,
            trade_date=trade_date,
            calculate_daily=payload.calculate_daily_factors,
            calculate_minute=False,
            calculate_snapshot=False,
            calculate_stock_fund=payload.calculate_stock_fund_factors,
            include_external_technical=payload.calculate_external_technical_factors,
            include_chip=False,
        )
        intraday_factors = await indicator.calculate_market_close(
            minute_targets,
            trade_date=trade_date,
            calculate_daily=False,
            calculate_minute=payload.calculate_minute_factors,
            calculate_snapshot=payload.calculate_technical_snapshot,
            calculate_stock_fund=False,
            include_external_technical=False,
            include_chip=False,
        )
        result.daily_factor_rows = factors.daily_factor_rows
        result.minute_factor_rows = intraday_factors.minute_factor_rows
        result.technical_snapshot_rows = intraday_factors.technical_snapshot_rows
        if factors.missing_daily_data:
            result.warnings.append(f"缺少日线数据导致无法计算日频因子的股票数: {factors.missing_daily_data}")
        if factors.insufficient_daily_history:
            result.warnings.append(f"日线历史窗口不足的股票数: {factors.insufficient_daily_history}")
        if factors.missing_stock_fund_flow:
            result.warnings.append(f"缺少个股资金流导致资金因子不完整的股票数: {factors.missing_stock_fund_flow}")
        if factors.missing_stock_technical_factor:
            result.warnings.append(f"缺少 Tushare 专业技术因子的股票数: {factors.missing_stock_technical_factor}")
        if intraday_factors.missing_minute_data:
            result.warnings.append(f"缺少分钟数据的股票数: {intraday_factors.missing_minute_data}")
        if intraday_factors.missing_snapshot_daily_data:
            result.warnings.append(f"缺少日线数据导致无法生成技术快照的股票数: {intraday_factors.missing_snapshot_daily_data}")
        if payload.calculate_sector_factors:
            result.sector_factor_rows = await indicator.calculate_sector_factors(trade_date=trade_date)

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

    async def _run_enrichment(self, label: str, enabled: bool, fail_on_error: bool, result: DailyMarketCloseIngestResult, operation, target) -> None:
        if not enabled:
            return
        logger.info("daily close ingest enrichment started: %s", label)
        try:
            value = await operation()
            if isinstance(target, tuple):
                for name, item in zip(target, value, strict=False):
                    setattr(result, name, int(item or 0))
            else:
                setattr(result, target, int(value or 0))
            await self.repository.commit()
            logger.info("daily close ingest enrichment finished: %s rows=%s", label, value)
        except Exception as exc:
            await self.repository.rollback()
            message = f"{label} 沉淀失败: {type(exc).__name__}: {exc}"
            if fail_on_error:
                raise DailyMarketCloseIngestError(message) from exc
            logger.warning("daily close ingest enrichment failed: %s", message)
            result.warnings.append(message)

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
            if block_result.get("status") == "success":
                self._apply_enrichment_value(result, target_by_label[label], block_result.get("value"))
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
        rows = []
        limit_response = await self._tushare_response("limit_list_d", {"trade_date": trade_date}, capability="daily_market_close_stock_limit")
        for record in limit_response.records:
            stock_code = normalize_symbol(str(record.get("ts_code") or ""))
            row_date = parse_date(record.get("trade_date"))
            if not stock_code or row_date is None or stock_code not in universe:
                continue
            limit_flag = str(record.get("limit") or record.get("limit_type") or "").upper()
            event_type = "limit_up" if limit_flag == "U" else "limit_down" if limit_flag == "D" else "limit_event"
            rows.append(
                {
                    "stock_code": stock_code,
                    "trade_date": row_date,
                    "event_type": event_type,
                    "source": "tushare:limit_list_d",
                    "close_price": safe_float(record.get("close")),
                    "limit_price": safe_float(record.get("limit_price")),
                    "first_time": None,
                    "last_time": None,
                    "open_count": None,
                    "turnover_amount": safe_float(record.get("amount")),
                    "metadata_json": {"provider": "tushare", "api_name": "limit_list_d", "raw": record},
                }
            )
        suspend_response = await self._tushare_response("suspend_d", {"trade_date": trade_date}, capability="daily_market_close_stock_suspend")
        for record in suspend_response.records:
            stock_code = normalize_symbol(str(record.get("ts_code") or ""))
            row_date = parse_date(record.get("trade_date") or record.get("suspend_date"))
            if stock_code and row_date and stock_code in universe:
                rows.append(
                    {
                        "stock_code": stock_code,
                        "trade_date": row_date,
                        "event_type": "suspend",
                        "source": "tushare:suspend_d",
                        "close_price": None,
                        "limit_price": None,
                        "first_time": None,
                        "last_time": None,
                        "open_count": None,
                        "turnover_amount": None,
                        "metadata_json": {"provider": "tushare", "api_name": "suspend_d", "raw": record},
                    }
                )
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
        rows = []
        missing_codes = []
        fallback_used: dict[str, str] = {}
        for index_code in self.core_index_codes:
            response = await self._tushare_response("index_daily", {"ts_code": index_code, "trade_date": trade_date}, capability="daily_market_close_index_bars")
            records = list(response.records)
            if not records:
                records = await self._akshare_index_daily_records(index_code, trade_date)
                if records:
                    fallback_used[normalize_symbol(index_code)] = "akshare:stock_zh_index_daily_em"
            if not records:
                records = await self._mootdx_index_daily_records(index_code, trade_date)
                if records:
                    fallback_used[normalize_symbol(index_code)] = "mootdx:index"
            if not records:
                missing_codes.append(index_code)
            mapping = self.tushare_market_adapter.map_index_daily(
                records,
                trade_date=trade_date,
                index_codes={normalize_symbol(index_code)},
            )
            self._log_mapping_summary(mapping)
            result.warnings.extend(mapping.warnings)
            rows.extend(mapping.rows)
        await self._capture_raw_summary(
            "daily_market_close_index_bars",
            trade_date,
            {"index_codes": list(self.core_index_codes), "missing_codes": missing_codes, "fallback_used": fallback_used},
            len(rows),
            normalized_table="t_index_bar",
        )
        if fallback_used:
            result.warnings.append(
                "index_daily fallback_used: "
                + ", ".join(f"{code}->{source}" for code, source in sorted(fallback_used.items()))
            )
        if missing_codes:
            result.warnings.append(f"index_daily 缺失指数: {', '.join(missing_codes)}")
        upserted = await self.repository.upsert_index_bar_rows(rows)
        logger.info(
            "provider canonical upsert: provider=%s api=%s capability=%s table=%s range=%s raw=%s mapped=%s upserted=%s missing=%s warnings=%s",
            "tushare",
            "index_daily",
            "index_daily",
            "t_index_bar",
            {"trade_date": trade_date.isoformat()},
            "mixed_per_index",
            len(rows),
            upserted,
            len(missing_codes),
            [f"missing_codes={missing_codes[:10]}"] if missing_codes else [],
        )
        return upserted

    async def _akshare_index_daily_records(self, index_code: str, trade_date: date) -> list[dict]:
        code = normalize_symbol(index_code)
        symbol = f"sz{code}" if code.startswith("399") else f"sh{code}"

        def fetch() -> list[dict]:
            import akshare as ak

            raw_rows = frame_records(
                ak.stock_zh_index_daily_em(
                    symbol=symbol,
                    start_date=trade_date.strftime("%Y%m%d"),
                    end_date=trade_date.strftime("%Y%m%d"),
                )
            )
            rows: list[dict] = []
            for item in raw_rows:
                row_date = parse_date(first(item, ["date", "日期"]))
                if row_date != trade_date:
                    continue
                amount_yuan = safe_float(first(item, ["amount", "成交额"]))
                rows.append(
                    {
                        "ts_code": code,
                        "trade_date": row_date,
                        "source": "akshare:stock_zh_index_daily_em",
                        "open": safe_float(first(item, ["open", "开盘"])),
                        "high": safe_float(first(item, ["high", "最高"])),
                        "low": safe_float(first(item, ["low", "最低"])),
                        "close": safe_float(first(item, ["close", "收盘"])),
                        "pct_chg": safe_float(first(item, ["涨跌幅", "change_pct"])),
                        "vol": safe_float(first(item, ["volume", "成交量"])),
                        "amount": amount_yuan / 1000 if amount_yuan is not None else None,
                        "raw": item,
                    }
                )
            return rows

        try:
            return await asyncio.to_thread(fetch)
        except Exception as exc:
            logger.warning("daily close ingest akshare index fallback failed: %s %s", index_code, exc)
            return []

    async def _mootdx_index_daily_records(self, index_code: str, trade_date: date) -> list[dict]:
        try:
            rows, _raw = await self.mootdx.index_bars(normalize_symbol(index_code), limit=10)
        except Exception as exc:
            logger.warning("daily close ingest mootdx index fallback failed: %s %s", index_code, exc)
            return []
        records: list[dict] = []
        for row in rows:
            if row.get("trade_date") != trade_date:
                continue
            amount_yuan = safe_float(row.get("amount_yuan"))
            records.append(
                {
                    "ts_code": normalize_symbol(index_code),
                    "trade_date": row.get("trade_date"),
                    "source": "mootdx:index",
                    "open": row.get("open_price"),
                    "high": row.get("high_price"),
                    "low": row.get("low_price"),
                    "close": row.get("close_price"),
                    "pct_chg": row.get("change_pct"),
                    "vol": None,
                    "amount": amount_yuan / 1000 if amount_yuan is not None else None,
                    "raw": row.get("metadata_json", {}).get("raw", row),
                }
            )
        return records

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
        response = await self._tushare_response("ths_daily", {"trade_date": trade_date}, capability="daily_market_close_sector_bars")
        records = list(response.records)
        if not records:
            result.warnings.append("ths_daily trade_date 全量返回 0，改为按板块 ts_code 逐个补取")
            for index, raw_code in enumerate(sorted(sector_map), start=1):
                if index % 200 == 0:
                    logger.info("daily close ingest ths_daily fallback progress: %s/%s", index, len(sector_map))
                fallback = await self._tushare_response(
                    "ths_daily",
                    {"ts_code": raw_code, "trade_date": trade_date},
                    capability="daily_market_close_sector_bars",
                )
                records.extend(fallback.records)
        mapping = self.tushare_market_adapter.map_ths_daily(records, trade_date=trade_date, sector_map=sector_map)
        self._log_mapping_summary(mapping)
        rows = mapping.rows
        await self._capture_raw_summary("daily_market_close_sector_bars", trade_date, {"api_name": "ths_daily", "raw_records": len(records)}, len(rows), normalized_table="t_sector_bar")
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
        for batch_no, batch in enumerate(self._chunks(minute_needed, minute_batch_size), start=1):
            batch_rows: list[dict] = []
            batch_fetched_codes: set[str] = set()
            batch_failed = 0
            queue: asyncio.Queue[str] = asyncio.Queue()
            for stock_code in batch:
                queue.put_nowait(stock_code)

            async def minute_worker(worker_id: int) -> None:
                nonlocal batch_failed
                provider = MootdxProvider()
                try:
                    while True:
                        try:
                            stock_code = queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                        minute_attempted.add(stock_code)
                        try:
                            rows, _ = await provider.minute_bars(stock_code)
                            for row in rows:
                                row["trade_date"] = trade_date
                                row["metadata_json"] = {"provider": "mootdx", "api_name": "minute", "ingest": "daily_close"}
                            batch_rows.extend(rows)
                            if rows:
                                batch_fetched_codes.add(stock_code)
                        except Exception as exc:  # provider failures are isolated per symbol
                            batch_failed += 1
                            append_error(f"minute {stock_code}: {type(exc).__name__}: {exc}")
                        finally:
                            queue.task_done()
                finally:
                    await asyncio.to_thread(provider.close)

            worker_count = min(max_concurrency, len(batch))
            await asyncio.gather(*(minute_worker(worker_id) for worker_id in range(worker_count)))
            if batch_rows:
                await self.repository.upsert_minute_bars(batch_rows)
                await self.repository.commit()
            minute_batches.append(
                {
                    "batch_no": batch_no,
                    "target_count": len(batch),
                    "fetched_stock_count": len(batch_fetched_codes),
                    "failed_stock_count": len(batch) - len(batch_fetched_codes),
                    "row_count": len(batch_rows),
                }
            )
            logger.info(
                "daily close ingest minute batch completed: batch=%s targets=%s rows=%s failed=%s",
                batch_no,
                len(batch),
                len(batch_rows),
                batch_failed,
            )

        counts_after = await self.repository.minute_bar_counts(stock_codes=stock_codes, trade_date=trade_date)
        return {
            "minute_complete_count": sum(count >= self.minute_complete_threshold for count in counts_after.values()),
            "minute_partial_count": sum(0 < count < self.minute_complete_threshold for count in counts_after.values()),
            "minute_failed_count": sum(
                stock_code in minute_attempted and counts_after.get(stock_code, 0) == 0 for stock_code in stock_codes
            ),
            "minute_batch_count": len(minute_batches),
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

    async def _capture_raw_summary(self, capability: str, trade_date: date, payload: dict, row_count: int, *, normalized_table: str | None = None) -> None:
        await self.repository.insert_raw(
            {
                "trace_id": uuid4().hex,
                "provider_code": "tushare",
                "capability": capability,
                "request_params": {"trade_date": trade_date.isoformat()},
                "record_key": trade_date.isoformat(),
                "payload": payload,
                "payload_summary": {"row_count": row_count, "raw_payload_keys": sorted(payload.keys())},
                "normalized_table": normalized_table or ("t_daily_bar" if capability.endswith("daily") else "t_stock_daily_basic"),
                "normalized_pk": trade_date.isoformat(),
                "status": "captured",
            }
        )

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
