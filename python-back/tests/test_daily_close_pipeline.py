from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace

import app.modules.market_data.close_ingest as close_ingest_module
from app.modules.market_data.close_ingest import (
    DailyMarketCloseIngestResult,
    DailyMarketCloseIngestService,
)
from app.modules.market_data.providers import MootdxProvider
from app.modules.market_data.scheduler_handlers import (
    DailyCloseCoreIngestHandler,
    DailyCloseEnrichmentIngestHandler,
    DailyCloseMinuteIngestHandler,
)
from app.modules.market_data.tushare.adapters import TushareMarketAdapter


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


def test_core_index_daily_uses_one_trade_date_batch_when_tushare_is_ready() -> None:
    trade_date = date(2026, 7, 23)
    calls: list[dict] = []
    raw_summaries: list[dict] = []
    core_codes = DailyMarketCloseIngestService.core_index_codes

    class Repository:
        async def upsert_index_bar_rows(self, rows):
            self.rows = rows
            return len(rows)

    service = object.__new__(DailyMarketCloseIngestService)
    service.repository = Repository()
    service.tushare_market_adapter = TushareMarketAdapter()

    async def response(api_name, params, *, capability):
        calls.append(
            {
                "api_name": api_name,
                "params": params,
                "capability": capability,
            }
        )
        return SimpleNamespace(
            records=[
                {
                    "ts_code": code,
                    "trade_date": trade_date.isoformat(),
                    "open": 100,
                    "high": 101,
                    "low": 99,
                    "close": 100.5,
                    "amount": 10,
                }
                for code in core_codes
            ]
        )

    async def unexpected_fallback(*_args, **_kwargs):
        raise AssertionError("fallback must not run when the batch contains every core index")

    async def capture(_capability, _trade_date, raw_payload, row_count, **_kwargs):
        raw_summaries.append({"payload": raw_payload, "row_count": row_count})

    service._tushare_response = response
    service._akshare_index_daily_records = unexpected_fallback
    service._mootdx_index_daily_records = unexpected_fallback
    service._capture_raw_summary = capture
    result = DailyMarketCloseIngestResult(trade_date=trade_date)

    written = asyncio.run(service._sync_index_bars(trade_date, result))

    assert written == len(core_codes)
    assert len(calls) == 1
    assert calls[0]["params"] == {"trade_date": trade_date}
    assert raw_summaries[0]["payload"]["tushare_request_mode"] == "batch_trade_date"
    assert raw_summaries[0]["payload"]["missing_codes"] == []


def test_core_index_daily_stops_mootdx_after_one_bounded_host_scan() -> None:
    trade_date = date(2026, 7, 24)
    raw_summaries: list[dict] = []

    class Repository:
        async def upsert_index_bar_rows(self, rows):
            assert rows == []
            return 0

    class FailingMootdx:
        def __init__(self):
            self.calls = 0

        async def index_bars(self, _index_code, *, limit):
            self.calls += 1
            assert limit == 10
            raise RuntimeError("no usable TDX host")

    service = object.__new__(DailyMarketCloseIngestService)
    service.repository = Repository()
    service.tushare_market_adapter = TushareMarketAdapter()
    service.mootdx = FailingMootdx()

    async def response(_api_name, params, *, capability):
        assert params == {"trade_date": trade_date}
        assert capability == "daily_market_close_index_bars"
        return SimpleNamespace(records=[])

    async def empty_akshare(*_args, **_kwargs):
        return []

    async def capture(_capability, _trade_date, raw_payload, row_count, **_kwargs):
        raw_summaries.append({"payload": raw_payload, "row_count": row_count})

    service._tushare_response = response
    service._akshare_index_daily_records = empty_akshare
    service._capture_raw_summary = capture
    result = DailyMarketCloseIngestResult(trade_date=trade_date)

    written = asyncio.run(service._sync_index_bars(trade_date, result))

    assert written == 0
    assert service.mootdx.calls == 1
    assert len(raw_summaries[0]["payload"]["missing_codes"]) == len(service.core_index_codes)
    assert raw_summaries[0]["payload"]["mootdx_error"] == "RuntimeError: no usable TDX host"
    assert any("index_daily 缺失指数" in warning for warning in result.warnings)


def test_mootdx_index_empty_response_retries_instead_of_caching_dead_host() -> None:
    provider = MootdxProvider(
        timeout_seconds=2,
        auto_retry=0,
        fallback_server_limit=4,
    )
    require_records_flags: list[bool] = []

    def call_quotes(_operation, *, require_records=False):
        require_records_flags.append(require_records)
        return []

    provider._call_quotes = call_quotes

    rows, raw = provider._index_bars_sync("000001", 10)

    assert rows == []
    assert raw == []
    assert require_records_flags == [True]
    assert provider.timeout_seconds == 2
    assert provider.auto_retry == 0
    assert provider.fallback_server_limit == 4


def test_parallel_block_explicitly_closes_its_provider(monkeypatch) -> None:
    created = []

    class Repository:
        async def commit(self):
            return None

        async def rollback(self):
            return None

    class Service:
        def __init__(self, *_args):
            self.repository = Repository()
            self.closed = False
            created.append(self)

        def close(self):
            self.closed = True

    class SessionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr(close_ingest_module, "get_sessionmaker", lambda: lambda: SessionContext())
    monkeypatch.setattr(close_ingest_module, "DailyMarketCloseIngestService", Service)
    service = object.__new__(DailyMarketCloseIngestService)

    async def run():
        return await service._run_parallel_enrichment_block(
            "index bars",
            lambda _service: asyncio.sleep(0, result=7),
            fail_on_error=False,
            mode="single_date",
            range_start_date=date(2026, 7, 24),
            range_end_date=date(2026, 7, 24),
        )

    result = asyncio.run(run())

    assert result["rows"] == 7
    assert created[0].closed is True
