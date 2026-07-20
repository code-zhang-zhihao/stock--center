from __future__ import annotations

from datetime import date, timedelta

from app.modules.market_data.models import (
    DailyBar,
    StockChipPerfDaily,
    StockFactorDaily,
    StockFactorMinute,
    StockTechnicalFactorDaily,
    TechnicalIndicatorSnapshot,
)
from app.modules.market_data.stock_analysis import StockAnalysisService


def _daily_bar(trade_date: date, close_price: float) -> DailyBar:
    return DailyBar(
        stock_code="600519",
        trade_date=trade_date,
        source="tushare:daily",
        adjust_mode="none",
        open_price=close_price,
        high_price=close_price,
        low_price=close_price,
        close_price=close_price,
        pre_close_price=close_price,
        change_amount=0,
        change_pct=0,
        volume_hand=100,
        volume_share=10000,
        amount_yuan=close_price * 10000,
        turnover_rate=None,
        metadata_json={},
    )


class _DailyChartRepository:
    def __init__(self, rows: list[DailyBar]) -> None:
        self.session = None
        self.rows = rows
        self.requested_trade_dates: list[date] = []

    async def list_daily_bars(self, *, stock_code: str, limit: int) -> list[DailyBar]:
        assert stock_code == "600519"
        return self.rows[:limit]

    async def list_stock_daily_factor_mas(
        self,
        *,
        stock_code: str,
        trade_dates: list[date],
    ) -> dict[date, dict[str, float | None]]:
        assert stock_code == "600519"
        self.requested_trade_dates = trade_dates
        return {
            trade_date: {
                "ma5": float(index + 5),
                "ma10": float(index + 10),
                "ma20": float(index + 20),
                "ma30": float(index + 30),
                "ma60": float(index + 60),
            }
            for index, trade_date in enumerate(trade_dates)
        }


async def test_daily_bars_return_matching_ma_series_for_every_chart_date() -> None:
    end_date = date(2026, 7, 17)
    rows = [_daily_bar(end_date - timedelta(days=index), 1200 - index) for index in range(250)]
    repository = _DailyChartRepository(rows)
    service = StockAnalysisService(repository)  # type: ignore[arg-type]

    result = await service.daily_bars("600519", limit=250)

    assert result["total"] == 250
    assert len(repository.requested_trade_dates) == 250
    assert result["items"][0]["trade_date"] == (end_date - timedelta(days=249)).isoformat()
    assert result["items"][-1]["trade_date"] == end_date.isoformat()
    assert all(item["ma5"] is not None for item in result["items"])
    assert all(item["ma60"] is not None for item in result["items"])


async def test_daily_bars_keep_missing_factor_dates_explicitly_null() -> None:
    trade_date = date(2026, 7, 17)
    repository = _DailyChartRepository([_daily_bar(trade_date, 1253)])

    async def no_factors(**_kwargs):
        return {}

    repository.list_stock_daily_factor_mas = no_factors  # type: ignore[method-assign]
    service = StockAnalysisService(repository)  # type: ignore[arg-type]

    result = await service.daily_bars("600519", limit=250)

    assert result["items"][0]["ma5"] is None
    assert result["items"][0]["ma60"] is None


class _FactorPageRepository:
    def __init__(self) -> None:
        self.session = None
        self.limits: dict[type, int] = {}

    async def list_rows(self, model, *, filters, order_by, limit):
        self.limits[model] = limit
        return []


async def test_factor_page_keeps_series_history_but_limits_large_detail_documents() -> None:
    repository = _FactorPageRepository()
    service = StockAnalysisService(repository)  # type: ignore[arg-type]

    result = await service.factors("600519", trade_date=date(2026, 7, 17), lookback=250)

    assert result["daily_factors"] == []
    assert repository.limits[StockFactorDaily] == 250
    assert repository.limits[StockFactorMinute] == 400
    assert repository.limits[TechnicalIndicatorSnapshot] == 1
    assert repository.limits[StockTechnicalFactorDaily] == 1
    assert repository.limits[StockChipPerfDaily] == 1
