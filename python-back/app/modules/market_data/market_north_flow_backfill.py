"""Resumable historical backfill for market-level northbound flow facts.

``moneyflow_hsgt`` is a compact, date-range API: one request can return many
trade dates.  It must therefore not share the stock-by-stock history pipeline
or inherit its high request count.  This service keeps each provider window
and database commit small, while retaining a raw audit record per window.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.modules.config_center.repository import ConfigCenterRepository
from app.modules.market_data.providers import parse_date, safe_float
from app.modules.market_data.repository import MarketDataRepository
from app.modules.market_data.tushare.contracts import TushareApiRequest
from app.modules.market_data.tushare_runtime import TushareProviderFactory


logger = logging.getLogger(__name__)

NORTH_FLOW_HISTORY_CAPABILITY = "market_north_flow_history_backfill"
NORTH_FLOW_SOURCE = "tushare:moneyflow_hsgt"


class MarketNorthFlowBackfillError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class MarketNorthFlowBackfillRequest(BaseModel):
    """Parameters for compact market-level ``moneyflow_hsgt`` history."""

    start_date: date | None = None
    end_date: date | None = None
    trade_days: int = Field(default=250, ge=60, le=1000)
    only_missing: bool = True
    request_window_trade_days: int = Field(default=120, ge=20, le=250)
    fail_fast: bool = False


class MarketNorthFlowBackfillResult(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    requested_trade_date_count: int = 0
    target_trade_date_count: int = 0
    skipped_complete_date_count: int = 0
    completed_window_count: int = 0
    failed_window_count: int = 0
    provider_row_count: int = 0
    upserted_rows: int = 0
    missing_trade_dates: list[str] = Field(default_factory=list)
    errors: list[dict[str, str]] = Field(default_factory=list)


class MarketNorthFlowBackfillService:
    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self.sessionmaker = sessionmaker

    async def run(
        self,
        payload: MarketNorthFlowBackfillRequest,
        *,
        progress_reporter: Callable[[dict], Awaitable[None]] | None = None,
    ) -> MarketNorthFlowBackfillResult:
        async with self.sessionmaker() as session:
            repository = MarketDataRepository(session)
            requested_dates = await self._resolve_dates(repository, payload)
            existing_dates = (
                await repository.existing_complete_market_north_flow_dates(
                    start_date=requested_dates[0],
                    end_date=requested_dates[-1],
                    source=NORTH_FLOW_SOURCE,
                )
                if payload.only_missing and requested_dates
                else set()
            )

        target_dates = [item for item in requested_dates if item not in existing_dates]
        result = MarketNorthFlowBackfillResult(
            start_date=requested_dates[0] if requested_dates else None,
            end_date=requested_dates[-1] if requested_dates else None,
            requested_trade_date_count=len(requested_dates),
            target_trade_date_count=len(target_dates),
            skipped_complete_date_count=len(requested_dates) - len(target_dates),
        )
        if not requested_dates:
            raise MarketNorthFlowBackfillError("trade_calendar_missing", "没有可用于北向资金流回填的已沉淀交易日")

        await self._report(
            progress_reporter,
            {
                "phase": "preparing_windows",
                "requested_trade_date_count": len(requested_dates),
                "target_trade_date_count": len(target_dates),
                "skipped_complete_date_count": result.skipped_complete_date_count,
                "start_date": result.start_date.isoformat() if result.start_date else None,
                "end_date": result.end_date.isoformat() if result.end_date else None,
            },
        )
        if not target_dates:
            return result

        windows = list(_chunked(target_dates, payload.request_window_trade_days))
        logger.info(
            "market north flow history backfill started: start_date=%s end_date=%s requested_dates=%s target_dates=%s windows=%s only_missing=%s",
            result.start_date,
            result.end_date,
            len(requested_dates),
            len(target_dates),
            len(windows),
            payload.only_missing,
        )
        async with self.sessionmaker() as session:
            repository = MarketDataRepository(session)
            tushare = TushareProviderFactory(ConfigCenterRepository(session))
            for window_index, window_dates in enumerate(windows, start=1):
                window_start = window_dates[0]
                window_end = window_dates[-1]
                try:
                    response = await tushare.call(
                        NORTH_FLOW_HISTORY_CAPABILITY,
                        lambda provider, start=window_start, end=window_end: provider.request(
                            TushareApiRequest(
                                api_name="moneyflow_hsgt",
                                params={"start_date": start, "end_date": end},
                            )
                        ),
                        request_summary={
                            "api_name": "moneyflow_hsgt",
                            "start_date": window_start.isoformat(),
                            "end_date": window_end.isoformat(),
                            "window_trade_date_count": len(window_dates),
                            "only_missing": payload.only_missing,
                        },
                        execution_mode="scheduler",
                    )
                    rows = _map_records(response.records, set(window_dates))
                    returned_dates = {row["trade_date"] for row in rows}
                    missing_dates = [item for item in window_dates if item not in returned_dates]
                    upserted = await repository.upsert_market_north_flow_rows(rows)
                    await repository.insert_ingest_audit(
                        {
                            "trace_id": uuid4().hex,
                            "provider_code": "tushare",
                            "capability": NORTH_FLOW_HISTORY_CAPABILITY,
                            "trade_date": window_end,
                            "request_params": {
                                "api_name": "moneyflow_hsgt",
                                "start_date": window_start.isoformat(),
                                "end_date": window_end.isoformat(),
                                "window_trade_date_count": len(window_dates),
                                "only_missing": payload.only_missing,
                            },
                            "requested_fields": [],
                            "response_row_count": len(response.records),
                            "normalized_row_count": len(rows),
                            "normalized_table": "t_market_north_flow_daily",
                            "schema_version": "canonical_v2",
                            "status": "captured" if rows else "complete_zero",
                        }
                    )
                    await session.commit()
                    result.completed_window_count += 1
                    result.provider_row_count += len(response.records)
                    result.upserted_rows += upserted
                    result.missing_trade_dates.extend(item.isoformat() for item in missing_dates)
                    logger.info(
                        "market north flow history window completed: window=%s/%s start_date=%s end_date=%s provider_rows=%s mapped_rows=%s upserted_rows=%s missing_dates=%s",
                        window_index,
                        len(windows),
                        window_start,
                        window_end,
                        len(response.records),
                        len(rows),
                        upserted,
                        len(missing_dates),
                    )
                except Exception as exc:
                    await session.rollback()
                    result.failed_window_count += 1
                    if len(result.errors) < 20:
                        result.errors.append(
                            {
                                "start_date": window_start.isoformat(),
                                "end_date": window_end.isoformat(),
                                "error": f"{type(exc).__name__}: {exc}",
                            }
                        )
                    logger.warning(
                        "market north flow history window failed: window=%s/%s start_date=%s end_date=%s error=%s",
                        window_index,
                        len(windows),
                        window_start,
                        window_end,
                        exc,
                    )
                    if payload.fail_fast:
                        raise
                finally:
                    await self._report(
                        progress_reporter,
                        {
                            "phase": "fetching_and_persisting",
                            "window_completed": window_index,
                            "window_total": len(windows),
                            "completed_window_count": result.completed_window_count,
                            "failed_window_count": result.failed_window_count,
                            "upserted_rows": result.upserted_rows,
                            "missing_trade_date_count": len(result.missing_trade_dates),
                            "current_window": {
                                "start_date": window_start.isoformat(),
                                "end_date": window_end.isoformat(),
                            },
                        },
                    )
        logger.info(
            "market north flow history backfill finished: requested_dates=%s target_dates=%s completed_windows=%s failed_windows=%s upserted_rows=%s missing_dates=%s",
            result.requested_trade_date_count,
            result.target_trade_date_count,
            result.completed_window_count,
            result.failed_window_count,
            result.upserted_rows,
            len(result.missing_trade_dates),
        )
        return result

    async def _resolve_dates(
        self,
        repository: MarketDataRepository,
        payload: MarketNorthFlowBackfillRequest,
    ) -> list[date]:
        if payload.start_date is not None:
            end_date = payload.end_date
            if end_date is None:
                recent = await repository.recent_daily_trade_dates(up_to=date.today(), limit=1)
                end_date = recent[0] if recent else None
            if end_date is None:
                return []
            if payload.start_date > end_date:
                raise MarketNorthFlowBackfillError("invalid_date_range", "开始日期不能晚于结束日期")
            return await repository.open_trade_dates_between(start_date=payload.start_date, end_date=end_date)

        resolved_end = payload.end_date
        if resolved_end is None:
            recent = await repository.recent_daily_trade_dates(up_to=date.today(), limit=1)
            resolved_end = recent[0] if recent else None
        if resolved_end is None:
            return []
        # Only request dates whose core daily bar already exists; a later V2
        # baseline cannot score a date that has no canonical market facts.
        recent_dates = await repository.recent_daily_trade_dates(
            up_to=resolved_end,
            limit=payload.trade_days,
        )
        return list(reversed(recent_dates))

    @staticmethod
    async def _report(
        progress_reporter: Callable[[dict], Awaitable[None]] | None,
        progress: dict,
    ) -> None:
        if progress_reporter is not None:
            await progress_reporter(progress)


def _map_records(records: list[dict[str, Any]], target_dates: set[date]) -> list[dict]:
    mapped: dict[date, dict] = {}
    for record in records:
        trade_date = parse_date(record.get("trade_date"))
        if trade_date is None or trade_date not in target_dates:
            continue
        mapped[trade_date] = {
            "trade_date": trade_date,
            "source": NORTH_FLOW_SOURCE,
            "hgt": safe_float(record.get("hgt")),
            "sgt": safe_float(record.get("sgt")),
            "north_money": safe_float(record.get("north_money")),
            "ggt_ss": safe_float(record.get("ggt_ss")),
            "ggt_sz": safe_float(record.get("ggt_sz")),
            "south_money": safe_float(record.get("south_money")),
            "metadata_json": {
                "provider": "tushare",
                "api_name": "moneyflow_hsgt",
                "value_unit": "provider_reported",
                "raw": record,
            },
        }
    return [mapped[item] for item in sorted(mapped)]


def _chunked(values: list[date], size: int):
    for index in range(0, len(values), size):
        yield values[index : index + size]
