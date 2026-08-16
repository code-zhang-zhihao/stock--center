from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from time import perf_counter
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.modules.indicator_engine.repository import IndicatorRepository
from app.modules.indicator_engine.service import IndicatorEngineService
from app.modules.market_data.repository import MarketDataRepository


logger = logging.getLogger(__name__)


class FactorBackfillError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class FactorBackfillRequest(BaseModel):
    pool_code: str = Field(default="focus", min_length=1, max_length=80)
    start_date: date = Field(default=date(2024, 1, 1))
    end_date: date | None = None
    ingest_mode: Literal["append_safe", "rebuild"] = "append_safe"
    only_missing: bool = True
    max_stocks: int | None = Field(default=None, ge=1)
    max_indexes: int | None = Field(default=None, ge=1)
    batch_size: int = Field(default=200, ge=20, le=1000)
    factor_window_trade_days: int = Field(default=20, ge=5, le=60)
    sql_stock_chunk_size: int = Field(default=200, ge=50, le=500)
    calculation_workers: int = Field(default=2, ge=1, le=4)
    fail_fast: bool = False

    @field_validator("pool_code")
    @classmethod
    def normalize_pool_code(cls, value: str) -> str:
        return value.strip()


class FactorBackfillResult(BaseModel):
    factor_kind: str
    pool_code: str | None = None
    start_date: date
    end_date: date
    trade_date_count: int = 0
    stock_count: int = 0
    index_count: int = 0
    processed_trade_dates: int = 0
    skipped_trade_dates: int = 0
    failed_trade_dates: int = 0
    daily_factor_rows: int = 0
    sector_factor_rows: int = 0
    sector_leader_rows: int = 0
    index_factor_rows: int = 0
    market_summary_rows: int = 0
    rebuild_deleted_rows: int = 0
    ingest_mode: Literal["append_safe", "rebuild"] = "append_safe"
    factor_window_trade_days: int = 20
    insufficient_daily_history: int = 0
    missing_daily_data: int = 0
    missing_stock_fund_flow: int = 0
    missing_stock_technical_factor: int = 0
    errors: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    date_summaries: list[dict[str, Any]] = Field(default_factory=list)


class StockFactorPipelineResult(BaseModel):
    pool_code: str
    start_date: date
    end_date: date
    stock_count: int = 0
    daily: FactorBackfillResult
    daily_factor_rows: int = 0
    rebuild_deleted_rows: int = 0
    failed_trade_dates: int = 0
    warnings: list[str] = Field(default_factory=list)


class FactorBackfillService:
    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self.sessionmaker = sessionmaker

    async def backfill_stock_daily_pipeline(self, payload: FactorBackfillRequest) -> StockFactorPipelineResult:
        end_date = payload.end_date or await self._resolve_latest_trade_date()
        resolved_payload = payload.model_copy(update={"end_date": end_date})
        daily = await self.backfill_standard_daily(resolved_payload)
        return StockFactorPipelineResult(
            pool_code=payload.pool_code,
            start_date=daily.start_date,
            end_date=daily.end_date,
            stock_count=daily.stock_count,
            daily=daily,
            daily_factor_rows=daily.daily_factor_rows,
            rebuild_deleted_rows=daily.rebuild_deleted_rows,
            failed_trade_dates=daily.failed_trade_dates,
            warnings=daily.warnings,
        )

    async def backfill_standard_daily(self, payload: FactorBackfillRequest) -> FactorBackfillResult:
        """Backfill the typed QFQ serving table by bounded date windows and stock shards."""
        end_date = payload.end_date or await self._resolve_latest_trade_date()
        trade_dates = await self._resolve_trade_dates(payload.start_date, end_date)
        stock_codes = await self._resolve_stock_codes(payload.pool_code)
        if payload.max_stocks:
            stock_codes = stock_codes[: payload.max_stocks]
        if not stock_codes:
            raise FactorBackfillError("empty_stock_pool", f"股票池没有可回填因子的沪深 active 股票: {payload.pool_code}")

        result = FactorBackfillResult(
            factor_kind="daily",
            pool_code=payload.pool_code,
            start_date=payload.start_date,
            end_date=end_date,
            trade_date_count=len(trade_dates),
            stock_count=len(stock_codes),
            ingest_mode=payload.ingest_mode,
            factor_window_trade_days=payload.factor_window_trade_days,
        )
        baseline_history_start = payload.start_date - timedelta(days=550)
        logger.info(
            "factor daily backfill started: pool=%s dates=%s stocks=%s history_start=%s chunk=%s workers=%s only_missing=%s",
            payload.pool_code,
            len(trade_dates),
            len(stock_codes),
            baseline_history_start,
            payload.sql_stock_chunk_size,
            payload.calculation_workers,
            payload.only_missing,
        )
        windows = [
            trade_dates[offset : offset + payload.factor_window_trade_days]
            for offset in range(0, len(trade_dates), payload.factor_window_trade_days)
        ]
        for window_index, window_dates in enumerate(windows, start=1):
            window_start, window_end = window_dates[0], window_dates[-1]
            try:
                async with self.sessionmaker() as session:
                    repository = IndicatorRepository(session)
                    daily_bar_keys = await repository.load_daily_bar_keys_between(
                        stock_codes,
                        start_date=window_start,
                        end_date=window_end,
                    )
                    ready_keys: set[tuple[str, date]] = set()
                    only_missing = payload.ingest_mode == "append_safe" and payload.only_missing
                    if only_missing:
                        ready_keys = await repository.load_stock_daily_ready_keys_between(
                            stock_codes,
                            start_date=window_start,
                            end_date=window_end,
                        )
                    target_keys = daily_bar_keys - ready_keys if ready_keys else daily_bar_keys
                    target_stock_codes = sorted({stock_code for stock_code, _ in target_keys})
                    target_count_by_date = {
                        trade_date: sum(1 for _, item_date in target_keys if item_date == trade_date)
                        for trade_date in window_dates
                    }
                    total_count_by_date = {
                        trade_date: sum(1 for _, item_date in daily_bar_keys if item_date == trade_date)
                        for trade_date in window_dates
                    }
                chunks = [
                    target_stock_codes[offset : offset + payload.sql_stock_chunk_size]
                    for offset in range(0, len(target_stock_codes), payload.sql_stock_chunk_size)
                ]
                logger.info(
                    "factor daily backfill window started: window=%s/%s start_date=%s end_date=%s trade_dates=%s stocks=%s targets=%s chunks=%s workers=%s",
                    window_index,
                    len(windows),
                    window_start,
                    window_end,
                    len(window_dates),
                    len(target_stock_codes),
                    len(target_keys),
                    len(chunks),
                    payload.calculation_workers,
                )
                semaphore = asyncio.Semaphore(payload.calculation_workers)

                async def calculate_chunk(chunk_index: int, codes: list[str]) -> dict[date, int]:
                    async with semaphore:
                        chunk_started = perf_counter()
                        async with self.sessionmaker() as chunk_session:
                            chunk_repository = IndicatorRepository(chunk_session)
                            chunk_written = await chunk_repository.assemble_stock_daily_factors_final_between(
                                codes,
                                start_date=window_start,
                                end_date=window_end,
                                history_start=window_start - timedelta(days=550),
                                only_missing=only_missing,
                            )
                            await chunk_session.commit()
                        logger.info(
                            "factor daily backfill chunk completed: window=%s/%s chunk=%s/%s stocks=%s rows=%s elapsed_ms=%s",
                            window_index,
                            len(windows),
                            chunk_index,
                            len(chunks),
                            len(codes),
                            sum(chunk_written.values()),
                            int((perf_counter() - chunk_started) * 1000),
                        )
                        return chunk_written

                chunk_results = await asyncio.gather(
                    *(
                        calculate_chunk(chunk_index, codes)
                        for chunk_index, codes in enumerate(chunks, start=1)
                    )
                )
                written_by_date: dict[date, int] = {}
                for chunk_written in chunk_results:
                    for trade_date, count in chunk_written.items():
                        written_by_date[trade_date] = written_by_date.get(trade_date, 0) + count

                async with self.sessionmaker() as percentile_session:
                    percentile_repository = IndicatorRepository(percentile_session)
                    percentile_started = perf_counter()
                    percentile_updates = await percentile_repository.refresh_stock_daily_final_percentiles(
                        start_date=window_start,
                        end_date=window_end,
                    )
                    market_summary_updates = 0
                    for summary_date in window_dates:
                        market_summary_updates += await percentile_repository.rebuild_market_summary(
                            trade_date=summary_date,
                        )
                    await percentile_session.commit()
                    result.market_summary_rows += market_summary_updates
                    logger.info(
                        "factor daily percentiles and market summaries refreshed: window=%s/%s dates=%s percentile_rows=%s summary_rows=%s elapsed_ms=%s",
                        window_index,
                        len(windows),
                        len(percentile_updates),
                        sum(percentile_updates.values()),
                        market_summary_updates,
                        int((perf_counter() - percentile_started) * 1000),
                    )
                for trade_date in window_dates:
                    target = target_count_by_date[trade_date]
                    written = written_by_date.get(trade_date, 0)
                    if target == 0:
                        result.skipped_trade_dates += 1
                        result.date_summaries.append(
                            {
                                "trade_date": trade_date.isoformat(),
                                "status": "skipped",
                                "reason": "ready_rows_already_present",
                                "target_rows": total_count_by_date[trade_date],
                            }
                        )
                        continue
                    result.processed_trade_dates += 1
                    result.daily_factor_rows += written
                    result.date_summaries.append(
                        {
                            "trade_date": trade_date.isoformat(),
                            "status": "success",
                            "target_rows": target,
                            "daily_factor_rows": written,
                        }
                    )
                logger.info(
                    "factor daily backfill window finished: window=%s/%s start_date=%s end_date=%s targets=%s rows=%s",
                    window_index,
                    len(windows),
                    window_start,
                    window_end,
                    len(target_keys),
                    sum(written_by_date.values()),
                )
            except Exception as exc:
                result.failed_trade_dates += len(window_dates)
                for trade_date in window_dates:
                    if len(result.errors) < 30:
                        result.errors.append(
                            {"trade_date": trade_date.isoformat(), "error": f"{type(exc).__name__}: {exc}"}
                        )
                logger.exception(
                    "factor daily backfill window failed: window=%s/%s start_date=%s end_date=%s",
                    window_index,
                    len(windows),
                    window_start,
                    window_end,
                )
                if payload.fail_fast:
                    raise
        if result.failed_trade_dates:
            result.warnings.append(f"{result.failed_trade_dates} 个交易日组装失败，可使用 append_safe 续跑。")
        logger.info(
            "factor daily backfill finished: processed=%s skipped=%s failed=%s rows=%s",
            result.processed_trade_dates,
            result.skipped_trade_dates,
            result.failed_trade_dates,
            result.daily_factor_rows,
        )
        return result

    async def backfill_sector(self, payload: FactorBackfillRequest) -> FactorBackfillResult:
        end_date = payload.end_date or await self._resolve_latest_trade_date()
        trade_dates = await self._resolve_trade_dates(payload.start_date, end_date)
        result = FactorBackfillResult(
            factor_kind="sector",
            pool_code=None,
            start_date=payload.start_date,
            end_date=end_date,
            trade_date_count=len(trade_dates),
            ingest_mode=payload.ingest_mode,
        )
        logger.info(
            "factor sector backfill started: start_date=%s end_date=%s trade_dates=%s ingest_mode=%s only_missing=%s workers=%s",
            payload.start_date,
            end_date,
            len(trade_dates),
            payload.ingest_mode,
            payload.only_missing,
            payload.calculation_workers,
        )
        queue: asyncio.Queue[date] = asyncio.Queue()
        for trade_date in trade_dates:
            queue.put_nowait(trade_date)
        lock = asyncio.Lock()

        async def worker(worker_id: int) -> None:
            async with self.sessionmaker() as session:
                indicator_repository = IndicatorRepository(session)
                indicator = IndicatorEngineService(indicator_repository)
                while True:
                    try:
                        trade_date = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    try:
                        deleted = 0
                        if payload.ingest_mode == "rebuild":
                            deleted = await indicator_repository.clear_sector_factor_rows(trade_date=trade_date)
                            await session.commit()
                            async with lock:
                                result.rebuild_deleted_rows += deleted
                        await indicator.calculate_sector_factors(trade_date=trade_date)
                        rows = await indicator_repository.rebuild_sector_final_metrics(trade_date=trade_date)
                        leader_rows = await indicator_repository.rebuild_sector_leaders(trade_date=trade_date)
                        await session.commit()
                        async with lock:
                            result.processed_trade_dates += 1
                            result.sector_factor_rows += rows
                            result.sector_leader_rows += leader_rows
                            result.date_summaries.append(
                                {
                                    "trade_date": trade_date.isoformat(),
                                    "status": "success",
                                    "sector_factor_rows": rows,
                                    "sector_leader_rows": leader_rows,
                                    "worker": worker_id,
                                }
                            )
                        logger.info(
                            "factor sector backfill date completed: worker=%s trade_date=%s rows=%s leaders=%s",
                            worker_id,
                            trade_date,
                            rows,
                            leader_rows,
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        await session.rollback()
                        async with lock:
                            result.failed_trade_dates += 1
                            if len(result.errors) < 30:
                                result.errors.append(
                                    {"trade_date": trade_date.isoformat(), "error": f"{type(exc).__name__}: {exc}"}
                                )
                        logger.exception("factor sector backfill date failed: worker=%s trade_date=%s", worker_id, trade_date)
                        if payload.fail_fast:
                            raise
                    finally:
                        queue.task_done()

        workers = [
            asyncio.create_task(worker(index + 1))
            for index in range(min(payload.calculation_workers, len(trade_dates)))
        ]
        await asyncio.gather(*workers)
        result.date_summaries.sort(key=lambda item: item["trade_date"])
        self._append_warnings(result)
        logger.info(
            "factor sector backfill finished: dates=%s processed=%s skipped=%s failed=%s rows=%s rebuild_deleted=%s",
            len(trade_dates),
            result.processed_trade_dates,
            result.skipped_trade_dates,
            result.failed_trade_dates,
            result.sector_factor_rows,
            result.rebuild_deleted_rows,
        )
        return result

    async def backfill_index(self, payload: FactorBackfillRequest) -> FactorBackfillResult:
        end_date = payload.end_date or await self._resolve_latest_trade_date()
        trade_dates = await self._resolve_trade_dates(payload.start_date, end_date)
        async with self.sessionmaker() as session:
            targets = await MarketDataRepository(session).list_index_history_targets()
        if payload.max_indexes:
            targets = targets[: payload.max_indexes]
        index_codes = [target["index_code"] for target in targets]
        if not index_codes:
            raise FactorBackfillError("index_catalog_missing", "没有指数主数据，请先运行 sync_index_catalog")
        result = FactorBackfillResult(
            factor_kind="index",
            start_date=payload.start_date,
            end_date=end_date,
            trade_date_count=len(trade_dates),
            index_count=len(index_codes),
            ingest_mode=payload.ingest_mode,
            factor_window_trade_days=payload.factor_window_trade_days,
        )
        for trade_date in trade_dates:
            try:
                async with self.sessionmaker() as session:
                    repository = IndicatorRepository(session)
                    if payload.ingest_mode == "rebuild":
                        result.rebuild_deleted_rows += await repository.clear_index_factor_rows_between(
                            index_codes,
                            start_date=trade_date,
                            end_date=trade_date,
                        )
                    written = await repository.rebuild_index_factors(trade_date=trade_date)
                    await session.commit()
                if written:
                    result.processed_trade_dates += 1
                    result.index_factor_rows += written
                    status = "success"
                else:
                    result.skipped_trade_dates += 1
                    status = "skipped"
                result.date_summaries.append(
                    {
                        "trade_date": trade_date.isoformat(),
                        "status": status,
                        "index_factor_rows": written,
                        "mode": "typed_core_index_final",
                    }
                )
                logger.info(
                    "index factor backfill date completed: trade_date=%s indexes=%s rows=%s",
                    trade_date,
                    len(index_codes),
                    written,
                )
            except Exception as exc:
                result.failed_trade_dates += 1
                if len(result.errors) < 30:
                    result.errors.append(
                        {"trade_date": trade_date.isoformat(), "error": f"{type(exc).__name__}: {exc}"}
                    )
                if payload.fail_fast:
                    raise
        return result

    async def _resolve_latest_trade_date(self) -> date:
        async with self.sessionmaker() as session:
            dates = await MarketDataRepository(session).recent_open_trade_dates(up_to=datetime.now().date(), limit=1)
            if not dates:
                raise FactorBackfillError("trade_calendar_missing", "找不到最近交易日，请先运行 sync_trade_calendar")
            return dates[0]

    async def _resolve_trade_dates(self, start_date: date, end_date: date) -> list[date]:
        if start_date > end_date:
            raise FactorBackfillError("invalid_date_range", "开始日期不能晚于结束日期")
        async with self.sessionmaker() as session:
            dates = await MarketDataRepository(session).open_trade_dates_between(start_date=start_date, end_date=end_date)
        if not dates:
            raise FactorBackfillError("trade_calendar_missing", "指定日期范围内没有交易日，请先同步交易日历")
        return dates

    async def _resolve_stock_codes(self, pool_code: str) -> list[str]:
        async with self.sessionmaker() as session:
            repository = MarketDataRepository(session)
            if pool_code == "all_a_share":
                return await repository.list_active_stock_codes()
            if not await repository.stock_pool_exists(pool_code):
                raise FactorBackfillError("stock_pool_not_found", f"股票池不存在或已禁用: {pool_code}")
            codes = await repository.stock_pool_member_codes(pool_code)
            stocks = await repository.get_stock_map(codes)
            return [
                code
                for code in codes
                if (stock := stocks.get(code)) is not None
                and stock.status == "active"
                and (stock.exchange in ("SH", "SZ", "SSE", "SZSE") or code.startswith(("0", "3", "6")))
            ]

    @staticmethod
    def _append_warnings(result: FactorBackfillResult) -> None:
        if result.missing_daily_data:
            result.warnings.append(f"缺少日线数据导致无法计算日频因子的股票数累计: {result.missing_daily_data}")
        if result.missing_snapshot_daily_data:
            result.warnings.append(f"缺少日线数据导致无法生成技术快照的股票数累计: {result.missing_snapshot_daily_data}")
        if result.missing_stock_fund_flow:
            result.warnings.append(f"缺少资金流导致资金因子不完整的股票数累计: {result.missing_stock_fund_flow}")
        if result.missing_stock_technical_factor:
            result.warnings.append(f"缺少 Tushare 专业技术因子的股票数累计: {result.missing_stock_technical_factor}")
