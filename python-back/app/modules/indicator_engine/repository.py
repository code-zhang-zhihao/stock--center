from __future__ import annotations

from datetime import date, datetime, timedelta
from statistics import pstdev
from zoneinfo import ZoneInfo

from sqlalchemy import Boolean, Date, String, bindparam, case, delete, func, or_, select, text
from sqlalchemy.dialects.postgresql import ARRAY, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.market_data.index_contract import (
    CORE_INDEX_CANONICAL_CODES,
    CSI300_CANONICAL_CODE,
)
from app.modules.market_data.models import (
    DailyBar,
    IndexBar,
    IndexDailyBasic,
    IndexFactorDaily,
    LimitEventDaily,
    MinuteBar,
    SectorBar,
    SectorBasic,
    SectorComponent,
    SectorFactorDaily,
    SectorLeaderDaily,
    SectorFundFlowDaily,
    StockFactorDaily,
    StockFactorMinute,
    StockFundFlowDaily,
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

    async def assemble_stock_daily_factors_final(
        self,
        stock_codes: list[str],
        *,
        trade_date: date,
        history_start: date,
    ) -> int:
        written = await self.assemble_stock_daily_factors_final_between(
            stock_codes,
            start_date=trade_date,
            end_date=trade_date,
            history_start=history_start,
            only_missing=False,
        )
        return written.get(trade_date, 0)

    async def assemble_stock_daily_factors_final_between(
        self,
        stock_codes: list[str],
        *,
        start_date: date,
        end_date: date,
        history_start: date,
        only_missing: bool,
    ) -> dict[date, int]:
        """Assemble local and service groups in the one official factor row.

        Professional columns may already have been written by ``stk_factor_pro``.
        Conflict updates preserve those values and fill only missing core price
        indicators from QFQ prices built with the adjustment-factor history.
        """
        if not stock_codes:
            return {}
        statement = text(
            """
            WITH ranked_bars AS (
                SELECT bar.*,
                       row_number() OVER (
                           PARTITION BY bar.stock_code, bar.trade_date
                           ORDER BY CASE bar.source WHEN 'tushare:daily' THEN 0
                               WHEN 'akshare_qfq' THEN 1 WHEN 'mootdx' THEN 2 ELSE 9 END,
                               bar.updated_at DESC, bar.id DESC
                       ) AS source_rank
                FROM t_daily_bar bar
                WHERE bar.stock_code = ANY(CAST(:stock_codes AS varchar[]))
                  AND bar.trade_date BETWEEN :history_start AND :end_date
            ),
            bars AS (SELECT * FROM ranked_bars WHERE source_rank = 1),
            adjustments AS (
                SELECT DISTINCT ON (stock_code, trade_date)
                    stock_code, trade_date, adj_factor, source
                FROM t_stock_adjust_factor
                WHERE stock_code = ANY(CAST(:stock_codes AS varchar[]))
                  AND trade_date BETWEEN :history_start AND :end_date
                ORDER BY stock_code, trade_date,
                         CASE WHEN source = 'tushare:adj_factor' THEN 0 ELSE 9 END,
                         created_at DESC, id DESC
            ),
            latest_adjustments AS (
                SELECT DISTINCT ON (stock_code)
                    stock_code, adj_factor AS latest_adj_factor
                FROM t_stock_adjust_factor
                WHERE stock_code = ANY(CAST(:stock_codes AS varchar[]))
                ORDER BY stock_code, trade_date DESC,
                         CASE WHEN source = 'tushare:adj_factor' THEN 0 ELSE 9 END,
                         created_at DESC, id DESC
            ),
            normalized AS (
                SELECT bar.*,
                       adj.adj_factor,
                       adj.source AS adjust_source,
                       latest.latest_adj_factor
                FROM bars bar
                LEFT JOIN adjustments adj USING (stock_code, trade_date)
                LEFT JOIN latest_adjustments latest USING (stock_code)
            ),
            qfq AS (
                SELECT normalized.*,
                       open_price * adj_factor / nullif(latest_adj_factor, 0) AS qfq_open,
                       high_price * adj_factor / nullif(latest_adj_factor, 0) AS qfq_high,
                       low_price * adj_factor / nullif(latest_adj_factor, 0) AS qfq_low,
                       close_price * adj_factor / nullif(latest_adj_factor, 0) AS qfq_close,
                       row_number() OVER (PARTITION BY stock_code ORDER BY trade_date) AS history_days
                FROM normalized
            ),
            changes AS (
                SELECT qfq.*,
                       lag(qfq_close, 1) OVER w AS close_1,
                       lag(qfq_close, 3) OVER w AS close_3,
                       lag(qfq_close, 5) OVER w AS close_5,
                       lag(qfq_close, 10) OVER w AS close_10,
                       lag(qfq_close, 20) OVER w AS close_20,
                       lag(qfq_close, 60) OVER w AS close_60,
                       lag(qfq_close, 120) OVER w AS close_120,
                       lag(qfq_close, 250) OVER w AS close_250,
                       lag(qfq_close, 1) OVER w AS pre_close_qfq,
                       avg(qfq_close) OVER (PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS local_ma5,
                       avg(qfq_close) OVER (PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 9 PRECEDING AND CURRENT ROW) AS local_ma10,
                       avg(qfq_close) OVER (PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS local_ma20,
                       avg(qfq_close) OVER (PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 29 PRECEDING AND CURRENT ROW) AS local_ma30,
                       avg(qfq_close) OVER (PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW) AS local_ma60,
                       avg(qfq_close) OVER (PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 89 PRECEDING AND CURRENT ROW) AS local_ma90,
                       avg(qfq_close) OVER (PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 249 PRECEDING AND CURRENT ROW) AS local_ma250,
                       avg(volume_share) OVER (PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING) AS avg_volume_5,
                       avg(volume_share) OVER (PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) AS avg_volume_10,
                       avg(volume_share) OVER (PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) AS avg_volume_20,
                       avg(amount_yuan) OVER (PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS avg_amount_5,
                       avg(amount_yuan) OVER (PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS avg_amount_20,
                       avg(amount_yuan) OVER (PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW) AS avg_amount_60,
                       avg(amount_yuan) OVER (PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING) AS previous_amount_5,
                       avg(amount_yuan) OVER (PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) AS previous_amount_10,
                       avg(amount_yuan) OVER (PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) AS previous_amount_20,
                       max(qfq_high) OVER (PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS high_20,
                       min(qfq_low) OVER (PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS low_20,
                       max(qfq_high) OVER (PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW) AS high_60,
                       min(qfq_low) OVER (PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW) AS low_60,
                       max(qfq_high) OVER (PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 119 PRECEDING AND CURRENT ROW) AS high_120,
                       min(qfq_low) OVER (PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 119 PRECEDING AND CURRENT ROW) AS low_120,
                       max(qfq_high) OVER (PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 249 PRECEDING AND CURRENT ROW) AS high_250,
                       min(qfq_low) OVER (PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 249 PRECEDING AND CURRENT ROW) AS low_250
                FROM qfq
                WINDOW w AS (PARTITION BY stock_code ORDER BY trade_date)
            ),
            returns AS (
                SELECT changes.*,
                       (qfq_close / nullif(close_1, 0) - 1) * 100 AS r1,
                       (qfq_close / nullif(close_3, 0) - 1) * 100 AS r3,
                       (qfq_close / nullif(close_5, 0) - 1) * 100 AS r5,
                       (qfq_close / nullif(close_10, 0) - 1) * 100 AS r10,
                       (qfq_close / nullif(close_20, 0) - 1) * 100 AS r20,
                       (qfq_close / nullif(close_60, 0) - 1) * 100 AS r60,
                       (qfq_close / nullif(close_120, 0) - 1) * 100 AS r120,
                       (qfq_close / nullif(close_250, 0) - 1) * 100 AS r250
                FROM changes
            ),
            metrics AS (
                SELECT returns.*,
                       stddev_pop(r1) OVER (PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS vol5,
                       stddev_pop(r1) OVER (PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 9 PRECEDING AND CURRENT ROW) AS vol10,
                       stddev_pop(r1) OVER (PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS vol20,
                       stddev_pop(r1) OVER (PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW) AS vol60
                FROM returns
            ),
            fund_grouped AS (
                SELECT flow.*,
                       sum(CASE WHEN coalesce(main_net_inflow_yuan, 0) <= 0 THEN 1 ELSE 0 END)
                           OVER (PARTITION BY stock_code ORDER BY trade_date) AS non_positive_group
                FROM t_stock_fund_flow_daily flow
                WHERE flow.stock_code = ANY(CAST(:stock_codes AS varchar[]))
                  AND flow.trade_date BETWEEN (CAST(:start_date AS date) - INTERVAL '45 days') AND :end_date
            ),
            fund AS (
                SELECT fund_grouped.*,
                       sum(main_net_inflow_yuan) OVER (PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) AS net3,
                       sum(main_net_inflow_yuan) OVER (PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS net5,
                       sum(main_net_inflow_yuan) OVER (PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 9 PRECEDING AND CURRENT ROW) AS net10,
                       sum(main_net_inflow_yuan) OVER (PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS net20,
                       count(*) FILTER (WHERE coalesce(main_net_inflow_yuan, 0) > 0)
                           OVER (PARTITION BY stock_code, non_positive_group) AS positive_days
                FROM fund_grouped
            ),
            candidates AS (
                SELECT m.*, basic.id AS basic_id, basic.source AS basic_source_value,
                       basic.turnover_rate_pct, basic.turnover_rate_free_pct,
                       basic.pe, basic.pe_ttm, basic.pb, basic.ps_ttm,
                       basic.dividend_yield_pct, basic.total_share_shares,
                       basic.float_share_shares, basic.free_share_shares,
                       basic.total_market_value_yuan, basic.circulating_market_value_yuan,
                       fund.id AS fund_id, fund.source AS fund_source_value,
                       fund.main_net_inflow_yuan, fund.main_net_ratio,
                       fund.big_order_net_inflow_yuan, fund.super_large_net_inflow_yuan,
                       fund.net3, fund.net5, fund.net10, fund.net20, fund.positive_days
                FROM metrics m
                LEFT JOIN t_stock_daily_basic basic USING (stock_code, trade_date)
                LEFT JOIN fund USING (stock_code, trade_date)
                WHERE m.trade_date BETWEEN :start_date AND :end_date
            )
            INSERT INTO t_stock_factor_daily (
                stock_code, trade_date, price_basis, price_status,
                technical_core_status, technical_extended_status,
                valuation_status, fund_status, quality_flags,
                price_source, basic_source, fund_source, local_source,
                calculation_revision, history_days,
                open_qfq, high_qfq, low_qfq, close_qfq, pre_close_qfq,
                ma5, ma10, ma20, ma30, ma60, ma90, ma250,
                return_1d_pct, return_3d_pct, return_5d_pct, return_10d_pct,
                return_20d_pct, return_60d_pct, return_120d_pct, return_250d_pct,
                amplitude_1d_pct, open_gap_pct, close_position_ratio,
                volume_ratio_5d, volume_ratio_10d, volume_ratio_20d,
                amount_ratio_5d, amount_ratio_10d, amount_ratio_20d,
                average_amount_5d_yuan, average_amount_20d_yuan, average_amount_60d_yuan,
                volatility_5d, volatility_10d, volatility_20d, volatility_60d,
                high_20d, low_20d, high_60d, low_60d,
                high_120d, low_120d, high_250d, low_250d,
                distance_high_20d_ratio, distance_low_20d_ratio,
                distance_high_60d_ratio, distance_low_60d_ratio,
                drawdown_20d_pct, drawdown_60d_pct, drawdown_120d_pct, drawdown_250d_pct,
                turnover_rate_pct, turnover_rate_free_pct, pe, pe_ttm, pb, ps_ttm,
                dividend_yield_pct, total_share_shares, float_share_shares, free_share_shares,
                total_market_value_yuan, circulating_market_value_yuan,
                main_net_inflow_yuan, provider_main_net_ratio, main_net_amount_ratio,
                big_order_net_inflow_yuan, big_order_net_amount_ratio,
                super_large_net_inflow_yuan, super_large_net_amount_ratio,
                main_net_inflow_3d_yuan, main_net_inflow_5d_yuan,
                main_net_inflow_10d_yuan, main_net_inflow_20d_yuan,
                continuous_main_inflow_days, calculated_at, created_at, updated_at
            )
            SELECT
                stock_code, trade_date, 'qfq',
                CASE WHEN qfq_close IS NOT NULL THEN 'ready' ELSE 'missing' END,
                'partial', 'partial',
                CASE WHEN basic_id IS NOT NULL THEN 'ready' ELSE 'missing' END,
                CASE WHEN fund_id IS NOT NULL THEN 'ready' ELSE 'missing' END,
                array_remove(ARRAY[
                    CASE WHEN adj_factor IS NULL THEN 'adjust_factor' END,
                    CASE WHEN basic_id IS NULL THEN 'daily_basic' END,
                    CASE WHEN fund_id IS NULL THEN 'fund_flow' END
                ]::text[], NULL),
                CASE WHEN adj_factor IS NOT NULL THEN 'local:t_daily_bar+adjust_factor' END,
                basic_source_value, fund_source_value, 'system:stock_daily_factor',
                'stock_daily_final_r1', history_days,
                qfq_open, qfq_high, qfq_low, qfq_close, pre_close_qfq,
                local_ma5, local_ma10, local_ma20, local_ma30, local_ma60, local_ma90, local_ma250,
                r1, r3, r5, r10, r20, r60, r120, r250,
                (high_price - low_price) / nullif(coalesce(pre_close_price, close_price), 0) * 100,
                (open_price / nullif(pre_close_price, 0) - 1) * 100,
                (close_price - low_price) / nullif(high_price - low_price, 0),
                volume_share / nullif(avg_volume_5, 0), volume_share / nullif(avg_volume_10, 0),
                volume_share / nullif(avg_volume_20, 0),
                amount_yuan / nullif(previous_amount_5, 0), amount_yuan / nullif(previous_amount_10, 0),
                amount_yuan / nullif(previous_amount_20, 0),
                avg_amount_5, avg_amount_20, avg_amount_60,
                vol5, vol10, vol20, vol60,
                high_20, low_20, high_60, low_60, high_120, low_120, high_250, low_250,
                qfq_close / nullif(high_20, 0) - 1, qfq_close / nullif(low_20, 0) - 1,
                qfq_close / nullif(high_60, 0) - 1, qfq_close / nullif(low_60, 0) - 1,
                (qfq_close / nullif(high_20, 0) - 1) * 100,
                (qfq_close / nullif(high_60, 0) - 1) * 100,
                (qfq_close / nullif(high_120, 0) - 1) * 100,
                (qfq_close / nullif(high_250, 0) - 1) * 100,
                turnover_rate_pct, turnover_rate_free_pct, pe, pe_ttm, pb, ps_ttm,
                dividend_yield_pct, total_share_shares, float_share_shares, free_share_shares,
                total_market_value_yuan, circulating_market_value_yuan,
                main_net_inflow_yuan, main_net_ratio, main_net_inflow_yuan / nullif(amount_yuan, 0),
                big_order_net_inflow_yuan, big_order_net_inflow_yuan / nullif(amount_yuan, 0),
                super_large_net_inflow_yuan, super_large_net_inflow_yuan / nullif(amount_yuan, 0),
                net3, net5, net10, net20, positive_days::integer, now(), now(), now()
            FROM candidates
            WHERE NOT :only_missing OR NOT EXISTS (
                SELECT 1 FROM t_stock_factor_daily existing
                WHERE existing.stock_code = candidates.stock_code
                  AND existing.trade_date = candidates.trade_date
                  AND existing.price_status = 'ready'
                  AND existing.valuation_status = 'ready'
                  AND existing.fund_status = 'ready'
                  AND existing.calculation_revision = 'stock_daily_final_r1'
            )
            ON CONFLICT (stock_code, trade_date) DO UPDATE SET
                price_basis = 'qfq',
                price_status = EXCLUDED.price_status,
                valuation_status = EXCLUDED.valuation_status,
                fund_status = EXCLUDED.fund_status,
                quality_flags = EXCLUDED.quality_flags,
                price_source = coalesce(t_stock_factor_daily.price_source, EXCLUDED.price_source),
                basic_source = EXCLUDED.basic_source,
                fund_source = EXCLUDED.fund_source,
                local_source = EXCLUDED.local_source,
                calculation_revision = EXCLUDED.calculation_revision,
                history_days = EXCLUDED.history_days,
                open_qfq = coalesce(t_stock_factor_daily.open_qfq, EXCLUDED.open_qfq),
                high_qfq = coalesce(t_stock_factor_daily.high_qfq, EXCLUDED.high_qfq),
                low_qfq = coalesce(t_stock_factor_daily.low_qfq, EXCLUDED.low_qfq),
                close_qfq = coalesce(t_stock_factor_daily.close_qfq, EXCLUDED.close_qfq),
                pre_close_qfq = coalesce(t_stock_factor_daily.pre_close_qfq, EXCLUDED.pre_close_qfq),
                ma5 = coalesce(t_stock_factor_daily.ma5, EXCLUDED.ma5),
                ma10 = coalesce(t_stock_factor_daily.ma10, EXCLUDED.ma10),
                ma20 = coalesce(t_stock_factor_daily.ma20, EXCLUDED.ma20),
                ma30 = coalesce(t_stock_factor_daily.ma30, EXCLUDED.ma30),
                ma60 = coalesce(t_stock_factor_daily.ma60, EXCLUDED.ma60),
                ma90 = coalesce(t_stock_factor_daily.ma90, EXCLUDED.ma90),
                ma250 = coalesce(t_stock_factor_daily.ma250, EXCLUDED.ma250),
                return_1d_pct = EXCLUDED.return_1d_pct,
                return_3d_pct = EXCLUDED.return_3d_pct,
                return_5d_pct = EXCLUDED.return_5d_pct,
                return_10d_pct = EXCLUDED.return_10d_pct,
                return_20d_pct = EXCLUDED.return_20d_pct,
                return_60d_pct = EXCLUDED.return_60d_pct,
                return_120d_pct = EXCLUDED.return_120d_pct,
                return_250d_pct = EXCLUDED.return_250d_pct,
                amplitude_1d_pct = EXCLUDED.amplitude_1d_pct,
                open_gap_pct = EXCLUDED.open_gap_pct,
                close_position_ratio = EXCLUDED.close_position_ratio,
                volume_ratio_5d = EXCLUDED.volume_ratio_5d,
                volume_ratio_10d = EXCLUDED.volume_ratio_10d,
                volume_ratio_20d = EXCLUDED.volume_ratio_20d,
                amount_ratio_5d = EXCLUDED.amount_ratio_5d,
                amount_ratio_10d = EXCLUDED.amount_ratio_10d,
                amount_ratio_20d = EXCLUDED.amount_ratio_20d,
                average_amount_5d_yuan = EXCLUDED.average_amount_5d_yuan,
                average_amount_20d_yuan = EXCLUDED.average_amount_20d_yuan,
                average_amount_60d_yuan = EXCLUDED.average_amount_60d_yuan,
                volatility_5d = EXCLUDED.volatility_5d,
                volatility_10d = EXCLUDED.volatility_10d,
                volatility_20d = EXCLUDED.volatility_20d,
                volatility_60d = EXCLUDED.volatility_60d,
                high_20d = EXCLUDED.high_20d, low_20d = EXCLUDED.low_20d,
                high_60d = EXCLUDED.high_60d, low_60d = EXCLUDED.low_60d,
                high_120d = EXCLUDED.high_120d, low_120d = EXCLUDED.low_120d,
                high_250d = EXCLUDED.high_250d, low_250d = EXCLUDED.low_250d,
                distance_high_20d_ratio = EXCLUDED.distance_high_20d_ratio,
                distance_low_20d_ratio = EXCLUDED.distance_low_20d_ratio,
                distance_high_60d_ratio = EXCLUDED.distance_high_60d_ratio,
                distance_low_60d_ratio = EXCLUDED.distance_low_60d_ratio,
                drawdown_20d_pct = EXCLUDED.drawdown_20d_pct,
                drawdown_60d_pct = EXCLUDED.drawdown_60d_pct,
                drawdown_120d_pct = EXCLUDED.drawdown_120d_pct,
                drawdown_250d_pct = EXCLUDED.drawdown_250d_pct,
                turnover_rate_pct = EXCLUDED.turnover_rate_pct,
                turnover_rate_free_pct = EXCLUDED.turnover_rate_free_pct,
                pe = EXCLUDED.pe, pe_ttm = EXCLUDED.pe_ttm, pb = EXCLUDED.pb, ps_ttm = EXCLUDED.ps_ttm,
                dividend_yield_pct = EXCLUDED.dividend_yield_pct,
                total_share_shares = EXCLUDED.total_share_shares,
                float_share_shares = EXCLUDED.float_share_shares,
                free_share_shares = EXCLUDED.free_share_shares,
                total_market_value_yuan = EXCLUDED.total_market_value_yuan,
                circulating_market_value_yuan = EXCLUDED.circulating_market_value_yuan,
                main_net_inflow_yuan = EXCLUDED.main_net_inflow_yuan,
                provider_main_net_ratio = EXCLUDED.provider_main_net_ratio,
                main_net_amount_ratio = EXCLUDED.main_net_amount_ratio,
                big_order_net_inflow_yuan = EXCLUDED.big_order_net_inflow_yuan,
                big_order_net_amount_ratio = EXCLUDED.big_order_net_amount_ratio,
                super_large_net_inflow_yuan = EXCLUDED.super_large_net_inflow_yuan,
                super_large_net_amount_ratio = EXCLUDED.super_large_net_amount_ratio,
                main_net_inflow_3d_yuan = EXCLUDED.main_net_inflow_3d_yuan,
                main_net_inflow_5d_yuan = EXCLUDED.main_net_inflow_5d_yuan,
                main_net_inflow_10d_yuan = EXCLUDED.main_net_inflow_10d_yuan,
                main_net_inflow_20d_yuan = EXCLUDED.main_net_inflow_20d_yuan,
                continuous_main_inflow_days = EXCLUDED.continuous_main_inflow_days,
                calculated_at = now(), updated_at = now()
            RETURNING trade_date
            """
        ).bindparams(
            bindparam("stock_codes", type_=ARRAY(String())),
            bindparam("start_date", type_=Date()),
            bindparam("end_date", type_=Date()),
            bindparam("history_start", type_=Date()),
            bindparam("only_missing", type_=Boolean()),
        )
        rows = (
            await self.session.execute(
                statement,
                {
                    "stock_codes": stock_codes,
                    "start_date": start_date,
                    "end_date": end_date,
                    "history_start": history_start,
                    "only_missing": only_missing,
                },
            )
        ).all()
        result: dict[date, int] = {}
        for (row_date,) in rows:
            result[row_date] = result.get(row_date, 0) + 1
        await self._fill_local_technical_core(
            stock_codes,
            start_date=start_date,
            end_date=end_date,
            history_start=history_start,
        )
        await self._fill_relative_csi300(
            stock_codes,
            start_date=start_date,
            end_date=end_date,
            history_start=history_start,
        )
        return result

    async def rebase_qfq_history_for_adjustment_changes(self, *, trade_date: date) -> int:
        """Re-anchor historical price-dimensional factors after an ex-date.

        The scale is derived from the last stored pre-event QFQ close and its
        BFQ/adjustment facts, rather than blindly applying the adjustment
        ratio.  A repeated run therefore derives a scale of one and is
        idempotent.  Dimensionless indicators and returns are not changed.
        """
        rows = (
            await self.session.execute(
                text(
                    """
                    WITH current_adjustment AS (
                        SELECT DISTINCT ON (stock_code)
                            stock_code, trade_date, adj_factor
                        FROM t_stock_adjust_factor
                        WHERE trade_date = :trade_date
                        ORDER BY stock_code,
                                 CASE WHEN source = 'tushare:adj_factor' THEN 0 ELSE 9 END,
                                 created_at DESC, id DESC
                    ),
                    changed AS (
                        SELECT current.stock_code, current.trade_date,
                               current.adj_factor AS current_factor,
                               previous.adj_factor AS previous_factor
                        FROM current_adjustment current
                        JOIN LATERAL (
                            SELECT adj_factor
                            FROM t_stock_adjust_factor prior
                            WHERE prior.stock_code = current.stock_code
                              AND prior.trade_date < current.trade_date
                            ORDER BY prior.trade_date DESC,
                                     CASE WHEN prior.source = 'tushare:adj_factor' THEN 0 ELSE 9 END,
                                     prior.created_at DESC, prior.id DESC
                            LIMIT 1
                        ) previous ON true
                        WHERE abs(current.adj_factor - previous.adj_factor) > 1e-12
                    ),
                    reference AS (
                        SELECT changed.*, factor.trade_date AS reference_date,
                               factor.close_qfq AS stored_qfq_close,
                               bar.close_price AS bfq_close,
                               reference_adjustment.adj_factor AS reference_factor
                        FROM changed
                        JOIN LATERAL (
                            SELECT stock_code, trade_date, close_qfq
                            FROM t_stock_factor_daily item
                            WHERE item.stock_code = changed.stock_code
                              AND item.trade_date < changed.trade_date
                              AND item.close_qfq IS NOT NULL
                            ORDER BY item.trade_date DESC
                            LIMIT 1
                        ) factor ON true
                        JOIN t_daily_bar bar
                          ON bar.stock_code = factor.stock_code
                         AND bar.trade_date = factor.trade_date
                        JOIN LATERAL (
                            SELECT adj_factor
                            FROM t_stock_adjust_factor item
                            WHERE item.stock_code = changed.stock_code
                              AND item.trade_date <= factor.trade_date
                            ORDER BY item.trade_date DESC,
                                     CASE WHEN item.source = 'tushare:adj_factor' THEN 0 ELSE 9 END,
                                     item.created_at DESC, item.id DESC
                            LIMIT 1
                        ) reference_adjustment ON true
                    ),
                    scales AS (
                        SELECT stock_code, trade_date,
                               (bfq_close * reference_factor / nullif(current_factor, 0))
                                   / nullif(stored_qfq_close, 0) AS scale
                        FROM reference
                    )
                    UPDATE t_stock_factor_daily target
                    SET open_qfq = target.open_qfq * scales.scale,
                        high_qfq = target.high_qfq * scales.scale,
                        low_qfq = target.low_qfq * scales.scale,
                        close_qfq = target.close_qfq * scales.scale,
                        pre_close_qfq = target.pre_close_qfq * scales.scale,
                        ma5 = target.ma5 * scales.scale,
                        ma10 = target.ma10 * scales.scale,
                        ma20 = target.ma20 * scales.scale,
                        ma30 = target.ma30 * scales.scale,
                        ma60 = target.ma60 * scales.scale,
                        ma90 = target.ma90 * scales.scale,
                        ma250 = target.ma250 * scales.scale,
                        ema5 = target.ema5 * scales.scale,
                        ema10 = target.ema10 * scales.scale,
                        ema20 = target.ema20 * scales.scale,
                        ema30 = target.ema30 * scales.scale,
                        ema60 = target.ema60 * scales.scale,
                        ema90 = target.ema90 * scales.scale,
                        ema250 = target.ema250 * scales.scale,
                        macd = target.macd * scales.scale,
                        macd_dif = target.macd_dif * scales.scale,
                        macd_dea = target.macd_dea * scales.scale,
                        boll_upper = target.boll_upper * scales.scale,
                        boll_mid = target.boll_mid * scales.scale,
                        boll_lower = target.boll_lower * scales.scale,
                        atr = target.atr * scales.scale,
                        bbi = target.bbi * scales.scale,
                        mtm = target.mtm * scales.scale,
                        mtmma = target.mtmma * scales.scale,
                        asi = target.asi * scales.scale,
                        asit = target.asit * scales.scale,
                        dfma_dif = target.dfma_dif * scales.scale,
                        dfma_difma = target.dfma_difma * scales.scale,
                        dpo = target.dpo * scales.scale,
                        madpo = target.madpo * scales.scale,
                        emv = target.emv * scales.scale,
                        maemv = target.maemv * scales.scale,
                        expma12 = target.expma12 * scales.scale,
                        expma50 = target.expma50 * scales.scale,
                        keltner_lower = target.keltner_lower * scales.scale,
                        keltner_mid = target.keltner_mid * scales.scale,
                        keltner_upper = target.keltner_upper * scales.scale,
                        taq_lower = target.taq_lower * scales.scale,
                        taq_mid = target.taq_mid * scales.scale,
                        taq_upper = target.taq_upper * scales.scale,
                        xsii_td1 = target.xsii_td1 * scales.scale,
                        xsii_td2 = target.xsii_td2 * scales.scale,
                        xsii_td3 = target.xsii_td3 * scales.scale,
                        xsii_td4 = target.xsii_td4 * scales.scale,
                        high_20d = target.high_20d * scales.scale,
                        low_20d = target.low_20d * scales.scale,
                        high_60d = target.high_60d * scales.scale,
                        low_60d = target.low_60d * scales.scale,
                        high_120d = target.high_120d * scales.scale,
                        low_120d = target.low_120d * scales.scale,
                        high_250d = target.high_250d * scales.scale,
                        low_250d = target.low_250d * scales.scale,
                        price_source = CASE
                            WHEN coalesce(target.price_source, '') LIKE '%system:qfq_rebase%'
                                THEN target.price_source
                            ELSE concat_ws('+', nullif(target.price_source, ''), 'system:qfq_rebase')
                        END,
                        technical_source = CASE
                            WHEN coalesce(target.technical_source, '') LIKE '%system:qfq_rebase%'
                                THEN target.technical_source
                            ELSE concat_ws('+', nullif(target.technical_source, ''), 'system:qfq_rebase')
                        END,
                        quality_flags = array_append(
                            array_remove(coalesce(target.quality_flags, ARRAY[]::text[]), 'qfq_basis_rebased'),
                            'qfq_basis_rebased'
                        ),
                        calculation_revision = 'stock_daily_final_r1',
                        calculated_at = now(),
                        updated_at = now()
                    FROM scales
                    WHERE target.stock_code = scales.stock_code
                      AND target.trade_date < scales.trade_date
                      AND scales.scale BETWEEN 0.01 AND 100
                      AND abs(scales.scale - 1) > 1e-8
                    RETURNING target.id
                    """
                ),
                {"trade_date": trade_date},
            )
        ).all()
        return len(rows)

    async def _fill_local_technical_core(
        self,
        stock_codes: list[str],
        *,
        start_date: date,
        end_date: date,
        history_start: date,
    ) -> int:
        """Fill only missing strategy-core indicators from a local QFQ series.

        The provider remains authoritative.  Existing provider values are
        never overwritten; this path makes a temporary ``stk_factor_pro``
        delay non-blocking for strategies that only need the core indicators.
        """
        if not stock_codes:
            return 0
        qfq_rows = (
            await self.session.execute(
                text(
                    """
                    WITH bars AS (
                        SELECT DISTINCT ON (bar.stock_code, bar.trade_date)
                            bar.stock_code, bar.trade_date, bar.open_price,
                            bar.high_price, bar.low_price, bar.close_price
                        FROM t_daily_bar bar
                        WHERE bar.stock_code = ANY(CAST(:stock_codes AS varchar[]))
                          AND bar.trade_date BETWEEN :history_start AND :end_date
                        ORDER BY bar.stock_code, bar.trade_date,
                                 CASE bar.source WHEN 'tushare:daily' THEN 0
                                     WHEN 'akshare_qfq' THEN 1 WHEN 'mootdx' THEN 2 ELSE 9 END,
                                 bar.updated_at DESC, bar.id DESC
                    ),
                    adjustments AS (
                        SELECT DISTINCT ON (stock_code, trade_date)
                            stock_code, trade_date, adj_factor
                        FROM t_stock_adjust_factor
                        WHERE stock_code = ANY(CAST(:stock_codes AS varchar[]))
                          AND trade_date BETWEEN :history_start AND :end_date
                        ORDER BY stock_code, trade_date,
                                 CASE WHEN source = 'tushare:adj_factor' THEN 0 ELSE 9 END,
                                 created_at DESC, id DESC
                    ),
                    latest_adjustments AS (
                        SELECT DISTINCT ON (stock_code)
                            stock_code, adj_factor AS latest_adj_factor
                        FROM t_stock_adjust_factor
                        WHERE stock_code = ANY(CAST(:stock_codes AS varchar[]))
                        ORDER BY stock_code, trade_date DESC,
                                 CASE WHEN source = 'tushare:adj_factor' THEN 0 ELSE 9 END,
                                 created_at DESC, id DESC
                    ),
                    series AS (
                        SELECT bars.*, adjustments.adj_factor, latest.latest_adj_factor
                        FROM bars
                        LEFT JOIN adjustments USING (stock_code, trade_date)
                        LEFT JOIN latest_adjustments latest USING (stock_code)
                    )
                    SELECT stock_code, trade_date,
                           open_price * adj_factor / nullif(latest_adj_factor, 0) AS open_qfq,
                           high_price * adj_factor / nullif(latest_adj_factor, 0) AS high_qfq,
                           low_price * adj_factor / nullif(latest_adj_factor, 0) AS low_qfq,
                           close_price * adj_factor / nullif(latest_adj_factor, 0) AS close_qfq
                    FROM series
                    WHERE adj_factor IS NOT NULL
                    ORDER BY stock_code, trade_date
                    """
                ).bindparams(bindparam("stock_codes", type_=ARRAY(String()))),
                {
                    "stock_codes": stock_codes,
                    "history_start": history_start,
                    "end_date": end_date,
                },
            )
        ).mappings().all()
        current_rows = (
            await self.session.execute(
                select(StockFactorDaily).where(
                    StockFactorDaily.stock_code.in_(stock_codes),
                    StockFactorDaily.trade_date.between(start_date, end_date),
                )
            )
        ).scalars().all()
        current_by_key = {(row.stock_code, row.trade_date): row for row in current_rows}
        by_stock: dict[str, list[dict]] = {}
        for raw in qfq_rows:
            if raw["close_qfq"] is not None:
                by_stock.setdefault(str(raw["stock_code"]), []).append(dict(raw))

        fallback_rows: list[dict] = []
        for stock_code, series in by_stock.items():
            closes: list[float] = []
            highs: list[float] = []
            lows: list[float] = []
            gains: list[float] = []
            losses: list[float] = []
            ema_values = {period: None for period in (5, 10, 12, 20, 26, 30, 60, 90, 250)}
            dea = None
            k_value = d_value = 50.0
            previous_close = None
            true_ranges: list[float] = []
            for item in series:
                close = float(item["close_qfq"])
                high = float(item["high_qfq"] or close)
                low = float(item["low_qfq"] or close)
                closes.append(close)
                highs.append(high)
                lows.append(low)
                change = 0.0 if previous_close is None else close - previous_close
                gains.append(max(change, 0.0))
                losses.append(max(-change, 0.0))
                true_ranges.append(
                    high - low if previous_close is None else max(high - low, abs(high - previous_close), abs(low - previous_close))
                )
                for period in ema_values:
                    previous = ema_values[period]
                    alpha = 2.0 / (period + 1)
                    ema_values[period] = close if previous is None else close * alpha + previous * (1 - alpha)
                dif = float(ema_values[12]) - float(ema_values[26])
                dea = dif if dea is None else dif * (2.0 / 10.0) + dea * (8.0 / 10.0)
                macd = 2 * (dif - dea)
                high9 = max(highs[-9:])
                low9 = min(lows[-9:])
                rsv = 50.0 if high9 == low9 else (close - low9) / (high9 - low9) * 100
                k_value = k_value * 2 / 3 + rsv / 3
                d_value = d_value * 2 / 3 + k_value / 3
                j_value = 3 * k_value - 2 * d_value

                if item["trade_date"] < start_date or item["trade_date"] > end_date:
                    previous_close = close
                    continue
                current = current_by_key.get((stock_code, item["trade_date"]))
                if current is None:
                    previous_close = close
                    continue
                needs_core_fallback = current.technical_core_status != "ready"
                needs_rsi14 = current.rsi14 is None
                if not needs_core_fallback and not needs_rsi14:
                    previous_close = close
                    continue
                middle = sum(closes[-20:]) / len(closes[-20:])
                variance = sum((value - middle) ** 2 for value in closes[-20:]) / len(closes[-20:])
                boll_std = variance ** 0.5

                def rsi(period: int) -> float:
                    avg_gain = sum(gains[-period:]) / len(gains[-period:])
                    avg_loss = sum(losses[-period:]) / len(losses[-period:])
                    if avg_loss == 0:
                        return 100.0 if avg_gain > 0 else 50.0
                    rs = avg_gain / avg_loss
                    return 100 - 100 / (1 + rs)

                flag_set = set(current.quality_flags or [])
                if needs_core_fallback:
                    # The group is ready after this local rebuild. Keep a
                    # provenance flag, not a stale "technical_core missing"
                    # flag that would contradict the typed status column.
                    flag_set.discard("technical_core")
                    flag_set.add("technical_pro_missing_local_core_fallback")
                flags = sorted(flag_set)
                if needs_core_fallback:
                    technical_source = (
                        "tushare:stk_factor_pro+local:qfq_core"
                        if current.technical_source == "tushare:stk_factor_pro"
                        else "local:t_daily_bar+adjust_factor"
                    )
                else:
                    technical_source = "tushare:stk_factor_pro+local:rsi14"
                fallback_rows.append(
                    {
                        "stock_code": stock_code,
                        "trade_date": item["trade_date"],
                        "price_basis": "qfq",
                        "technical_core_status": "ready",
                        "technical_extended_status": current.technical_extended_status or "missing",
                        "technical_source": technical_source,
                        "quality_flags": flags,
                        "ema5": ema_values[5], "ema10": ema_values[10], "ema20": ema_values[20],
                        "ema30": ema_values[30], "ema60": ema_values[60], "ema90": ema_values[90],
                        "ema250": ema_values[250],
                        "macd": macd, "macd_dif": dif, "macd_dea": dea,
                        "kdj_k": k_value, "kdj_d": d_value, "kdj_j": j_value,
                        "rsi6": rsi(6), "rsi12": rsi(12), "rsi24": rsi(24), "rsi14": rsi(14),
                        "boll_mid": middle, "boll_upper": middle + 2 * boll_std,
                        "boll_lower": middle - 2 * boll_std,
                        "atr": sum(true_ranges[-14:]) / len(true_ranges[-14:]),
                        "calculation_revision": "stock_daily_final_r1",
                        "calculated_at": datetime.now(ZoneInfo("Asia/Shanghai")),
                    }
                )
                previous_close = close

        if not fallback_rows:
            return 0
        update_columns = (
            "ema5", "ema10", "ema20", "ema30", "ema60", "ema90", "ema250",
            "macd", "macd_dif", "macd_dea", "kdj_k", "kdj_d", "kdj_j",
            "rsi6", "rsi12", "rsi24", "rsi14", "boll_mid", "boll_upper", "boll_lower", "atr",
        )
        for batch in _chunked(fallback_rows, _safe_batch_size(fallback_rows)):
            stmt = insert(StockFactorDaily).values(batch)
            values = {name: func.coalesce(getattr(StockFactorDaily, name), stmt.excluded[name]) for name in update_columns}
            values.update(
                {
                    "technical_core_status": "ready",
                    "technical_source": stmt.excluded.technical_source,
                    "quality_flags": stmt.excluded.quality_flags,
                    "calculation_revision": stmt.excluded.calculation_revision,
                    "calculated_at": func.now(),
                    "updated_at": func.now(),
                }
            )
            await self.session.execute(
                stmt.on_conflict_do_update(
                    index_elements=[StockFactorDaily.stock_code, StockFactorDaily.trade_date],
                    set_=values,
                )
            )
        return len(fallback_rows)

    async def _fill_relative_csi300(
        self,
        stock_codes: list[str],
        *,
        start_date: date,
        end_date: date,
        history_start: date,
    ) -> int:
        """Fill typed relative-strength columns against the settled CSI 300 close."""
        if not stock_codes:
            return 0
        result = await self.session.execute(
            text(
                """
                WITH index_returns AS (
                    SELECT trade_date, close_price,
                           (close_price / nullif(lag(close_price, 5) OVER (ORDER BY trade_date), 0) - 1) * 100 AS return5,
                           (close_price / nullif(lag(close_price, 20) OVER (ORDER BY trade_date), 0) - 1) * 100 AS return20,
                           (close_price / nullif(lag(close_price, 60) OVER (ORDER BY trade_date), 0) - 1) * 100 AS return60
                    FROM t_index_bar
                    WHERE index_code = :csi300_code
                      AND trade_date BETWEEN :history_start AND :end_date
                )
                UPDATE t_stock_factor_daily factor
                SET relative_csi300_5d_pct = factor.return_5d_pct - benchmark.return5,
                    relative_csi300_20d_pct = factor.return_20d_pct - benchmark.return20,
                    relative_csi300_60d_pct = factor.return_60d_pct - benchmark.return60,
                    calculated_at = now(), updated_at = now()
                FROM index_returns benchmark
                WHERE factor.trade_date = benchmark.trade_date
                  AND factor.stock_code = ANY(CAST(:stock_codes AS varchar[]))
                  AND factor.trade_date BETWEEN :start_date AND :end_date
                RETURNING factor.trade_date
                """
            ).bindparams(bindparam("stock_codes", type_=ARRAY(String()))),
            {
                "stock_codes": stock_codes,
                "csi300_code": CSI300_CANONICAL_CODE,
                "start_date": start_date,
                "end_date": end_date,
                "history_start": history_start,
            },
        )
        return len(result.all())

    async def refresh_stock_daily_final_percentiles(
        self,
        *,
        start_date: date,
        end_date: date,
    ) -> dict[date, int]:
        """Refresh all cross-sectional ranks once after stock batches finish."""
        rows = (
            await self.session.execute(
                text(
                    """
                    WITH ranked AS (
                        SELECT factor.stock_code, factor.trade_date,
                            cume_dist() OVER (PARTITION BY factor.trade_date ORDER BY factor.return_1d_pct) * 100 AS return_p1,
                            cume_dist() OVER (PARTITION BY factor.trade_date ORDER BY factor.return_5d_pct) * 100 AS return_p5,
                            cume_dist() OVER (PARTITION BY factor.trade_date ORDER BY factor.return_20d_pct) * 100 AS return_p20,
                            cume_dist() OVER (PARTITION BY factor.trade_date ORDER BY bar.amount_yuan) * 100 AS amount_p,
                            cume_dist() OVER (PARTITION BY factor.trade_date ORDER BY factor.turnover_rate_pct) * 100 AS turnover_p,
                            cume_dist() OVER (PARTITION BY factor.trade_date ORDER BY factor.main_net_inflow_yuan) * 100 AS fund_p
                        FROM t_stock_factor_daily factor
                        LEFT JOIN t_daily_bar bar USING (stock_code, trade_date)
                        WHERE factor.trade_date BETWEEN :start_date AND :end_date
                    )
                    UPDATE t_stock_factor_daily factor
                    SET return_percentile_1d = ranked.return_p1,
                        return_percentile_5d = ranked.return_p5,
                        return_percentile_20d = ranked.return_p20,
                        amount_percentile = ranked.amount_p,
                        turnover_percentile = ranked.turnover_p,
                        main_net_inflow_percentile = ranked.fund_p,
                        calculated_at = now(), updated_at = now()
                    FROM ranked
                    WHERE factor.stock_code = ranked.stock_code
                      AND factor.trade_date = ranked.trade_date
                    RETURNING factor.trade_date
                    """
                ),
                {"start_date": start_date, "end_date": end_date},
            )
        ).all()
        updated: dict[date, int] = {}
        for (row_date,) in rows:
            updated[row_date] = updated.get(row_date, 0) + 1
        return updated

    async def load_stock_daily_ready_keys_between(
        self,
        stock_codes: list[str],
        *,
        start_date: date,
        end_date: date,
    ) -> set[tuple[str, date]]:
        if not stock_codes:
            return set()
        rows = await self.session.execute(
            text(
                """
                SELECT stock_code, trade_date
                FROM t_stock_factor_daily
                WHERE stock_code = ANY(CAST(:stock_codes AS varchar[]))
                  AND trade_date BETWEEN :start_date AND :end_date
                  AND price_status = 'ready'
                  AND valuation_status = 'ready'
                  AND fund_status = 'ready'
                  AND calculation_revision = 'stock_daily_final_r1'
                """
            ).bindparams(bindparam("stock_codes", type_=ARRAY(String()))),
            {"stock_codes": stock_codes, "start_date": start_date, "end_date": end_date},
        )
        return {(stock_code, row_date) for stock_code, row_date in rows.all()}

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
                    lag(minute.price, 1) OVER (
                        PARTITION BY minute.stock_code, minute.trade_date
                        ORDER BY minute.bar_time, minute.id
                    ) AS price_1m_ago,
                    lag(minute.price, 5) OVER (
                        PARTITION BY minute.stock_code, minute.trade_date
                        ORDER BY minute.bar_time, minute.id
                    ) AS price_5m_ago,
                    lag(minute.price, 15) OVER (
                        PARTITION BY minute.stock_code, minute.trade_date
                        ORDER BY minute.bar_time, minute.id
                    ) AS price_15m_ago,
                    avg(minute.price) OVER (
                        PARTITION BY minute.stock_code, minute.trade_date
                        ORDER BY minute.bar_time, minute.id ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
                    ) AS ma5,
                    avg(minute.price) OVER (
                        PARTITION BY minute.stock_code, minute.trade_date
                        ORDER BY minute.bar_time, minute.id ROWS BETWEEN 9 PRECEDING AND CURRENT ROW
                    ) AS ma10,
                    avg(minute.price) OVER (
                        PARTITION BY minute.stock_code, minute.trade_date
                        ORDER BY minute.bar_time, minute.id ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                    ) AS ma20,
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
                    vwap, return_1m_pct, return_5m_pct, return_15m_pct,
                    ma5, ma10, ma20, volume_ratio_20m, intraday_position_ratio,
                    created_at
                )
                SELECT
                    stock_code,
                    trade_date,
                    bar_time,
                    'system:daily_close',
                    cumulative_amount / NULLIF(cumulative_amount_volume * 100, 0),
                    (price - price_1m_ago) / NULLIF(price_1m_ago, 0) * 100,
                    (price - price_5m_ago) / NULLIF(price_5m_ago, 0) * 100,
                    (price - price_15m_ago) / NULLIF(price_15m_ago, 0) * 100,
                    ma5,
                    ma10,
                    ma20,
                    CASE
                        WHEN previous_volume_count_20 = 20
                        THEN volume_hand / NULLIF(previous_volume_mean_20, 0)
                    END,
                    (price - running_low) / NULLIF(running_high - running_low, 0),
                    now()
                FROM minute_metrics
                WHERE price IS NOT NULL
                ON CONFLICT (stock_code, trade_date, bar_time, source)
                DO UPDATE SET
                    vwap = EXCLUDED.vwap,
                    return_1m_pct = EXCLUDED.return_1m_pct,
                    return_5m_pct = EXCLUDED.return_5m_pct,
                    return_15m_pct = EXCLUDED.return_15m_pct,
                    ma5 = EXCLUDED.ma5,
                    ma10 = EXCLUDED.ma10,
                    ma20 = EXCLUDED.ma20,
                    volume_ratio_20m = EXCLUDED.volume_ratio_20m,
                    intraday_position_ratio = EXCLUDED.intraday_position_ratio
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

    async def list_sector_factor_trade_dates_between(
        self,
        *,
        start_date: date,
        end_date: date,
    ) -> list[date]:
        """Return dates backed by canonical THS sector bars, not calendar-only dates."""
        rows = await self.session.execute(
            select(SectorBar.trade_date)
            .join(SectorBasic, SectorBasic.sector_code == SectorBar.sector_code)
            .where(
                SectorBar.trade_date.between(start_date, end_date),
                SectorBasic.source.like("tushare:%"),
                SectorBasic.sector_code.like("ths_%"),
            )
            .distinct()
            .order_by(SectorBar.trade_date)
        )
        return list(rows.scalars().all())

    async def clear_sector_factor_rows_between(self, *, start_date: date, end_date: date) -> int:
        leader_result = await self.session.execute(
            delete(SectorLeaderDaily).where(SectorLeaderDaily.trade_date.between(start_date, end_date))
        )
        factor_result = await self.session.execute(
            delete(SectorFactorDaily).where(SectorFactorDaily.trade_date.between(start_date, end_date))
        )
        return int(leader_result.rowcount or 0) + int(factor_result.rowcount or 0)

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
        normalized_rows: list[dict] = []
        for source_row in rows:
            row = dict(source_row)
            features = row.pop("features", {}) or {}
            row["local_source"] = row.pop("source", "system:daily_close")
            row["return_1d_pct"] = row.pop("return_1d", None)
            row["amplitude_1d_pct"] = row.pop("amplitude", None)
            row["volume_ratio_5d"] = row.pop("volume_ratio", None)
            row["amount_ratio_5d"] = row.pop("amount_ratio", None)
            row["close_position_ratio"] = row.pop("close_position", None)
            row["history_days"] = int(features.get("history_days") or row.get("history_days") or 0)
            row["calculation_revision"] = "stock_daily_final_r1"
            normalized_rows.append(row)
        rows = normalized_rows
        for batch in _chunked(rows, _safe_batch_size(rows)):
            stmt = insert(StockFactorDaily).values(batch)
            await self.session.execute(
                stmt.on_conflict_do_update(
                    index_elements=[StockFactorDaily.stock_code, StockFactorDaily.trade_date],
                    set_={
                        "ma5": stmt.excluded.ma5,
                        "ma10": stmt.excluded.ma10,
                        "ma20": stmt.excluded.ma20,
                        "ma30": stmt.excluded.ma30,
                        "ma60": stmt.excluded.ma60,
                        "return_1d_pct": stmt.excluded.return_1d_pct,
                        "amplitude_1d_pct": stmt.excluded.amplitude_1d_pct,
                        "volume_ratio_5d": stmt.excluded.volume_ratio_5d,
                        "amount_ratio_5d": stmt.excluded.amount_ratio_5d,
                        "volatility_20d": stmt.excluded.volatility_20d,
                        "close_position_ratio": stmt.excluded.close_position_ratio,
                        "history_days": stmt.excluded.history_days,
                        "local_source": stmt.excluded.local_source,
                        "calculated_at": func.now(),
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
                        "return_1m_pct": stmt.excluded.return_1m_pct,
                        "return_5m_pct": stmt.excluded.return_5m_pct,
                        "return_15m_pct": stmt.excluded.return_15m_pct,
                        "ma5": stmt.excluded.ma5,
                        "ma10": stmt.excluded.ma10,
                        "ma20": stmt.excluded.ma20,
                        "volume_ratio_20m": stmt.excluded.volume_ratio_20m,
                        "intraday_position_ratio": stmt.excluded.intraday_position_ratio,
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
                        "main_net_inflow_yuan": stmt.excluded.main_net_inflow_yuan,
                        "main_net_inflow_3d_yuan": stmt.excluded.main_net_inflow_3d_yuan,
                        "main_net_inflow_5d_yuan": stmt.excluded.main_net_inflow_5d_yuan,
                        "main_net_inflow_10d_yuan": stmt.excluded.main_net_inflow_10d_yuan,
                        "continuous_inflow_days": stmt.excluded.continuous_inflow_days,
                        "component_count": stmt.excluded.component_count,
                        "component_coverage_ratio": stmt.excluded.component_coverage_ratio,
                        "rising_stock_count": stmt.excluded.rising_stock_count,
                        "falling_stock_count": stmt.excluded.falling_stock_count,
                        "flat_stock_count": stmt.excluded.flat_stock_count,
                        "limit_up_stock_count": stmt.excluded.limit_up_stock_count,
                        "average_change_pct": stmt.excluded.average_change_pct,
                        "volatility_20d": stmt.excluded.volatility_20d,
                        "quality_flags": stmt.excluded.quality_flags,
                        "calculation_revision": stmt.excluded.calculation_revision,
                    },
                )
            )
        return len(rows)

    async def assemble_sector_daily_factors_final_between(
        self,
        *,
        start_date: date,
        end_date: date,
        history_start: date,
    ) -> dict[date, int]:
        """Assemble a bounded window of typed sector factors in one PostgreSQL pass."""
        statement = text(
            """
            WITH eligible_sectors AS (
                SELECT sector_code, sector_name, sector_type
                FROM t_sector_basic
                WHERE source LIKE 'tushare:%'
                  AND sector_code LIKE 'ths_%'
            ),
            target_keys AS (
                SELECT bar.sector_code, bar.trade_date
                FROM t_sector_bar bar
                JOIN eligible_sectors sector USING (sector_code)
                WHERE bar.trade_date BETWEEN :start_date AND :end_date
                UNION
                SELECT flow.sector_code, flow.trade_date
                FROM t_sector_fund_flow_daily flow
                JOIN eligible_sectors sector USING (sector_code)
                WHERE flow.trade_date BETWEEN :start_date AND :end_date
            ),
            bar_history AS (
                SELECT bar.*,
                       avg(bar.close_price) OVER sector_rows_5 AS ma5,
                       avg(bar.close_price) OVER sector_rows_10 AS ma10,
                       avg(bar.close_price) OVER sector_rows_20 AS ma20,
                       avg(bar.close_price) OVER sector_rows_60 AS ma60,
                       lag(bar.close_price, 1) OVER sector_order AS close1,
                       lag(bar.close_price, 5) OVER sector_order AS close5,
                       lag(bar.close_price, 20) OVER sector_order AS close20,
                       max(bar.close_price) OVER sector_rows_20 AS high20,
                       CASE
                           WHEN count(bar.change_pct) OVER sector_rows_20 >= 2
                           THEN stddev_pop(bar.change_pct) OVER sector_rows_20
                       END AS volatility20
                FROM t_sector_bar bar
                JOIN eligible_sectors sector USING (sector_code)
                WHERE bar.trade_date BETWEEN :history_start AND :end_date
                WINDOW
                    sector_order AS (PARTITION BY bar.sector_code ORDER BY bar.trade_date),
                    sector_rows_5 AS (
                        PARTITION BY bar.sector_code ORDER BY bar.trade_date
                        ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
                    ),
                    sector_rows_10 AS (
                        PARTITION BY bar.sector_code ORDER BY bar.trade_date
                        ROWS BETWEEN 9 PRECEDING AND CURRENT ROW
                    ),
                    sector_rows_20 AS (
                        PARTITION BY bar.sector_code ORDER BY bar.trade_date
                        ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                    ),
                    sector_rows_60 AS (
                        PARTITION BY bar.sector_code ORDER BY bar.trade_date
                        ROWS BETWEEN 59 PRECEDING AND CURRENT ROW
                    )
            ),
            flow_marked AS (
                SELECT flow.*,
                       sum(
                           CASE WHEN coalesce(flow.main_net_inflow_yuan, 0) > 0 THEN 0 ELSE 1 END
                       ) OVER (
                           PARTITION BY flow.sector_code ORDER BY flow.trade_date
                           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                       ) AS positive_group
                FROM t_sector_fund_flow_daily flow
                JOIN eligible_sectors sector USING (sector_code)
                WHERE flow.trade_date BETWEEN :history_start AND :end_date
            ),
            flow_history AS (
                SELECT flow.*,
                       sum(flow.main_net_inflow_yuan) OVER (
                           PARTITION BY flow.sector_code ORDER BY flow.trade_date
                           ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
                       ) AS net_3d,
                       sum(flow.main_net_inflow_yuan) OVER (
                           PARTITION BY flow.sector_code ORDER BY flow.trade_date
                           ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
                       ) AS net_5d,
                       sum(flow.main_net_inflow_yuan) OVER (
                           PARTITION BY flow.sector_code ORDER BY flow.trade_date
                           ROWS BETWEEN 9 PRECEDING AND CURRENT ROW
                       ) AS net_10d,
                       CASE
                           WHEN coalesce(flow.main_net_inflow_yuan, 0) > 0
                           THEN count(*) FILTER (
                               WHERE coalesce(flow.main_net_inflow_yuan, 0) > 0
                           ) OVER (
                               PARTITION BY flow.sector_code, flow.positive_group
                               ORDER BY flow.trade_date
                               ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                           )
                           ELSE 0
                       END AS continuous_days
                FROM flow_marked flow
            ),
            active_components AS (
                SELECT DISTINCT component.sector_code, component.stock_code,
                                component.start_date, component.end_date
                FROM t_sector_component component
                JOIN eligible_sectors sector USING (sector_code)
                JOIN t_stock stock ON stock.stock_code = component.stock_code
                WHERE stock.status = 'active'
                  AND stock.is_st IS FALSE
                  AND stock.exchange IN ('SH','SZ','SSE','SZSE')
            ),
            stock_events AS (
                SELECT event.stock_code,
                       event.trade_date,
                       bool_or(event.event_type = 'limit_up') AS is_limit_up,
                       bool_or(event.event_type = 'limit_down') AS is_limit_down,
                       bool_or(event.event_type = 'limit_break') AS is_limit_break,
                       max(event.limit_price) FILTER (WHERE event.event_type = 'limit_up') AS limit_up_price,
                       min(coalesce(event.open_count, 0)) FILTER (WHERE event.event_type = 'limit_up') AS open_count
                FROM t_limit_event_daily event
                WHERE event.trade_date BETWEEN :start_date AND :end_date
                  AND event.event_type IN ('limit_up', 'limit_down', 'limit_break')
                GROUP BY event.stock_code, event.trade_date
            ),
            member_stats AS (
                SELECT target.sector_code,
                       target.trade_date,
                       count(component.stock_code) AS component_count,
                       count(daily.stock_code) AS covered_count,
                       count(*) FILTER (WHERE daily.change_pct > 0) AS rising_count,
                       count(*) FILTER (WHERE daily.change_pct < 0) AS falling_count,
                       count(*) FILTER (WHERE daily.change_pct = 0) AS flat_count,
                       avg(daily.change_pct) AS average_change,
                       percentile_cont(0.5) WITHIN GROUP (ORDER BY daily.change_pct) AS median_change,
                       avg((factor.close_qfq >= factor.ma20)::int)
                           FILTER (WHERE factor.close_qfq IS NOT NULL AND factor.ma20 IS NOT NULL) AS above_ma20,
                       avg((factor.close_qfq >= factor.ma60)::int)
                           FILTER (WHERE factor.close_qfq IS NOT NULL AND factor.ma60 IS NOT NULL) AS above_ma60,
                       count(*) FILTER (
                           WHERE factor.close_qfq IS NOT NULL AND factor.high_20d IS NOT NULL
                             AND factor.close_qfq >= factor.high_20d
                       ) AS high20_count,
                       count(*) FILTER (
                           WHERE factor.close_qfq IS NOT NULL AND factor.low_20d IS NOT NULL
                             AND factor.close_qfq <= factor.low_20d
                       ) AS low20_count,
                       count(*) FILTER (
                           WHERE factor.close_qfq IS NOT NULL AND factor.high_60d IS NOT NULL
                             AND factor.close_qfq >= factor.high_60d
                       ) AS high60_count,
                       count(*) FILTER (
                           WHERE factor.close_qfq IS NOT NULL AND factor.low_60d IS NOT NULL
                             AND factor.close_qfq <= factor.low_60d
                       ) AS low60_count,
                       count(*) FILTER (WHERE event.is_limit_up) AS limit_up_count,
                       count(*) FILTER (WHERE event.is_limit_down) AS limit_down_count,
                       count(*) FILTER (WHERE event.is_limit_break) AS break_count,
                       count(*) FILTER (
                           WHERE event.is_limit_up
                             AND daily.open_price = event.limit_up_price
                             AND coalesce(event.open_count, 0) = 0
                       ) AS one_word_count
                FROM t_sector_bar target
                JOIN eligible_sectors sector USING (sector_code)
                LEFT JOIN active_components component
                  ON component.sector_code = target.sector_code
                 AND coalesce(component.start_date, DATE '1900-01-01') <= target.trade_date
                 AND coalesce(component.end_date, DATE '2999-12-31') >= target.trade_date
                LEFT JOIN t_daily_bar daily
                  ON daily.stock_code = component.stock_code
                 AND daily.trade_date = target.trade_date
                LEFT JOIN t_stock_factor_daily factor
                  ON factor.stock_code = component.stock_code
                 AND factor.trade_date = target.trade_date
                LEFT JOIN stock_events event
                  ON event.stock_code = component.stock_code
                 AND event.trade_date = target.trade_date
                WHERE target.trade_date BETWEEN :start_date AND :end_date
                GROUP BY target.sector_code, target.trade_date
            ),
            target_flows AS (
                SELECT flow.*,
                       cume_dist() OVER (
                           PARTITION BY flow.trade_date ORDER BY flow.main_net_inflow_yuan
                       ) * 100 AS fund_strength,
                       dense_rank() OVER (
                           PARTITION BY flow.trade_date
                           ORDER BY flow.main_net_inflow_yuan DESC
                       ) AS fund_rank
                FROM flow_history flow
                WHERE flow.trade_date BETWEEN :start_date AND :end_date
                  AND flow.main_net_inflow_yuan IS NOT NULL
            ),
            assembled AS (
                SELECT target.sector_code,
                       target.trade_date,
                       sector.sector_name,
                       sector.sector_type,
                       bar.ma5, bar.ma10, bar.ma20, bar.ma60,
                       (bar.close_price / nullif(bar.close1, 0) - 1) * 100 AS return_1d_pct,
                       (bar.close_price / nullif(bar.close5, 0) - 1) * 100 AS return_5d_pct,
                       (bar.close_price / nullif(bar.close20, 0) - 1) * 100 AS return_20d_pct,
                       (bar.close_price / nullif(bar.high20, 0) - 1) * 100 AS drawdown_20d_pct,
                       flow.fund_strength,
                       flow.main_net_inflow_yuan,
                       flow.net_3d,
                       flow.net_5d,
                       flow.net_10d,
                       coalesce(flow.continuous_days, 0) AS continuous_days,
                       flow.fund_rank,
                       stats.component_count,
                       stats.covered_count::double precision / nullif(stats.component_count, 0) AS coverage_ratio,
                       stats.rising_count,
                       stats.falling_count,
                       stats.flat_count,
                       stats.limit_up_count,
                       stats.limit_down_count,
                       stats.break_count,
                       stats.one_word_count,
                       greatest(stats.limit_up_count - stats.one_word_count, 0) AS natural_count,
                       stats.average_change,
                       stats.median_change,
                       stats.above_ma20,
                       stats.above_ma60,
                       stats.high20_count,
                       stats.low20_count,
                       stats.high60_count,
                       stats.low60_count,
                       bar.volatility20,
                       coalesce(stats.average_change, 0) * 8
                         + coalesce(stats.limit_up_count, 0) * 3
                         + coalesce(flow.fund_strength, 0) * 0.35
                         + least(coalesce(flow.continuous_days, 0), 5) * 2 AS heat_score,
                       least(coalesce(flow.continuous_days, 0) * 20, 100) AS persistence_score,
                       array_remove(ARRAY[
                           CASE WHEN bar.sector_code IS NULL THEN 'sector_bar' END,
                           CASE WHEN flow.sector_code IS NULL THEN 'sector_fund_flow' END,
                           CASE WHEN stats.component_count = 0 THEN 'components' END,
                           CASE
                               WHEN stats.component_count > 0
                                AND stats.covered_count < stats.component_count * 0.8
                               THEN 'component_coverage'
                           END
                       ]::text[], NULL) AS quality_flags
                FROM target_keys target
                JOIN eligible_sectors sector USING (sector_code)
                LEFT JOIN bar_history bar
                  ON bar.sector_code = target.sector_code AND bar.trade_date = target.trade_date
                LEFT JOIN target_flows flow
                  ON flow.sector_code = target.sector_code AND flow.trade_date = target.trade_date
                LEFT JOIN member_stats stats
                  ON stats.sector_code = target.sector_code AND stats.trade_date = target.trade_date
            ),
            ranked AS (
                SELECT assembled.*,
                       dense_rank() OVER (
                           PARTITION BY assembled.trade_date
                           ORDER BY assembled.heat_score DESC
                       ) AS heat_rank
                FROM assembled
            ),
            upserted AS (
                INSERT INTO t_sector_factor_daily (
                    sector_code, sector_name, sector_type, trade_date, source,
                    ma5, ma10, ma20, ma60,
                    return_1d_pct, return_5d_pct, return_20d_pct, drawdown_20d_pct,
                    fund_strength, main_net_inflow_yuan,
                    main_net_inflow_3d_yuan, main_net_inflow_5d_yuan, main_net_inflow_10d_yuan,
                    continuous_inflow_days, fund_rank,
                    component_count, component_coverage_ratio,
                    rising_stock_count, falling_stock_count, flat_stock_count,
                    limit_up_stock_count, limit_down_stock_count, limit_break_stock_count,
                    one_word_limit_up_count, natural_limit_up_count,
                    average_change_pct, median_change_pct,
                    above_ma20_ratio, above_ma60_ratio,
                    new_high_20d_count, new_low_20d_count,
                    new_high_60d_count, new_low_60d_count,
                    volatility_20d, heat_score, heat_rank, persistence_score,
                    calculation_revision, quality_flags, created_at, updated_at
                )
                SELECT sector_code, sector_name, sector_type, trade_date, 'system:daily_close',
                       ma5, ma10, ma20, ma60,
                       return_1d_pct, return_5d_pct, return_20d_pct, drawdown_20d_pct,
                       fund_strength, main_net_inflow_yuan,
                       net_3d, net_5d, net_10d,
                       continuous_days, fund_rank,
                       component_count, coverage_ratio,
                       rising_count, falling_count, flat_count,
                       limit_up_count, limit_down_count, break_count,
                       one_word_count, natural_count,
                       average_change, median_change,
                       above_ma20, above_ma60,
                       high20_count, low20_count, high60_count, low60_count,
                       volatility20, heat_score, heat_rank, persistence_score,
                       'sector_daily_final_r1', quality_flags, now(), now()
                FROM ranked
                ON CONFLICT (sector_code, trade_date) DO UPDATE SET
                    sector_name = EXCLUDED.sector_name,
                    sector_type = EXCLUDED.sector_type,
                    source = EXCLUDED.source,
                    ma5 = EXCLUDED.ma5,
                    ma10 = EXCLUDED.ma10,
                    ma20 = EXCLUDED.ma20,
                    ma60 = EXCLUDED.ma60,
                    return_1d_pct = EXCLUDED.return_1d_pct,
                    return_5d_pct = EXCLUDED.return_5d_pct,
                    return_20d_pct = EXCLUDED.return_20d_pct,
                    drawdown_20d_pct = EXCLUDED.drawdown_20d_pct,
                    fund_strength = EXCLUDED.fund_strength,
                    main_net_inflow_yuan = EXCLUDED.main_net_inflow_yuan,
                    main_net_inflow_3d_yuan = EXCLUDED.main_net_inflow_3d_yuan,
                    main_net_inflow_5d_yuan = EXCLUDED.main_net_inflow_5d_yuan,
                    main_net_inflow_10d_yuan = EXCLUDED.main_net_inflow_10d_yuan,
                    continuous_inflow_days = EXCLUDED.continuous_inflow_days,
                    fund_rank = EXCLUDED.fund_rank,
                    component_count = EXCLUDED.component_count,
                    component_coverage_ratio = EXCLUDED.component_coverage_ratio,
                    rising_stock_count = EXCLUDED.rising_stock_count,
                    falling_stock_count = EXCLUDED.falling_stock_count,
                    flat_stock_count = EXCLUDED.flat_stock_count,
                    limit_up_stock_count = EXCLUDED.limit_up_stock_count,
                    limit_down_stock_count = EXCLUDED.limit_down_stock_count,
                    limit_break_stock_count = EXCLUDED.limit_break_stock_count,
                    one_word_limit_up_count = EXCLUDED.one_word_limit_up_count,
                    natural_limit_up_count = EXCLUDED.natural_limit_up_count,
                    average_change_pct = EXCLUDED.average_change_pct,
                    median_change_pct = EXCLUDED.median_change_pct,
                    above_ma20_ratio = EXCLUDED.above_ma20_ratio,
                    above_ma60_ratio = EXCLUDED.above_ma60_ratio,
                    new_high_20d_count = EXCLUDED.new_high_20d_count,
                    new_low_20d_count = EXCLUDED.new_low_20d_count,
                    new_high_60d_count = EXCLUDED.new_high_60d_count,
                    new_low_60d_count = EXCLUDED.new_low_60d_count,
                    volatility_20d = EXCLUDED.volatility_20d,
                    heat_score = EXCLUDED.heat_score,
                    heat_rank = EXCLUDED.heat_rank,
                    persistence_score = EXCLUDED.persistence_score,
                    calculation_revision = EXCLUDED.calculation_revision,
                    quality_flags = EXCLUDED.quality_flags,
                    updated_at = now()
                RETURNING trade_date
            )
            SELECT trade_date, count(*) AS row_count
            FROM upserted
            GROUP BY trade_date
            ORDER BY trade_date
            """
        ).bindparams(
            bindparam("start_date", type_=Date()),
            bindparam("end_date", type_=Date()),
            bindparam("history_start", type_=Date()),
        )
        rows = (
            await self.session.execute(
                statement,
                {
                    "start_date": start_date,
                    "end_date": end_date,
                    "history_start": history_start,
                },
            )
        ).mappings().all()
        return {row["trade_date"]: int(row["row_count"] or 0) for row in rows}

    async def rebuild_sector_final_metrics(self, *, trade_date: date) -> int:
        """Fill typed trend/breadth/event fields after the base sector pass."""
        statement = text(
            """
                WITH bar_series AS (
                    SELECT bar.*,
                        avg(close_price) OVER (PARTITION BY sector_code ORDER BY trade_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS ma5,
                        avg(close_price) OVER (PARTITION BY sector_code ORDER BY trade_date ROWS BETWEEN 9 PRECEDING AND CURRENT ROW) AS ma10,
                        avg(close_price) OVER (PARTITION BY sector_code ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS ma20,
                        avg(close_price) OVER (PARTITION BY sector_code ORDER BY trade_date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW) AS ma60,
                        lag(close_price, 1) OVER (PARTITION BY sector_code ORDER BY trade_date) AS close1,
                        lag(close_price, 5) OVER (PARTITION BY sector_code ORDER BY trade_date) AS close5,
                        lag(close_price, 20) OVER (PARTITION BY sector_code ORDER BY trade_date) AS close20,
                        max(close_price) OVER (PARTITION BY sector_code ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS high20
                    FROM t_sector_bar bar
                    WHERE trade_date BETWEEN (CAST(:trade_date AS date) - INTERVAL '180 days') AND :trade_date
                ),
                current_bar AS (
                    SELECT * FROM bar_series WHERE trade_date = :trade_date
                ),
                member_facts AS (
                    SELECT component.sector_code, component.stock_code,
                           bar.change_pct, factor.close_qfq, factor.ma20, factor.ma60,
                           factor.high_20d, factor.low_20d, factor.high_60d, factor.low_60d
                    FROM t_sector_component component
                    JOIN t_stock stock ON stock.stock_code = component.stock_code
                    LEFT JOIN t_daily_bar bar
                      ON bar.stock_code = component.stock_code AND bar.trade_date = :trade_date
                    LEFT JOIN t_stock_factor_daily factor
                      ON factor.stock_code = component.stock_code AND factor.trade_date = :trade_date
                    WHERE stock.status = 'active' AND stock.is_st IS FALSE
                      AND stock.exchange IN ('SH','SZ','SSE','SZSE')
                      AND coalesce(component.start_date, DATE '1900-01-01') <= :trade_date
                      AND coalesce(component.end_date, DATE '2999-12-31') >= :trade_date
                ),
                breadth AS (
                    SELECT sector_code,
                           count(*) AS component_count,
                           count(change_pct) AS covered_count,
                           count(*) FILTER (WHERE change_pct > 0) AS rising_count,
                           count(*) FILTER (WHERE change_pct < 0) AS falling_count,
                           count(*) FILTER (WHERE change_pct = 0) AS flat_count,
                           avg(change_pct) AS average_change,
                           percentile_cont(0.5) WITHIN GROUP (ORDER BY change_pct) AS median_change,
                           avg((close_qfq >= ma20)::int) FILTER (WHERE close_qfq IS NOT NULL AND ma20 IS NOT NULL) AS above_ma20,
                           avg((close_qfq >= ma60)::int) FILTER (WHERE close_qfq IS NOT NULL AND ma60 IS NOT NULL) AS above_ma60,
                           count(*) FILTER (WHERE close_qfq >= high_20d) AS high20_count,
                           count(*) FILTER (WHERE close_qfq <= low_20d) AS low20_count,
                           count(*) FILTER (WHERE close_qfq >= high_60d) AS high60_count,
                           count(*) FILTER (WHERE close_qfq <= low_60d) AS low60_count
                    FROM member_facts GROUP BY sector_code
                ),
                events AS (
                    SELECT member.sector_code,
                           count(DISTINCT event.stock_code) FILTER (WHERE event.event_type = 'limit_up') AS limit_up_count,
                           count(DISTINCT event.stock_code) FILTER (WHERE event.event_type = 'limit_down') AS limit_down_count,
                           count(DISTINCT event.stock_code) FILTER (WHERE event.event_type = 'limit_break') AS break_count,
                           count(DISTINCT event.stock_code) FILTER (
                               WHERE event.event_type = 'limit_up' AND daily.open_price = event.limit_price
                                 AND coalesce(event.open_count, 0) = 0
                           ) AS one_word_count
                    FROM member_facts member
                    LEFT JOIN t_limit_event_daily event
                      ON event.stock_code = member.stock_code AND event.trade_date = :trade_date
                    LEFT JOIN t_daily_bar daily
                      ON daily.stock_code = member.stock_code AND daily.trade_date = :trade_date
                    GROUP BY member.sector_code
                ),
                ranked AS (
                    SELECT factor.sector_code,
                           dense_rank() OVER (ORDER BY factor.fund_strength DESC NULLS LAST) AS fund_rank,
                           dense_rank() OVER (
                               ORDER BY (
                                   coalesce(breadth.average_change, 0) * 8
                                   + coalesce(events.limit_up_count, 0) * 3
                                   + coalesce(factor.fund_strength, 0) * 0.35
                                   + least(coalesce(factor.continuous_inflow_days, 0), 5) * 2
                               ) DESC
                           ) AS heat_rank,
                           (coalesce(breadth.average_change, 0) * 8
                            + coalesce(events.limit_up_count, 0) * 3
                            + coalesce(factor.fund_strength, 0) * 0.35
                            + least(coalesce(factor.continuous_inflow_days, 0), 5) * 2) AS heat_score
                    FROM t_sector_factor_daily factor
                    LEFT JOIN breadth USING (sector_code)
                    LEFT JOIN events USING (sector_code)
                    WHERE factor.trade_date = :trade_date
                )
                UPDATE t_sector_factor_daily factor
                SET ma5 = current_bar.ma5, ma10 = current_bar.ma10,
                    ma20 = current_bar.ma20, ma60 = current_bar.ma60,
                    return_1d_pct = (current_bar.close_price / nullif(current_bar.close1, 0) - 1) * 100,
                    return_5d_pct = (current_bar.close_price / nullif(current_bar.close5, 0) - 1) * 100,
                    return_20d_pct = (current_bar.close_price / nullif(current_bar.close20, 0) - 1) * 100,
                    drawdown_20d_pct = (current_bar.close_price / nullif(current_bar.high20, 0) - 1) * 100,
                    main_net_inflow_yuan = flow.main_net_inflow_yuan,
                    fund_rank = ranked.fund_rank,
                    component_count = breadth.component_count,
                    component_coverage_ratio = breadth.covered_count::double precision / nullif(breadth.component_count, 0),
                    rising_stock_count = breadth.rising_count,
                    falling_stock_count = breadth.falling_count,
                    flat_stock_count = breadth.flat_count,
                    average_change_pct = breadth.average_change,
                    median_change_pct = breadth.median_change,
                    above_ma20_ratio = breadth.above_ma20,
                    above_ma60_ratio = breadth.above_ma60,
                    new_high_20d_count = breadth.high20_count,
                    new_low_20d_count = breadth.low20_count,
                    new_high_60d_count = breadth.high60_count,
                    new_low_60d_count = breadth.low60_count,
                    limit_up_stock_count = events.limit_up_count,
                    limit_down_stock_count = events.limit_down_count,
                    limit_break_stock_count = events.break_count,
                    one_word_limit_up_count = events.one_word_count,
                    natural_limit_up_count = greatest(events.limit_up_count - events.one_word_count, 0),
                    heat_score = ranked.heat_score,
                    heat_rank = ranked.heat_rank,
                    persistence_score = least(coalesce(factor.continuous_inflow_days, 0) * 20, 100),
                    calculation_revision = 'sector_daily_final_r1',
                    quality_flags = array_remove(ARRAY[
                        CASE WHEN current_bar.sector_code IS NULL THEN 'sector_bar' END,
                        CASE WHEN flow.sector_code IS NULL THEN 'sector_fund_flow' END,
                        CASE WHEN breadth.covered_count < breadth.component_count * 0.8 THEN 'component_coverage' END
                    ]::text[], NULL),
                    updated_at = now()
                FROM ranked
                LEFT JOIN current_bar ON current_bar.sector_code = ranked.sector_code
                LEFT JOIN breadth ON breadth.sector_code = ranked.sector_code
                LEFT JOIN events ON events.sector_code = ranked.sector_code
                LEFT JOIN t_sector_fund_flow_daily flow
                  ON flow.sector_code = ranked.sector_code AND flow.trade_date = :trade_date
                WHERE factor.sector_code = ranked.sector_code
                  AND factor.trade_date = :trade_date
                RETURNING factor.id
            """
        ).bindparams(bindparam("trade_date", type_=Date()))
        result = await self.session.execute(
            statement,
            {"trade_date": trade_date},
        )
        return len(result.all())

    async def rebuild_sector_leaders(self, *, trade_date: date) -> int:
        rows = await self.rebuild_sector_leaders_between(start_date=trade_date, end_date=trade_date)
        return rows.get(trade_date, 0)

    async def rebuild_sector_leaders_between(self, *, start_date: date, end_date: date) -> dict[date, int]:
        """Replace leaders for a bounded window and restrict them to factor-backed sectors."""
        await self.session.execute(
            delete(SectorLeaderDaily).where(SectorLeaderDaily.trade_date.between(start_date, end_date))
        )
        await self.session.execute(
            text(
                """
                UPDATE t_sector_factor_daily
                SET leader_strength_score = NULL,
                    updated_at = now()
                WHERE trade_date BETWEEN :start_date AND :end_date
                """
            ).bindparams(
                bindparam("start_date", type_=Date()),
                bindparam("end_date", type_=Date()),
            ),
            {"start_date": start_date, "end_date": end_date},
        )
        statement = text(
            """
            WITH target_factors AS (
                SELECT factor.sector_code, factor.trade_date
                FROM t_sector_factor_daily factor
                JOIN t_sector_basic sector USING (sector_code)
                WHERE factor.trade_date BETWEEN :start_date AND :end_date
                  AND factor.calculation_revision = 'sector_daily_final_r1'
                  AND sector.source LIKE 'tushare:%'
                  AND sector.sector_code LIKE 'ths_%'
            ),
            active_components AS (
                SELECT DISTINCT component.sector_code, component.stock_code,
                                component.start_date, component.end_date
                FROM t_sector_component component
                JOIN (SELECT DISTINCT sector_code FROM target_factors) target USING (sector_code)
                JOIN t_stock stock ON stock.stock_code = component.stock_code
                WHERE stock.status = 'active'
                  AND stock.is_st IS FALSE
                  AND stock.exchange IN ('SH','SZ','SSE','SZSE')
            ),
            evidence AS (
                SELECT item.stock_code, item.trade_date, max(item.board_count) AS board_count
                FROM t_market_limit_up_evidence_daily item
                WHERE item.trade_date BETWEEN :start_date AND :end_date
                GROUP BY item.stock_code, item.trade_date
            ),
            candidates AS (
                SELECT target.sector_code,
                       target.trade_date,
                       bar.stock_code,
                       stock.stock_name,
                       bar.change_pct,
                       bar.amount_yuan,
                       evidence.board_count,
                       coalesce(evidence.board_count, 0) * 20
                         + coalesce(bar.change_pct, 0) * 3
                         + coalesce(factor.return_percentile_1d, 0) * 0.2 AS leader_score,
                       row_number() OVER (
                           PARTITION BY target.sector_code, target.trade_date
                           ORDER BY coalesce(evidence.board_count, 0) DESC,
                                    bar.change_pct DESC NULLS LAST,
                                    bar.amount_yuan DESC NULLS LAST,
                                    bar.stock_code
                       ) AS leader_rank
                FROM target_factors target
                JOIN active_components component
                  ON component.sector_code = target.sector_code
                 AND coalesce(component.start_date, DATE '1900-01-01') <= target.trade_date
                 AND coalesce(component.end_date, DATE '2999-12-31') >= target.trade_date
                JOIN t_daily_bar bar
                  ON bar.stock_code = component.stock_code
                 AND bar.trade_date = target.trade_date
                JOIN t_stock stock ON stock.stock_code = bar.stock_code
                LEFT JOIN t_stock_factor_daily factor
                  ON factor.stock_code = bar.stock_code
                 AND factor.trade_date = target.trade_date
                LEFT JOIN evidence
                  ON evidence.stock_code = bar.stock_code
                 AND evidence.trade_date = target.trade_date
            ),
            inserted AS (
                INSERT INTO t_sector_leader_daily (
                    sector_code, trade_date, leader_rank, stock_code, stock_name,
                    change_pct, amount_yuan, limit_board_count, leader_score,
                    source, calculated_at
                )
                SELECT sector_code, trade_date, leader_rank, stock_code, stock_name,
                       change_pct, amount_yuan, board_count, leader_score,
                       'system:sector_factor', now()
                FROM candidates
                WHERE leader_rank <= 5
                RETURNING sector_code, trade_date, leader_score
            ),
            strengths AS (
                SELECT sector_code, trade_date, max(leader_score) AS leader_strength_score
                FROM inserted
                GROUP BY sector_code, trade_date
            ),
            updated AS (
                UPDATE t_sector_factor_daily factor
                SET leader_strength_score = strengths.leader_strength_score,
                    updated_at = now()
                FROM strengths
                WHERE factor.sector_code = strengths.sector_code
                  AND factor.trade_date = strengths.trade_date
                RETURNING factor.id
            )
            SELECT trade_date, count(*) AS row_count
            FROM inserted
            GROUP BY trade_date
            ORDER BY trade_date
            """
        ).bindparams(
            bindparam("start_date", type_=Date()),
            bindparam("end_date", type_=Date()),
        )
        rows = (
            await self.session.execute(
                statement,
                {"start_date": start_date, "end_date": end_date},
            )
        ).mappings().all()
        return {row["trade_date"]: int(row["row_count"] or 0) for row in rows}

    async def rebuild_index_factors(self, *, trade_date: date) -> int:
        core_codes = CORE_INDEX_CANONICAL_CODES
        bars = list(
            (
                await self.session.execute(
                    select(IndexBar)
                    .where(
                        IndexBar.index_code.in_(core_codes),
                        IndexBar.trade_date.between(trade_date - timedelta(days=550), trade_date),
                    )
                    .order_by(IndexBar.index_code, IndexBar.trade_date)
                )
            ).scalars().all()
        )
        basics = {
            row.index_code: row
            for row in (
                await self.session.execute(
                    select(IndexDailyBasic).where(
                        IndexDailyBasic.index_code.in_(core_codes),
                        IndexDailyBasic.trade_date == trade_date,
                    )
                )
            ).scalars().all()
        }
        grouped: dict[str, list[IndexBar]] = {}
        for bar in bars:
            grouped.setdefault(bar.index_code, []).append(bar)

        def mean_window(values: list[float], window: int) -> float | None:
            chunk = values[-window:]
            return sum(chunk) / len(chunk) if chunk else None

        def ema(values: list[float], window: int) -> float | None:
            if not values:
                return None
            alpha = 2.0 / (window + 1)
            current = values[0]
            for value in values[1:]:
                current = alpha * value + (1 - alpha) * current
            return current

        rows: list[dict] = []
        for code in core_codes:
            series = grouped.get(code, [])
            if not series or series[-1].trade_date != trade_date:
                continue
            closes = [float(row.close_price) for row in series if row.close_price is not None]
            highs = [float(row.high_price) for row in series if row.high_price is not None]
            lows = [float(row.low_price) for row in series if row.low_price is not None]
            amounts = [float(row.amount_yuan) for row in series if row.amount_yuan is not None]
            volumes = [float(row.volume) for row in series if row.volume is not None]
            if not closes:
                continue
            current = series[-1]

            def return_pct(window: int) -> float | None:
                baseline_index = max(0, len(closes) - 1 - window)
                baseline = closes[baseline_index]
                return (closes[-1] / baseline - 1) * 100 if baseline else None

            returns = [
                (closes[index] / closes[index - 1] - 1) * 100
                for index in range(1, len(closes)) if closes[index - 1]
            ]
            high20, high60 = max(highs[-20:]), max(highs[-60:])
            low20, low60 = min(lows[-20:]), min(lows[-60:])
            basic = basics.get(code)
            ma20 = mean_window(closes, 20)
            ma60 = mean_window(closes, 60)
            rows.append({
                "index_code": code,
                "trade_date": trade_date,
                "source": "system:index_factor",
                **{f"ma{window}": mean_window(closes, window) for window in (5, 10, 20, 30, 60, 120, 250)},
                **{f"ema{window}": ema(closes, window) for window in (5, 10, 20, 30, 60)},
                **{f"return_{window}d_pct": return_pct(window) for window in (1, 5, 10, 20, 60)},
                "amplitude_pct": (
                    (float(current.high_price) - float(current.low_price))
                    / float(current.close_price) * 100
                    if current.high_price is not None and current.low_price is not None and current.close_price
                    else None
                ),
                "volume_ratio_5d": volumes[-1] / (sum(volumes[-6:-1]) / len(volumes[-6:-1])) if len(volumes) > 1 and volumes[-6:-1] and sum(volumes[-6:-1]) else None,
                "amount_ratio_5d": amounts[-1] / (sum(amounts[-6:-1]) / len(amounts[-6:-1])) if len(amounts) > 1 and amounts[-6:-1] and sum(amounts[-6:-1]) else None,
                "volatility_20d": pstdev(returns[-20:]) if len(returns[-20:]) >= 2 else None,
                "volatility_60d": pstdev(returns[-60:]) if len(returns[-60:]) >= 2 else None,
                "high_20d": high20, "low_20d": low20,
                "high_60d": high60, "low_60d": low60,
                "drawdown_20d_pct": (closes[-1] / high20 - 1) * 100 if high20 else None,
                "drawdown_60d_pct": (closes[-1] / high60 - 1) * 100 if high60 else None,
                "trend_status": "bull" if ma20 and ma60 and closes[-1] > ma20 > ma60 else "bear" if ma20 and ma60 and closes[-1] < ma20 < ma60 else "range",
                "turnover_rate_pct": basic.turnover_rate_pct if basic else None,
                "pe_ttm": basic.pe_ttm if basic else None,
                "pb": basic.pb if basic else None,
                "calculation_revision": "index_daily_final_r1",
                "quality_flags": [] if basic else ["valuation"],
            })
        if not rows:
            return 0
        for batch in _chunked(rows, _safe_batch_size(rows)):
            statement = insert(IndexFactorDaily).values(batch)
            await self.session.execute(
                statement.on_conflict_do_update(
                    index_elements=[IndexFactorDaily.index_code, IndexFactorDaily.trade_date],
                    set_={
                        column.name: getattr(statement.excluded, column.name)
                        for column in IndexFactorDaily.__table__.columns
                        if column.name not in {"id", "index_code", "trade_date", "created_at"}
                    },
                )
            )
        return len(rows)

    async def rebuild_market_summary(self, *, trade_date: date) -> int:
        rows = (
            await self.session.execute(
                text(
                    """
                    WITH cutoff AS (
                        SELECT min(trade_date) AS date
                        FROM (SELECT trade_date FROM t_trade_calendar
                              WHERE market = 'CN' AND is_open IS TRUE AND trade_date <= :trade_date
                              ORDER BY trade_date DESC LIMIT 6) d
                    ),
                    eligible AS (
                        SELECT stock_code FROM t_stock, cutoff
                        WHERE status = 'active' AND is_st IS FALSE
                          AND exchange IN ('SH','SZ','SSE','SZSE')
                          AND list_date IS NOT NULL AND list_date <= cutoff.date
                    ),
                    facts AS (
                        SELECT eligible.stock_code, bar.change_pct, bar.amount_yuan,
                               basic.id AS basic_id, basic.turnover_rate_pct,
                               fund.id AS fund_id, fund.main_net_inflow_yuan,
                               factor.id AS factor_id, factor.volatility_20d,
                               factor.close_qfq, factor.ma5, factor.ma20, factor.ma60, factor.ma250,
                               factor.high_20d, factor.low_20d, factor.high_60d, factor.low_60d,
                               factor.high_250d, factor.low_250d
                        FROM eligible
                        LEFT JOIN t_daily_bar bar USING (stock_code)
                        LEFT JOIN t_stock_daily_basic basic
                          ON basic.stock_code = eligible.stock_code AND basic.trade_date = :trade_date
                        LEFT JOIN t_stock_fund_flow_daily fund
                          ON fund.stock_code = eligible.stock_code AND fund.trade_date = :trade_date
                        LEFT JOIN t_stock_factor_daily factor
                          ON factor.stock_code = eligible.stock_code AND factor.trade_date = :trade_date
                        WHERE bar.trade_date = :trade_date
                    ),
                    aggregate_fact AS (
                        SELECT (SELECT count(*) FROM eligible) AS eligible_count,
                               count(*) AS daily_count,
                               count(basic_id) AS basic_count,
                               count(fund_id) AS fund_count,
                               count(factor_id) AS factor_count,
                               count(*) FILTER (WHERE change_pct > 0) AS up_count,
                               count(*) FILTER (WHERE change_pct < 0) AS down_count,
                               count(*) FILTER (WHERE change_pct = 0) AS flat_count,
                               avg(change_pct) AS average_change,
                               percentile_cont(0.5) WITHIN GROUP (ORDER BY change_pct) AS median_change,
                               count(*) FILTER (WHERE change_pct >= 1) AS up1,
                               count(*) FILTER (WHERE change_pct <= -1) AS down1,
                               count(*) FILTER (WHERE change_pct >= 3) AS up3,
                               count(*) FILTER (WHERE change_pct <= -3) AS down3,
                               count(*) FILTER (WHERE change_pct >= 5) AS up5,
                               count(*) FILTER (WHERE change_pct <= -5) AS down5,
                               count(*) FILTER (WHERE change_pct >= 7) AS up7,
                               count(*) FILTER (WHERE change_pct <= -7) AS down7,
                               sum(amount_yuan) AS total_amount,
                               avg(turnover_rate_pct) AS average_turnover,
                               percentile_cont(0.5) WITHIN GROUP (ORDER BY turnover_rate_pct) AS median_turnover,
                               avg(volatility_20d) AS average_volatility_20d,
                               sum(main_net_inflow_yuan) AS main_net,
                               avg((close_qfq >= ma5)::int) FILTER (WHERE close_qfq IS NOT NULL AND ma5 IS NOT NULL) AS above_ma5,
                               avg((close_qfq >= ma20)::int) FILTER (WHERE close_qfq IS NOT NULL AND ma20 IS NOT NULL) AS above_ma20,
                               avg((close_qfq >= ma60)::int) FILTER (WHERE close_qfq IS NOT NULL AND ma60 IS NOT NULL) AS above_ma60,
                               avg((close_qfq >= ma250)::int) FILTER (WHERE close_qfq IS NOT NULL AND ma250 IS NOT NULL) AS above_ma250,
                               count(*) FILTER (WHERE close_qfq >= high_20d) AS high20,
                               count(*) FILTER (WHERE close_qfq <= low_20d) AS low20,
                               count(*) FILTER (WHERE close_qfq >= high_60d) AS high60,
                               count(*) FILTER (WHERE close_qfq <= low_60d) AS low60,
                               count(*) FILTER (WHERE close_qfq >= high_250d) AS high250,
                               count(*) FILTER (WHERE close_qfq <= low_250d) AS low250
                        FROM facts
                    ),
                    events AS (
                        SELECT count(*) FILTER (WHERE event_type = 'limit_up') AS limit_up,
                               count(*) FILTER (WHERE event_type = 'limit_down') AS limit_down,
                               count(*) FILTER (WHERE event_type = 'limit_break') AS limit_break,
                               count(*) FILTER (WHERE event_type = 'limit_up' AND daily.open_price = event.limit_price
                                   AND coalesce(event.open_count, 0) = 0) AS one_word
                        FROM t_limit_event_daily event
                        JOIN eligible USING (stock_code)
                        LEFT JOIN t_daily_bar daily
                          ON daily.stock_code = event.stock_code AND daily.trade_date = event.trade_date
                        WHERE event.trade_date = :trade_date
                    ),
                    index_fact AS (
                        SELECT count(*) AS ready_count,
                               count(*) FILTER (WHERE return_1d_pct > 0) AS rising_count,
                               avg(return_1d_pct) AS avg_return_1d,
                               avg(amplitude_pct) AS avg_amplitude
                        FROM t_index_factor_daily
                        WHERE trade_date = :trade_date
                          AND index_code = ANY(CAST(:core_index_codes AS varchar[]))
                    ),
                    event_completion AS (
                        SELECT coalesce(bool_or(
                            capability IN (
                                'daily_market_close_stock_limit',
                                'stock_limit_event_history_backfill'
                            )
                            AND status IN ('captured', 'complete_zero')
                        ), false) AS limit_complete
                        FROM t_provider_ingest_audit
                        WHERE trade_date = :trade_date
                          AND normalized_table = 't_limit_event_daily'
                    ),
                    board AS (
                        SELECT max(board_count) AS highest_board
                        FROM t_market_limit_up_evidence_daily WHERE trade_date = :trade_date
                    ),
                    previous_trade AS (
                        SELECT max(trade_date) AS trade_date
                        FROM t_trade_calendar
                        WHERE market = 'CN' AND is_open IS TRUE AND trade_date < :trade_date
                    ),
                    promotion AS (
                        SELECT count(DISTINCT previous.stock_code) AS previous_limit_up_count,
                               count(DISTINCT current.stock_code) FILTER (
                                   WHERE current.stock_code IS NOT NULL AND current.board_count >= 2
                               ) AS promoted_count
                        FROM t_limit_event_daily previous
                        CROSS JOIN previous_trade previous_date
                        LEFT JOIN t_market_limit_up_evidence_daily current
                          ON current.stock_code = previous.stock_code
                         AND current.trade_date = :trade_date
                        WHERE previous.trade_date = previous_date.trade_date
                          AND previous.event_type = 'limit_up'
                    ),
                    amount_history AS (
                        SELECT avg(total_amount_yuan) FILTER (WHERE history_rank <= 5) AS average_5d,
                               avg(total_amount_yuan) FILTER (WHERE history_rank <= 20) AS average_20d
                        FROM (
                            SELECT total_amount_yuan,
                                   row_number() OVER (ORDER BY trade_date DESC) AS history_rank
                            FROM t_market_summary_daily
                            WHERE trade_date < :trade_date AND total_amount_yuan IS NOT NULL
                            ORDER BY trade_date DESC
                            LIMIT 20
                        ) history
                    ),
                    north AS (
                        SELECT trade_date, north_money_yuan FROM t_market_north_flow_daily
                        WHERE trade_date <= :trade_date AND north_money_yuan IS NOT NULL
                        ORDER BY trade_date DESC LIMIT 1
                    ),
                    margin AS (
                        SELECT trade_date, sum(margin_total_balance_yuan) AS balance
                        FROM t_margin_summary_daily WHERE trade_date <= :trade_date
                        GROUP BY trade_date ORDER BY trade_date DESC LIMIT 1
                    )
                    INSERT INTO t_market_summary_daily (
                        trade_date, eligible_count, daily_bar_count, daily_basic_count,
                        fund_flow_count, factor_count, up_count, down_count, flat_count,
                        average_change_pct, median_change_pct,
                        up_1pct_count, down_1pct_count, up_3pct_count, down_3pct_count,
                        up_5pct_count, down_5pct_count, up_7pct_count, down_7pct_count,
                        total_amount_yuan, amount_ratio_5d, amount_ratio_20d,
                        average_turnover_pct, median_turnover_pct, average_volatility_20d_pct,
                        main_net_inflow_yuan, main_net_inflow_ratio,
                        above_ma5_ratio, above_ma20_ratio, above_ma60_ratio, above_ma250_ratio,
                        new_high_20d_count, new_low_20d_count, new_high_60d_count,
                        new_low_60d_count, new_high_250d_count, new_low_250d_count,
                        limit_up_count, limit_down_count, limit_break_count,
                        one_word_limit_up_count, natural_limit_up_count, highest_board_count,
                        promotion_rate,
                        core_index_ready_count, core_index_rising_count,
                        core_index_average_return_1d_pct,
                        core_index_average_amplitude_pct,
                        north_flow_yuan, north_flow_disclosure_date,
                        margin_balance_yuan, margin_disclosure_date,
                        core_ready, quality_flags, calculation_revision, calculated_at
                    )
                    SELECT :trade_date, a.eligible_count, a.daily_count, a.basic_count,
                           a.fund_count, a.factor_count, a.up_count, a.down_count, a.flat_count,
                           a.average_change, a.median_change,
                           a.up1, a.down1, a.up3, a.down3, a.up5, a.down5, a.up7, a.down7,
                           a.total_amount,
                           a.total_amount / nullif(amounts.average_5d, 0),
                           a.total_amount / nullif(amounts.average_20d, 0),
                           a.average_turnover, a.median_turnover, a.average_volatility_20d,
                           a.main_net, a.main_net / nullif(a.total_amount, 0),
                           a.above_ma5, a.above_ma20, a.above_ma60, a.above_ma250,
                           a.high20, a.low20, a.high60, a.low60, a.high250, a.low250,
                           CASE WHEN completion.limit_complete THEN e.limit_up END,
                           CASE WHEN completion.limit_complete THEN e.limit_down END,
                           CASE WHEN completion.limit_complete THEN e.limit_break END,
                           CASE WHEN completion.limit_complete THEN e.one_word END,
                           CASE WHEN completion.limit_complete
                               THEN greatest(e.limit_up - e.one_word, 0) END,
                           CASE WHEN completion.limit_complete THEN board.highest_board END,
                           CASE WHEN completion.limit_complete
                               THEN promotion.promoted_count::double precision
                                 / nullif(promotion.previous_limit_up_count, 0) END,
                           idx.ready_count, idx.rising_count, idx.avg_return_1d, idx.avg_amplitude,
                           north.north_money_yuan, north.trade_date,
                           margin.balance, margin.trade_date,
                           a.daily_count >= a.eligible_count * 0.98
                             AND a.basic_count >= a.daily_count * 0.98
                             AND a.fund_count >= a.daily_count * 0.98
                             AND a.factor_count >= a.daily_count * 0.98
                             AND idx.ready_count = 7
                             AND completion.limit_complete,
                           array_remove(ARRAY[
                               CASE WHEN a.daily_count < a.eligible_count * 0.98 THEN 'daily_bar_coverage' END,
                               CASE WHEN a.basic_count < a.daily_count * 0.98 THEN 'daily_basic_coverage' END,
                               CASE WHEN a.fund_count < a.daily_count * 0.98 THEN 'fund_flow_coverage' END,
                               CASE WHEN a.factor_count < a.daily_count * 0.98 THEN 'factor_coverage' END,
                               CASE WHEN idx.ready_count < 7 THEN 'core_index_coverage' END,
                               CASE WHEN NOT completion.limit_complete THEN 'limit_event_audit' END,
                               CASE WHEN north.trade_date IS NULL THEN 'north_flow_missing' END,
                               CASE WHEN margin.trade_date IS NULL THEN 'margin_missing' END
                           ]::text[], NULL),
                           'market_summary_final_r1', now()
                    FROM aggregate_fact a CROSS JOIN events e CROSS JOIN index_fact idx
                    CROSS JOIN board CROSS JOIN promotion CROSS JOIN amount_history amounts
                    CROSS JOIN event_completion completion
                    LEFT JOIN north ON true LEFT JOIN margin ON true
                    ON CONFLICT (trade_date) DO UPDATE SET
                        eligible_count = EXCLUDED.eligible_count,
                        daily_bar_count = EXCLUDED.daily_bar_count,
                        daily_basic_count = EXCLUDED.daily_basic_count,
                        fund_flow_count = EXCLUDED.fund_flow_count,
                        factor_count = EXCLUDED.factor_count,
                        up_count = EXCLUDED.up_count, down_count = EXCLUDED.down_count,
                        flat_count = EXCLUDED.flat_count,
                        average_change_pct = EXCLUDED.average_change_pct,
                        median_change_pct = EXCLUDED.median_change_pct,
                        up_1pct_count = EXCLUDED.up_1pct_count, down_1pct_count = EXCLUDED.down_1pct_count,
                        up_3pct_count = EXCLUDED.up_3pct_count, down_3pct_count = EXCLUDED.down_3pct_count,
                        up_5pct_count = EXCLUDED.up_5pct_count, down_5pct_count = EXCLUDED.down_5pct_count,
                        up_7pct_count = EXCLUDED.up_7pct_count, down_7pct_count = EXCLUDED.down_7pct_count,
                        total_amount_yuan = EXCLUDED.total_amount_yuan,
                        amount_ratio_5d = EXCLUDED.amount_ratio_5d,
                        amount_ratio_20d = EXCLUDED.amount_ratio_20d,
                        average_turnover_pct = EXCLUDED.average_turnover_pct,
                        median_turnover_pct = EXCLUDED.median_turnover_pct,
                        average_volatility_20d_pct = EXCLUDED.average_volatility_20d_pct,
                        main_net_inflow_yuan = EXCLUDED.main_net_inflow_yuan,
                        main_net_inflow_ratio = EXCLUDED.main_net_inflow_ratio,
                        above_ma5_ratio = EXCLUDED.above_ma5_ratio,
                        above_ma20_ratio = EXCLUDED.above_ma20_ratio,
                        above_ma60_ratio = EXCLUDED.above_ma60_ratio,
                        above_ma250_ratio = EXCLUDED.above_ma250_ratio,
                        new_high_20d_count = EXCLUDED.new_high_20d_count,
                        new_low_20d_count = EXCLUDED.new_low_20d_count,
                        new_high_60d_count = EXCLUDED.new_high_60d_count,
                        new_low_60d_count = EXCLUDED.new_low_60d_count,
                        new_high_250d_count = EXCLUDED.new_high_250d_count,
                        new_low_250d_count = EXCLUDED.new_low_250d_count,
                        limit_up_count = EXCLUDED.limit_up_count,
                        limit_down_count = EXCLUDED.limit_down_count,
                        limit_break_count = EXCLUDED.limit_break_count,
                        one_word_limit_up_count = EXCLUDED.one_word_limit_up_count,
                        natural_limit_up_count = EXCLUDED.natural_limit_up_count,
                        highest_board_count = EXCLUDED.highest_board_count,
                        promotion_rate = EXCLUDED.promotion_rate,
                        core_index_ready_count = EXCLUDED.core_index_ready_count,
                        core_index_rising_count = EXCLUDED.core_index_rising_count,
                        core_index_average_return_1d_pct = EXCLUDED.core_index_average_return_1d_pct,
                        core_index_average_amplitude_pct = EXCLUDED.core_index_average_amplitude_pct,
                        north_flow_yuan = EXCLUDED.north_flow_yuan,
                        north_flow_disclosure_date = EXCLUDED.north_flow_disclosure_date,
                        margin_balance_yuan = EXCLUDED.margin_balance_yuan,
                        margin_disclosure_date = EXCLUDED.margin_disclosure_date,
                        core_ready = EXCLUDED.core_ready,
                        quality_flags = EXCLUDED.quality_flags,
                        calculation_revision = EXCLUDED.calculation_revision,
                        calculated_at = now()
                    RETURNING trade_date
                    """
                ).bindparams(bindparam("core_index_codes", type_=ARRAY(String()))),
                {"trade_date": trade_date, "core_index_codes": list(CORE_INDEX_CANONICAL_CODES)},
            )
        ).all()
        return len(rows)

    async def commit(self) -> None:
        await self.session.commit()
