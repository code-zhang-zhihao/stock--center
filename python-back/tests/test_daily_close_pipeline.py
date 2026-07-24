from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace

from app.modules.market_data.close_ingest import (
    DailyMarketCloseIngestResult,
    DailyMarketCloseIngestService,
)
from app.modules.market_data.scheduler_handlers import (
    DailyCloseCoreIngestHandler,
    DailyCloseEnrichmentIngestHandler,
    DailyCloseMinuteIngestHandler,
)


def test_minute_job_keeps_persisted_factors_with_bounded_sql_batches() -> None:
    payload = DailyCloseMinuteIngestHandler.default_payload

    assert payload["sync_minute"] is True
    assert payload["calculate_minute_factors"] is True
    assert payload["minute_max_concurrency"] == 10
    assert payload["minute_retention_trade_days"] == 30
    assert payload["minute_factor_stock_batch_size"] == 200
    assert DailyCloseMinuteIngestHandler.parameter_schema["minute_factor_stock_batch_size"]["max"] == 500


def test_core_and_enrichment_do_not_repeat_minute_or_full_daily_factor_work() -> None:
    core = DailyCloseCoreIngestHandler.default_payload
    enrichment = DailyCloseEnrichmentIngestHandler.default_payload

    assert core["sync_minute"] is False
    assert core["calculate_minute_factors"] is False
    assert core["calculate_daily_factors"] is True
    assert core["calculate_sector_factors"] is False
    assert enrichment["calculate_daily_factors"] is False
    assert enrichment["merge_external_technical_factors"] is True
    assert enrichment["calculate_sector_factors"] is True


def test_large_raw_payload_is_compacted_but_small_events_remain_complete() -> None:
    large = {
        "code": 0,
        "data": {
            "fields": ["ts_code", "trade_date"],
            "items": [[f"{index:06d}.SZ", "20260724"] for index in range(501)],
        },
    }
    compact = DailyMarketCloseIngestService._compact_raw_payload(large, row_count=501)

    assert compact["row_count"] == 501
    assert len(compact["sha256"]) == 64
    assert len(compact["sample_first_last"]) == 2
    assert "data" not in compact

    small = {"data": {"items": [["000001.SZ", "20260724"]]}}
    assert DailyMarketCloseIngestService._compact_raw_payload(small, row_count=1) is small


def test_sector_daily_uses_three_batches_plus_one_missing_retry() -> None:
    trade_date = date(2026, 7, 24)
    raw_codes = [f"{700000 + index}.TI" for index in range(1003)]
    calls: list[dict] = []

    class Repository:
        async def tushare_ths_sector_map(self):
            return {
                code: {
                    "sector_code": f"ths_{code.split('.')[0]}",
                    "sector_name": code,
                    "sector_type": "concept",
                }
                for code in raw_codes
            }

        async def upsert_sector_bar_rows(self, rows):
            self.rows = rows
            return len(rows)

    class Adapter:
        def map_ths_daily(self, records, *, trade_date, sector_map):
            rows = [
                {
                    "sector_code": sector_map[item["ts_code"]]["sector_code"],
                    "trade_date": trade_date,
                }
                for item in records
            ]
            return SimpleNamespace(
                provider_code="tushare",
                api_name="ths_daily",
                capability_code="sector_daily",
                request_range={"trade_date": trade_date.isoformat()},
                raw_count=len(records),
                mapped_count=len(rows),
                missing_count=0,
                unit_conversions={},
                warnings=[],
                rows=rows,
            )

    service = object.__new__(DailyMarketCloseIngestService)
    service.repository = Repository()
    service.tushare_market_adapter = Adapter()

    async def response(_api_name, params, *, capability):
        calls.append({"params": params, "capability": capability})
        codes = str(params["ts_code"]).split(",")
        if capability == "daily_market_close_sector_bars" and raw_codes[-1] in codes:
            codes = [code for code in codes if code != raw_codes[-1]]
        return SimpleNamespace(
            records=[
                {"ts_code": code, "trade_date": trade_date.isoformat()}
                for code in codes
            ]
        )

    async def capture(*_args, **_kwargs):
        return None

    service._tushare_response = response
    service._capture_raw_summary = capture
    result = DailyMarketCloseIngestResult(trade_date=trade_date)

    written = asyncio.run(service._sync_sector_bars(trade_date, result))

    assert written == 1003
    assert len(calls) == 4
    assert max(len(call["params"]["ts_code"].split(",")) for call in calls[:3]) <= 500
    assert calls[-1]["capability"] == "daily_market_close_sector_bars_retry_missing"
