from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from statistics import mean

from app.modules.indicator_engine.factor_calculators import SectorFactorCalculator
from app.modules.indicator_engine.repository import IndicatorRepository
from app.modules.market_data.models import MinuteBar


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class IndicatorBatchResult:
    """Compatibility counters used by bounded backfill responses."""

    daily_factor_rows: int = 0
    minute_factor_rows: int = 0
    sector_factor_rows: int = 0
    insufficient_daily_history: int = 0
    missing_daily_data: int = 0
    missing_minute_data: int = 0
    missing_stock_fund_flow: int = 0
    missing_stock_technical_factor: int = 0


class IndicatorEngineService:
    """Small calculation facade for assets not assembled directly by SQL.

    Official daily stock factors are assembled by ``IndicatorRepository`` in
    bounded stock/date chunks.  This service intentionally contains no legacy
    daily-factor JSON, technical snapshot, or chip-factor path.
    """

    factor_source = "system:daily_close"

    def __init__(self, repository: IndicatorRepository | None) -> None:
        self.repository = repository

    async def calculate_sector_factors(self, *, trade_date: date) -> int:
        if self.repository is None:
            raise RuntimeError("indicator repository is required")
        logger.info("indicator sector factor calculation started: trade_date=%s", trade_date)
        inputs = await self.repository.load_sector_factor_inputs(trade_date=trade_date)
        if not inputs["sectors"]:
            logger.warning(
                "indicator sector factor calculation skipped: trade_date=%s reason=no_tushare_ths_sectors",
                trade_date,
            )
            return 0
        rows = SectorFactorCalculator().rows(trade_date=trade_date, inputs=inputs)
        affected = await self.repository.upsert_sector_factors(rows)
        await self.repository.commit()
        logger.info(
            "indicator sector factor calculation finished: trade_date=%s rows=%s affected=%s",
            trade_date,
            len(rows),
            affected,
        )
        return affected

    def _minute_factors(self, stock_code: str, trade_date: date, bars: list[MinuteBar]) -> list[dict]:
        """Generate typed minute factors from a chronological intraday series."""
        if not bars:
            return []
        total_amount = 0.0
        amount_volume_shares = 0.0
        prices: list[float] = []
        positive_volumes = [self._none_float(bar.volume_hand) for bar in bars]
        first_price = next(
            (self._none_float(bar.price) for bar in bars if self._none_float(bar.price) is not None),
            None,
        )
        if first_price is None:
            return []
        running_high = first_price
        running_low = first_price
        rows: list[dict] = []
        for index, bar in enumerate(bars):
            price = self._none_float(bar.price)
            if price is None:
                continue
            volume_hand = self._none_float(bar.volume_hand)
            amount_yuan = self._none_float(bar.amount_yuan)
            if amount_yuan is not None and volume_hand is not None and volume_hand > 0:
                total_amount += amount_yuan
                amount_volume_shares += volume_hand * 100
            running_high = max(running_high, price)
            running_low = min(running_low, price)
            prices.append(price)
            baseline = [
                value
                for value in positive_volumes[max(0, index - 20) : index]
                if value is not None and value > 0
            ]
            baseline_mean = mean(baseline) if len(baseline) == 20 else None
            rows.append(
                {
                    "stock_code": stock_code,
                    "trade_date": trade_date,
                    "bar_time": bar.bar_time,
                    "source": self.factor_source,
                    "vwap": total_amount / amount_volume_shares if amount_volume_shares else None,
                    "return_1m_pct": self._trailing_return(prices, 1),
                    "return_5m_pct": self._trailing_return(prices, 5),
                    "return_15m_pct": self._trailing_return(prices, 15),
                    "ma5": mean(prices[-5:]),
                    "ma10": mean(prices[-10:]),
                    "ma20": mean(prices[-20:]),
                    "volume_ratio_20m": self._ratio(volume_hand, baseline_mean),
                    "intraday_position_ratio": self._ratio(
                        price - running_low,
                        running_high - running_low,
                    ),
                }
            )
        return rows

    def _trailing_return(self, prices: list[float], minutes: int) -> float | None:
        if len(prices) <= minutes:
            return None
        base = prices[-minutes - 1]
        return self._ratio(prices[-1] - base, base, percent=True)

    @staticmethod
    def _none_float(value: object) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _ratio(
        numerator: float | None,
        denominator: float | None,
        *,
        percent: bool = False,
    ) -> float | None:
        if numerator is None or denominator in (None, 0):
            return None
        value = numerator / denominator
        return value * 100 if percent else value
