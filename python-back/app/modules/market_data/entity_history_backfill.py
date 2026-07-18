from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.modules.config_center.repository import ConfigCenterRepository
from app.modules.market_data.close_ingest import DailyMarketCloseIngestService
from app.modules.market_data.repository import MarketDataRepository
from app.modules.market_data.tushare.adapters import TushareMarketAdapter
from app.modules.market_data.tushare.contracts import TushareApiRequest
from app.modules.market_data.tushare_runtime import TushareProviderFactory


logger = logging.getLogger(__name__)


class EntityDailyFactsBackfillError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class SectorDailyFactsBackfillRequest(BaseModel):
    start_date: date = Field(default=date(2024, 1, 1))
    end_date: date | None = None
    ingest_mode: Literal["append_safe", "rebuild"] = "append_safe"
    max_sectors: int | None = Field(default=None, ge=1)
    workers: int = Field(default=12, ge=1, le=20)
    moneyflow_workers: int = Field(default=2, ge=1, le=4)
    moneyflow_window_trade_days: int = Field(default=20, ge=1, le=20)
    fail_fast: bool = False


class SectorDailyFactsBackfillResult(BaseModel):
    start_date: date
    end_date: date
    trade_date_count: int = 0
    sector_count: int = 0
    completed_sector_count: int = 0
    skipped_sector_count: int = 0
    failed_sector_count: int = 0
    completed_moneyflow_windows: int = 0
    failed_blocks: int = 0
    sector_bar_rows: int = 0
    sector_moneyflow_rows: int = 0
    rebuild_deleted_rows: int = 0
    errors: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class IndexDailyFactsBackfillRequest(BaseModel):
    start_date: date = Field(default=date(2024, 1, 1))
    end_date: date | None = None
    ingest_mode: Literal["append_safe", "rebuild"] = "append_safe"
    only_missing: bool = True
    max_indexes: int | None = Field(default=None, ge=1)
    workers: int = Field(default=4, ge=1, le=8)
    fail_fast: bool = False


class IndexDailyFactsBackfillResult(BaseModel):
    start_date: date
    end_date: date
    index_count: int = 0
    completed_index_count: int = 0
    skipped_index_count: int = 0
    failed_index_count: int = 0
    index_bar_rows: int = 0
    index_daily_basic_rows: int = 0
    rebuild_deleted_rows: int = 0
    errors: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class _HistoryBase:
    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self.sessionmaker = sessionmaker

    async def _latest_trade_date(self) -> date:
        async with self.sessionmaker() as session:
            dates = await MarketDataRepository(session).recent_open_trade_dates(up_to=datetime.now().date(), limit=1)
        if not dates:
            raise EntityDailyFactsBackfillError("trade_calendar_missing", "找不到最近交易日，请先运行 sync_trade_calendar")
        return dates[0]

    async def _trade_dates(self, start_date: date, end_date: date) -> list[date]:
        if start_date > end_date:
            raise EntityDailyFactsBackfillError("invalid_date_range", "开始日期不能晚于结束日期")
        async with self.sessionmaker() as session:
            dates = await MarketDataRepository(session).open_trade_dates_between(start_date=start_date, end_date=end_date)
        if not dates:
            raise EntityDailyFactsBackfillError("trade_calendar_missing", "指定日期范围内没有交易日，请先同步交易日历")
        return dates


class SectorDailyFactsBackfillService(_HistoryBase):
    async def run(self, payload: SectorDailyFactsBackfillRequest) -> SectorDailyFactsBackfillResult:
        end_date = payload.end_date or await self._latest_trade_date()
        trade_dates = await self._trade_dates(payload.start_date, end_date)
        result = SectorDailyFactsBackfillResult(
            start_date=payload.start_date,
            end_date=end_date,
            trade_date_count=len(trade_dates),
        )
        trade_date_set = set(trade_dates)
        async with self.sessionmaker() as session:
            sector_map = await MarketDataRepository(session).tushare_ths_sector_map()
        if payload.max_sectors:
            sector_map = dict(sorted(sector_map.items())[: payload.max_sectors])
        if not sector_map:
            raise EntityDailyFactsBackfillError("sector_catalog_missing", "没有 Tushare THS 板块主数据，请先运行 sync_sector_catalog")
        result.sector_count = len(sector_map)
        if payload.ingest_mode == "rebuild":
            async with self.sessionmaker() as session:
                result.rebuild_deleted_rows = await MarketDataRepository(session).clear_sector_daily_fact_range(
                    start_date=payload.start_date,
                    end_date=end_date,
                )
                await session.commit()

        lock = asyncio.Lock()

        async def record_error(block: str, exc: Exception, *, sector_failed: bool = False) -> None:
            async with lock:
                result.failed_blocks += 1
                if sector_failed:
                    result.failed_sector_count += 1
                if len(result.errors) < 30:
                    result.errors.append({"block": block, "error": f"{type(exc).__name__}: {exc}"})

        async def run_bar_worker(worker_id: int, queue: asyncio.Queue[tuple[str, dict[str, Any]]]) -> None:
            adapter = TushareMarketAdapter()
            async with self.sessionmaker() as session:
                repository = MarketDataRepository(session)
                tushare = TushareProviderFactory(ConfigCenterRepository(session))
                while True:
                    try:
                        raw_code, sector = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    sector_code = str(sector["sector_code"])
                    try:
                        if payload.ingest_mode == "append_safe":
                            existing_dates = await repository.existing_sector_bar_dates(
                                sector_code=sector_code,
                                start_date=payload.start_date,
                                end_date=end_date,
                            )
                            if trade_date_set.issubset(existing_dates):
                                async with lock:
                                    result.skipped_sector_count += 1
                                continue
                        response = await tushare.call(
                            "sector_daily_bars_history_backfill",
                            lambda provider: provider.request(
                                TushareApiRequest(
                                    "ths_daily",
                                    {
                                        "ts_code": raw_code,
                                        "start_date": payload.start_date,
                                        "end_date": end_date,
                                    },
                                )
                            ),
                            request_summary={
                                "api_name": "ths_daily",
                                "sector_code": raw_code,
                                "start_date": payload.start_date.isoformat(),
                                "end_date": end_date.isoformat(),
                            },
                            execution_mode="scheduler",
                        )
                        mapping = adapter.map_ths_daily_range(
                            response.records,
                            start_date=payload.start_date,
                            end_date=end_date,
                            sector_map={raw_code: sector},
                        )
                        rows = await repository.upsert_sector_bar_rows(mapping.rows)
                        await session.commit()
                        async with lock:
                            result.completed_sector_count += 1
                            result.sector_bar_rows += rows
                            available_warning_slots = max(50 - len(result.warnings), 0)
                            result.warnings.extend(
                                f"{sector_code}: {warning}"
                                for warning in mapping.warnings[:available_warning_slots]
                            )
                            if not mapping.rows and len(result.warnings) < 50:
                                result.warnings.append(f"{sector_code}: ths_daily 在目标区间没有返回数据")
                        logger.info(
                            "sector daily bar history target completed: worker=%s sector=%s raw_code=%s range=%s..%s raw=%s rows=%s",
                            worker_id,
                            sector_code,
                            raw_code,
                            payload.start_date,
                            end_date,
                            len(response.records),
                            rows,
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        await session.rollback()
                        await record_error(f"sector_bars:{sector_code}", exc, sector_failed=True)
                        if payload.fail_fast:
                            raise
                    finally:
                        queue.task_done()

        bar_queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
        for item in sorted(sector_map.items()):
            bar_queue.put_nowait(item)
        bar_workers = [
            asyncio.create_task(run_bar_worker(index + 1, bar_queue))
            for index in range(min(payload.workers, len(sector_map)))
        ]
        await asyncio.gather(*bar_workers)

        windows = [
            trade_dates[offset : offset + payload.moneyflow_window_trade_days]
            for offset in range(0, len(trade_dates), payload.moneyflow_window_trade_days)
        ]
        window_queue: asyncio.Queue[list[date]] = asyncio.Queue()
        for window in windows:
            window_queue.put_nowait(window)

        async def run_moneyflow_worker() -> None:
            async with self.sessionmaker() as session:
                service = DailyMarketCloseIngestService(
                    MarketDataRepository(session),
                    ConfigCenterRepository(session),
                )
                while True:
                    try:
                        window = window_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    start_date, window_end = window[0], window[-1]
                    try:
                        rows = await service._sync_sector_moneyflow(
                            window_end,
                            start_date=start_date,
                            end_date=window_end,
                        )
                        await session.commit()
                        async with lock:
                            result.completed_moneyflow_windows += 1
                            result.sector_moneyflow_rows += rows
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        await session.rollback()
                        await record_error(
                            f"sector_moneyflow:{start_date.isoformat()}:{window_end.isoformat()}",
                            exc,
                        )
                        if payload.fail_fast:
                            raise
                    finally:
                        window_queue.task_done()

        moneyflow_workers = [
            asyncio.create_task(run_moneyflow_worker())
            for _ in range(min(payload.moneyflow_workers, len(windows)))
        ]
        await asyncio.gather(*moneyflow_workers)
        logger.info(
            "sector daily facts backfill finished: start_date=%s end_date=%s dates=%s sectors=%s completed=%s skipped=%s failed=%s bars=%s moneyflow=%s failed_blocks=%s",
            payload.start_date,
            end_date,
            len(trade_dates),
            result.sector_count,
            result.completed_sector_count,
            result.skipped_sector_count,
            result.failed_sector_count,
            result.sector_bar_rows,
            result.sector_moneyflow_rows,
            result.failed_blocks,
        )
        return result


class IndexDailyFactsBackfillService(_HistoryBase):
    async def run(self, payload: IndexDailyFactsBackfillRequest) -> IndexDailyFactsBackfillResult:
        end_date = payload.end_date or await self._latest_trade_date()
        trade_dates = await self._trade_dates(payload.start_date, end_date)
        trade_date_set = set(trade_dates)
        async with self.sessionmaker() as session:
            targets = await MarketDataRepository(session).list_index_history_targets()
        if payload.max_indexes:
            targets = targets[: payload.max_indexes]
        if not targets:
            raise EntityDailyFactsBackfillError("index_catalog_missing", "没有指数主数据，请先运行 sync_index_catalog")
        result = IndexDailyFactsBackfillResult(
            start_date=payload.start_date,
            end_date=end_date,
            index_count=len(targets),
        )
        if payload.ingest_mode == "rebuild":
            async with self.sessionmaker() as session:
                result.rebuild_deleted_rows = await MarketDataRepository(session).clear_index_daily_fact_range(
                    index_codes=[target["index_code"] for target in targets],
                    start_date=payload.start_date,
                    end_date=end_date,
                )
                await session.commit()

        queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        for target in targets:
            queue.put_nowait(target)
        lock = asyncio.Lock()

        async def worker(worker_id: int) -> None:
            adapter = TushareMarketAdapter()
            async with self.sessionmaker() as session:
                repository = MarketDataRepository(session)
                tushare = TushareProviderFactory(ConfigCenterRepository(session))
                while True:
                    try:
                        target = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    index_code = target["index_code"]
                    official_code = target["official_index_code"]
                    try:
                        if payload.ingest_mode == "append_safe" and payload.only_missing:
                            bar_dates = await repository.existing_index_bar_dates(
                                index_code=index_code,
                                start_date=payload.start_date,
                                end_date=end_date,
                            )
                            basic_dates = await repository.existing_index_daily_basic_dates(
                                index_code=index_code,
                                start_date=payload.start_date,
                                end_date=end_date,
                            )
                            if trade_date_set.issubset(bar_dates) and trade_date_set.issubset(basic_dates):
                                async with lock:
                                    result.skipped_index_count += 1
                                continue

                        response = await tushare.call(
                            "index_daily_facts_backfill",
                            lambda provider: provider.request(
                                TushareApiRequest(
                                    "index_daily",
                                    {
                                        "ts_code": official_code,
                                        "start_date": payload.start_date,
                                        "end_date": end_date,
                                    },
                                )
                            ),
                            request_summary={
                                "api_name": "index_daily",
                                "index_code": official_code,
                                "start_date": payload.start_date.isoformat(),
                                "end_date": end_date.isoformat(),
                            },
                            execution_mode="scheduler",
                        )
                        bars = adapter.map_index_daily_range(
                            response.records,
                            start_date=payload.start_date,
                            end_date=end_date,
                            index_codes={index_code},
                        )
                        bar_rows = await repository.upsert_index_bar_rows(bars.rows)
                        await session.commit()

                        response = await tushare.call(
                            "index_daily_basic_backfill",
                            lambda provider: provider.request(
                                TushareApiRequest(
                                    "index_dailybasic",
                                    {
                                        "ts_code": official_code,
                                        "start_date": payload.start_date,
                                        "end_date": end_date,
                                    },
                                )
                            ),
                            request_summary={
                                "api_name": "index_dailybasic",
                                "index_code": official_code,
                                "start_date": payload.start_date.isoformat(),
                                "end_date": end_date.isoformat(),
                            },
                            execution_mode="scheduler",
                        )
                        basics = adapter.map_index_daily_basic(
                            response.records,
                            start_date=payload.start_date,
                            end_date=end_date,
                            index_codes={index_code},
                        )
                        basic_rows = await repository.upsert_index_daily_basic_rows(basics.rows)
                        await session.commit()
                        async with lock:
                            result.completed_index_count += 1
                            result.index_bar_rows += bar_rows
                            result.index_daily_basic_rows += basic_rows
                            result.warnings.extend(f"{index_code}: {item}" for item in [*bars.warnings, *basics.warnings])
                        logger.info(
                            "index daily facts backfill index completed: worker=%s index=%s bars=%s basics=%s",
                            worker_id,
                            index_code,
                            bar_rows,
                            basic_rows,
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        await session.rollback()
                        async with lock:
                            result.failed_index_count += 1
                            if len(result.errors) < 30:
                                result.errors.append(
                                    {"index_code": index_code, "error": f"{type(exc).__name__}: {exc}"}
                                )
                        if payload.fail_fast:
                            raise
                    finally:
                        queue.task_done()

        workers = [
            asyncio.create_task(worker(index + 1))
            for index in range(min(payload.workers, len(targets)))
        ]
        await asyncio.gather(*workers)
        logger.info(
            "index daily facts backfill finished: indexes=%s completed=%s skipped=%s failed=%s bars=%s basics=%s",
            result.index_count,
            result.completed_index_count,
            result.skipped_index_count,
            result.failed_index_count,
            result.index_bar_rows,
            result.index_daily_basic_rows,
        )
        return result
