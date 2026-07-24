from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import and_, bindparam, case, delete, func, or_, select, text
from sqlalchemy.dialects.postgresql import ARRAY, insert
from sqlalchemy import String
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.market_data.models import (
    DailyBar,
    IndexFactorDaily,
    LimitEventDaily,
    MinuteBar,
    SectorBar,
    SectorBasic,
    SectorComponent,
    SectorFactorDaily,
    SectorFundFlowDaily,
    StockChipPerfDaily,
    StockFactorDaily,
    StockFactorMinute,
    StockFundFlowDaily,
    StockTechnicalFactorDaily,
    TechnicalIndicatorSnapshot,
)
from app.modules.market_data.partitioning import ensure_market_partitions


MAX_POSTGRES_QUERY_PARAMS = 30000
DEFAULT_BULK_UPSERT_BATCH_SIZE = 1000
TUSHARE_TECHNICAL_FEATURE_NAMES = (
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


def _chunked(rows: list[dict], batch_size: int):
    for offset in range(0, len(rows), batch_size):
        yield rows[offset : offset + batch_size]


def _safe_batch_size(rows: list[dict], *, default: int = DEFAULT_BULK_UPSERT_BATCH_SIZE) -> int:
    if not rows:
        return default
    return max(1, min(default, MAX_POSTGRES_QUERY_PARAMS // max(1, len(rows[0]))))


class IndicatorRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def ensure_trade_date_partitions(self, trade_date: date) -> None:
        """Create factor partitions before bulk upserts touch partitioned factor tables."""
        await ensure_market_partitions(
            self.session,
            trade_date=trade_date,
            include_minute_bar=False,
            include_minute_factor=True,
        )

    async def load_daily_bars(self, stock_codes: list[str], *, trade_date: date, lookback_days: int = 100) -> dict[str, list[DailyBar]]:
        start_date = trade_date.fromordinal(trade_date.toordinal() - lookback_days)
        return await self.load_daily_bars_between(stock_codes, start_date=start_date, end_date=trade_date)

    async def load_daily_bars_between(
        self,
        stock_codes: list[str],
        *,
        start_date: date,
        end_date: date,
    ) -> dict[str, list[DailyBar]]:
        """Load a ranked daily-bar range once for a stock batch.

        Historical factor backfill uses this range form so adjacent trade dates
        share one read of their overlapping lookback history.
        """
        if not stock_codes:
            return {}
        source_priority = case(
            (DailyBar.source == "tushare:daily", 0),
            (DailyBar.source == "akshare_qfq", 1),
            (DailyBar.source == "mootdx", 2),
            else_=9,
        )
        ranked = (
            select(
                DailyBar.id.label("daily_bar_id"),
                func.row_number().over(
                    partition_by=(DailyBar.stock_code, DailyBar.trade_date),
                    order_by=(source_priority, DailyBar.updated_at.desc(), DailyBar.id.desc()),
                ).label("rn"),
            )
            .where(
                DailyBar.stock_code.in_(stock_codes),
                DailyBar.trade_date.between(start_date, end_date),
            )
            .subquery()
        )
        rows = (
            await self.session.execute(
                select(DailyBar)
                .join(ranked, DailyBar.id == ranked.c.daily_bar_id)
                .where(ranked.c.rn == 1)
                .order_by(DailyBar.stock_code, DailyBar.trade_date)
            )
        ).scalars().all()
        grouped: dict[str, list[DailyBar]] = {}
        for row in rows:
            grouped.setdefault(row.stock_code, []).append(row)
        return grouped

    async def load_daily_bar_keys_between(
        self,
        stock_codes: list[str],
        *,
        start_date: date,
        end_date: date,
    ) -> set[tuple[str, date]]:
        """Return the canonical daily-bar keys for a window without loading history."""
        if not stock_codes:
            return set()
        source_priority = case(
            (DailyBar.source == "tushare:daily", 0),
            (DailyBar.source == "akshare_qfq", 1),
            (DailyBar.source == "mootdx", 2),
            else_=9,
        )
        ranked = (
            select(
                DailyBar.id.label("daily_bar_id"),
                func.row_number().over(
                    partition_by=(DailyBar.stock_code, DailyBar.trade_date),
                    order_by=(source_priority, DailyBar.updated_at.desc(), DailyBar.id.desc()),
                ).label("rn"),
            )
            .where(
                DailyBar.stock_code.in_(stock_codes),
                DailyBar.trade_date.between(start_date, end_date),
            )
            .subquery()
        )
        rows = (
            await self.session.execute(
                select(DailyBar.stock_code, DailyBar.trade_date)
                .join(ranked, DailyBar.id == ranked.c.daily_bar_id)
                .where(ranked.c.rn == 1)
            )
        ).all()
        return {(stock_code, trade_date) for stock_code, trade_date in rows}

    async def load_minute_bars(self, stock_codes: list[str], *, trade_date: date) -> dict[str, list[MinuteBar]]:
        if not stock_codes:
            return {}
        source_priority = case((MinuteBar.source == "mootdx", 0), else_=9)
        ranked = (
            select(
                MinuteBar.id.label("minute_bar_id"),
                MinuteBar.trade_date.label("trade_date"),
                func.row_number().over(
                    partition_by=(MinuteBar.stock_code, MinuteBar.bar_time),
                    order_by=(source_priority, MinuteBar.created_at.desc(), MinuteBar.id.desc()),
                ).label("rn"),
            )
            .where(MinuteBar.stock_code.in_(stock_codes), MinuteBar.trade_date == trade_date)
            .subquery()
        )
        rows = (
            await self.session.execute(
                select(MinuteBar)
                .join(ranked, (MinuteBar.id == ranked.c.minute_bar_id) & (MinuteBar.trade_date == ranked.c.trade_date))
                .where(ranked.c.rn == 1)
                .order_by(MinuteBar.stock_code, MinuteBar.bar_time)
            )
        ).scalars().all()
        grouped: dict[str, list[MinuteBar]] = {}
        for row in rows:
            grouped.setdefault(row.stock_code, []).append(row)
        return grouped

    async def load_stock_fund_flows(self, stock_codes: list[str], *, trade_date: date) -> dict[str, list[StockFundFlowDaily]]:
        start_date = trade_date.fromordinal(trade_date.toordinal() - 20)
        return await self.load_stock_fund_flows_between(stock_codes, start_date=start_date, end_date=trade_date)

    async def load_stock_fund_flows_between(
        self,
        stock_codes: list[str],
        *,
        start_date: date,
        end_date: date,
    ) -> dict[str, list[StockFundFlowDaily]]:
        if not stock_codes:
            return {}
        rows = (
            await self.session.execute(
                select(StockFundFlowDaily)
                .where(
                    StockFundFlowDaily.stock_code.in_(stock_codes),
                    StockFundFlowDaily.trade_date.between(start_date, end_date),
                )
                .order_by(StockFundFlowDaily.stock_code, StockFundFlowDaily.trade_date)
            )
        ).scalars().all()
        grouped: dict[str, list[StockFundFlowDaily]] = {}
        for row in rows:
            grouped.setdefault(row.stock_code, []).append(row)
        return grouped

    async def load_stock_fund_cross_section(self, stock_codes: list[str], *, trade_date: date) -> dict[str, StockFundFlowDaily]:
        if not stock_codes:
            return {}
        rows = (
            await self.session.execute(
                select(StockFundFlowDaily).where(
                    StockFundFlowDaily.stock_code.in_(stock_codes),
                    StockFundFlowDaily.trade_date == trade_date,
                )
            )
        ).scalars().all()
        return {row.stock_code: row for row in rows}

    async def load_stock_fund_cross_sections(
        self,
        stock_codes: list[str],
        *,
        trade_dates: list[date],
    ) -> dict[date, dict[str, StockFundFlowDaily]]:
        if not stock_codes or not trade_dates:
            return {}
        rows = (
            await self.session.execute(
                select(StockFundFlowDaily).where(
                    StockFundFlowDaily.stock_code.in_(stock_codes),
                    StockFundFlowDaily.trade_date.in_(trade_dates),
                )
            )
        ).scalars().all()
        grouped: dict[date, dict[str, StockFundFlowDaily]] = {}
        for row in rows:
            grouped.setdefault(row.trade_date, {})[row.stock_code] = row
        return grouped

    async def load_stock_technical_factors(self, stock_codes: list[str], *, trade_date: date) -> dict[str, StockTechnicalFactorDaily]:
        if not stock_codes:
            return {}
        rows = (
            await self.session.execute(
                select(StockTechnicalFactorDaily).where(
                    StockTechnicalFactorDaily.stock_code.in_(stock_codes),
                    StockTechnicalFactorDaily.trade_date == trade_date,
                )
            )
        ).scalars().all()
        return {row.stock_code: row for row in rows}

    async def load_stock_technical_factors_between(
        self,
        stock_codes: list[str],
        *,
        start_date: date,
        end_date: date,
    ) -> dict[tuple[str, date], StockTechnicalFactorDaily]:
        if not stock_codes:
            return {}
        rows = (
            await self.session.execute(
                select(StockTechnicalFactorDaily).where(
                    StockTechnicalFactorDaily.stock_code.in_(stock_codes),
                    StockTechnicalFactorDaily.trade_date.between(start_date, end_date),
                )
            )
        ).scalars().all()
        return {(row.stock_code, row.trade_date): row for row in rows}

    async def load_stock_chip_perf(self, stock_codes: list[str], *, trade_date: date) -> dict[str, StockChipPerfDaily]:
        if not stock_codes:
            return {}
        rows = (
            await self.session.execute(
                select(StockChipPerfDaily).where(
                    StockChipPerfDaily.stock_code.in_(stock_codes),
                    StockChipPerfDaily.trade_date == trade_date,
                )
            )
        ).scalars().all()
        return {row.stock_code: row for row in rows}

    async def load_daily_factor_rows(self, stock_codes: list[str], *, trade_date: date) -> dict[str, dict]:
        if not stock_codes:
            return {}
        rows = (
            await self.session.execute(
                select(StockFactorDaily).where(
                    StockFactorDaily.stock_code.in_(stock_codes),
                    StockFactorDaily.trade_date == trade_date,
                    StockFactorDaily.source == "system:daily_close",
                )
            )
        ).scalars().all()
        return {
            row.stock_code: {
                "stock_code": row.stock_code,
                "trade_date": row.trade_date,
                "ma5": row.ma5,
                "ma10": row.ma10,
                "ma20": row.ma20,
                "ma30": row.ma30,
                "ma60": row.ma60,
                "return_1d": row.return_1d,
                "features": row.features,
            }
            for row in rows
        }

    async def count_daily_factor_rows(self, stock_codes: list[str], *, trade_date: date) -> int:
        if not stock_codes:
            return 0
        result = await self.session.execute(
            select(func.count(StockFactorDaily.id)).where(
                StockFactorDaily.stock_code.in_(stock_codes),
                StockFactorDaily.trade_date == trade_date,
                StockFactorDaily.source == "system:daily_close",
            )
        )
        return int(result.scalar_one() or 0)

    async def load_daily_factor_keys_between(
        self,
        stock_codes: list[str],
        *,
        start_date: date,
        end_date: date,
    ) -> set[tuple[str, date]]:
        if not stock_codes:
            return set()
        rows = (
            await self.session.execute(
                select(StockFactorDaily.stock_code, StockFactorDaily.trade_date).where(
                    StockFactorDaily.stock_code.in_(stock_codes),
                    StockFactorDaily.trade_date.between(start_date, end_date),
                    StockFactorDaily.source == "system:daily_close",
                )
            )
        ).all()
        return {(stock_code, trade_date) for stock_code, trade_date in rows}

    async def count_technical_snapshot_rows(self, stock_codes: list[str], *, trade_date: date) -> int:
        if not stock_codes:
            return 0
        start = datetime.combine(trade_date, datetime.min.time(), tzinfo=ZoneInfo("Asia/Shanghai"))
        end = datetime.combine(
            trade_date.fromordinal(trade_date.toordinal() + 1),
            datetime.min.time(),
            tzinfo=ZoneInfo("Asia/Shanghai"),
        )
        result = await self.session.execute(
            select(func.count(TechnicalIndicatorSnapshot.id)).where(
                TechnicalIndicatorSnapshot.stock_code.in_(stock_codes),
                TechnicalIndicatorSnapshot.source == "system:daily_close",
                TechnicalIndicatorSnapshot.snapshot_time >= start,
                TechnicalIndicatorSnapshot.snapshot_time < end,
            )
        )
        return int(result.scalar_one() or 0)

    async def count_sector_factor_rows(self, *, trade_date: date) -> int:
        result = await self.session.execute(
            select(func.count(SectorFactorDaily.id)).where(SectorFactorDaily.trade_date == trade_date)
        )
        return int(result.scalar_one() or 0)

    async def clear_daily_factor_rows(self, stock_codes: list[str], *, trade_date: date) -> int:
        if not stock_codes:
            return 0
        deleted = 0
        for codes in _chunked(stock_codes, 1000):
            result = await self.session.execute(
                delete(StockFactorDaily).where(
                    StockFactorDaily.stock_code.in_(codes),
                    StockFactorDaily.trade_date == trade_date,
                    StockFactorDaily.source == "system:daily_close",
                )
            )
            deleted += int(result.rowcount or 0)
        return deleted

    async def clear_daily_factor_rows_between(
        self,
        stock_codes: list[str],
        *,
        start_date: date,
        end_date: date,
    ) -> int:
        if not stock_codes:
            return 0
        deleted = 0
        for codes in _chunked(stock_codes, 1000):
            result = await self.session.execute(
                delete(StockFactorDaily).where(
                    StockFactorDaily.stock_code.in_(codes),
                    StockFactorDaily.trade_date.between(start_date, end_date),
                    StockFactorDaily.source == "system:daily_close",
                )
            )
            deleted += int(result.rowcount or 0)
        return deleted

    async def backfill_daily_factors_set_based(
        self,
        stock_codes: list[str],
        *,
        start_date: date,
        end_date: date,
        history_start: date,
        fund_history_start: date,
        only_missing: bool,
        calculate_stock_fund: bool,
        include_external_technical: bool,
    ) -> dict[date, int]:
        """Calculate one historical daily-factor window inside PostgreSQL.

        Historical backfill used to materialize overlapping daily bars, fund-flow
        rows and full ``stk_factor_pro`` JSON documents in Python for every
        200-stock batch.  The query below keeps the calculation next to the
        canonical tables and extracts only the small professional-factor subset
        that is exposed through ``features.tushare_technical``.
        """
        if not stock_codes:
            return {}

        conflict_clause = (
            "DO NOTHING"
            if only_missing
            else """DO UPDATE SET
                ma5 = EXCLUDED.ma5,
                ma10 = EXCLUDED.ma10,
                ma20 = EXCLUDED.ma20,
                ma30 = EXCLUDED.ma30,
                ma60 = EXCLUDED.ma60,
                return_1d = EXCLUDED.return_1d,
                amplitude = EXCLUDED.amplitude,
                volume_ratio = EXCLUDED.volume_ratio,
                amount_ratio = EXCLUDED.amount_ratio,
                volatility_20d = EXCLUDED.volatility_20d,
                close_position = EXCLUDED.close_position,
                features = EXCLUDED.features"""
        )
        statement = text(
            f"""
            WITH ranked_bars AS (
                SELECT
                    bar.id,
                    bar.stock_code,
                    bar.trade_date,
                    bar.open_price,
                    bar.high_price,
                    bar.low_price,
                    bar.close_price,
                    bar.pre_close_price,
                    bar.volume_hand,
                    bar.amount_yuan,
                    row_number() OVER (
                        PARTITION BY bar.stock_code, bar.trade_date
                        ORDER BY CASE bar.source
                            WHEN 'tushare:daily' THEN 0
                            WHEN 'akshare_qfq' THEN 1
                            WHEN 'mootdx' THEN 2
                            ELSE 9
                        END, bar.updated_at DESC, bar.id DESC
                    ) AS source_rank
                FROM t_daily_bar AS bar
                WHERE bar.stock_code = ANY(CAST(:stock_codes AS varchar[]))
                  AND bar.trade_date BETWEEN :history_start AND :end_date
            ),
            bars AS (
                SELECT * FROM ranked_bars WHERE source_rank = 1
            ),
            bar_with_previous AS (
                SELECT
                    bars.*,
                    lag(close_price) OVER (
                        PARTITION BY stock_code ORDER BY trade_date
                    ) AS previous_close_price,
                    row_number() OVER (
                        PARTITION BY stock_code ORDER BY trade_date
                    ) AS history_days
                FROM bars
            ),
            bar_metrics AS (
                SELECT
                    bar_with_previous.*,
                    CASE
                        WHEN previous_close_price IS NOT NULL AND previous_close_price <> 0
                        THEN (close_price - previous_close_price) / previous_close_price * 100
                    END AS close_return,
                    avg(close_price) FILTER (WHERE close_price IS NOT NULL) OVER (
                        PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
                    ) AS ma5,
                    avg(close_price) FILTER (WHERE close_price IS NOT NULL) OVER (
                        PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 9 PRECEDING AND CURRENT ROW
                    ) AS ma10,
                    avg(close_price) FILTER (WHERE close_price IS NOT NULL) OVER (
                        PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                    ) AS ma20,
                    avg(close_price) FILTER (WHERE close_price IS NOT NULL) OVER (
                        PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
                    ) AS ma30,
                    avg(close_price) FILTER (WHERE close_price IS NOT NULL) OVER (
                        PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW
                    ) AS ma60,
                    avg(volume_hand) FILTER (WHERE volume_hand IS NOT NULL) OVER (
                        PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
                    ) AS previous_volume_mean_5,
                    avg(amount_yuan) FILTER (WHERE amount_yuan IS NOT NULL) OVER (
                        PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
                    ) AS previous_amount_mean_5
                FROM bar_with_previous
            ),
            daily_metrics AS (
                SELECT
                    bar_metrics.*,
                    stddev_pop(close_return) FILTER (WHERE close_return IS NOT NULL) OVER (
                        PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                    ) AS volatility_20d
                FROM bar_metrics
            ),
            fund_with_streak_group AS (
                SELECT
                    flow.*,
                    sum(CASE WHEN coalesce(main_net_inflow, 0) <= 0 THEN 1 ELSE 0 END) OVER (
                        PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    ) AS non_positive_group
                FROM t_stock_fund_flow_daily AS flow
                WHERE :calculate_stock_fund
                  AND flow.stock_code = ANY(CAST(:stock_codes AS varchar[]))
                  AND flow.trade_date BETWEEN :fund_history_start AND :end_date
            ),
            fund_metrics AS (
                SELECT
                    fund_with_streak_group.*,
                    count(*) FILTER (WHERE coalesce(main_net_inflow, 0) > 0) OVER (
                        PARTITION BY stock_code, non_positive_group
                    ) AS continuous_main_inflow_days,
                    sum(coalesce(main_net_inflow, 0)) OVER (
                        PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
                    ) AS main_net_inflow_3d,
                    sum(coalesce(main_net_inflow, 0)) OVER (
                        PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
                    ) AS main_net_inflow_5d,
                    sum(coalesce(main_net_inflow, 0)) OVER (
                        PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 9 PRECEDING AND CURRENT ROW
                    ) AS main_net_inflow_10d,
                    count(*) OVER (
                        PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
                    ) AS fund_days_3,
                    count(*) OVER (
                        PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
                    ) AS fund_days_5,
                    count(*) OVER (
                        PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 9 PRECEDING AND CURRENT ROW
                    ) AS fund_days_10
                FROM fund_with_streak_group
            ),
            fund_cross_section AS (
                SELECT
                    stock_code,
                    trade_date,
                    cume_dist() OVER (
                        PARTITION BY trade_date ORDER BY main_net_inflow
                    ) * 100 AS fund_strength_percentile
                FROM t_stock_fund_flow_daily
                WHERE :calculate_stock_fund
                  AND trade_date BETWEEN :start_date AND :end_date
                  AND main_net_inflow IS NOT NULL
            ),
            technical_raw AS (
                SELECT
                    technical.stock_code,
                    technical.trade_date,
                    jsonb_strip_nulls(jsonb_build_object(
                        'ma_bfq_5', technical.factors -> 'ma_bfq_5',
                        'ma_bfq_10', technical.factors -> 'ma_bfq_10',
                        'ma_bfq_20', technical.factors -> 'ma_bfq_20',
                        'ma_bfq_60', technical.factors -> 'ma_bfq_60',
                        'ma_bfq_90', technical.factors -> 'ma_bfq_90',
                        'ma_bfq_250', technical.factors -> 'ma_bfq_250',
                        'ema_bfq_5', technical.factors -> 'ema_bfq_5',
                        'ema_bfq_10', technical.factors -> 'ema_bfq_10',
                        'ema_bfq_20', technical.factors -> 'ema_bfq_20',
                        'ema_bfq_60', technical.factors -> 'ema_bfq_60',
                        'macd_bfq', technical.factors -> 'macd_bfq',
                        'macd_dif_bfq', technical.factors -> 'macd_dif_bfq',
                        'macd_dea_bfq', technical.factors -> 'macd_dea_bfq',
                        'kdj_bfq', technical.factors -> 'kdj_bfq',
                        'kdj_k_bfq', technical.factors -> 'kdj_k_bfq',
                        'kdj_d_bfq', technical.factors -> 'kdj_d_bfq',
                        'rsi_bfq_6', technical.factors -> 'rsi_bfq_6',
                        'rsi_bfq_12', technical.factors -> 'rsi_bfq_12',
                        'rsi_bfq_24', technical.factors -> 'rsi_bfq_24',
                        'boll_upper_bfq', technical.factors -> 'boll_upper_bfq',
                        'boll_mid_bfq', technical.factors -> 'boll_mid_bfq',
                        'boll_lower_bfq', technical.factors -> 'boll_lower_bfq',
                        'atr_bfq', technical.factors -> 'atr_bfq',
                        'cci_bfq', technical.factors -> 'cci_bfq',
                        'vr_bfq', technical.factors -> 'vr_bfq',
                        'wr_bfq', technical.factors -> 'wr_bfq',
                        'wr1_bfq', technical.factors -> 'wr1_bfq',
                        'bias1_bfq', technical.factors -> 'bias1_bfq',
                        'bias2_bfq', technical.factors -> 'bias2_bfq',
                        'bias3_bfq', technical.factors -> 'bias3_bfq',
                        'obv_bfq', technical.factors -> 'obv_bfq',
                        'mfi_bfq', technical.factors -> 'mfi_bfq',
                        'roc_bfq', technical.factors -> 'roc_bfq',
                        'mtm_bfq', technical.factors -> 'mtm_bfq',
                        'updays', technical.factors -> 'updays',
                        'downdays', technical.factors -> 'downdays',
                        'topdays', technical.factors -> 'topdays',
                        'lowdays', technical.factors -> 'lowdays'
                    )) AS selected_factors
                FROM t_stock_technical_factor_daily AS technical
                WHERE :include_external_technical
                  AND technical.stock_code = ANY(CAST(:stock_codes AS varchar[]))
                  AND technical.trade_date BETWEEN :start_date AND :end_date
            ),
            candidates AS (
                SELECT
                    daily.stock_code,
                    daily.trade_date,
                    daily.ma5,
                    daily.ma10,
                    daily.ma20,
                    daily.ma30,
                    daily.ma60,
                    CASE
                        WHEN coalesce(daily.pre_close_price, daily.previous_close_price) IS NOT NULL
                         AND coalesce(daily.pre_close_price, daily.previous_close_price) <> 0
                        THEN (daily.close_price - coalesce(daily.pre_close_price, daily.previous_close_price))
                             / coalesce(daily.pre_close_price, daily.previous_close_price) * 100
                    END AS return_1d,
                    CASE
                        WHEN coalesce(daily.pre_close_price, daily.close_price) IS NOT NULL
                         AND coalesce(daily.pre_close_price, daily.close_price) <> 0
                        THEN (daily.high_price - daily.low_price)
                             / coalesce(daily.pre_close_price, daily.close_price) * 100
                    END AS amplitude,
                    daily.volume_hand / NULLIF(daily.previous_volume_mean_5, 0) AS volume_ratio,
                    daily.amount_yuan / NULLIF(daily.previous_amount_mean_5, 0) AS amount_ratio,
                    daily.volatility_20d,
                    (daily.close_price - daily.low_price) / NULLIF(daily.high_price - daily.low_price, 0) AS close_position,
                    jsonb_build_object(
                        'history_days', daily.history_days,
                        'missing_windows', to_jsonb(array_remove(ARRAY[
                            CASE WHEN daily.history_days < 5 THEN 'ma5' END,
                            CASE WHEN daily.history_days < 10 THEN 'ma10' END,
                            CASE WHEN daily.history_days < 20 THEN 'ma20' END,
                            CASE WHEN daily.history_days < 30 THEN 'ma30' END,
                            CASE WHEN daily.history_days < 60 THEN 'ma60' END,
                            CASE WHEN daily.history_days < 21 THEN 'volatility_20d' END
                        ]::text[], NULL))
                    )
                    || CASE
                        WHEN :calculate_stock_fund THEN CASE
                            WHEN fund.stock_code IS NULL THEN jsonb_build_object('fund_flow_available', false)
                            ELSE jsonb_build_object(
                                'fund_flow_available', true,
                                'main_net_inflow', fund.main_net_inflow,
                                'main_net_ratio', fund.main_net_inflow / NULLIF(daily.amount_yuan, 0),
                                'big_order_net_inflow', fund.big_order_net_inflow,
                                'big_order_net_ratio', fund.big_order_net_inflow / NULLIF(daily.amount_yuan, 0),
                                'super_large_net_inflow', fund.super_large_net_inflow,
                                'super_large_net_ratio', fund.super_large_net_inflow / NULLIF(daily.amount_yuan, 0),
                                'continuous_main_inflow_days', fund.continuous_main_inflow_days,
                                'main_net_inflow_3d', fund.main_net_inflow_3d,
                                'main_net_inflow_5d', fund.main_net_inflow_5d,
                                'main_net_inflow_10d', fund.main_net_inflow_10d,
                                'fund_strength_percentile', cross_section.fund_strength_percentile,
                                'fund_factor_missing_windows', to_jsonb(array_remove(ARRAY[
                                    CASE WHEN fund.fund_days_3 < 3 THEN 'main_net_inflow_3d' END,
                                    CASE WHEN fund.fund_days_5 < 5 THEN 'main_net_inflow_5d' END,
                                    CASE WHEN fund.fund_days_10 < 10 THEN 'main_net_inflow_10d' END,
                                    CASE WHEN daily.amount_yuan IS NULL OR daily.amount_yuan = 0 THEN 'main_net_ratio' END,
                                    CASE WHEN daily.amount_yuan IS NULL OR daily.amount_yuan = 0 THEN 'big_order_net_ratio' END,
                                    CASE WHEN daily.amount_yuan IS NULL OR daily.amount_yuan = 0 THEN 'super_large_net_ratio' END
                                ]::text[], NULL))
                            )
                        END
                        ELSE '{{}}'::jsonb
                    END
                    || CASE
                        WHEN :include_external_technical AND technical.selected_factors <> '{{}}'::jsonb
                        THEN jsonb_build_object(
                            'tushare_technical', technical.selected_factors || jsonb_build_object('source', 'tushare:stk_factor_pro')
                        )
                        ELSE '{{}}'::jsonb
                    END AS features
                FROM daily_metrics AS daily
                LEFT JOIN fund_metrics AS fund
                  ON :calculate_stock_fund
                 AND fund.stock_code = daily.stock_code
                 AND fund.trade_date = daily.trade_date
                LEFT JOIN fund_cross_section AS cross_section
                  ON :calculate_stock_fund
                 AND cross_section.stock_code = daily.stock_code
                 AND cross_section.trade_date = daily.trade_date
                LEFT JOIN technical_raw AS technical
                  ON :include_external_technical
                 AND technical.stock_code = daily.stock_code
                 AND technical.trade_date = daily.trade_date
                WHERE daily.trade_date BETWEEN :start_date AND :end_date
            )
            INSERT INTO t_stock_factor_daily (
                stock_code, trade_date, source,
                ma5, ma10, ma20, ma30, ma60, return_1d, amplitude,
                volume_ratio, amount_ratio, volatility_20d, close_position, features, created_at
            )
            SELECT
                stock_code, trade_date, 'system:daily_close',
                ma5, ma10, ma20, ma30, ma60, return_1d, amplitude,
                volume_ratio, amount_ratio, volatility_20d, close_position, features, now()
            FROM candidates
            ON CONFLICT (stock_code, trade_date, source) {conflict_clause}
            RETURNING trade_date
            """
        ).bindparams(bindparam("stock_codes", type_=ARRAY(String())))
        rows = (
            await self.session.execute(
                statement,
                {
                    "stock_codes": stock_codes,
                    "start_date": start_date,
                    "end_date": end_date,
                    "history_start": history_start,
                    "fund_history_start": fund_history_start,
                    "only_missing": only_missing,
                    "calculate_stock_fund": calculate_stock_fund,
                    "include_external_technical": include_external_technical,
                },
            )
        ).all()
        written: dict[date, int] = {}
        for (trade_date,) in rows:
            written[trade_date] = written.get(trade_date, 0) + 1
        return written

    async def merge_external_technical_features(
        self,
        stock_codes: list[str],
        *,
        trade_date: date,
    ) -> int:
        """Merge only the selected Tushare technical fields into existing daily factors."""
        if not stock_codes:
            return 0
        technical_pairs = ", ".join(
            f"'{name}', technical.factors -> '{name}'"
            for name in TUSHARE_TECHNICAL_FEATURE_NAMES
        )
        statement = text(
            f"""
            WITH selected AS (
                SELECT
                    technical.stock_code,
                    technical.trade_date,
                    jsonb_strip_nulls(jsonb_build_object({technical_pairs}))
                        || jsonb_build_object('source', 'tushare:stk_factor_pro') AS factors
                FROM t_stock_technical_factor_daily AS technical
                WHERE technical.stock_code = ANY(CAST(:stock_codes AS varchar[]))
                  AND technical.trade_date = :trade_date
            )
            UPDATE t_stock_factor_daily AS factor
            SET features = coalesce(factor.features, '{{}}'::jsonb)
                || jsonb_build_object('tushare_technical', selected.factors)
            FROM selected
            WHERE factor.stock_code = selected.stock_code
              AND factor.trade_date = selected.trade_date
              AND factor.source = 'system:daily_close'
              AND selected.factors <> jsonb_build_object('source', 'tushare:stk_factor_pro')
            RETURNING factor.id
            """
        ).bindparams(bindparam("stock_codes", type_=ARRAY(String())))
        rows = (
            await self.session.execute(
                statement,
                {"stock_codes": stock_codes, "trade_date": trade_date},
            )
        ).all()
        return len(rows)

    async def clear_technical_snapshot_rows(self, stock_codes: list[str], *, trade_date: date) -> int:
        if not stock_codes:
            return 0
        start = datetime.combine(trade_date, datetime.min.time(), tzinfo=ZoneInfo("Asia/Shanghai"))
        end = datetime.combine(
            trade_date.fromordinal(trade_date.toordinal() + 1),
            datetime.min.time(),
            tzinfo=ZoneInfo("Asia/Shanghai"),
        )
        deleted = 0
        for codes in _chunked(stock_codes, 1000):
            result = await self.session.execute(
                delete(TechnicalIndicatorSnapshot).where(
                    TechnicalIndicatorSnapshot.stock_code.in_(codes),
                    TechnicalIndicatorSnapshot.source == "system:daily_close",
                    TechnicalIndicatorSnapshot.snapshot_time >= start,
                    TechnicalIndicatorSnapshot.snapshot_time < end,
                )
            )
            deleted += int(result.rowcount or 0)
        return deleted

    async def clear_technical_snapshot_rows_between(
        self,
        stock_codes: list[str],
        *,
        start_date: date,
        end_date: date,
    ) -> int:
        if not stock_codes:
            return 0
        start = datetime.combine(start_date, datetime.min.time(), tzinfo=ZoneInfo("Asia/Shanghai"))
        end = datetime.combine(
            end_date.fromordinal(end_date.toordinal() + 1),
            datetime.min.time(),
            tzinfo=ZoneInfo("Asia/Shanghai"),
        )
        deleted = 0
        for offset in range(0, len(stock_codes), 1000):
            result = await self.session.execute(
                delete(TechnicalIndicatorSnapshot).where(
                    TechnicalIndicatorSnapshot.stock_code.in_(stock_codes[offset : offset + 1000]),
                    TechnicalIndicatorSnapshot.snapshot_time >= start,
                    TechnicalIndicatorSnapshot.snapshot_time < end,
                    TechnicalIndicatorSnapshot.source == "system:daily_close",
                )
            )
            deleted += int(result.rowcount or 0)
        return deleted

    async def backfill_technical_snapshots_set_based(
        self,
        stock_codes: list[str],
        *,
        start_date: date,
        end_date: date,
        only_missing: bool,
    ) -> dict[date, int]:
        """Build EOD snapshots from canonical daily/minute bars and daily factors."""
        if not stock_codes:
            return {}
        conflict_clause = (
            "DO NOTHING"
            if only_missing
            else """DO UPDATE SET
                last_price = EXCLUDED.last_price,
                change_pct = EXCLUDED.change_pct,
                intraday_strength = EXCLUDED.intraday_strength,
                volume_score = EXCLUDED.volume_score,
                trend_score = EXCLUDED.trend_score,
                factor_payload = EXCLUDED.factor_payload"""
        )
        statement = text(
            f"""
            WITH ranked_bars AS (
                SELECT
                    bar.*,
                    row_number() OVER (
                        PARTITION BY bar.stock_code, bar.trade_date
                        ORDER BY CASE bar.source
                            WHEN 'tushare:daily' THEN 0
                            WHEN 'akshare_qfq' THEN 1
                            WHEN 'mootdx' THEN 2
                            ELSE 9
                        END, bar.updated_at DESC, bar.id DESC
                    ) AS source_rank
                FROM t_daily_bar AS bar
                WHERE bar.stock_code = ANY(CAST(:stock_codes AS varchar[]))
                  AND bar.trade_date BETWEEN :start_date AND :end_date
            ),
            factors AS (
                SELECT DISTINCT ON (stock_code, trade_date)
                    stock_code, trade_date, ma5, ma10, ma20, return_1d
                FROM t_stock_factor_daily
                WHERE stock_code = ANY(CAST(:stock_codes AS varchar[]))
                  AND trade_date BETWEEN :start_date AND :end_date
                ORDER BY stock_code, trade_date,
                    CASE WHEN source = 'system:daily_close' THEN 0 ELSE 9 END,
                    created_at DESC, id DESC
            ),
            minute_metrics AS (
                SELECT
                    minute.stock_code,
                    minute.trade_date,
                    minute.bar_time,
                    minute.price,
                    minute.volume_hand,
                    min(minute.price) OVER (
                        PARTITION BY minute.stock_code, minute.trade_date
                    ) AS day_low,
                    max(minute.price) OVER (
                        PARTITION BY minute.stock_code, minute.trade_date
                    ) AS day_high,
                    avg(minute.volume_hand) FILTER (
                        WHERE minute.volume_hand IS NOT NULL AND minute.volume_hand > 0
                    ) OVER (
                        PARTITION BY minute.stock_code, minute.trade_date
                        ORDER BY minute.bar_time
                        ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
                    ) AS previous_volume_mean_20,
                    count(minute.volume_hand) FILTER (
                        WHERE minute.volume_hand IS NOT NULL AND minute.volume_hand > 0
                    ) OVER (
                        PARTITION BY minute.stock_code, minute.trade_date
                        ORDER BY minute.bar_time
                        ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
                    ) AS previous_volume_count_20,
                    row_number() OVER (
                        PARTITION BY minute.stock_code, minute.trade_date
                        ORDER BY minute.bar_time DESC, minute.id DESC
                    ) AS latest_rank
                FROM t_minute_bar AS minute
                WHERE minute.stock_code = ANY(CAST(:stock_codes AS varchar[]))
                  AND minute.trade_date BETWEEN :start_date AND :end_date
            ),
            latest_minute AS (
                SELECT * FROM minute_metrics WHERE latest_rank = 1
            )
            INSERT INTO t_technical_indicator_snapshot (
                stock_code, snapshot_time, source, last_price, change_pct,
                intraday_strength, volume_score, trend_score, factor_payload, created_at
            )
            SELECT
                bar.stock_code,
                (bar.trade_date::timestamp + time '15:00') AT TIME ZONE 'Asia/Shanghai',
                'system:daily_close',
                bar.close_price,
                bar.change_pct,
                coalesce(
                    (minute.price - minute.day_low) / NULLIF(minute.day_high - minute.day_low, 0),
                    bar.change_pct
                ),
                CASE
                    WHEN minute.previous_volume_count_20 = 20
                     AND minute.previous_volume_mean_20 <> 0
                    THEN LEAST(minute.volume_hand / minute.previous_volume_mean_20 * 20, 100)
                END,
                CASE
                    WHEN factor.ma5 IS NULL OR factor.ma10 IS NULL THEN NULL
                    ELSE LEAST(
                        50
                        + CASE WHEN factor.ma5 > factor.ma10 THEN 20 ELSE 0 END
                        + CASE WHEN factor.ma20 IS NOT NULL AND factor.ma10 > factor.ma20 THEN 20 ELSE 0 END
                        + CASE WHEN factor.return_1d > 0 THEN 10 ELSE 0 END,
                        100
                    )
                END,
                jsonb_build_object(
                    'daily_factor_trade_date', CASE WHEN factor.trade_date IS NULL THEN NULL ELSE factor.trade_date::text END,
                    'minute_factor_bar_time', CASE WHEN minute.bar_time IS NULL THEN NULL ELSE minute.bar_time::text END,
                    'daily_bar_id', bar.id,
                    'price_source', 't_daily_bar'
                ),
                now()
            FROM ranked_bars AS bar
            LEFT JOIN factors AS factor
              ON factor.stock_code = bar.stock_code
             AND factor.trade_date = bar.trade_date
            LEFT JOIN latest_minute AS minute
              ON minute.stock_code = bar.stock_code
             AND minute.trade_date = bar.trade_date
            WHERE bar.source_rank = 1
            ON CONFLICT (stock_code, snapshot_time, source) {conflict_clause}
            RETURNING (snapshot_time AT TIME ZONE 'Asia/Shanghai')::date
            """
        ).bindparams(bindparam("stock_codes", type_=ARRAY(String())))
        rows = (
            await self.session.execute(
                statement,
                {
                    "stock_codes": stock_codes,
                    "start_date": start_date,
                    "end_date": end_date,
                },
            )
        ).all()
        written: dict[date, int] = {}
        for (trade_date,) in rows:
            written[trade_date] = written.get(trade_date, 0) + 1
        return written

    async def clear_minute_factor_rows(self, stock_codes: list[str], *, trade_date: date) -> int:
        if not stock_codes:
            return 0
        deleted = 0
        for codes in _chunked(stock_codes, 1000):
            result = await self.session.execute(
                delete(StockFactorMinute).where(
                    StockFactorMinute.stock_code.in_(codes),
                    StockFactorMinute.trade_date == trade_date,
                    StockFactorMinute.source == "system:daily_close",
                )
            )
            deleted += int(result.rowcount or 0)
        return deleted

    async def backfill_minute_factors_set_based(
        self,
        stock_codes: list[str],
        *,
        trade_date: date,
    ) -> int:
        """Calculate and upsert one trading day's minute factors inside PostgreSQL."""
        if not stock_codes:
            return 0
        statement = text(
            """
            WITH minute_metrics AS (
                SELECT
                    minute.stock_code,
                    minute.trade_date,
                    minute.bar_time,
                    minute.price,
                    minute.volume_hand,
                    sum(minute.amount_yuan) FILTER (
                        WHERE minute.amount_yuan IS NOT NULL
                          AND minute.volume_hand IS NOT NULL
                          AND minute.volume_hand > 0
                    ) OVER (
                        PARTITION BY minute.stock_code, minute.trade_date
                        ORDER BY minute.bar_time, minute.id
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    ) AS cumulative_amount,
                    sum(minute.volume_hand) FILTER (
                        WHERE minute.amount_yuan IS NOT NULL
                          AND minute.volume_hand IS NOT NULL
                          AND minute.volume_hand > 0
                    ) OVER (
                        PARTITION BY minute.stock_code, minute.trade_date
                        ORDER BY minute.bar_time, minute.id
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    ) AS cumulative_amount_volume,
                    first_value(minute.price) OVER (
                        PARTITION BY minute.stock_code, minute.trade_date
                        ORDER BY minute.bar_time, minute.id
                        ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                    ) AS first_price,
                    min(minute.price) OVER (
                        PARTITION BY minute.stock_code, minute.trade_date
                        ORDER BY minute.bar_time, minute.id
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    ) AS running_low,
                    max(minute.price) OVER (
                        PARTITION BY minute.stock_code, minute.trade_date
                        ORDER BY minute.bar_time, minute.id
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    ) AS running_high,
                    avg(minute.volume_hand) FILTER (
                        WHERE minute.volume_hand IS NOT NULL AND minute.volume_hand > 0
                    ) OVER (
                        PARTITION BY minute.stock_code, minute.trade_date
                        ORDER BY minute.bar_time, minute.id
                        ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
                    ) AS previous_volume_mean_20,
                    count(minute.volume_hand) FILTER (
                        WHERE minute.volume_hand IS NOT NULL AND minute.volume_hand > 0
                    ) OVER (
                        PARTITION BY minute.stock_code, minute.trade_date
                        ORDER BY minute.bar_time, minute.id
                        ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
                    ) AS previous_volume_count_20,
                    count(*) OVER (
                        PARTITION BY minute.stock_code, minute.trade_date
                    ) AS day_bar_count,
                    row_number() OVER (
                        PARTITION BY minute.stock_code, minute.trade_date
                        ORDER BY minute.bar_time, minute.id
                    ) AS minute_index
                FROM t_minute_bar AS minute
                WHERE minute.stock_code = ANY(CAST(:stock_codes AS varchar[]))
                  AND minute.trade_date = :trade_date
            ),
            upserted AS (
                INSERT INTO t_stock_factor_minute (
                    stock_code, trade_date, bar_time, source,
                    vwap, minute_return, volume_spike_ratio, intraday_strength,
                    features, created_at
                )
                SELECT
                    stock_code,
                    trade_date,
                    bar_time,
                    'system:daily_close',
                    cumulative_amount / NULLIF(cumulative_amount_volume * 100, 0),
                    (price - first_price) / NULLIF(first_price, 0) * 100,
                    CASE
                        WHEN previous_volume_count_20 = 20
                        THEN volume_hand / NULLIF(previous_volume_mean_20, 0)
                    END,
                    (price - running_low) / NULLIF(running_high - running_low, 0),
                    jsonb_build_object(
                        'minute_index', minute_index,
                        'day_bar_count', day_bar_count,
                        'volume_baseline', CASE
                            WHEN previous_volume_count_20 = 20 THEN 'previous_20_minutes'
                        END,
                        'amount_based_features_available', cumulative_amount IS NOT NULL,
                        'intraday_strength_kind', 'running_range_position'
                    ),
                    now()
                FROM minute_metrics
                WHERE price IS NOT NULL
                ON CONFLICT (stock_code, trade_date, bar_time, source)
                DO UPDATE SET
                    vwap = EXCLUDED.vwap,
                    minute_return = EXCLUDED.minute_return,
                    volume_spike_ratio = EXCLUDED.volume_spike_ratio,
                    intraday_strength = EXCLUDED.intraday_strength,
                    features = EXCLUDED.features
                RETURNING 1
            )
            SELECT count(*) FROM upserted
            """
        ).bindparams(bindparam("stock_codes", type_=ARRAY(String())))
        return int(
            await self.session.scalar(
                statement,
                {"stock_codes": stock_codes, "trade_date": trade_date},
            )
            or 0
        )

    async def clear_sector_factor_rows(self, *, trade_date: date) -> int:
        result = await self.session.execute(delete(SectorFactorDaily).where(SectorFactorDaily.trade_date == trade_date))
        return int(result.rowcount or 0)

    async def clear_index_factor_rows_between(
        self,
        index_codes: list[str],
        *,
        start_date: date,
        end_date: date,
    ) -> int:
        if not index_codes:
            return 0
        deleted = 0
        for codes in _chunked(index_codes, 1000):
            result = await self.session.execute(
                delete(IndexFactorDaily).where(
                    IndexFactorDaily.index_code.in_(codes),
                    IndexFactorDaily.trade_date >= start_date,
                    IndexFactorDaily.trade_date <= end_date,
                )
            )
            deleted += int(result.rowcount or 0)
        return deleted

    async def backfill_index_factors_set_based(
        self,
        index_codes: list[str],
        *,
        start_date: date,
        end_date: date,
        history_start: date,
        only_missing: bool,
    ) -> dict[date, int]:
        if not index_codes:
            return {}
        conflict_clause = (
            "DO NOTHING"
            if only_missing
            else """DO UPDATE SET
                source = EXCLUDED.source,
                ma5 = EXCLUDED.ma5,
                ma10 = EXCLUDED.ma10,
                ma20 = EXCLUDED.ma20,
                ma30 = EXCLUDED.ma30,
                ma60 = EXCLUDED.ma60,
                return_1d = EXCLUDED.return_1d,
                amplitude = EXCLUDED.amplitude,
                volume_ratio = EXCLUDED.volume_ratio,
                amount_ratio = EXCLUDED.amount_ratio,
                volatility_20d = EXCLUDED.volatility_20d,
                turnover_rate = EXCLUDED.turnover_rate,
                pe_ttm = EXCLUDED.pe_ttm,
                pb = EXCLUDED.pb,
                features = EXCLUDED.features,
                updated_at = now()"""
        )
        statement = text(
            f"""
            WITH bars AS (
                SELECT
                    bar.*,
                    lag(close_price) OVER (PARTITION BY index_code ORDER BY trade_date) AS previous_close,
                    row_number() OVER (PARTITION BY index_code ORDER BY trade_date) AS history_days,
                    avg(close_price) OVER (PARTITION BY index_code ORDER BY trade_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS ma5,
                    avg(close_price) OVER (PARTITION BY index_code ORDER BY trade_date ROWS BETWEEN 9 PRECEDING AND CURRENT ROW) AS ma10,
                    avg(close_price) OVER (PARTITION BY index_code ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS ma20,
                    avg(close_price) OVER (PARTITION BY index_code ORDER BY trade_date ROWS BETWEEN 29 PRECEDING AND CURRENT ROW) AS ma30,
                    avg(close_price) OVER (PARTITION BY index_code ORDER BY trade_date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW) AS ma60,
                    avg(volume) OVER (PARTITION BY index_code ORDER BY trade_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING) AS previous_volume_mean_5,
                    avg(amount_yuan) OVER (PARTITION BY index_code ORDER BY trade_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING) AS previous_amount_mean_5
                FROM t_index_bar AS bar
                WHERE bar.index_code = ANY(CAST(:index_codes AS varchar[]))
                  AND bar.trade_date BETWEEN :history_start AND :end_date
            ),
            returns AS (
                SELECT
                    bars.*,
                    CASE WHEN previous_close IS NOT NULL AND previous_close <> 0
                        THEN (close_price - previous_close) / previous_close * 100 END AS close_return
                FROM bars
            ),
            metrics AS (
                SELECT
                    returns.*,
                    stddev_pop(close_return) FILTER (WHERE close_return IS NOT NULL) OVER (
                        PARTITION BY index_code ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                    ) AS volatility_20d
                FROM returns
            )
            INSERT INTO t_index_factor_daily (
                index_code, trade_date, source,
                ma5, ma10, ma20, ma30, ma60,
                return_1d, amplitude, volume_ratio, amount_ratio, volatility_20d,
                turnover_rate, pe_ttm, pb, features, created_at, updated_at
            )
            SELECT
                metrics.index_code,
                metrics.trade_date,
                'system:history_backfill',
                metrics.ma5,
                metrics.ma10,
                metrics.ma20,
                metrics.ma30,
                metrics.ma60,
                metrics.close_return,
                CASE WHEN coalesce(metrics.previous_close, metrics.close_price) <> 0
                    THEN (metrics.high_price - metrics.low_price) / coalesce(metrics.previous_close, metrics.close_price) * 100 END,
                metrics.volume / NULLIF(metrics.previous_volume_mean_5, 0),
                metrics.amount_yuan / NULLIF(metrics.previous_amount_mean_5, 0),
                metrics.volatility_20d,
                basic.turnover_rate,
                basic.pe_ttm,
                basic.pb,
                jsonb_build_object(
                    'history_days', metrics.history_days,
                    'missing_windows', to_jsonb(array_remove(ARRAY[
                        CASE WHEN metrics.history_days < 5 THEN 'ma5' END,
                        CASE WHEN metrics.history_days < 10 THEN 'ma10' END,
                        CASE WHEN metrics.history_days < 20 THEN 'ma20' END,
                        CASE WHEN metrics.history_days < 30 THEN 'ma30' END,
                        CASE WHEN metrics.history_days < 60 THEN 'ma60' END,
                        CASE WHEN metrics.history_days < 21 THEN 'volatility_20d' END,
                        CASE WHEN basic.index_code IS NULL THEN 'index_daily_basic' END
                    ]::text[], NULL)),
                    'source_tables', jsonb_build_array('t_index_bar', 't_index_daily_basic')
                ),
                now(),
                now()
            FROM metrics
            LEFT JOIN t_index_daily_basic AS basic
              ON basic.index_code = metrics.index_code
             AND basic.trade_date = metrics.trade_date
            WHERE metrics.trade_date BETWEEN :start_date AND :end_date
            ON CONFLICT (index_code, trade_date) {conflict_clause}
            RETURNING trade_date
            """
        ).bindparams(bindparam("index_codes", type_=ARRAY(String())))
        rows = (
            await self.session.execute(
                statement,
                {
                    "index_codes": index_codes,
                    "start_date": start_date,
                    "end_date": end_date,
                    "history_start": history_start,
                },
            )
        ).all()
        written: dict[date, int] = {}
        for (trade_date,) in rows:
            written[trade_date] = written.get(trade_date, 0) + 1
        return written

    async def load_sector_factor_inputs(self, *, trade_date: date, lookback_days: int = 30) -> dict:
        start_date = trade_date.fromordinal(trade_date.toordinal() - lookback_days)
        sector_basics = (
            await self.session.execute(
                select(SectorBasic).where(
                    SectorBasic.source.like("tushare:%"),
                    SectorBasic.sector_code.like("ths_%"),
                )
            )
        ).scalars().all()
        sector_codes = [row.sector_code for row in sector_basics]
        if not sector_codes:
            return {
                "sectors": {},
                "bars": {},
                "flows": {},
                "components": {},
                "daily_bars": {},
                "stock_flows": {},
                "limit_up_codes": set(),
            }
        bars = (
            await self.session.execute(
                select(SectorBar)
                .where(SectorBar.sector_code.in_(sector_codes), SectorBar.trade_date.between(start_date, trade_date))
                .order_by(SectorBar.sector_code, SectorBar.trade_date)
            )
        ).scalars().all()
        flows = (
            await self.session.execute(
                select(SectorFundFlowDaily)
                .where(
                    SectorFundFlowDaily.sector_code.in_(sector_codes),
                    SectorFundFlowDaily.trade_date.between(start_date, trade_date),
                )
                .order_by(SectorFundFlowDaily.sector_code, SectorFundFlowDaily.trade_date)
            )
        ).scalars().all()
        components = (
            await self.session.execute(
                select(SectorComponent).where(
                    SectorComponent.sector_code.in_(sector_codes),
                    SectorComponent.source.like("tushare:%"),
                    or_(SectorComponent.end_date.is_(None), SectorComponent.end_date >= trade_date),
                )
            )
        ).scalars().all()
        stock_codes = sorted({row.stock_code for row in components})
        daily_bars = (
            await self.session.execute(
                select(DailyBar).where(DailyBar.stock_code.in_(stock_codes), DailyBar.trade_date == trade_date)
            )
        ).scalars().all() if stock_codes else []
        stock_flows = (
            await self.session.execute(
                select(StockFundFlowDaily).where(
                    StockFundFlowDaily.stock_code.in_(stock_codes),
                    StockFundFlowDaily.trade_date == trade_date,
                )
            )
        ).scalars().all() if stock_codes else []
        limit_rows = (
            await self.session.execute(
                select(LimitEventDaily.stock_code).where(
                    LimitEventDaily.trade_date == trade_date,
                    LimitEventDaily.event_type == "limit_up",
                )
            )
        ).scalars().all()

        grouped_bars: dict[str, list[SectorBar]] = {}
        for row in bars:
            grouped_bars.setdefault(row.sector_code, []).append(row)
        grouped_flows: dict[str, list[SectorFundFlowDaily]] = {}
        for row in flows:
            grouped_flows.setdefault(row.sector_code, []).append(row)
        grouped_components: dict[str, list[str]] = {}
        for row in components:
            grouped_components.setdefault(row.sector_code, []).append(row.stock_code)
        return {
            "sectors": {row.sector_code: row for row in sector_basics},
            "bars": grouped_bars,
            "flows": grouped_flows,
            "components": grouped_components,
            "daily_bars": {row.stock_code: row for row in daily_bars},
            "stock_flows": {row.stock_code: row for row in stock_flows},
            "limit_up_codes": set(limit_rows),
        }

    async def upsert_daily_factors(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        for batch in _chunked(rows, _safe_batch_size(rows)):
            stmt = insert(StockFactorDaily).values(batch)
            await self.session.execute(
                stmt.on_conflict_do_update(
                    index_elements=[StockFactorDaily.stock_code, StockFactorDaily.trade_date, StockFactorDaily.source],
                    set_={
                        "ma5": stmt.excluded.ma5,
                        "ma10": stmt.excluded.ma10,
                        "ma20": stmt.excluded.ma20,
                        "ma30": stmt.excluded.ma30,
                        "ma60": stmt.excluded.ma60,
                        "return_1d": stmt.excluded.return_1d,
                        "amplitude": stmt.excluded.amplitude,
                        "volume_ratio": stmt.excluded.volume_ratio,
                        "amount_ratio": stmt.excluded.amount_ratio,
                        "volatility_20d": stmt.excluded.volatility_20d,
                        "close_position": stmt.excluded.close_position,
                        "features": stmt.excluded.features,
                    },
                )
            )
        return len(rows)

    async def upsert_minute_factors(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        for batch in _chunked(rows, _safe_batch_size(rows)):
            stmt = insert(StockFactorMinute).values(batch)
            await self.session.execute(
                stmt.on_conflict_do_update(
                    index_elements=[
                        StockFactorMinute.stock_code,
                        StockFactorMinute.trade_date,
                        StockFactorMinute.bar_time,
                        StockFactorMinute.source,
                    ],
                    set_={
                        "vwap": stmt.excluded.vwap,
                        "minute_return": stmt.excluded.minute_return,
                        "volume_spike_ratio": stmt.excluded.volume_spike_ratio,
                        "intraday_strength": stmt.excluded.intraday_strength,
                        "features": stmt.excluded.features,
                    },
                )
            )
        return len(rows)

    async def upsert_technical_snapshots(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        for batch in _chunked(rows, _safe_batch_size(rows)):
            stmt = insert(TechnicalIndicatorSnapshot).values(batch)
            await self.session.execute(
                stmt.on_conflict_do_update(
                    index_elements=[
                        TechnicalIndicatorSnapshot.stock_code,
                        TechnicalIndicatorSnapshot.snapshot_time,
                        TechnicalIndicatorSnapshot.source,
                    ],
                    set_={
                        "last_price": stmt.excluded.last_price,
                        "change_pct": stmt.excluded.change_pct,
                        "intraday_strength": stmt.excluded.intraday_strength,
                        "volume_score": stmt.excluded.volume_score,
                        "trend_score": stmt.excluded.trend_score,
                        "factor_payload": stmt.excluded.factor_payload,
                    },
                )
            )
        return len(rows)

    async def upsert_sector_factors(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        for batch in _chunked(rows, _safe_batch_size(rows)):
            stmt = insert(SectorFactorDaily).values(batch)
            await self.session.execute(
                stmt.on_conflict_do_update(
                    index_elements=[SectorFactorDaily.sector_code, SectorFactorDaily.trade_date],
                    set_={
                        "sector_name": stmt.excluded.sector_name,
                        "sector_type": stmt.excluded.sector_type,
                        "source": stmt.excluded.source,
                        "fund_strength": stmt.excluded.fund_strength,
                        "net_inflow_3d": stmt.excluded.net_inflow_3d,
                        "net_inflow_5d": stmt.excluded.net_inflow_5d,
                        "net_inflow_10d": stmt.excluded.net_inflow_10d,
                        "continuous_inflow_days": stmt.excluded.continuous_inflow_days,
                        "rising_stock_count": stmt.excluded.rising_stock_count,
                        "limit_up_stock_count": stmt.excluded.limit_up_stock_count,
                        "average_change_pct": stmt.excluded.average_change_pct,
                        "volatility_20d": stmt.excluded.volatility_20d,
                        "tags": stmt.excluded.tags,
                        "features": stmt.excluded.features,
                    },
                )
            )
        return len(rows)

    async def commit(self) -> None:
        await self.session.commit()
