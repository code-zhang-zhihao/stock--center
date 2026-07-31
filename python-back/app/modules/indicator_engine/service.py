from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time
from statistics import mean, pstdev
from zoneinfo import ZoneInfo

from app.modules.indicator_engine.factor_calculators import SectorFactorCalculator, StockFundFactorCalculator
from app.modules.indicator_engine.repository import IndicatorRepository
from app.modules.market_data.models import DailyBar, MinuteBar


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class IndicatorBatchResult:
    daily_factor_rows: int = 0
    minute_factor_rows: int = 0
    technical_snapshot_rows: int = 0
    sector_factor_rows: int = 0
    insufficient_daily_history: int = 0
    missing_daily_data: int = 0
    missing_minute_data: int = 0
    missing_snapshot_daily_data: int = 0
    missing_stock_fund_flow: int = 0
    missing_stock_technical_factor: int = 0
    missing_stock_chip_perf: int = 0


@dataclass(slots=True)
class DailyFactorWindowResult:
    """Pure calculation output for one stock batch across multiple trade dates."""

    rows_by_trade_date: dict[date, list[dict]]
    stats_by_trade_date: dict[date, IndicatorBatchResult]


class IndicatorEngineService:
    """Computes reusable factors strictly from canonical market data."""

    factor_source = "system:daily_close"

    def __init__(self, repository: IndicatorRepository) -> None:
        self.repository = repository

    def build_daily_factor_window(
        self,
        stock_codes: list[str],
        *,
        trade_dates: list[date],
        target_codes_by_trade_date: dict[date, set[str]],
        daily_by_stock: dict[str, list[DailyBar]],
        fund_flows_by_stock: dict[str, list],
        technical_factors_by_key: dict[tuple[str, date], object],
        cross_section_flows_by_trade_date: dict[date, dict],
        calculate_stock_fund: bool,
        include_external_technical: bool,
    ) -> DailyFactorWindowResult:
        """Calculate many dates from already loaded canonical ranges.

        The caller owns all database I/O. Keeping this method pure means a
        historical window can reuse the same 100-day daily-bar history instead
        of querying it once per trade date.
        """
        stock_fund_calculator = StockFundFactorCalculator()
        rows_by_trade_date = {trade_date: [] for trade_date in trade_dates}
        stats_by_trade_date = {trade_date: IndicatorBatchResult() for trade_date in trade_dates}
        percentiles_by_trade_date = {
            trade_date: stock_fund_calculator.cross_section_percentiles(flows)
            for trade_date, flows in cross_section_flows_by_trade_date.items()
        } if calculate_stock_fund else {}

        for trade_date in trade_dates:
            target_codes = target_codes_by_trade_date.get(trade_date, set())
            if not target_codes:
                continue
            stats = stats_by_trade_date[trade_date]
            percentiles = percentiles_by_trade_date.get(trade_date, {})
            cross_section_flows = cross_section_flows_by_trade_date.get(trade_date, {})
            for stock_code in stock_codes:
                if stock_code not in target_codes:
                    continue
                bars = daily_by_stock.get(stock_code, [])
                row, insufficient = self._daily_factor(stock_code, trade_date, bars)
                if row is None:
                    stats.missing_daily_data += 1
                    continue
                if insufficient:
                    stats.insufficient_daily_history += 1
                if calculate_stock_fund:
                    if stock_code not in cross_section_flows:
                        stats.missing_stock_fund_flow += 1
                    row["features"] = {
                        **row.get("features", {}),
                        **stock_fund_calculator.features(
                            trade_date=trade_date,
                            bars=bars,
                            flows=fund_flows_by_stock.get(stock_code, []),
                            cross_section_percentile=percentiles.get(stock_code),
                        ),
                    }
                if include_external_technical:
                    technical_factor = technical_factors_by_key.get((stock_code, trade_date))
                    if technical_factor is None:
                        stats.missing_stock_technical_factor += 1
                    technical_feature = self._tushare_technical_feature(technical_factor)
                    if technical_feature:
                        row["features"] = {
                            **row.get("features", {}),
                            "tushare_technical": technical_feature,
                        }
                rows_by_trade_date[trade_date].append(row)
                stats.daily_factor_rows += 1
        return DailyFactorWindowResult(
            rows_by_trade_date=rows_by_trade_date,
            stats_by_trade_date=stats_by_trade_date,
        )

    async def calculate_market_close(
        self,
        stock_codes: list[str],
        *,
        trade_date: date,
        calculate_daily: bool,
        calculate_minute: bool,
        calculate_snapshot: bool,
        calculate_stock_fund: bool = False,
        include_external_technical: bool = True,
        include_chip: bool = True,
        batch_size: int = 200,
    ) -> IndicatorBatchResult:
        result = IndicatorBatchResult()
        logger.info(
            "indicator market close calculation started: trade_date=%s stocks=%s batch_size=%s daily=%s minute=%s snapshot=%s stock_fund=%s",
            trade_date,
            len(stock_codes),
            batch_size,
            calculate_daily,
            calculate_minute,
            calculate_snapshot,
            calculate_stock_fund,
        )
        if not stock_codes:
            logger.warning("indicator market close calculation skipped: trade_date=%s reason=no_stock_codes", trade_date)
            return result
        if not (calculate_daily or calculate_minute or calculate_snapshot):
            logger.info("indicator market close calculation skipped: trade_date=%s reason=no_enabled_factor_blocks", trade_date)
            return result
        if calculate_minute:
            await self.repository.ensure_trade_date_partitions(trade_date)
        stock_fund_calculator = StockFundFactorCalculator()
        stock_fund_percentiles: dict[str, float] = {}
        if calculate_stock_fund and stock_codes:
            cross_section_flows = await self.repository.load_stock_fund_cross_section(stock_codes, trade_date=trade_date)
            stock_fund_percentiles = stock_fund_calculator.cross_section_percentiles(cross_section_flows)
            logger.info(
                "indicator stock fund cross-section loaded: trade_date=%s requested=%s fund_flow_rows=%s percentile_rows=%s",
                trade_date,
                len(stock_codes),
                len(cross_section_flows),
                len(stock_fund_percentiles),
            )
            if not cross_section_flows:
                logger.warning(
                    "indicator stock fund factors have no same-day fund flow input: trade_date=%s requested=%s",
                    trade_date,
                    len(stock_codes),
                )

        for batch_index, offset in enumerate(range(0, len(stock_codes), batch_size), start=1):
            codes = stock_codes[offset : offset + batch_size]
            daily_by_stock = await self.repository.load_daily_bars(codes, trade_date=trade_date)
            minute_by_stock = await self.repository.load_minute_bars(codes, trade_date=trade_date) if (calculate_minute or calculate_snapshot) else {}
            fund_flows = await self.repository.load_stock_fund_flows(codes, trade_date=trade_date) if calculate_stock_fund else {}
            technical_factors = await self.repository.load_stock_technical_factors(codes, trade_date=trade_date) if (calculate_daily and include_external_technical) else {}
            chip_perf = await self.repository.load_stock_chip_perf(codes, trade_date=trade_date) if (calculate_daily and include_chip) else {}
            same_day_daily_by_stock = {
                stock_code: next((bar for bar in reversed(bars) if bar.trade_date == trade_date), None)
                for stock_code, bars in daily_by_stock.items()
            }
            same_day_daily_codes = {
                stock_code for stock_code, bar in same_day_daily_by_stock.items() if bar is not None
            }
            same_day_fund_codes = {
                stock_code
                for stock_code, flows in fund_flows.items()
                if any(flow.trade_date == trade_date for flow in flows)
            }
            logger.info(
                "indicator batch input loaded: trade_date=%s batch=%s targets=%s daily=%s minute=%s fund_flow=%s technical=%s chip=%s",
                trade_date,
                batch_index,
                len(codes),
                len(same_day_daily_codes),
                len(minute_by_stock),
                len(same_day_fund_codes),
                len(technical_factors),
                len(chip_perf),
            )

            daily_rows: list[dict] = []
            minute_rows: list[dict] = []
            daily_factor_by_stock: dict[str, dict] = {}
            minute_factor_by_stock: dict[str, dict] = {}
            if calculate_snapshot and not calculate_daily:
                daily_factor_by_stock = await self.repository.load_daily_factor_rows(codes, trade_date=trade_date)
                logger.info(
                    "indicator batch loaded existing daily factors for snapshots: trade_date=%s batch=%s rows=%s",
                    trade_date,
                    batch_index,
                    len(daily_factor_by_stock),
                )

            missing_daily_samples: list[str] = []
            missing_minute_samples: list[str] = []
            missing_snapshot_daily_samples: list[str] = []
            missing_fund_samples: list[str] = []
            missing_technical_samples: list[str] = []
            missing_chip_samples: list[str] = []
            batch_missing_daily = 0
            batch_missing_minute = 0
            batch_missing_snapshot_daily = 0
            batch_missing_fund = 0
            batch_missing_technical = 0
            batch_missing_chip = 0

            for stock_code in codes:
                if calculate_daily:
                    row, insufficient = self._daily_factor(stock_code, trade_date, daily_by_stock.get(stock_code, []))
                    if row:
                        if calculate_stock_fund:
                            if stock_code not in same_day_fund_codes:
                                batch_missing_fund += 1
                                result.missing_stock_fund_flow += 1
                                self._append_sample(missing_fund_samples, stock_code)
                            row["features"] = {
                                **row.get("features", {}),
                                **stock_fund_calculator.features(
                                    trade_date=trade_date,
                                    bars=daily_by_stock.get(stock_code, []),
                                    flows=fund_flows.get(stock_code, []),
                                    cross_section_percentile=stock_fund_percentiles.get(stock_code),
                                ),
                        }
                        if include_external_technical and stock_code not in technical_factors:
                            batch_missing_technical += 1
                            result.missing_stock_technical_factor += 1
                            self._append_sample(missing_technical_samples, stock_code)
                        if include_external_technical:
                            technical_feature = self._tushare_technical_feature(technical_factors.get(stock_code))
                            if technical_feature:
                                row["features"] = {**row.get("features", {}), "tushare_technical": technical_feature}
                        if include_chip and stock_code not in chip_perf:
                            batch_missing_chip += 1
                            result.missing_stock_chip_perf += 1
                            self._append_sample(missing_chip_samples, stock_code)
                        if include_chip:
                            chip_feature = self._chip_feature(chip_perf.get(stock_code), daily_by_stock.get(stock_code, []), trade_date)
                            if chip_feature:
                                row["features"] = {**row.get("features", {}), "chip": chip_feature}
                        daily_rows.append(row)
                        daily_factor_by_stock[stock_code] = row
                    else:
                        batch_missing_daily += 1
                        result.missing_daily_data += 1
                        self._append_sample(missing_daily_samples, stock_code)
                    if insufficient:
                        result.insufficient_daily_history += 1

                if calculate_minute:
                    rows = self._minute_factors(stock_code, trade_date, minute_by_stock.get(stock_code, []))
                    if rows:
                        minute_rows.extend(rows)
                        minute_factor_by_stock[stock_code] = rows[-1]
                    else:
                        batch_missing_minute += 1
                        result.missing_minute_data += 1
                        self._append_sample(missing_minute_samples, stock_code)

            daily_affected = await self.repository.upsert_daily_factors(daily_rows)
            minute_affected = await self.repository.upsert_minute_factors(minute_rows)
            result.daily_factor_rows += daily_affected
            result.minute_factor_rows += minute_affected

            if calculate_snapshot:
                snapshots: list[dict] = []
                for stock_code in codes:
                    daily_bar = same_day_daily_by_stock.get(stock_code)
                    if daily_bar is None:
                        batch_missing_snapshot_daily += 1
                        result.missing_snapshot_daily_data += 1
                        self._append_sample(missing_snapshot_daily_samples, stock_code)
                        continue
                    snapshots.append(
                        self._technical_snapshot(
                            stock_code,
                            trade_date,
                            daily_bar,
                            daily_factor_by_stock.get(stock_code),
                            minute_factor_by_stock.get(stock_code),
                        )
                    )
                snapshot_affected = await self.repository.upsert_technical_snapshots(snapshots)
                result.technical_snapshot_rows += snapshot_affected
            else:
                snapshot_affected = 0
            await self.repository.commit()
            logger.info(
                "indicator batch completed: trade_date=%s batch=%s targets=%s daily_rows=%s daily_affected=%s minute_rows=%s minute_affected=%s snapshot_affected=%s missing_daily=%s missing_minute=%s missing_snapshot_daily=%s missing_fund=%s missing_technical=%s missing_chip=%s",
                trade_date,
                batch_index,
                len(codes),
                len(daily_rows),
                daily_affected,
                len(minute_rows),
                minute_affected,
                snapshot_affected,
                batch_missing_daily,
                batch_missing_minute,
                batch_missing_snapshot_daily,
                batch_missing_fund,
                batch_missing_technical,
                batch_missing_chip,
            )
            if missing_daily_samples or missing_minute_samples or missing_snapshot_daily_samples or missing_fund_samples or missing_technical_samples or missing_chip_samples:
                logger.warning(
                    "indicator batch missing input samples: trade_date=%s batch=%s daily=%s minute=%s snapshot_daily=%s fund_flow=%s technical=%s chip=%s",
                    trade_date,
                    batch_index,
                    missing_daily_samples,
                    missing_minute_samples,
                    missing_snapshot_daily_samples,
                    missing_fund_samples,
                    missing_technical_samples,
                    missing_chip_samples,
                )
        logger.info(
            "indicator market close calculation finished: trade_date=%s daily_factor_rows=%s minute_factor_rows=%s technical_snapshot_rows=%s insufficient_daily_history=%s missing_daily=%s missing_minute=%s missing_snapshot_daily=%s missing_fund=%s missing_technical=%s missing_chip=%s",
            trade_date,
            result.daily_factor_rows,
            result.minute_factor_rows,
            result.technical_snapshot_rows,
            result.insufficient_daily_history,
            result.missing_daily_data,
            result.missing_minute_data,
            result.missing_snapshot_daily_data,
            result.missing_stock_fund_flow,
            result.missing_stock_technical_factor,
            result.missing_stock_chip_perf,
        )
        return result

    async def calculate_sector_factors(self, *, trade_date: date) -> int:
        logger.info("indicator sector factor calculation started: trade_date=%s", trade_date)
        inputs = await self.repository.load_sector_factor_inputs(trade_date=trade_date)
        sector_count = len(inputs["sectors"])
        sector_bar_count = sum(1 for history in inputs["bars"].values() if any(row.trade_date == trade_date for row in history))
        sector_flow_count = sum(1 for history in inputs["flows"].values() if any(row.trade_date == trade_date for row in history))
        component_sector_count = len(inputs["components"])
        component_count = sum(len(codes) for codes in inputs["components"].values())
        logger.info(
            "indicator sector factor inputs loaded: trade_date=%s sectors=%s sector_bars=%s sector_flows=%s component_sectors=%s components=%s component_daily_bars=%s component_fund_flows=%s limit_up_codes=%s",
            trade_date,
            sector_count,
            sector_bar_count,
            sector_flow_count,
            component_sector_count,
            component_count,
            len(inputs["daily_bars"]),
            len(inputs["stock_flows"]),
            len(inputs["limit_up_codes"]),
        )
        if not inputs["sectors"]:
            logger.warning("indicator sector factor calculation skipped: trade_date=%s reason=no_tushare_ths_sectors", trade_date)
            return 0
        rows = SectorFactorCalculator().rows(trade_date=trade_date, inputs=inputs)
        if not rows:
            logger.warning(
                "indicator sector factor produced no rows: trade_date=%s sectors=%s sector_bars=%s sector_flows=%s",
                trade_date,
                sector_count,
                sector_bar_count,
                sector_flow_count,
            )
        affected = await self.repository.upsert_sector_factors(rows)
        await self.repository.commit()
        logger.info(
            "indicator sector factor calculation finished: trade_date=%s rows=%s affected=%s",
            trade_date,
            len(rows),
            affected,
        )
        return affected

    @staticmethod
    def _append_sample(samples: list[str], stock_code: str, *, limit: int = 10) -> None:
        if len(samples) < limit:
            samples.append(stock_code)

    def _daily_factor(self, stock_code: str, trade_date: date, bars: list[DailyBar]) -> tuple[dict | None, bool]:
        current = next((bar for bar in reversed(bars) if bar.trade_date == trade_date), None)
        if current is None:
            return None, True
        closes = [self._float(bar.close_price) for bar in bars]
        volumes = [self._float(bar.volume_hand) for bar in bars]
        amounts = [self._float(bar.amount_yuan) for bar in bars]
        index = bars.index(current)
        close = closes[index]
        previous_close = self._float(current.pre_close_price) or (closes[index - 1] if index else None)
        high, low = self._float(current.high_price), self._float(current.low_price)
        returns = self._returns(closes[max(0, index - 20) : index + 1])
        history_days = index + 1
        return {
            "stock_code": stock_code,
            "trade_date": trade_date,
            "source": self.factor_source,
            "ma5": self._window_mean(closes, index, 5),
            "ma10": self._window_mean(closes, index, 10),
            "ma20": self._window_mean(closes, index, 20),
            "ma30": self._window_mean(closes, index, 30),
            "ma60": self._window_mean(closes, index, 60),
            "return_1d": self._ratio(close - previous_close, previous_close, percent=True),
            "amplitude": self._ratio(high - low, previous_close or close, percent=True),
            "volume_ratio": self._ratio(volumes[index], self._window_mean(volumes, index - 1, 5)),
            "amount_ratio": self._ratio(amounts[index], self._window_mean(amounts, index - 1, 5)),
            "volatility_20d": pstdev(returns) if len(returns) >= 2 else None,
            "close_position": self._ratio(close - low, high - low),
            "features": {"history_days": history_days, "missing_windows": [name for name, minimum in (("ma5", 5), ("ma10", 10), ("ma20", 20), ("ma30", 30), ("ma60", 60), ("volatility_20d", 21)) if history_days < minimum]},
        }, history_days < 20

    def _minute_factors(self, stock_code: str, trade_date: date, bars: list[MinuteBar]) -> list[dict]:
        if not bars:
            return []
        total_amount = 0.0
        amount_volume = 0.0
        amount_available = False
        volumes = [self._none_float(bar.volume_hand) for bar in bars]
        first_price = next((self._none_float(bar.price) for bar in bars if self._none_float(bar.price) is not None), None)
        if first_price is None:
            return []
        running_high = first_price
        running_low = first_price
        rows: list[dict] = []
        for index, bar in enumerate(bars):
            price = self._none_float(bar.price)
            if price is None:
                continue
            volume = self._none_float(bar.volume_hand)
            amount = self._none_float(bar.amount_yuan)
            if amount is not None and volume is not None and volume > 0:
                total_amount += amount
                amount_volume += volume
                amount_available = True
            running_high = max(running_high, price)
            running_low = min(running_low, price)
            baseline_values = [value for value in volumes[max(0, index - 20) : index] if value is not None and value > 0]
            volume_baseline = mean(baseline_values) if len(baseline_values) == 20 else None
            rows.append(
                {
                    "stock_code": stock_code,
                    "trade_date": trade_date,
                    "bar_time": bar.bar_time,
                    "source": self.factor_source,
                    "vwap": total_amount / (amount_volume * 100) if amount_available and amount_volume else None,
                    "minute_return": self._ratio(price - first_price, first_price, percent=True),
                    "volume_spike_ratio": self._ratio(volume, volume_baseline),
                    "intraday_strength": self._ratio(price - running_low, running_high - running_low),
                    "features": {},
                }
            )
        return rows

    def _technical_snapshot(self, stock_code: str, trade_date: date, daily_bar: DailyBar, daily_factor: dict | None, minute_factor: dict | None) -> dict:
        snapshot_time = datetime.combine(trade_date, time(15, 0), tzinfo=ZoneInfo("Asia/Shanghai"))
        return {
            "stock_code": stock_code,
            "snapshot_time": snapshot_time,
            "source": self.factor_source,
            "last_price": daily_bar.close_price,
            "change_pct": daily_bar.change_pct,
            "intraday_strength": (minute_factor or {}).get("intraday_strength") if (minute_factor or {}).get("intraday_strength") is not None else daily_bar.change_pct,
            "volume_score": min(float((minute_factor or {}).get("volume_spike_ratio")) * 20, 100) if (minute_factor or {}).get("volume_spike_ratio") is not None else None,
            "trend_score": self._trend_score(daily_factor),
            "factor_payload": {
                "daily_factor_trade_date": self._iso_value((daily_factor or {}).get("trade_date")),
                "minute_factor_bar_time": self._iso_value((minute_factor or {}).get("bar_time")),
                "daily_bar_id": daily_bar.id,
                "price_source": "t_daily_bar",
            },
        }

    def _tushare_technical_feature(self, row) -> dict | None:
        if row is None:
            return None
        factors = dict(row.factors or {})
        selected_names = (
            "ma_bfq_5", "ma_bfq_10", "ma_bfq_20", "ma_bfq_60", "ma_bfq_90", "ma_bfq_250",
            "ema_bfq_5", "ema_bfq_10", "ema_bfq_20", "ema_bfq_60",
            "macd_bfq", "macd_dif_bfq", "macd_dea_bfq",
            "kdj_bfq", "kdj_k_bfq", "kdj_d_bfq",
            "rsi_bfq_6", "rsi_bfq_12", "rsi_bfq_24",
            "boll_upper_bfq", "boll_mid_bfq", "boll_lower_bfq",
            "atr_bfq", "cci_bfq", "vr_bfq", "wr_bfq", "wr1_bfq",
            "bias1_bfq", "bias2_bfq", "bias3_bfq",
            "obv_bfq", "mfi_bfq", "roc_bfq", "mtm_bfq",
            "updays", "downdays", "topdays", "lowdays",
        )
        selected = {name: factors.get(name) for name in selected_names if factors.get(name) is not None}
        if not selected:
            return None
        selected["source"] = "tushare:stk_factor_pro"
        return selected

    def _chip_feature(self, row, bars: list[DailyBar], trade_date: date) -> dict | None:
        if row is None:
            return None
        current = next((bar for bar in reversed(bars) if bar.trade_date == trade_date), None)
        close = self._float(current.close_price) if current is not None else None
        weight_avg = self._none_float(row.weight_avg)
        cost_5 = self._none_float(row.cost_5pct)
        cost_15 = self._none_float(row.cost_15pct)
        cost_85 = self._none_float(row.cost_85pct)
        cost_95 = self._none_float(row.cost_95pct)
        cost_90_width = self._ratio(cost_95 - cost_5, weight_avg, percent=True) if cost_95 is not None and cost_5 is not None else None
        cost_70_width = self._ratio(cost_85 - cost_15, weight_avg, percent=True) if cost_85 is not None and cost_15 is not None else None
        concentration_score = None
        if cost_90_width is not None:
            concentration_score = max(0.0, min(100.0, 100.0 - cost_90_width))
        return {
            "source": "tushare:cyq_perf",
            "winner_rate": row.winner_rate,
            "avg_cost": row.weight_avg,
            "his_low": row.his_low,
            "his_high": row.his_high,
            "cost_5pct": row.cost_5pct,
            "cost_15pct": row.cost_15pct,
            "cost_50pct": row.cost_50pct,
            "cost_85pct": row.cost_85pct,
            "cost_95pct": row.cost_95pct,
            "cost_90_width": cost_90_width,
            "cost_70_width": cost_70_width,
            "close_vs_avg_cost_pct": self._ratio(close - weight_avg, weight_avg, percent=True) if close is not None and weight_avg else None,
            "chip_concentration_score": concentration_score,
        }

    @staticmethod
    def _float(value: object) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _none_float(value: object) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _window_mean(values: list[float], index: int, window: int) -> float | None:
        if index < 0:
            return None
        chunk = values[max(0, index - window + 1) : index + 1]
        return mean(chunk) if chunk else None

    @staticmethod
    def _ratio(numerator: float | None, denominator: float | None, *, percent: bool = False) -> float | None:
        if numerator is None or denominator in (None, 0):
            return None
        value = numerator / denominator
        return value * 100 if percent else value

    def _returns(self, closes: list[float]) -> list[float]:
        return [self._ratio(closes[index] - closes[index - 1], closes[index - 1], percent=True) for index in range(1, len(closes)) if closes[index - 1]]

    @staticmethod
    def _trend_score(factor: dict | None) -> float | None:
        if factor is None or factor.get("ma5") is None or factor.get("ma10") is None:
            return None
        score = 50
        if factor["ma5"] > factor["ma10"]:
            score += 20
        if factor.get("ma20") and factor["ma10"] > factor["ma20"]:
            score += 20
        if factor.get("return_1d") and factor["return_1d"] > 0:
            score += 10
        return min(score, 100)

    @staticmethod
    def _iso_value(value: object) -> str | None:
        return value.isoformat() if hasattr(value, "isoformat") else None
