from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.modules.config_center.repository import ConfigCenterRepository
from app.modules.market_data.providers import normalize_symbol, parse_date
from app.modules.market_data.repository import MarketDataRepository
from app.modules.market_data.tushare.adapters import TushareStockDailyAdapter
from app.modules.market_data.tushare.contracts import TushareApiRequest
from app.modules.market_data.tushare_runtime import TushareProviderFactory


logger = logging.getLogger(__name__)

StockFactKind = Literal["daily", "daily_basic", "moneyflow", "stock_technical_factor_pro"]


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
    workers: int = Field(default=4, ge=1, le=10)
    commit_stock_batch_size: int = Field(default=20, ge=1, le=200)
    max_upsert_rows_per_commit: int = Field(default=5000, ge=100, le=50000)
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

    async def run_stock_technical_factor_pro(self, payload: StockDailyBackfillRequest) -> StockDailyBackfillResult:
        return await self._run_fact(payload, "stock_technical_factor_pro")

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
                        api_name = "stk_factor_pro" if fact_kind == "stock_technical_factor_pro" else fact_kind
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
                "close",
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
                "limit_status",
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
        return ()

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
        elif fact_kind == "stock_technical_factor_pro":
            count = await repository.upsert_stock_technical_factor_rows(rows)
        else:
            count = await repository.upsert_stock_fund_flow_rows(rows)
        await session.commit()
        return count
