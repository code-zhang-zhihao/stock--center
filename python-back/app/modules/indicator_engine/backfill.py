from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from time import perf_counter
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.modules.indicator_engine.repository import IndicatorRepository
from app.modules.indicator_engine.service import IndicatorBatchResult, IndicatorEngineService
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
    include_external_technical: bool = True
    calculate_stock_fund: bool = True

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
    minute_factor_rows: int = 0
    technical_snapshot_rows: int = 0
    sector_factor_rows: int = 0
    index_factor_rows: int = 0
    rebuild_deleted_rows: int = 0
    ingest_mode: Literal["append_safe", "rebuild"] = "append_safe"
    factor_window_trade_days: int = 20
    insufficient_daily_history: int = 0
    missing_daily_data: int = 0
    missing_minute_data: int = 0
    missing_snapshot_daily_data: int = 0
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
    technical_snapshots: FactorBackfillResult
    daily_factor_rows: int = 0
    technical_snapshot_rows: int = 0
    rebuild_deleted_rows: int = 0
    failed_trade_dates: int = 0
    warnings: list[str] = Field(default_factory=list)


class FactorBackfillService:
    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self.sessionmaker = sessionmaker

    async def backfill_stock_daily_pipeline(self, payload: FactorBackfillRequest) -> StockFactorPipelineResult:
        end_date = payload.end_date or await self._resolve_latest_trade_date()
        resolved_payload = payload.model_copy(update={"end_date": end_date})
        daily = await self.backfill_standard_daily_v2(resolved_payload)
        technical_snapshots = FactorBackfillResult(
            factor_kind="technical_snapshot_dynamic",
            pool_code=payload.pool_code,
            start_date=daily.start_date,
            end_date=daily.end_date,
            stock_count=daily.stock_count,
            ingest_mode=payload.ingest_mode,
            warnings=["技术快照已改为 API 动态生成，本任务不再写入物理快照表。"],
        )
        return StockFactorPipelineResult(
            pool_code=payload.pool_code,
            start_date=daily.start_date,
            end_date=daily.end_date,
            stock_count=daily.stock_count,
            daily=daily,
            technical_snapshots=technical_snapshots,
            daily_factor_rows=daily.daily_factor_rows,
            technical_snapshot_rows=technical_snapshots.technical_snapshot_rows,
            rebuild_deleted_rows=daily.rebuild_deleted_rows + technical_snapshots.rebuild_deleted_rows,
            failed_trade_dates=daily.failed_trade_dates + technical_snapshots.failed_trade_dates,
            warnings=[*daily.warnings, *technical_snapshots.warnings],
        )

    async def backfill_standard_daily_v2(self, payload: FactorBackfillRequest) -> FactorBackfillResult:
        """Backfill the typed QFQ serving table, one date and one stock shard at a time."""
        end_date = payload.end_date or await self._resolve_latest_trade_date()
        trade_dates = await self._resolve_trade_dates(payload.start_date, end_date)
        stock_codes = await self._resolve_stock_codes(payload.pool_code)
        if payload.max_stocks:
            stock_codes = stock_codes[: payload.max_stocks]
        if not stock_codes:
            raise FactorBackfillError("empty_stock_pool", f"股票池没有可回填因子的沪深 active 股票: {payload.pool_code}")

        result = FactorBackfillResult(
            factor_kind="daily_v2",
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
            "factor daily V2 backfill started: pool=%s dates=%s stocks=%s history_start=%s chunk=%s only_missing=%s",
            payload.pool_code,
            len(trade_dates),
            len(stock_codes),
            baseline_history_start,
            payload.sql_stock_chunk_size,
            payload.only_missing,
        )
        for trade_date in trade_dates:
            date_rows = 0
            attempted = 0
            try:
                async with self.sessionmaker() as session:
                    repository = IndicatorRepository(session)
                    for offset in range(0, len(stock_codes), payload.sql_stock_chunk_size):
                        codes = stock_codes[offset : offset + payload.sql_stock_chunk_size]
                        if payload.ingest_mode == "append_safe" and payload.only_missing:
                            ready_codes = await repository.existing_stock_daily_v2_ready_codes(
                                codes,
                                trade_date=trade_date,
                            )
                            codes = [code for code in codes if code not in ready_codes]
                        if not codes:
                            continue
                        attempted += len(codes)
                        date_rows += await repository.assemble_stock_daily_factors_v2(
                            codes,
                            trade_date=trade_date,
                            history_start=trade_date - timedelta(days=550),
                        )
                        await session.commit()
                if attempted == 0:
                    result.skipped_trade_dates += 1
                    status = "skipped"
                    reason = "ready_rows_already_present"
                else:
                    result.processed_trade_dates += 1
                    result.daily_factor_rows += date_rows
                    status = "success"
                    reason = None
                result.date_summaries.append(
                    {
                        "trade_date": trade_date.isoformat(),
                        "status": status,
                        "attempted_stocks": attempted,
                        "daily_factor_v2_rows": date_rows,
                        **({"reason": reason} if reason else {}),
                    }
                )
            except Exception as exc:
                result.failed_trade_dates += 1
                if len(result.errors) < 30:
                    result.errors.append(
                        {"trade_date": trade_date.isoformat(), "error": f"{type(exc).__name__}: {exc}"}
                    )
                logger.exception("factor daily V2 backfill date failed: trade_date=%s", trade_date)
                if payload.fail_fast:
                    raise
        if result.failed_trade_dates:
            result.warnings.append(f"{result.failed_trade_dates} 个交易日组装失败，可使用 append_safe 续跑。")
        logger.info(
            "factor daily V2 backfill finished: processed=%s skipped=%s failed=%s rows=%s",
            result.processed_trade_dates,
            result.skipped_trade_dates,
            result.failed_trade_dates,
            result.daily_factor_rows,
        )
        return result

    async def backfill_daily(self, payload: FactorBackfillRequest) -> FactorBackfillResult:
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
        logger.info(
            "factor daily backfill started: mode=postgres_set_based pool=%s stocks=%s start_date=%s end_date=%s trade_dates=%s ingest_mode=%s only_missing=%s window_trade_days=%s sql_stock_chunk_size=%s calculate_stock_fund=%s include_external_technical=%s",
            payload.pool_code,
            len(stock_codes),
            payload.start_date,
            end_date,
            len(trade_dates),
            payload.ingest_mode,
            payload.only_missing,
            payload.factor_window_trade_days,
            payload.sql_stock_chunk_size,
            payload.calculate_stock_fund,
            payload.include_external_technical,
        )

        windows = [
            trade_dates[offset : offset + payload.factor_window_trade_days]
            for offset in range(0, len(trade_dates), payload.factor_window_trade_days)
        ]
        for window_index, window_dates in enumerate(windows, start=1):
            try:
                async with self.sessionmaker() as session:
                    summary = await self._backfill_daily_window_set_based(
                        session=session,
                        window_index=window_index,
                        stock_codes=stock_codes,
                        trade_dates=window_dates,
                        payload=payload,
                    )
                result.rebuild_deleted_rows += summary["rebuild_deleted_rows"]
                result.processed_trade_dates += summary["processed_trade_dates"]
                result.skipped_trade_dates += summary["skipped_trade_dates"]
                result.daily_factor_rows += summary["daily_factor_rows"]
                result.insufficient_daily_history += summary["insufficient_daily_history"]
                result.missing_daily_data += summary["missing_daily_data"]
                result.missing_stock_fund_flow += summary["missing_stock_fund_flow"]
                result.missing_stock_technical_factor += summary["missing_stock_technical_factor"]
                result.date_summaries.extend(summary["date_summaries"])
            except Exception as exc:
                result.failed_trade_dates += len(window_dates)
                for trade_date in window_dates:
                    if len(result.errors) < 30:
                        result.errors.append(
                            {"trade_date": trade_date.isoformat(), "error": f"{type(exc).__name__}: {exc}"}
                        )
                logger.exception(
                    "factor daily backfill set-based window failed: window=%s start_date=%s end_date=%s",
                    window_index,
                    window_dates[0],
                    window_dates[-1],
                )
                if payload.fail_fast:
                    raise

        self._append_warnings(result)
        logger.info(
            "factor daily backfill finished: mode=postgres_set_based pool=%s dates=%s processed=%s skipped=%s failed=%s rows=%s rebuild_deleted=%s window_trade_days=%s",
            payload.pool_code,
            len(trade_dates),
            result.processed_trade_dates,
            result.skipped_trade_dates,
            result.failed_trade_dates,
            result.daily_factor_rows,
            result.rebuild_deleted_rows,
            payload.factor_window_trade_days,
        )
        return result

    async def _backfill_daily_window_set_based(
        self,
        *,
        session,
        window_index: int,
        stock_codes: list[str],
        trade_dates: list[date],
        payload: FactorBackfillRequest,
    ) -> dict[str, Any]:
        """Persist one date window with a single PostgreSQL INSERT .. SELECT."""
        started = perf_counter()
        start_date, end_date = trade_dates[0], trade_dates[-1]
        history_start = start_date.fromordinal(start_date.toordinal() - 100)
        fund_history_start = start_date.fromordinal(start_date.toordinal() - 20)
        repository = IndicatorRepository(session)
        summary: dict[str, Any] = {
            "rebuild_deleted_rows": 0,
            "processed_trade_dates": 0,
            "skipped_trade_dates": 0,
            "daily_factor_rows": 0,
            "insufficient_daily_history": 0,
            "missing_daily_data": 0,
            "missing_stock_fund_flow": 0,
            "missing_stock_technical_factor": 0,
            "date_summaries": [],
        }
        logger.info(
            "factor daily backfill set-based window started: window=%s start_date=%s end_date=%s trade_dates=%s stocks=%s sql_stock_chunk_size=%s",
            window_index,
            start_date,
            end_date,
            len(trade_dates),
            len(stock_codes),
            payload.sql_stock_chunk_size,
        )

        daily_bar_keys = await repository.load_daily_bar_keys_between(
            stock_codes,
            start_date=start_date,
            end_date=end_date,
        )
        existing_keys: set[tuple[str, date]] = set()
        if payload.ingest_mode == "append_safe" and payload.only_missing:
            existing_keys = await repository.load_daily_factor_keys_between(
                stock_codes,
                start_date=start_date,
                end_date=end_date,
            )
        target_keys = daily_bar_keys - existing_keys if existing_keys else daily_bar_keys
        target_count_by_date = {
            trade_date: sum(1 for _, item_date in target_keys if item_date == trade_date)
            for trade_date in trade_dates
        }
        total_daily_rows_by_date = {
            trade_date: sum(1 for _, item_date in daily_bar_keys if item_date == trade_date)
            for trade_date in trade_dates
        }
        if payload.ingest_mode == "rebuild":
            summary["rebuild_deleted_rows"] = await repository.clear_daily_factor_rows_between(
                stock_codes,
                start_date=start_date,
                end_date=end_date,
            )
            await session.commit()
            target_keys = daily_bar_keys
            target_count_by_date = total_daily_rows_by_date

        if not target_keys:
            for trade_date in trade_dates:
                summary["skipped_trade_dates"] += 1
                summary["date_summaries"].append(
                    {
                        "trade_date": trade_date.isoformat(),
                        "status": "skipped",
                        "reason": "daily_factors_already_complete",
                        "target_rows": total_daily_rows_by_date[trade_date],
                        "elapsed_ms": int((perf_counter() - started) * 1000),
                    }
                )
            return summary

        target_stock_codes = sorted({stock_code for stock_code, _ in target_keys})
        written_by_date: dict[date, int] = {}
        for chunk_index, offset in enumerate(range(0, len(target_stock_codes), payload.sql_stock_chunk_size), start=1):
            chunk_codes = target_stock_codes[offset : offset + payload.sql_stock_chunk_size]
            chunk_started = perf_counter()
            chunk_written = await repository.backfill_daily_factors_set_based(
                chunk_codes,
                start_date=start_date,
                end_date=end_date,
                history_start=history_start,
                fund_history_start=fund_history_start,
                only_missing=payload.ingest_mode == "append_safe" and payload.only_missing,
                calculate_stock_fund=payload.calculate_stock_fund,
                include_external_technical=payload.include_external_technical,
            )
            await session.commit()
            for trade_date, count in chunk_written.items():
                written_by_date[trade_date] = written_by_date.get(trade_date, 0) + count
            logger.info(
                "factor daily backfill set-based chunk completed: window=%s start_date=%s end_date=%s chunk=%s stocks=%s upserted=%s elapsed_ms=%s",
                window_index,
                start_date,
                end_date,
                chunk_index,
                len(chunk_codes),
                sum(chunk_written.values()),
                int((perf_counter() - chunk_started) * 1000),
            )
        elapsed_ms = int((perf_counter() - started) * 1000)
        for trade_date in trade_dates:
            written = written_by_date.get(trade_date, 0)
            target = target_count_by_date[trade_date]
            if target == 0:
                summary["skipped_trade_dates"] += 1
                summary["date_summaries"].append(
                    {
                        "trade_date": trade_date.isoformat(),
                        "status": "skipped",
                        "reason": "daily_factors_already_complete",
                        "target_rows": total_daily_rows_by_date[trade_date],
                        "elapsed_ms": elapsed_ms,
                    }
                )
                continue
            summary["processed_trade_dates"] += 1
            summary["daily_factor_rows"] += written
            summary["date_summaries"].append(
                {
                    "trade_date": trade_date.isoformat(),
                    "status": "success",
                    "target_rows": target,
                    "daily_factor_rows": written,
                    "mode": "postgres_set_based",
                    "elapsed_ms": elapsed_ms,
                }
            )
        logger.info(
            "factor daily backfill set-based window finished: window=%s start_date=%s end_date=%s canonical_daily_rows=%s targets=%s chunks=%s upserted=%s elapsed_ms=%s",
            window_index,
            start_date,
            end_date,
            len(daily_bar_keys),
            len(target_keys),
            (len(target_stock_codes) + payload.sql_stock_chunk_size - 1) // payload.sql_stock_chunk_size,
            sum(written_by_date.values()),
            elapsed_ms,
        )
        return summary

    async def _backfill_daily_window(
        self,
        *,
        session,
        worker_id: int,
        stock_codes: list[str],
        trade_dates: list[date],
        payload: FactorBackfillRequest,
    ) -> dict[str, Any]:
        """Backfill a consecutive date window with one range read per stock batch."""
        started = perf_counter()
        start_date, end_date = trade_dates[0], trade_dates[-1]
        history_start = start_date.fromordinal(start_date.toordinal() - 100)
        fund_history_start = start_date.fromordinal(start_date.toordinal() - 20)
        repository = IndicatorRepository(session)
        indicator = IndicatorEngineService(repository)
        summary: dict[str, Any] = {
            "rebuild_deleted_rows": 0,
            "processed_trade_dates": 0,
            "skipped_trade_dates": 0,
            "daily_factor_rows": 0,
            "insufficient_daily_history": 0,
            "missing_daily_data": 0,
            "missing_stock_fund_flow": 0,
            "missing_stock_technical_factor": 0,
            "date_summaries": [],
        }
        logger.info(
            "factor daily backfill window started: worker=%s start_date=%s end_date=%s trade_dates=%s stocks=%s batch_size=%s",
            worker_id,
            start_date,
            end_date,
            len(trade_dates),
            len(stock_codes),
            payload.batch_size,
        )
        if payload.ingest_mode == "rebuild":
            summary["rebuild_deleted_rows"] = await repository.clear_daily_factor_rows_between(
                stock_codes,
                start_date=start_date,
                end_date=end_date,
            )
            await session.commit()
        daily_bar_keys = await repository.load_daily_bar_keys_between(
            stock_codes,
            start_date=start_date,
            end_date=end_date,
        )
        existing_keys = set()
        if payload.ingest_mode == "append_safe" and payload.only_missing:
            existing_keys = await repository.load_daily_factor_keys_between(
                stock_codes,
                start_date=start_date,
                end_date=end_date,
            )
        target_keys = daily_bar_keys - existing_keys if existing_keys else daily_bar_keys
        target_codes_by_date_all = {trade_date: set() for trade_date in trade_dates}
        for stock_code, trade_date in target_keys:
            target_codes_by_date_all[trade_date].add(stock_code)
        target_count_by_date = {
            trade_date: len(target_codes_by_date_all[trade_date])
            for trade_date in trade_dates
        }
        if not target_keys:
            for trade_date in trade_dates:
                summary["skipped_trade_dates"] += 1
                summary["date_summaries"].append(
                    {
                        "trade_date": trade_date.isoformat(),
                        "status": "skipped",
                        "reason": "daily_factors_already_complete",
                        "elapsed_ms": int((perf_counter() - started) * 1000),
                    }
                )
            logger.info(
                "factor daily backfill window skipped complete: worker=%s start_date=%s end_date=%s daily_bar_keys=%s",
                worker_id,
                start_date,
                end_date,
                len(daily_bar_keys),
            )
            return summary
        cross_sections = {}
        if payload.calculate_stock_fund:
            cross_sections = await repository.load_stock_fund_cross_sections(stock_codes, trade_dates=trade_dates)

        written_count_by_date = {trade_date: 0 for trade_date in trade_dates}
        stats_by_date = {trade_date: None for trade_date in trade_dates}
        for batch_index, offset in enumerate(range(0, len(stock_codes), payload.batch_size), start=1):
            codes = stock_codes[offset : offset + payload.batch_size]
            batch_code_set = set(codes)
            target_codes_by_date = {
                trade_date: target_codes_by_date_all[trade_date] & batch_code_set
                for trade_date in trade_dates
            }
            if not any(target_codes_by_date.values()):
                continue
            batch_started = perf_counter()
            daily_by_stock = await repository.load_daily_bars_between(
                codes,
                start_date=history_start,
                end_date=end_date,
            )
            fund_flows_by_stock = await repository.load_stock_fund_flows_between(
                codes,
                start_date=fund_history_start,
                end_date=end_date,
            ) if payload.calculate_stock_fund else {}
            technical_factors_by_key = await repository.load_stock_technical_factors_between(
                codes,
                start_date=start_date,
                end_date=end_date,
            ) if payload.include_external_technical else {}
            computed = indicator.build_daily_factor_window(
                codes,
                trade_dates=trade_dates,
                target_codes_by_trade_date=target_codes_by_date,
                daily_by_stock=daily_by_stock,
                fund_flows_by_stock=fund_flows_by_stock,
                technical_factors_by_key=technical_factors_by_key,
                cross_section_flows_by_trade_date=cross_sections,
                calculate_stock_fund=payload.calculate_stock_fund,
                include_external_technical=payload.include_external_technical,
            )
            rows = [row for trade_date in trade_dates for row in computed.rows_by_trade_date[trade_date]]
            affected = await repository.upsert_daily_factors(rows)
            await session.commit()
            for trade_date in trade_dates:
                stats = computed.stats_by_trade_date[trade_date]
                previous = stats_by_date[trade_date]
                if previous is None:
                    stats_by_date[trade_date] = stats
                else:
                    previous.daily_factor_rows += stats.daily_factor_rows
                    previous.insufficient_daily_history += stats.insufficient_daily_history
                    previous.missing_daily_data += stats.missing_daily_data
                    previous.missing_stock_fund_flow += stats.missing_stock_fund_flow
                    previous.missing_stock_technical_factor += stats.missing_stock_technical_factor
                written_count_by_date[trade_date] += len(computed.rows_by_trade_date[trade_date])
            logger.info(
                "factor daily backfill window batch completed: worker=%s start_date=%s end_date=%s batch=%s targets=%s daily_history_rows=%s fund_history_rows=%s technical_rows=%s upserted=%s elapsed_ms=%s",
                worker_id,
                start_date,
                end_date,
                batch_index,
                sum(len(values) for values in target_codes_by_date.values()),
                sum(len(values) for values in daily_by_stock.values()),
                sum(len(values) for values in fund_flows_by_stock.values()),
                len(technical_factors_by_key),
                affected,
                int((perf_counter() - batch_started) * 1000),
            )
        for trade_date in trade_dates:
            stats = stats_by_date[trade_date] or IndicatorBatchResult()
            elapsed_ms = int((perf_counter() - started) * 1000)
            if target_count_by_date[trade_date] == 0:
                summary["skipped_trade_dates"] += 1
                reason = "daily_factors_already_complete" if any(
                    (stock_code, trade_date) in existing_keys for stock_code in stock_codes
                ) else "no_daily_bars_in_pool"
                summary["date_summaries"].append(
                    {
                        "trade_date": trade_date.isoformat(),
                        "status": "skipped",
                        "reason": reason,
                        "elapsed_ms": elapsed_ms,
                    }
                )
                continue
            summary["processed_trade_dates"] += 1
            summary["daily_factor_rows"] += written_count_by_date[trade_date]
            summary["insufficient_daily_history"] += stats.insufficient_daily_history
            summary["missing_daily_data"] += stats.missing_daily_data
            summary["missing_stock_fund_flow"] += stats.missing_stock_fund_flow
            summary["missing_stock_technical_factor"] += stats.missing_stock_technical_factor
            summary["date_summaries"].append(
                {
                    "trade_date": trade_date.isoformat(),
                    "status": "success",
                    "target_rows": target_count_by_date[trade_date],
                    "daily_factor_rows": written_count_by_date[trade_date],
                    "missing_daily_data": stats.missing_daily_data,
                    "missing_stock_fund_flow": stats.missing_stock_fund_flow,
                    "missing_stock_technical_factor": stats.missing_stock_technical_factor,
                    "insufficient_daily_history": stats.insufficient_daily_history,
                    "elapsed_ms": elapsed_ms,
                }
            )
        logger.info(
            "factor daily backfill window finished: worker=%s start_date=%s end_date=%s processed=%s skipped=%s rows=%s elapsed_ms=%s",
            worker_id,
            start_date,
            end_date,
            summary["processed_trade_dates"],
            summary["skipped_trade_dates"],
            summary["daily_factor_rows"],
            int((perf_counter() - started) * 1000),
        )
        return summary

    async def backfill_technical_snapshots(self, payload: FactorBackfillRequest) -> FactorBackfillResult:
        end_date = payload.end_date or await self._resolve_latest_trade_date()
        trade_dates = await self._resolve_trade_dates(payload.start_date, end_date)
        stock_codes = await self._resolve_stock_codes(payload.pool_code)
        if payload.max_stocks:
            stock_codes = stock_codes[: payload.max_stocks]
        if not stock_codes:
            raise FactorBackfillError("empty_stock_pool", f"股票池没有可回填技术快照的沪深 active 股票: {payload.pool_code}")

        result = FactorBackfillResult(
            factor_kind="technical_snapshot",
            pool_code=payload.pool_code,
            start_date=payload.start_date,
            end_date=end_date,
            trade_date_count=len(trade_dates),
            stock_count=len(stock_codes),
            ingest_mode=payload.ingest_mode,
        )
        logger.info(
            "technical snapshot backfill started: mode=postgres_set_based pool=%s stocks=%s start_date=%s end_date=%s trade_dates=%s ingest_mode=%s only_missing=%s",
            payload.pool_code,
            len(stock_codes),
            payload.start_date,
            end_date,
            len(trade_dates),
            payload.ingest_mode,
            payload.only_missing,
        )

        windows = [
            trade_dates[offset : offset + payload.factor_window_trade_days]
            for offset in range(0, len(trade_dates), payload.factor_window_trade_days)
        ]
        for window_index, window_dates in enumerate(windows, start=1):
            start_date, window_end_date = window_dates[0], window_dates[-1]
            try:
                async with self.sessionmaker() as session:
                    repository = IndicatorRepository(session)
                    if payload.ingest_mode == "rebuild":
                        deleted = await repository.clear_technical_snapshot_rows_between(
                            stock_codes,
                            start_date=start_date,
                            end_date=window_end_date,
                        )
                        await session.commit()
                        result.rebuild_deleted_rows += deleted
                    written_by_date: dict[date, int] = {}
                    for offset in range(0, len(stock_codes), payload.sql_stock_chunk_size):
                        codes = stock_codes[offset : offset + payload.sql_stock_chunk_size]
                        written = await repository.backfill_technical_snapshots_set_based(
                            codes,
                            start_date=start_date,
                            end_date=window_end_date,
                            only_missing=payload.ingest_mode == "append_safe" and payload.only_missing,
                        )
                        await session.commit()
                        for trade_date, count in written.items():
                            written_by_date[trade_date] = written_by_date.get(trade_date, 0) + count
                    for trade_date in window_dates:
                        written = written_by_date.get(trade_date, 0)
                        if written:
                            result.processed_trade_dates += 1
                            result.technical_snapshot_rows += written
                            status = "success"
                        else:
                            result.skipped_trade_dates += 1
                            status = "skipped"
                        result.date_summaries.append(
                            {
                                "trade_date": trade_date.isoformat(),
                                "status": status,
                                "technical_snapshot_rows": written,
                                "mode": "postgres_set_based_daily_only",
                            }
                        )
                    logger.info(
                        "technical snapshot backfill window completed: window=%s start_date=%s end_date=%s stocks=%s rows=%s",
                        window_index,
                        start_date,
                        window_end_date,
                        len(stock_codes),
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
                    "technical snapshot backfill window failed: window=%s start_date=%s end_date=%s",
                    window_index,
                    start_date,
                    window_end_date,
                )
                if payload.fail_fast:
                    raise
        self._append_warnings(result)
        logger.info(
            "technical snapshot backfill finished: pool=%s dates=%s processed=%s skipped=%s failed=%s snapshot_rows=%s rebuild_deleted=%s",
            payload.pool_code,
            len(trade_dates),
            result.processed_trade_dates,
            result.skipped_trade_dates,
            result.failed_trade_dates,
            result.technical_snapshot_rows,
            result.rebuild_deleted_rows,
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
                        if payload.ingest_mode == "append_safe" and payload.only_missing:
                            existing = await indicator_repository.count_sector_factor_rows(trade_date=trade_date)
                            if existing > 0:
                                async with lock:
                                    result.skipped_trade_dates += 1
                                    result.date_summaries.append(
                                        {
                                            "trade_date": trade_date.isoformat(),
                                            "status": "skipped",
                                            "reason": "sector_factors_already_present",
                                            "existing_rows": existing,
                                        }
                                    )
                                continue
                        rows = await indicator.calculate_sector_factors(trade_date=trade_date)
                        async with lock:
                            result.processed_trade_dates += 1
                            result.sector_factor_rows += rows
                            result.date_summaries.append(
                                {
                                    "trade_date": trade_date.isoformat(),
                                    "status": "success",
                                    "sector_factor_rows": rows,
                                    "worker": worker_id,
                                }
                            )
                        logger.info(
                            "factor sector backfill date completed: worker=%s trade_date=%s rows=%s",
                            worker_id,
                            trade_date,
                            rows,
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
        windows = [
            trade_dates[offset : offset + payload.factor_window_trade_days]
            for offset in range(0, len(trade_dates), payload.factor_window_trade_days)
        ]
        for window_index, window_dates in enumerate(windows, start=1):
            start_date, window_end = window_dates[0], window_dates[-1]
            try:
                async with self.sessionmaker() as session:
                    repository = IndicatorRepository(session)
                    if payload.ingest_mode == "rebuild":
                        result.rebuild_deleted_rows += await repository.clear_index_factor_rows_between(
                            index_codes,
                            start_date=start_date,
                            end_date=window_end,
                        )
                        await session.commit()
                    written_by_date: dict[date, int] = {}
                    history_start = start_date.fromordinal(start_date.toordinal() - 100)
                    for offset in range(0, len(index_codes), payload.sql_stock_chunk_size):
                        written = await repository.backfill_index_factors_set_based(
                            index_codes[offset : offset + payload.sql_stock_chunk_size],
                            start_date=start_date,
                            end_date=window_end,
                            history_start=history_start,
                            only_missing=payload.ingest_mode == "append_safe" and payload.only_missing,
                        )
                        await session.commit()
                        for trade_date, count in written.items():
                            written_by_date[trade_date] = written_by_date.get(trade_date, 0) + count
                for trade_date in window_dates:
                    written = written_by_date.get(trade_date, 0)
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
                            "mode": "postgres_set_based",
                        }
                    )
                logger.info(
                    "index factor backfill window completed: window=%s start_date=%s end_date=%s indexes=%s rows=%s",
                    window_index,
                    start_date,
                    window_end,
                    len(index_codes),
                    sum(written_by_date.values()),
                )
            except Exception as exc:
                result.failed_trade_dates += len(window_dates)
                for trade_date in window_dates:
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
