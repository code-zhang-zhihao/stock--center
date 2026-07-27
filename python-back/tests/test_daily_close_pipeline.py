from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from types import SimpleNamespace

import app.modules.market_data.close_ingest as close_ingest_module
from app.modules.market_data.close_ingest import (
    DailyMarketCloseIngestRequest,
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
    assert core["sync_stock_limit_status"] is False
    assert core["sync_sector_bars"] is False
    assert enrichment["calculate_daily_factors"] is False
    assert enrichment["merge_external_technical_factors"] is True
    assert enrichment["calculate_sector_factors"] is True
    assert enrichment["sync_stock_limit_status"] is True
    assert enrichment["sync_sector_bars"] is True


def test_late_limit_and_sector_facts_run_in_enrichment_not_core() -> None:
    trade_date = date(2026, 7, 24)
    payload = DailyMarketCloseIngestRequest(
        sync_daily=False,
        sync_daily_basic=False,
        sync_stock_technical_factor_pro=False,
        sync_stock_moneyflow=False,
        sync_stock_limit_status=True,
        sync_lhb=False,
        sync_index_bars=False,
        sync_index_daily_basic=False,
        sync_north_hold=False,
        sync_market_stats=False,
        sync_sector_bars=True,
        sync_sector_moneyflow=False,
        sync_minute=False,
        calculate_daily_factors=False,
        calculate_minute_factors=False,
        calculate_technical_snapshot=False,
        calculate_stock_fund_factors=False,
        calculate_external_technical_factors=False,
        merge_external_technical_factors=False,
        calculate_sector_factors=False,
    )
    service = object.__new__(DailyMarketCloseIngestService)
    core_result = DailyMarketCloseIngestResult(trade_date=trade_date)

    asyncio.run(
        service._run_parallel_core_blocks(
            trade_date=trade_date,
            payload=payload,
            result=core_result,
            universe_set=set(),
        )
    )

    assert core_result.enrichment_blocks == []

    labels: list[str] = []

    async def run_block(label, _operation, **_kwargs):
        labels.append(label)
        return {"label": label, "status": "success", "rows": 1, "value": 1}

    service._run_parallel_enrichment_block = run_block
    enrichment_result = DailyMarketCloseIngestResult(trade_date=trade_date)
    asyncio.run(
        service._run_parallel_enrichment_blocks(
            trade_date=trade_date,
            payload=payload,
            result=enrichment_result,
            universe_set=set(),
        )
    )

    assert labels == ["stock limit/suspend", "sector bars"]
    assert enrichment_result.stock_limit_rows == 1
    assert enrichment_result.sector_bar_rows == 1


def test_readiness_marks_late_events_and_sector_bars_as_enhancement() -> None:
    trade_date = date(2026, 7, 24)

    class Repository:
        async def daily_close_asset_counts(self, _trade_date):
            return {
                "active_stock": 100,
                "daily_bar": 100,
                "daily_basic": 100,
                "stock_moneyflow": 100,
                "daily_factor": 100,
                "technical_snapshot": 100,
                "stock_technical": 0,
                "index_bar": 7,
                "index_daily_basic": 0,
                "sector_bar": 0,
                "tushare_sector": 100,
                "limit_event": 0,
                "lhb_event": 0,
                "sector_moneyflow": 0,
                "sector_factor": 0,
                "market_stat": 0,
                "raw_capabilities": set(),
            }

    service = object.__new__(DailyMarketCloseIngestService)
    service.repository = Repository()

    readiness = asyncio.run(service.assess_readiness(trade_date))

    assert readiness["core_ready"] is True
    assert readiness["report_quality"] == "degraded"
    assert readiness["block_status"]["stock_events"]["status"] == "missing"
    assert readiness["block_status"]["sector_bars"]["status"] == "missing"


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


def test_core_index_daily_prefers_tickflow_current_day_bars_without_tushare() -> None:
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
        calls.append({"api_name": api_name, "params": params, "capability": capability})
        raise AssertionError("Tushare must not run when TickFlow returns every current-day core index")

    async def tickflow_rows(_trade_date):
        assert _trade_date == trade_date
        return [
            {
                "index_code": code.split(".")[0],
                "trade_date": trade_date,
                "source": "tickflow:klines",
                "close_price": 100.5,
            }
            for code in core_codes
        ], {}

    async def capture(_capability, _trade_date, raw_payload, row_count, **_kwargs):
        raw_summaries.append({"payload": raw_payload, "row_count": row_count})

    service._tushare_response = response
    service._tickflow_index_daily_rows = tickflow_rows
    service._capture_raw_summary = capture
    result = DailyMarketCloseIngestResult(trade_date=trade_date)

    written = asyncio.run(service._sync_index_bars(trade_date, result))

    assert written == len(core_codes)
    assert calls == []
    assert raw_summaries[0]["payload"]["tickflow_request_count"] == len(core_codes)
    assert raw_summaries[0]["payload"]["tushare_fallback_requested"] == []
    assert raw_summaries[0]["payload"]["missing_codes"] == []


def test_core_index_daily_only_uses_tushare_for_tickflow_missing_indexes() -> None:
    trade_date = date(2026, 7, 24)
    raw_summaries: list[dict] = []
    core_codes = DailyMarketCloseIngestService.core_index_codes

    class Repository:
        async def upsert_index_bar_rows(self, rows):
            self.rows = rows
            return len(rows)

    service = object.__new__(DailyMarketCloseIngestService)
    service.repository = Repository()
    service.tushare_market_adapter = TushareMarketAdapter()

    async def response(_api_name, params, *, capability):
        assert params == {"trade_date": trade_date}
        assert capability == "daily_market_close_index_bars_tushare_fallback"
        return SimpleNamespace(
            records=[
                {
                    "ts_code": core_codes[-1],
                    "trade_date": trade_date.isoformat(),
                    "open": 100,
                    "high": 101,
                    "low": 99,
                    "close": 100.5,
                    "amount": 10,
                }
            ],
            raw_payload={"data": {"items": [[core_codes[-1], trade_date.isoformat()]]}},
        )

    async def tickflow_rows(_trade_date):
        assert _trade_date == trade_date
        return [
            {
                "index_code": code.split(".")[0],
                "trade_date": trade_date,
                "source": "tickflow:klines",
                "close_price": 100.5,
            }
            for code in core_codes[:-1]
        ], {core_codes[-1].split(".")[0]: "no current-day bar"}

    async def capture(_capability, _trade_date, raw_payload, row_count, **_kwargs):
        raw_summaries.append({"payload": raw_payload, "row_count": row_count})

    service._tushare_response = response
    service._tickflow_index_daily_rows = tickflow_rows
    service._capture_raw_summary = capture
    result = DailyMarketCloseIngestResult(trade_date=trade_date)

    written = asyncio.run(service._sync_index_bars(trade_date, result))

    assert written == len(core_codes)
    assert service.repository.rows[-1]["source"] == "tushare:index_daily"
    assert raw_summaries[-1]["payload"]["tushare_fallback_requested"] == [core_codes[-1]]
    assert raw_summaries[-1]["payload"]["fallback_used"] == {core_codes[-1].split(".")[0]: "tushare:index_daily"}


def test_tickflow_index_daily_row_rejects_a_previous_trade_day() -> None:
    trade_date = date(2026, 7, 24)
    row = DailyMarketCloseIngestService._tickflow_index_daily_row(
        "000001.SH",
        trade_date,
        [
            {
                "source_symbol": "000001.SH",
                "bar_time": datetime(2026, 7, 22, 16, tzinfo=timezone.utc),
                "close_price": 4000.0,
            }
        ],
    )

    assert row is None


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
