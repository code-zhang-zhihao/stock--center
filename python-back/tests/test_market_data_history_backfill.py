import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import app.modules.market_data.history_backfill as history_backfill
from app.modules.market_data.history_backfill import StockDailyBackfillRequest, StockDailyBackfillService


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def commit(self):
        return None

    async def rollback(self):
        return None


class _FakeSessionMaker:
    def __call__(self):
        return _FakeSession()


def test_limit_event_backfill_skips_completed_dates_and_marks_new_completion(monkeypatch):
    trade_dates = [date(2026, 7, 1), date(2026, 7, 2)]

    class FakeRepository:
        upserted_rows = []
        raw_markers = []

        def __init__(self, session):
            self.session = session

        async def open_trade_dates_between(self, *, start_date, end_date):
            return trade_dates

        async def completed_stock_limit_event_backfill_dates(self, **kwargs):
            return {trade_dates[0]}

        async def upsert_limit_event_rows(self, rows):
            self.upserted_rows.extend(rows)
            return len(rows)

        async def insert_raw(self, row):
            self.raw_markers.append(row)
            return SimpleNamespace(id=len(self.raw_markers))

    class FakeProviderFactory:
        calls = []

        def __init__(self, repository):
            self.repository = repository

        async def call(self, capability, operation, *, request_summary, execution_mode):
            self.calls.append(request_summary)
            if request_summary["api_name"] == "limit_list_d":
                records = [
                    {
                        "ts_code": "600519.SH",
                        "trade_date": request_summary["trade_date"].replace("-", ""),
                        "limit": "U",
                        "close": 110,
                    }
                ]
            else:
                records = [
                    {
                        "ts_code": "000001.SZ",
                        "suspend_date": request_summary["trade_date"].replace("-", ""),
                    }
                ]
            return SimpleNamespace(records=records)

    monkeypatch.setattr(history_backfill, "MarketDataRepository", FakeRepository)
    monkeypatch.setattr(history_backfill, "TushareProviderFactory", FakeProviderFactory)
    monkeypatch.setattr(history_backfill, "ConfigCenterRepository", lambda session: object())

    service = StockDailyBackfillService(_FakeSessionMaker())
    service._resolve_stock_codes = AsyncMock(return_value=["000001", "600519"])
    payload = StockDailyBackfillRequest(
        pool_code="all_a_share",
        start_date=trade_dates[0],
        end_date=trade_dates[-1],
        ingest_mode="append_safe",
        only_missing=True,
        event_workers=2,
    )

    result = asyncio.run(service.run_limit_events(payload))

    assert result.trade_date_count == 2
    assert result.skipped_trade_date_count == 1
    assert result.completed_trade_date_count == 1
    assert result.failed_trade_date_count == 0
    assert result.upserted_rows == 2
    assert {row["event_type"] for row in FakeRepository.upserted_rows} == {"limit_up", "suspend"}
    assert [call["api_name"] for call in FakeProviderFactory.calls] == ["limit_list_d", "suspend_d"]
    assert FakeRepository.raw_markers[0]["capability"] == history_backfill.STOCK_LIMIT_EVENT_HISTORY_CAPABILITY
    assert FakeRepository.raw_markers[0]["request_params"]["trade_date"] == "2026-07-02"


def test_stock_daily_backfill_request_enables_event_stage_by_default():
    payload = StockDailyBackfillRequest()

    assert payload.include_limit_events is True
    assert payload.event_workers == 4
