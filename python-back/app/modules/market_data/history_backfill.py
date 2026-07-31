from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import date, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.modules.config_center.repository import ConfigCenterRepository
from app.modules.market_data.providers import normalize_symbol, parse_date
from app.modules.market_data.repository import MarketDataRepository, STOCK_LIMIT_EVENT_HISTORY_CAPABILITY
from app.modules.market_data.tushare.adapters import TushareStockDailyAdapter
from app.modules.market_data.tushare.contracts import TushareApiRequest
from app.modules.market_data.tushare_runtime import TushareProviderFactory


logger = logging.getLogger(__name__)

StockFactKind = Literal["daily", "daily_basic", "adjust_factor", "moneyflow", "stock_technical_factor_pro"]


class StockDailyBackfillError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class StockDailyBackfillRequest(BaseModel):
    pool_code: str = Field(default="focus", min_length=1, max_length=80)
    start_date: date = Field(default=date(2024, 1, 1))
    end_date: date | None = None
    ingest_mode: Literal["append_safe", "rebuild"] = "append_safe"
    only_missing: bool = True
    max_stocks: int | None = Field(default=None, ge=1)
    workers: int = Field(default=12, ge=1, le=20)
    commit_stock_batch_size: int = Field(default=20, ge=1, le=200)
    max_upsert_rows_per_commit: int = Field(default=5000, ge=100, le=50000)
    include_limit_events: bool = True
    event_workers: int = Field(default=4, ge=1, le=8)
    fail_fast: bool = False

    @field_validator("pool_code")
    @classmethod
    def normalize_pool_code(cls, value: str) -> str:
        return value.strip()


class StockDailyBackfillResult(BaseModel):
    fact_kind: StockFactKind = "daily"
    pool_code: str
    start_date: date
    end_date: date
    stock_count: int = 0
    completed_stock_count: int = 0
    skipped_stock_count: int = 0
    failed_stock_count: int = 0
    fetched_rows: int = 0
    upserted_rows: int = 0
    rebuild_deleted_rows: int = 0
    workers: int
    ingest_mode: Literal["append_safe", "rebuild"]
    only_missing: bool
    max_upsert_rows_per_commit: int = 5000
    errors: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class StockLimitEventBackfillResult(BaseModel):
    pool_code: str
    start_date: date
    end_date: date
    trade_date_count: int = 0
    completed_trade_date_count: int = 0
    skipped_trade_date_count: int = 0
    failed_trade_date_count: int = 0
    fetched_rows: int = 0
    upserted_rows: int = 0
    rebuild_deleted_rows: int = 0
    event_workers: int
    ingest_mode: Literal["append_safe", "rebuild"]
    only_missing: bool
    completion_scope: str
    errors: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class StockDailyFactsBackfillResult(BaseModel):
    pool_code: str
    start_date: date
    end_date: date
    stock_count: int = 0
    fact_results: dict[str, StockDailyBackfillResult] = Field(default_factory=dict)
    limit_event_result: StockLimitEventBackfillResult | None = None
    completed_fact_count: int = 0
    failed_stock_fact_count: int = 0
    failed_event_trade_date_count: int = 0
    fetched_rows: int = 0
    upserted_rows: int = 0
    rebuild_deleted_rows: int = 0
    workers: int
    ingest_mode: Literal["append_safe", "rebuild"]
    warnings: list[str] = Field(default_factory=list)


def _ts_code(stock_code: str) -> str:
    code = normalize_symbol(stock_code)
    if code.startswith("6"):
        return f"{code}.SH"
    if code.startswith(("4", "8", "920")):
        return f"{code}.BJ"
    return f"{code}.SZ"


class StockDailyBackfillService:
    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self.sessionmaker = sessionmaker

    async def run(self, payload: StockDailyBackfillRequest) -> StockDailyBackfillResult:
        return await self._run_fact(payload, "daily")

    async def run_daily_basic(self, payload: StockDailyBackfillRequest) -> StockDailyBackfillResult:
        return await self._run_fact(payload, "daily_basic")

    async def run_moneyflow(self, payload: StockDailyBackfillRequest) -> StockDailyBackfillResult:
        return await self._run_fact(payload, "moneyflow")

    async def run_adjust_factor(self, payload: StockDailyBackfillRequest) -> StockDailyBackfillResult:
        return await self._run_fact(payload, "adjust_factor")

    async def run_stock_technical_factor_pro(self, payload: StockDailyBackfillRequest) -> StockDailyBackfillResult:
        return await self._run_fact(payload, "stock_technical_factor_pro")

    async def run_limit_events(self, payload: StockDailyBackfillRequest) -> StockLimitEventBackfillResult:
        return await self._run_limit_events(payload)

    async def run_all(self, payload: StockDailyBackfillRequest) -> StockDailyFactsBackfillResult:
        """Backfill stock daily facts and market-wide stock events as one resumable pipeline."""
        end_date = payload.end_date or await self._resolve_latest_trade_date()
        resolved_payload = payload.model_copy(update={"end_date": end_date})
        fact_results: dict[str, StockDailyBackfillResult] = {}
        for fact_kind in ("daily", "daily_basic", "adjust_factor", "moneyflow", "stock_technical_factor_pro"):
            fact_results[fact_kind] = await self._run_fact(resolved_payload, fact_kind)
        limit_event_result = await self._run_limit_events(resolved_payload) if resolved_payload.include_limit_events else None

        first = fact_results["daily"]
        result = StockDailyFactsBackfillResult(
            pool_code=first.pool_code,
            start_date=first.start_date,
            end_date=first.end_date,
            stock_count=first.stock_count,
            fact_results=fact_results,
            limit_event_result=limit_event_result,
            completed_fact_count=len(fact_results) + (1 if limit_event_result is not None else 0),
            failed_stock_fact_count=sum(item.failed_stock_count for item in fact_results.values()),
            failed_event_trade_date_count=limit_event_result.failed_trade_date_count if limit_event_result else 0,
            fetched_rows=sum(item.fetched_rows for item in fact_results.values()) + (limit_event_result.fetched_rows if limit_event_result else 0),
            upserted_rows=sum(item.upserted_rows for item in fact_results.values()) + (limit_event_result.upserted_rows if limit_event_result else 0),
            rebuild_deleted_rows=sum(item.rebuild_deleted_rows for item in fact_results.values()) + (limit_event_result.rebuild_deleted_rows if limit_event_result else 0),
            workers=resolved_payload.workers,
            ingest_mode=resolved_payload.ingest_mode,
        )
        for fact_kind, item in fact_results.items():
            result.warnings.extend(f"{fact_kind}: {warning}" for warning in item.warnings)
            if item.failed_stock_count:
                result.warnings.append(f"{fact_kind} 失败股票数: {item.failed_stock_count}")
        if limit_event_result is not None:
            result.warnings.extend(f"limit_events: {warning}" for warning in limit_event_result.warnings)
            if limit_event_result.failed_trade_date_count:
                result.warnings.append(f"limit_events 失败交易日数: {limit_event_result.failed_trade_date_count}")
        logger.info(
            "stock daily facts pipeline finished: pool=%s stocks=%s facts=%s failed_stock_facts=%s failed_event_dates=%s fetched_rows=%s upserted_rows=%s rebuild_deleted=%s",
            result.pool_code,
            result.stock_count,
            result.completed_fact_count,
            result.failed_stock_fact_count,
            result.failed_event_trade_date_count,
            result.fetched_rows,
            result.upserted_rows,
            result.rebuild_deleted_rows,
        )
        return result

    async def _run_limit_events(self, payload: StockDailyBackfillRequest) -> StockLimitEventBackfillResult:
        end_date = payload.end_date or await self._resolve_latest_trade_date()
        if payload.start_date > end_date:
            raise StockDailyBackfillError("invalid_date_range", "开始日期不能晚于结束日期")
        stock_codes = await self._resolve_stock_codes(payload.pool_code)
        if payload.max_stocks:
            stock_codes = stock_codes[: payload.max_stocks]
        if not stock_codes:
            raise StockDailyBackfillError("empty_stock_pool", f"股票池没有可回填的沪深 active 股票: {payload.pool_code}")

        completion_scope = f"{payload.pool_code}:max_stocks={payload.max_stocks or 'all'}"
        async with self.sessionmaker() as session:
            repository = MarketDataRepository(session)
            trade_dates = await repository.open_trade_dates_between(
                start_date=payload.start_date,
                end_date=end_date,
            )
            if not trade_dates:
                raise StockDailyBackfillError("trade_calendar_missing", "指定日期范围内没有交易日，请先同步交易日历")
            completed_dates = (
                await repository.completed_stock_limit_event_backfill_dates(
                    completion_scope=completion_scope,
                    start_date=payload.start_date,
                    end_date=end_date,
                )
                if payload.ingest_mode == "append_safe" and payload.only_missing
                else set()
            )
            rebuild_deleted = 0
            if payload.ingest_mode == "rebuild":
                rebuild_deleted = await repository.clear_stock_limit_event_range(
                    stock_codes=stock_codes,
                    start_date=payload.start_date,
                    end_date=end_date,
                )
                await session.commit()

        target_dates = [trade_date for trade_date in trade_dates if trade_date not in completed_dates]
        result = StockLimitEventBackfillResult(
            pool_code=payload.pool_code,
            start_date=payload.start_date,
            end_date=end_date,
            trade_date_count=len(trade_dates),
            skipped_trade_date_count=len(trade_dates) - len(target_dates),
            rebuild_deleted_rows=rebuild_deleted,
            event_workers=payload.event_workers,
            ingest_mode=payload.ingest_mode,
            only_missing=payload.only_missing,
            completion_scope=completion_scope,
        )
        if not target_dates:
            logger.info(
                "stock limit event backfill skipped: pool=%s start_date=%s end_date=%s trade_dates=%s reason=already_complete",
                payload.pool_code,
                payload.start_date,
                end_date,
                len(trade_dates),
            )
            return result

        logger.info(
            "stock limit event backfill started: pool=%s stocks=%s start_date=%s end_date=%s trade_dates=%s target_dates=%s workers=%s ingest_mode=%s only_missing=%s",
            payload.pool_code,
            len(stock_codes),
            payload.start_date,
            end_date,
            len(trade_dates),
            len(target_dates),
            payload.event_workers,
            payload.ingest_mode,
            payload.only_missing,
        )
        universe = set(stock_codes)
        queue: asyncio.Queue[date] = asyncio.Queue()
        for trade_date in target_dates:
            queue.put_nowait(trade_date)
        lock = asyncio.Lock()

        async def update_result(**values: int) -> None:
            async with lock:
                for key, value in values.items():
                    setattr(result, key, getattr(result, key) + value)

        async def add_error(trade_date: date, exc: Exception) -> None:
            async with lock:
                if len(result.errors) < 30:
                    result.errors.append({"trade_date": trade_date.isoformat(), "error": f"{type(exc).__name__}: {exc}"})

        async def worker(worker_id: int) -> None:
            adapter = TushareStockDailyAdapter()
            async with self.sessionmaker() as session:
                repository = MarketDataRepository(session)
                tushare = TushareProviderFactory(ConfigCenterRepository(session))
                while True:
                    try:
                        trade_date = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    try:
                        limit_response = await tushare.call(
                            "stock_limit_event_history_backfill",
                            lambda provider, current_date=trade_date: provider.request(
                                TushareApiRequest(
                                    api_name="limit_list_d",
                                    params={"trade_date": current_date},
                                )
                            ),
                            request_summary={
                                "api_name": "limit_list_d",
                                "trade_date": trade_date.isoformat(),
                                "pool_code": payload.pool_code,
                            },
                            execution_mode="scheduler",
                        )
                        suspend_response = await tushare.call(
                            "stock_suspend_event_history_backfill",
                            lambda provider, current_date=trade_date: provider.request(
                                TushareApiRequest(
                                    api_name="suspend_d",
                                    params={"trade_date": current_date},
                                )
                            ),
                            request_summary={
                                "api_name": "suspend_d",
                                "trade_date": trade_date.isoformat(),
                                "pool_code": payload.pool_code,
                            },
                            execution_mode="scheduler",
                        )
                        limit_mapping = adapter.map_limit_events(
                            limit_response.records,
                            trade_date=trade_date,
                            universe=universe,
                        )
                        suspend_mapping = adapter.map_suspend_events(
                            suspend_response.records,
                            trade_date=trade_date,
                            universe=universe,
                        )
                        rows = [*limit_mapping.rows, *suspend_mapping.rows]
                        upserted = await repository.upsert_limit_event_rows(rows)
                        raw_count = len(limit_response.records) + len(suspend_response.records)
                        await repository.insert_ingest_audit(
                            {
                                "trace_id": uuid4().hex,
                                "provider_code": "tushare",
                                "capability": STOCK_LIMIT_EVENT_HISTORY_CAPABILITY,
                                "trade_date": trade_date,
                                "request_params": {
                                    "completion_scope": completion_scope,
                                    "pool_code": payload.pool_code,
                                    "max_stocks": payload.max_stocks,
                                    "trade_date": trade_date.isoformat(),
                                },
                                "requested_fields": [],
                                "response_row_count": raw_count,
                                "normalized_row_count": len(rows),
                                "normalized_table": "t_limit_event_daily",
                                "schema_version": "canonical_v2",
                                "status": "captured" if rows else "complete_zero",
                            }
                        )
                        await session.commit()
                        await update_result(
                            completed_trade_date_count=1,
                            fetched_rows=len(rows),
                            upserted_rows=upserted,
                        )
                        logger.info(
                            "stock limit event date completed: worker=%s trade_date=%s raw_rows=%s mapped_rows=%s upserted_rows=%s",
                            worker_id,
                            trade_date,
                            raw_count,
                            len(rows),
                            upserted,
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        await session.rollback()
                        await update_result(failed_trade_date_count=1)
                        await add_error(trade_date, exc)
                        logger.warning(
                            "stock limit event date failed: worker=%s trade_date=%s error=%s",
                            worker_id,
                            trade_date,
                            exc,
                        )
                        if payload.fail_fast:
                            raise
                    finally:
                        queue.task_done()

        workers = [
            asyncio.create_task(worker(index + 1))
            for index in range(min(payload.event_workers, len(target_dates)))
        ]
        try:
            await asyncio.gather(*workers)
        except Exception:
            for task in workers:
                task.cancel()
            raise

        logger.info(
            "stock limit event backfill finished: pool=%s trade_dates=%s completed=%s skipped=%s failed=%s fetched_rows=%s upserted_rows=%s rebuild_deleted=%s",
            result.pool_code,
            result.trade_date_count,
            result.completed_trade_date_count,
            result.skipped_trade_date_count,
            result.failed_trade_date_count,
            result.fetched_rows,
            result.upserted_rows,
            result.rebuild_deleted_rows,
        )
        return result

    async def _run_fact(self, payload: StockDailyBackfillRequest, fact_kind: StockFactKind) -> StockDailyBackfillResult:
        end_date = payload.end_date or await self._resolve_latest_trade_date()
        if payload.start_date > end_date:
            raise StockDailyBackfillError("invalid_date_range", "开始日期不能晚于结束日期")
        stock_codes = await self._resolve_stock_codes(payload.pool_code)
        if payload.max_stocks:
            stock_codes = stock_codes[: payload.max_stocks]
        if not stock_codes:
            raise StockDailyBackfillError("empty_stock_pool", f"股票池没有可回填的沪深 active 股票: {payload.pool_code}")

        date_span_days = (end_date - payload.start_date).days + 1

        logger.info(
            "stock fact backfill started: fact=%s pool=%s stocks=%s start_date=%s end_date=%s span_days=%s workers=%s ingest_mode=%s only_missing=%s max_upsert_rows_per_commit=%s",
            fact_kind,
            payload.pool_code,
            len(stock_codes),
            payload.start_date,
            end_date,
            date_span_days,
            payload.workers,
            payload.ingest_mode,
            payload.only_missing,
            payload.max_upsert_rows_per_commit,
        )

        rebuild_deleted = 0
        if payload.ingest_mode == "rebuild":
            async with self.sessionmaker() as session:
                repository = MarketDataRepository(session)
                rebuild_deleted = await repository.clear_stock_fact_range(
                    fact_kind=fact_kind,
                    stock_codes=stock_codes,
                    start_date=payload.start_date,
                    end_date=end_date,
                )
                await session.commit()
            logger.info(
                "stock fact backfill rebuild range cleared: fact=%s pool=%s start_date=%s end_date=%s stocks=%s deleted=%s",
                fact_kind,
                payload.pool_code,
                payload.start_date,
                end_date,
                len(stock_codes),
                rebuild_deleted,
            )

        result = StockDailyBackfillResult(
            fact_kind=fact_kind,
            pool_code=payload.pool_code,
            start_date=payload.start_date,
            end_date=end_date,
            stock_count=len(stock_codes),
            rebuild_deleted_rows=rebuild_deleted,
            workers=payload.workers,
            ingest_mode=payload.ingest_mode,
            only_missing=payload.only_missing,
            max_upsert_rows_per_commit=payload.max_upsert_rows_per_commit,
        )
        queue: asyncio.Queue[str] = asyncio.Queue()
        for stock_code in stock_codes:
            queue.put_nowait(stock_code)
        lock = asyncio.Lock()

        async def update_result(**values: int) -> None:
            async with lock:
                for key, value in values.items():
                    setattr(result, key, getattr(result, key) + value)

        async def add_error(stock_code: str, exc: Exception) -> None:
            async with lock:
                if len(result.errors) < 30:
                    result.errors.append({"stock_code": stock_code, "error": f"{type(exc).__name__}: {exc}"})

        async def worker(worker_id: int) -> None:
            buffer: list[dict[str, Any]] = []
            buffered_stocks = 0
            adapter = TushareStockDailyAdapter()
            async with self.sessionmaker() as session:
                repository = MarketDataRepository(session)
                tushare = TushareProviderFactory(ConfigCenterRepository(session))
                trade_dates = await repository.open_trade_dates_between(start_date=payload.start_date, end_date=end_date)
                trade_date_set = set(trade_dates)
                if not trade_dates:
                    raise StockDailyBackfillError("trade_calendar_missing", "指定日期范围内没有交易日，请先同步交易日历")
                while True:
                    try:
                        stock_code = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    try:
                        existing_dates = await self._existing_dates(
                            repository,
                            fact_kind,
                            stock_code=stock_code,
                            start_date=payload.start_date,
                            end_date=end_date,
                        ) if payload.ingest_mode == "append_safe" and payload.only_missing else set()
                        if payload.ingest_mode == "append_safe" and payload.only_missing and trade_date_set.issubset(existing_dates):
                            await update_result(skipped_stock_count=1)
                            logger.info(
                                "stock fact backfill skipped complete stock: fact=%s worker=%s stock_code=%s existing=%s",
                                fact_kind,
                                worker_id,
                                stock_code,
                                len(existing_dates),
                            )
                            continue
                        api_name = {
                            "stock_technical_factor_pro": "stk_factor_pro",
                            "adjust_factor": "adj_factor",
                        }.get(fact_kind, fact_kind)
                        response = await tushare.call(
                            f"stock_{fact_kind}_backfill",
                            lambda provider, code=stock_code: provider.request(
                                TushareApiRequest(
                                    api_name=api_name,
                                    params={
                                        "ts_code": _ts_code(code),
                                        "start_date": payload.start_date,
                                        "end_date": end_date,
                                    },
                                    fields=self._fields(fact_kind),
                                )
                            ),
                            request_summary={
                                "api_name": api_name,
                                "stock_code": stock_code,
                                "start_date": payload.start_date.isoformat(),
                                "end_date": end_date.isoformat(),
                                "ingest_mode": payload.ingest_mode,
                                "only_missing": payload.only_missing,
                            },
                            execution_mode="scheduler",
                        )
                        if fact_kind == "stock_technical_factor_pro":
                            rows, raw_count, mapped_count, warnings = self._map_stock_technical_factor_pro(
                                response.records,
                                payload.start_date,
                                end_date,
                            )
                            unit_conversions: list[str] = []
                        else:
                            mapping = self._map_response(adapter, fact_kind, response.records, payload.start_date, end_date)
                            rows = mapping.rows
                            raw_count = mapping.raw_count
                            mapped_count = mapping.mapped_count
                            warnings = mapping.warnings
                            unit_conversions = mapping.unit_conversions
                        await repository.insert_ingest_audit(
                            {
                                "trace_id": uuid4().hex,
                                "provider_code": "tushare",
                                "capability": f"stock_{fact_kind}_history_backfill",
                                "trade_date": end_date,
                                "request_params": {
                                    "api_name": api_name,
                                    "stock_code": stock_code,
                                    "start_date": payload.start_date.isoformat(),
                                    "end_date": end_date.isoformat(),
                                },
                                "requested_fields": list(self._fields(fact_kind)),
                                "response_row_count": raw_count,
                                "normalized_row_count": mapped_count,
                                "payload_sha256": self._payload_sha256(response.records),
                                "normalized_table": self._normalized_table(fact_kind),
                                "schema_version": "stock_daily_asset_v2",
                                "status": "captured" if raw_count else "complete_zero",
                            }
                        )
                        # 审计记录独立提交；事实行仍按批次提交，避免保存完整 Provider payload。
                        await session.commit()
                        if payload.ingest_mode == "append_safe" and payload.only_missing:
                            rows = [row for row in rows if row["trade_date"] not in existing_dates]
                        buffer.extend(rows)
                        buffered_stocks += 1
                        async with lock:
                            for warning in warnings[:3]:
                                if len(result.warnings) < 50:
                                    result.warnings.append(f"{stock_code}: {warning}")
                        await update_result(completed_stock_count=1, fetched_rows=mapped_count)
                        logger.info(
                            "stock fact backfill stock completed: fact=%s worker=%s stock_code=%s raw_rows=%s mapped_rows=%s filtered_rows=%s pending_upsert=%s warnings=%s unit_conversions=%s",
                            fact_kind,
                            worker_id,
                            stock_code,
                            raw_count,
                            mapped_count,
                            len(rows),
                            len(rows),
                            warnings[:3],
                            unit_conversions,
                        )
                        if (
                            buffered_stocks >= payload.commit_stock_batch_size
                            or len(buffer) >= payload.max_upsert_rows_per_commit
                        ):
                            upserted = await self._flush(repository, session, buffer, fact_kind)
                            await update_result(upserted_rows=upserted)
                            logger.info(
                                "stock fact backfill batch committed: fact=%s worker=%s stocks=%s rows=%s max_rows_per_commit=%s",
                                fact_kind,
                                worker_id,
                                buffered_stocks,
                                upserted,
                                payload.max_upsert_rows_per_commit,
                            )
                            buffer.clear()
                            buffered_stocks = 0
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        await session.rollback()
                        try:
                            await repository.insert_ingest_audit(
                                {
                                    "trace_id": uuid4().hex,
                                    "provider_code": "tushare",
                                    "capability": f"stock_{fact_kind}_history_backfill",
                                    "trade_date": end_date,
                                    "request_params": {
                                        "stock_code": stock_code,
                                        "start_date": payload.start_date.isoformat(),
                                        "end_date": end_date.isoformat(),
                                    },
                                    "requested_fields": list(self._fields(fact_kind)),
                                    "response_row_count": 0,
                                    "normalized_row_count": 0,
                                    "normalized_table": self._normalized_table(fact_kind),
                                    "schema_version": "stock_daily_asset_v2",
                                    "status": "failed",
                                    "error_code": type(exc).__name__,
                                    "error_message": str(exc)[:1000],
                                }
                            )
                            await session.commit()
                        except Exception:
                            await session.rollback()
                        buffer.clear()
                        buffered_stocks = 0
                        await update_result(failed_stock_count=1)
                        await add_error(stock_code, exc)
                        logger.warning(
                            "stock fact backfill stock failed: fact=%s worker=%s stock_code=%s error=%s",
                            fact_kind,
                            worker_id,
                            stock_code,
                            exc,
                        )
                        if payload.fail_fast:
                            raise
                    finally:
                        queue.task_done()
                if buffer:
                    upserted = await self._flush(repository, session, buffer, fact_kind)
                    await update_result(upserted_rows=upserted)
                    logger.info("stock fact backfill final batch committed: fact=%s worker=%s rows=%s", fact_kind, worker_id, upserted)

        workers = [asyncio.create_task(worker(index + 1)) for index in range(min(payload.workers, len(stock_codes)))]
        try:
            await asyncio.gather(*workers)
        except Exception:
            for task in workers:
                task.cancel()
            raise

        logger.info(
            "stock fact backfill finished: fact=%s pool=%s stocks=%s completed=%s skipped=%s failed=%s fetched_rows=%s upserted_rows=%s rebuild_deleted=%s",
            result.fact_kind,
            result.pool_code,
            result.stock_count,
            result.completed_stock_count,
            result.skipped_stock_count,
            result.failed_stock_count,
            result.fetched_rows,
            result.upserted_rows,
            result.rebuild_deleted_rows,
        )
        return result

    async def _resolve_latest_trade_date(self) -> date:
        async with self.sessionmaker() as session:
            dates = await MarketDataRepository(session).recent_open_trade_dates(up_to=datetime.now().date(), limit=1)
            if not dates:
                raise StockDailyBackfillError("trade_calendar_missing", "找不到最近交易日，请先运行 sync_trade_calendar")
            return dates[0]

    async def _resolve_stock_codes(self, pool_code: str) -> list[str]:
        async with self.sessionmaker() as session:
            repository = MarketDataRepository(session)
            if pool_code == "all_a_share":
                return await repository.list_active_stock_codes()
            if not await repository.stock_pool_exists(pool_code):
                raise StockDailyBackfillError("stock_pool_not_found", f"股票池不存在或已禁用: {pool_code}")
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
    async def _existing_dates(
        repository: MarketDataRepository,
        fact_kind: StockFactKind,
        *,
        stock_code: str,
        start_date: date,
        end_date: date,
    ) -> set[date]:
        if fact_kind == "daily":
            return await repository.existing_daily_bar_dates(stock_code=stock_code, start_date=start_date, end_date=end_date)
        if fact_kind == "daily_basic":
            return await repository.existing_daily_basic_dates(stock_code=stock_code, start_date=start_date, end_date=end_date)
        if fact_kind == "adjust_factor":
            return await repository.existing_adjust_factor_dates(stock_code=stock_code, start_date=start_date, end_date=end_date)
        if fact_kind == "moneyflow":
            return await repository.existing_stock_fund_flow_dates(stock_code=stock_code, start_date=start_date, end_date=end_date)
        return await repository.existing_stock_technical_factor_dates(stock_code=stock_code, start_date=start_date, end_date=end_date)

    @staticmethod
    def _fields(fact_kind: StockFactKind) -> tuple[str, ...]:
        if fact_kind == "daily":
            return (
                "ts_code",
                "trade_date",
                "open",
                "high",
                "low",
                "close",
                "pre_close",
                "change",
                "pct_chg",
                "vol",
                "amount",
            )
        if fact_kind == "daily_basic":
            return (
                "ts_code",
                "trade_date",
                "turnover_rate",
                "turnover_rate_f",
                "volume_ratio",
                "pe",
                "pe_ttm",
                "pb",
                "ps",
                "ps_ttm",
                "dv_ratio",
                "dv_ttm",
                "total_share",
                "float_share",
                "free_share",
                "total_mv",
                "circ_mv",
            )
        if fact_kind == "moneyflow":
            return (
                "ts_code",
                "trade_date",
                "buy_sm_amount",
                "sell_sm_amount",
                "buy_md_amount",
                "sell_md_amount",
                "buy_lg_amount",
                "sell_lg_amount",
                "buy_elg_amount",
                "sell_elg_amount",
                "net_mf_amount",
            )
        if fact_kind == "adjust_factor":
            return ("ts_code", "trade_date", "adj_factor")
        return ()

    @staticmethod
    def _normalized_table(fact_kind: StockFactKind) -> str:
        return {
            "daily": "t_daily_bar",
            "daily_basic": "t_stock_daily_basic",
            "adjust_factor": "t_stock_adjust_factor",
            "moneyflow": "t_stock_fund_flow_daily",
            "stock_technical_factor_pro": "t_stock_technical_factor_daily",
        }[fact_kind]

    @staticmethod
    def _payload_sha256(records: list[dict[str, Any]]) -> str:
        encoded = json.dumps(records, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _map_response(
        adapter: TushareStockDailyAdapter,
        fact_kind: StockFactKind,
        records: list[dict[str, Any]],
        start_date: date,
        end_date: date,
    ):
        if fact_kind == "daily":
            return adapter.map_daily_range(records, start_date=start_date, end_date=end_date)
        if fact_kind == "daily_basic":
            return adapter.map_daily_basic_range(records, start_date=start_date, end_date=end_date)
        if fact_kind == "adjust_factor":
            return adapter.map_adjust_factor_range(records, start_date=start_date, end_date=end_date)
        return adapter.map_moneyflow_range(records, start_date=start_date, end_date=end_date)

    @staticmethod
    def _map_stock_technical_factor_pro(
        records: list[dict[str, Any]],
        start_date: date,
        end_date: date,
    ) -> tuple[list[dict[str, Any]], int, int, list[str]]:
        rows: list[dict[str, Any]] = []
        warnings: list[str] = []
        for record in records:
            stock_code = normalize_symbol(str(record.get("ts_code") or ""))
            trade_date = parse_date(record.get("trade_date"))
            if not stock_code or trade_date is None:
                if len(warnings) < 20:
                    warnings.append(f"missing stock_code/trade_date: {record}")
                continue
            if trade_date < start_date or trade_date > end_date:
                continue
            factors = {
                key: value
                for key, value in record.items()
                if key not in {"ts_code", "trade_date"} and value is not None
            }
            rows.append(
                {
                    "stock_code": stock_code,
                    "trade_date": trade_date,
                    "source": "tushare:stk_factor_pro",
                    "factors": factors,
                    "metadata_json": {
                        "provider": "tushare",
                        "api_name": "stk_factor_pro",
                        "mapping_version": "history_backfill_v1",
                    },
                }
            )
        return rows, len(records), len(rows), warnings

    @staticmethod
    async def _flush(repository: MarketDataRepository, session, rows: list[dict[str, Any]], fact_kind: StockFactKind) -> int:
        if not rows:
            await session.commit()
            return 0
        if fact_kind == "daily":
            count = await repository.upsert_daily_bars(rows)
        elif fact_kind == "daily_basic":
            count = await repository.upsert_daily_basic_rows(rows)
        elif fact_kind == "adjust_factor":
            count = await repository.upsert_adjust_factor_rows(rows)
        elif fact_kind == "stock_technical_factor_pro":
            count = await repository.upsert_stock_technical_factor_rows(rows)
        else:
            count = await repository.upsert_stock_fund_flow_rows(rows)
        await session.commit()
        return count
