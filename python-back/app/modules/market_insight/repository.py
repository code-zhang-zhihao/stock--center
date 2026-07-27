from __future__ import annotations

from datetime import date

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.market_data.models import DailyBar, LimitEventDaily, ProviderRawRecord, Stock, TradeCalendar
from app.modules.market_insight.models import MarketSentimentDaily


def _active_stock_filters() -> tuple:
    return (
        Stock.status == "active",
        Stock.is_st.is_(False),
        Stock.exchange.in_(("SH", "SZ", "SSE", "SZSE")),
    )


class MarketInsightRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def latest_daily_bar_trade_date(self) -> date | None:
        return (await self.session.execute(select(func.max(DailyBar.trade_date)))).scalar_one_or_none()

    async def open_trade_dates_between(self, *, start_date: date, end_date: date) -> list[date]:
        if end_date < start_date:
            return []
        return list(
            (
                await self.session.execute(
                    select(TradeCalendar.trade_date)
                    .where(
                        TradeCalendar.market == "CN",
                        TradeCalendar.is_open.is_(True),
                        TradeCalendar.trade_date >= start_date,
                        TradeCalendar.trade_date <= end_date,
                    )
                    .order_by(TradeCalendar.trade_date)
                )
            ).scalars().all()
        )

    async def active_stock_count(self) -> int:
        return int(
            (
                await self.session.execute(
                    select(func.count()).select_from(Stock).where(*_active_stock_filters())
                )
            ).scalar_one()
            or 0
        )

    async def daily_bar_metrics(self, trade_dates: list[date]) -> dict[date, dict]:
        if not trade_dates:
            return {}
        rows = await self.session.execute(
            select(
                DailyBar.trade_date.label("trade_date"),
                func.count(DailyBar.id).label("daily_bar_count"),
                func.count(DailyBar.id).filter(DailyBar.change_pct > 0).label("up_count"),
                func.count(DailyBar.id).filter(DailyBar.change_pct < 0).label("down_count"),
                func.count(DailyBar.id).filter(DailyBar.change_pct == 0).label("flat_count"),
                func.avg(DailyBar.change_pct).label("average_change_pct"),
                func.percentile_cont(0.5).within_group(DailyBar.change_pct.asc()).label("median_change_pct"),
                func.sum(DailyBar.amount_yuan).label("total_amount_yuan"),
            )
            .join(Stock, Stock.stock_code == DailyBar.stock_code)
            .where(DailyBar.trade_date.in_(trade_dates), *_active_stock_filters())
            .group_by(DailyBar.trade_date)
        )
        return {
            row.trade_date: {
                "daily_bar_count": int(row.daily_bar_count or 0),
                "up_count": int(row.up_count or 0),
                "down_count": int(row.down_count or 0),
                "flat_count": int(row.flat_count or 0),
                "average_change_pct": _float_or_none(row.average_change_pct),
                "median_change_pct": _float_or_none(row.median_change_pct),
                "total_amount_yuan": _float_or_none(row.total_amount_yuan),
            }
            for row in rows
        }

    async def limit_event_metrics(self, trade_dates: list[date]) -> dict[date, dict]:
        if not trade_dates:
            return {}
        rows = await self.session.execute(
            select(
                LimitEventDaily.trade_date.label("trade_date"),
                func.count(LimitEventDaily.id).filter(LimitEventDaily.event_type == "limit_up").label("limit_up_count"),
                func.count(LimitEventDaily.id).filter(LimitEventDaily.event_type == "limit_down").label("limit_down_count"),
                func.count(LimitEventDaily.id).filter(LimitEventDaily.event_type == "limit_break").label("limit_break_count"),
            )
            .join(Stock, Stock.stock_code == LimitEventDaily.stock_code)
            .where(
                LimitEventDaily.trade_date.in_(trade_dates),
                LimitEventDaily.event_type.in_(("limit_up", "limit_down", "limit_break")),
                *_active_stock_filters(),
            )
            .group_by(LimitEventDaily.trade_date)
        )
        return {
            row.trade_date: {
                "limit_up_count": int(row.limit_up_count or 0),
                "limit_down_count": int(row.limit_down_count or 0),
                "limit_break_count": int(row.limit_break_count or 0),
            }
            for row in rows
        }

    async def limit_up_codes(self, trade_dates: list[date]) -> dict[date, set[str]]:
        if not trade_dates:
            return {}
        rows = await self.session.execute(
            select(LimitEventDaily.trade_date, LimitEventDaily.stock_code)
            .join(Stock, Stock.stock_code == LimitEventDaily.stock_code)
            .where(
                LimitEventDaily.trade_date.in_(trade_dates),
                LimitEventDaily.event_type == "limit_up",
                *_active_stock_filters(),
            )
        )
        result: dict[date, set[str]] = {}
        for trade_date, stock_code in rows.all():
            result.setdefault(trade_date, set()).add(str(stock_code))
        return result

    async def limit_event_completion_capabilities(self, trade_dates: list[date]) -> dict[date, set[str]]:
        if not trade_dates:
            return {}
        date_keys = [item.isoformat() for item in trade_dates]
        rows = await self.session.execute(
            select(ProviderRawRecord.normalized_pk, ProviderRawRecord.capability).where(
                ProviderRawRecord.status == "captured",
                ProviderRawRecord.normalized_table == "t_limit_event_daily",
                ProviderRawRecord.normalized_pk.in_(date_keys),
            )
        )
        result: dict[date, set[str]] = {}
        for date_key, capability in rows.all():
            try:
                parsed_date = date.fromisoformat(str(date_key))
            except ValueError:
                continue
            result.setdefault(parsed_date, set()).add(str(capability))
        return result

    async def previous_limit_up_premiums(self, trade_dates: list[date]) -> dict[date, dict]:
        """Average target-day return for stocks that were limit-up on the prior open day."""
        if not trade_dates:
            return {}
        rows = await self.session.execute(
            select(
                DailyBar.trade_date.label("trade_date"),
                func.count(DailyBar.id).label("stock_count"),
                func.avg(DailyBar.change_pct).label("average_change_pct"),
            )
            .join(
                TradeCalendar,
                and_(
                    TradeCalendar.trade_date == DailyBar.trade_date,
                    TradeCalendar.market == "CN",
                    TradeCalendar.is_open.is_(True),
                ),
            )
            .join(
                LimitEventDaily,
                and_(
                    LimitEventDaily.stock_code == DailyBar.stock_code,
                    LimitEventDaily.trade_date == TradeCalendar.previous_trade_date,
                    LimitEventDaily.event_type == "limit_up",
                ),
            )
            .join(Stock, Stock.stock_code == DailyBar.stock_code)
            .where(DailyBar.trade_date.in_(trade_dates), *_active_stock_filters())
            .group_by(DailyBar.trade_date)
        )
        return {
            row.trade_date: {
                "stock_count": int(row.stock_count or 0),
                "average_change_pct": _float_or_none(row.average_change_pct),
            }
            for row in rows
        }

    async def sentiment_scores_before(
        self,
        *,
        trade_date: date,
        universe_code: str,
        calculation_version: str,
        limit: int,
    ) -> list[float]:
        rows = await self.session.execute(
            select(MarketSentimentDaily.sentiment_score)
            .where(
                MarketSentimentDaily.trade_date < trade_date,
                MarketSentimentDaily.universe_code == universe_code,
                MarketSentimentDaily.calculation_version == calculation_version,
                MarketSentimentDaily.status == "ready",
                MarketSentimentDaily.sentiment_score.is_not(None),
            )
            .order_by(MarketSentimentDaily.trade_date.desc())
            .limit(limit)
        )
        return [float(value) for value in rows.scalars().all() if value is not None]

    async def upsert_sentiments(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        for offset in range(0, len(rows), 500):
            statement = insert(MarketSentimentDaily).values(rows[offset : offset + 500])
            await self.session.execute(
                statement.on_conflict_do_update(
                    index_elements=[
                        MarketSentimentDaily.trade_date,
                        MarketSentimentDaily.universe_code,
                        MarketSentimentDaily.calculation_version,
                    ],
                    set_={
                        "status": statement.excluded.status,
                        "sentiment_score": statement.excluded.sentiment_score,
                        "stage_code": statement.excluded.stage_code,
                        "components": statement.excluded.components,
                        "metrics": statement.excluded.metrics,
                        "coverage": statement.excluded.coverage,
                        "source_facts": statement.excluded.source_facts,
                        "calculated_at": func.now(),
                        "updated_at": func.now(),
                    },
                )
            )
        return len(rows)

    async def latest_sentiment(
        self,
        *,
        universe_code: str,
        calculation_version: str,
        trade_date: date | None = None,
    ) -> MarketSentimentDaily | None:
        statement = select(MarketSentimentDaily).where(
            MarketSentimentDaily.universe_code == universe_code,
            MarketSentimentDaily.calculation_version == calculation_version,
        )
        if trade_date is not None:
            statement = statement.where(MarketSentimentDaily.trade_date == trade_date)
        statement = statement.order_by(MarketSentimentDaily.trade_date.desc()).limit(1)
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def commit(self) -> None:
        await self.session.commit()


def _float_or_none(value) -> float | None:
    return float(value) if value is not None else None
