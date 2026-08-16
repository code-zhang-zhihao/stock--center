from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import asyncio

from sqlalchemy import BigInteger
from sqlalchemy.dialects import postgresql

from app.modules.indicator_engine import backfill as backfill_module
from app.modules.indicator_engine.backfill import FactorBackfillRequest, FactorBackfillService
from app.modules.indicator_engine.repository import IndicatorRepository
from app.modules.indicator_engine.service import IndicatorEngineService
from app.modules.market_data.index_contract import CORE_INDEX_CANONICAL_CODES, CSI300_CANONICAL_CODE
from app.modules.market_data.close_ingest import DailyMarketCloseIngestRequest, DailyMarketCloseIngestService
from app.modules.market_data.models import DailyBar, MinuteBar, QuoteSnapshot, TickTrade
from app.modules.market_data.repository import MAX_POSTGRES_QUERY_PARAMS, MarketDataRepository, _safe_batch_size
from app.modules.market_data.stock_factor_contract import (
    STK_FACTOR_PRO_COUNT_COLUMNS,
    STK_FACTOR_PRO_QFQ_COLUMNS,
    map_stk_factor_pro_record,
)
from app.modules.market_data.tushare.adapters.stock_daily import TushareStockDailyAdapter


def _daily_bar(trade_date: date, close: float, volume: int = 100) -> DailyBar:
    return DailyBar(
        stock_code="600519",
        trade_date=trade_date,
        source="tushare:daily",
        adjust_mode="none",
        open_price=close - 1,
        high_price=close + 2,
        low_price=close - 2,
        close_price=close,
        pre_close_price=close - 1,
        change_amount=1,
        change_pct=1,
        volume_hand=volume,
        volume_share=volume * 100,
        amount_yuan=volume * close * 100,
    )


def test_professional_factor_contract_maps_78_qfq_fields_and_four_count_fields() -> None:
    assert len(STK_FACTOR_PRO_QFQ_COLUMNS) == 78
    record = {"ts_code": "600519.SH", "trade_date": "20260622"}
    record.update({field: index + 0.5 for index, field in enumerate(STK_FACTOR_PRO_QFQ_COLUMNS)})
    record.update({field: index + 1 for index, field in enumerate(STK_FACTOR_PRO_COUNT_COLUMNS)})

    row = map_stk_factor_pro_record(record)

    assert row is not None
    assert row["stock_code"] == "600519"
    assert row["price_basis"] == "qfq"
    assert row["technical_core_status"] == "ready"
    assert row["technical_extended_status"] == "ready"
    assert row["calculation_revision"] == "technical_pro_only"
    assert "factors" not in row


def test_core_index_contract_uses_canonical_database_codes() -> None:
    assert CORE_INDEX_CANONICAL_CODES == (
        "000001",
        "399001",
        "399006",
        "000300",
        "000905",
        "000852",
        "000016",
    )
    assert CSI300_CANONICAL_CODE == "000300"
    assert all("." not in code for code in CORE_INDEX_CANONICAL_CODES)


def test_final_backfill_accepts_decimal_rendered_integral_counters() -> None:
    sql = (
        Path(__file__).resolve().parents[2]
        / "docs/sql/78-daily-assets-final-backfill.sql"
    ).read_text(encoding="utf-8")

    for field in ("updays", "downdays", "topdays", "lowdays"):
        assert f"factors ->> '{field}', '')::numeric::integer" in sql


def test_final_index_sql_binds_canonical_codes() -> None:
    class Result:
        @staticmethod
        def all():
            return []

    class Session:
        calls = []

        async def execute(self, statement, params=None):
            self.calls.append((statement, params or {}))
            return Result()

    session = Session()
    repository = IndicatorRepository(session)  # type: ignore[arg-type]
    trade_date = date(2026, 8, 14)

    asyncio.run(
        repository._fill_relative_csi300(
            ["600519"],
            start_date=trade_date,
            end_date=trade_date,
            history_start=date(2026, 1, 1),
        )
    )
    assert session.calls[-1][1]["csi300_code"] == "000300"

    asyncio.run(repository.rebuild_market_summary(trade_date=trade_date))
    assert session.calls[-1][1]["core_index_codes"] == list(CORE_INDEX_CANONICAL_CODES)


def test_partial_professional_upsert_preserves_existing_local_core_values() -> None:
    class Result:
        rowcount = 1

    class Session:
        statement = None

        async def execute(self, statement):
            self.statement = statement
            return Result()

    session = Session()
    repository = MarketDataRepository(session)  # type: ignore[arg-type]
    row = map_stk_factor_pro_record(
        {
            "ts_code": "600519.SH",
            "trade_date": "20260622",
            "ma_qfq_5": 123.45,
        }
    )

    asyncio.run(repository.upsert_stock_factor_professional_rows([row]))

    sql = str(session.statement.compile(dialect=postgresql.dialect()))
    assert "ma5 = coalesce(excluded.ma5, t_stock_factor_daily.ma5)" in sql
    assert "ema5 = coalesce(excluded.ema5, t_stock_factor_daily.ema5)" in sql
    assert "technical_core_status = CASE" in sql
    assert "array_append(array_remove" in sql


def test_qfq_rebase_is_idempotent_and_updates_only_price_dimensional_fields() -> None:
    class Result:
        @staticmethod
        def all():
            return [(1,), (2,)]

    class Session:
        statement = None
        params = None

        async def execute(self, statement, params=None):
            self.statement = statement
            self.params = params
            return Result()

    session = Session()
    repository = IndicatorRepository(session)  # type: ignore[arg-type]
    affected = asyncio.run(
        repository.rebase_qfq_history_for_adjustment_changes(trade_date=date(2026, 6, 22))
    )

    sql = str(session.statement)
    assert affected == 2
    assert session.params == {"trade_date": date(2026, 6, 22)}
    assert "stored_qfq_close" in sql
    assert "abs(scales.scale - 1) > 1e-8" in sql
    assert "return_1d_pct" not in sql
    assert "quality_flags = array_append" in sql


def test_minute_factor_uses_canonical_minutes_and_keeps_trade_date() -> None:
    service = IndicatorEngineService(repository=None)
    trade_date = date(2026, 6, 22)
    first_time = datetime(2026, 6, 22, 1, 31, tzinfo=timezone.utc)
    bars = [
        MinuteBar(
            stock_code="600519",
            trade_date=trade_date,
            bar_time=first_time + timedelta(minutes=index),
            interval="1m",
            source="mootdx",
            price=100 + index,
            avg_price=None,
            volume_hand=100,
            volume_share=10000,
            amount_yuan=(100 + index) * 10000,
        )
        for index in range(3)
    ]

    rows = service._minute_factors("600519", trade_date, bars)

    assert len(rows) == 3
    assert rows[-1]["trade_date"] == trade_date
    assert rows[-1]["vwap"] == 101
    assert rows[-1]["return_1m_pct"] == 100 / 101
    assert rows[-1]["return_5m_pct"] is None


def test_minute_factor_waits_for_twenty_prior_bars_before_volume_baseline() -> None:
    service = IndicatorEngineService(repository=None)
    trade_date = date(2026, 6, 22)
    first_time = datetime(2026, 6, 22, 1, 31, tzinfo=timezone.utc)
    bars = [
        MinuteBar(
            stock_code="600519",
            trade_date=trade_date,
            bar_time=first_time + timedelta(minutes=index),
            interval="1m",
            source="mootdx",
            price=100 + index * 0.1,
            avg_price=None,
            volume_hand=100,
            volume_share=10000,
            amount_yuan=None,
        )
        for index in range(21)
    ]

    rows = service._minute_factors("600519", trade_date, bars)

    assert rows[19]["volume_ratio_20m"] is None
    assert rows[20]["volume_ratio_20m"] == 1
    assert rows[0]["intraday_position_ratio"] is None
    assert rows[-1]["intraday_position_ratio"] == 1
    assert rows[-1]["vwap"] is None


def test_daily_adapter_maps_tushare_rows_without_ts_code_as_canonical_key() -> None:
    mapping = TushareStockDailyAdapter().map_daily(
        [
            {
                "ts_code": "600519.SH",
                "trade_date": "20260622",
                "open": 1500,
                "high": 1510,
                "low": 1490,
                "close": 1505,
                "pre_close": 1490,
                "change": 15,
                "pct_chg": 1.01,
                "vol": 123,
                "amount": 4567.8,
            }
        ],
        trade_date=date(2026, 6, 22),
    )
    rows = mapping.rows

    assert rows[0]["stock_code"] == "600519"
    assert rows[0]["amount_yuan"] == 4567800.0
    assert "ts_code" not in rows[0]


def test_close_ingest_marks_non_trading_day_as_skipped_without_provider_call() -> None:
    class Repository:
        async def get_trade_day(self, _trade_date):
            return SimpleNamespace(is_open=False)

    service = DailyMarketCloseIngestService(Repository(), config_repository=None)
    result = asyncio.run(service.run(DailyMarketCloseIngestRequest(trade_date=date(2026, 6, 21))))

    assert result.status == "skipped"
    assert result.universe_count == 0


def test_bulk_daily_bar_batch_size_stays_under_asyncpg_parameter_limit() -> None:
    rows = [
        {
            "stock_code": f"{index:06d}",
            "trade_date": date(2026, 6, 26),
            "source": "tushare:daily",
            "adjust_mode": "none",
            "open_price": 1.0,
            "high_price": 1.0,
            "low_price": 1.0,
            "close_price": 1.0,
            "pre_close_price": 1.0,
            "change_amount": 0.0,
            "change_pct": 0.0,
            "volume_hand": 1,
            "volume_share": 100,
            "amount_yuan": 100.0,
        }
        for index in range(5500)
    ]

    batch_size = _safe_batch_size(rows, default=5500)

    assert batch_size < len(rows)
    assert batch_size * len(rows[0]) <= MAX_POSTGRES_QUERY_PARAMS


def test_market_volume_columns_use_bigint_bind_types() -> None:
    assert isinstance(DailyBar.__table__.c.volume_hand.type, BigInteger)
    assert isinstance(DailyBar.__table__.c.volume_share.type, BigInteger)
    assert isinstance(MinuteBar.__table__.c.volume_hand.type, BigInteger)
    assert isinstance(MinuteBar.__table__.c.volume_share.type, BigInteger)
    assert isinstance(QuoteSnapshot.__table__.c.volume_hand.type, BigInteger)
    assert isinstance(TickTrade.__table__.c.volume_hand.type, BigInteger)


def test_final_history_backfill_uses_configured_trade_date_windows(monkeypatch) -> None:
    trade_dates = [date(2026, 6, 1) + timedelta(days=index) for index in range(6)]
    stock_codes = ["000001", "600000", "300001"]
    range_calls: list[tuple[date, date, tuple[str, ...], bool]] = []

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def commit(self):
            return None

    class FakeSessionmaker:
        def __call__(self):
            return FakeSession()

    class FakeRepository:
        def __init__(self, _session):
            pass

        async def load_daily_bar_keys_between(self, codes, *, start_date, end_date):
            return {
                (stock_code, trade_date)
                for stock_code in codes
                for trade_date in trade_dates
                if start_date <= trade_date <= end_date
            }

        async def load_stock_daily_ready_keys_between(self, _codes, *, start_date, end_date):
            if start_date <= trade_dates[0] <= end_date:
                return {(stock_codes[0], trade_dates[0])}
            return set()

        async def assemble_stock_daily_factors_final_between(
            self,
            codes,
            *,
            start_date,
            end_date,
            history_start,
            only_missing,
        ):
            assert history_start == start_date - timedelta(days=550)
            range_calls.append((start_date, end_date, tuple(codes), only_missing))
            return {
                trade_date: len(codes) - (1 if trade_date == trade_dates[0] else 0)
                for trade_date in trade_dates
                if start_date <= trade_date <= end_date
            }

        async def refresh_stock_daily_final_percentiles(self, *, start_date, end_date):
            return {
                trade_date: len(stock_codes)
                for trade_date in trade_dates
                if start_date <= trade_date <= end_date
            }

        async def rebuild_market_summary(self, *, trade_date):
            assert trade_date in trade_dates
            return 1

    service = FactorBackfillService(FakeSessionmaker())

    async def resolve_trade_dates(_start_date, _end_date):
        return trade_dates

    async def resolve_stock_codes(_pool_code):
        return stock_codes

    service._resolve_trade_dates = resolve_trade_dates
    service._resolve_stock_codes = resolve_stock_codes
    monkeypatch.setattr(backfill_module, "IndicatorRepository", FakeRepository)

    result = asyncio.run(
        service.backfill_standard_daily(
            FactorBackfillRequest(
                pool_code="all_a_share",
                start_date=trade_dates[0],
                end_date=trade_dates[-1],
                factor_window_trade_days=5,
                sql_stock_chunk_size=50,
            )
        )
    )

    assert [(start, end) for start, end, _, _ in range_calls] == [
        (trade_dates[0], trade_dates[4]),
        (trade_dates[5], trade_dates[5]),
    ]
    assert all(only_missing is True for _, _, _, only_missing in range_calls)
    assert result.processed_trade_dates == 6
    assert result.failed_trade_dates == 0
    assert result.daily_factor_rows == 17
    assert result.market_summary_rows == 6
