from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
import asyncio

from sqlalchemy import BigInteger

from app.modules.indicator_engine.service import IndicatorEngineService
from app.modules.market_data.close_ingest import DailyMarketCloseIngestRequest, DailyMarketCloseIngestService
from app.modules.market_data.models import DailyBar, MinuteBar, QuoteSnapshot, TickTrade
from app.modules.market_data.repository import MAX_POSTGRES_QUERY_PARAMS, _safe_batch_size


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
        turnover_rate=None,
        metadata_json={},
    )


def test_daily_factor_is_derived_from_canonical_bar_history() -> None:
    service = IndicatorEngineService(repository=None)  # Calculation helpers do not access a provider.
    trade_date = date(2026, 6, 22)
    bars = [_daily_bar(trade_date - timedelta(days=19 - index), 100 + index) for index in range(20)]

    row, insufficient = service._daily_factor("600519", trade_date, bars)

    assert insufficient is False
    assert row is not None
    assert row["source"] == "system:daily_close"
    assert row["ma5"] == 117
    assert row["ma20"] == 109.5
    assert row["features"]["history_days"] == 20


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
            metadata_json={},
        )
        for index in range(3)
    ]

    rows = service._minute_factors("600519", trade_date, bars)

    assert len(rows) == 3
    assert rows[-1]["trade_date"] == trade_date
    assert rows[-1]["vwap"] == 101
    assert rows[-1]["minute_return"] == 2


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
            metadata_json={},
        )
        for index in range(21)
    ]

    rows = service._minute_factors("600519", trade_date, bars)

    assert rows[19]["volume_spike_ratio"] is None
    assert rows[20]["volume_spike_ratio"] == 1
    assert rows[0]["intraday_strength"] is None
    assert rows[-1]["intraday_strength"] == 1
    assert rows[-1]["vwap"] is None


def test_close_ingest_maps_tushare_rows_without_ts_code_as_canonical_key() -> None:
    service = object.__new__(DailyMarketCloseIngestService)
    rows = service._daily_rows(
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
        ]
    )

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
            "turnover_rate": None,
            "metadata": {},
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
