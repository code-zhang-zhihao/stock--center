from __future__ import annotations

from datetime import date

from sqlalchemy import Date, and_, cast, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.market_data.models import (
    Announcement,
    DailyBar,
    LhbEvent,
    LimitEventDaily,
    ProviderRawRecord,
    SectorBasic,
    SectorComponent,
    Stock,
    StockFundFlowDaily,
    TradeCalendar,
)
from app.modules.market_insight.models import MarketLimitUpEvidenceDaily, MarketSectorHeatDaily, MarketSentimentDaily


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

    async def concept_metrics(self, trade_dates: list[date]) -> dict[date, list[dict]]:
        """Aggregate concept strength directly from canonical component facts.

        ``ths_daily`` is deliberately not an input here.  Its publication can
        lag the individual-stock daily facts, whereas a post-close concept
        review needs to remain reproducible from the settled stock universe.
        """
        if not trade_dates:
            return {}
        rows = await self.session.execute(
            select(
                DailyBar.trade_date.label("trade_date"),
                SectorBasic.sector_code.label("sector_code"),
                SectorBasic.sector_name.label("sector_name"),
                func.count(func.distinct(DailyBar.stock_code)).label("priced_component_count"),
                func.count(func.distinct(DailyBar.stock_code)).filter(DailyBar.change_pct > 0).label("rising_stock_count"),
                func.count(func.distinct(DailyBar.stock_code)).filter(DailyBar.change_pct < 0).label("falling_stock_count"),
                func.avg(DailyBar.change_pct).label("average_change_pct"),
                func.percentile_cont(0.5).within_group(DailyBar.change_pct.asc()).label("median_change_pct"),
                func.count(func.distinct(LimitEventDaily.stock_code)).label("limit_up_stock_count"),
                func.count(func.distinct(StockFundFlowDaily.stock_code)).label("fund_flow_stock_count"),
                func.sum(StockFundFlowDaily.main_net_inflow).label("main_net_inflow"),
            )
            .select_from(DailyBar)
            .join(Stock, Stock.stock_code == DailyBar.stock_code)
            .join(
                SectorComponent,
                and_(
                    SectorComponent.stock_code == DailyBar.stock_code,
                    or_(SectorComponent.start_date.is_(None), SectorComponent.start_date <= DailyBar.trade_date),
                    or_(SectorComponent.end_date.is_(None), SectorComponent.end_date >= DailyBar.trade_date),
                ),
            )
            .join(SectorBasic, SectorBasic.sector_code == SectorComponent.sector_code)
            .outerjoin(
                StockFundFlowDaily,
                and_(
                    StockFundFlowDaily.stock_code == DailyBar.stock_code,
                    StockFundFlowDaily.trade_date == DailyBar.trade_date,
                ),
            )
            .outerjoin(
                LimitEventDaily,
                and_(
                    LimitEventDaily.stock_code == DailyBar.stock_code,
                    LimitEventDaily.trade_date == DailyBar.trade_date,
                    LimitEventDaily.event_type == "limit_up",
                ),
            )
            .where(
                DailyBar.trade_date.in_(trade_dates),
                SectorBasic.sector_type == "concept",
                SectorBasic.source.like("tushare:%"),
                *_active_stock_filters(),
            )
            .group_by(DailyBar.trade_date, SectorBasic.sector_code, SectorBasic.sector_name)
        )
        result: dict[date, list[dict]] = {}
        for row in rows:
            result.setdefault(row.trade_date, []).append(
                {
                    "sector_code": str(row.sector_code),
                    "sector_name": str(row.sector_name),
                    "priced_component_count": int(row.priced_component_count or 0),
                    "rising_stock_count": int(row.rising_stock_count or 0),
                    "falling_stock_count": int(row.falling_stock_count or 0),
                    "average_change_pct": _float_or_none(row.average_change_pct),
                    "median_change_pct": _float_or_none(row.median_change_pct),
                    "limit_up_stock_count": int(row.limit_up_stock_count or 0),
                    "fund_flow_stock_count": int(row.fund_flow_stock_count or 0),
                    "main_net_inflow": _float_or_none(row.main_net_inflow),
                }
            )
        return result

    async def concept_leader_candidates(self, *, trade_dates: list[date], sector_codes: list[str]) -> dict[tuple[date, str], list[dict]]:
        if not trade_dates or not sector_codes:
            return {}
        rows = await self.session.execute(
            select(
                DailyBar.trade_date.label("trade_date"),
                SectorComponent.sector_code.label("sector_code"),
                Stock.stock_code.label("stock_code"),
                Stock.stock_name.label("stock_name"),
                DailyBar.change_pct.label("change_pct"),
                DailyBar.close_price.label("close_price"),
                DailyBar.amount_yuan.label("amount_yuan"),
                StockFundFlowDaily.main_net_inflow.label("main_net_inflow"),
                LimitEventDaily.stock_code.label("limit_up_stock_code"),
            )
            .select_from(DailyBar)
            .join(Stock, Stock.stock_code == DailyBar.stock_code)
            .join(
                SectorComponent,
                and_(
                    SectorComponent.stock_code == DailyBar.stock_code,
                    or_(SectorComponent.start_date.is_(None), SectorComponent.start_date <= DailyBar.trade_date),
                    or_(SectorComponent.end_date.is_(None), SectorComponent.end_date >= DailyBar.trade_date),
                ),
            )
            .outerjoin(
                StockFundFlowDaily,
                and_(
                    StockFundFlowDaily.stock_code == DailyBar.stock_code,
                    StockFundFlowDaily.trade_date == DailyBar.trade_date,
                ),
            )
            .outerjoin(
                LimitEventDaily,
                and_(
                    LimitEventDaily.stock_code == DailyBar.stock_code,
                    LimitEventDaily.trade_date == DailyBar.trade_date,
                    LimitEventDaily.event_type == "limit_up",
                ),
            )
            .where(
                DailyBar.trade_date.in_(trade_dates),
                SectorComponent.sector_code.in_(sector_codes),
                *_active_stock_filters(),
            )
            .distinct()
        )
        result: dict[tuple[date, str], list[dict]] = {}
        for row in rows:
            result.setdefault((row.trade_date, str(row.sector_code)), []).append(
                {
                    "stock_code": str(row.stock_code),
                    "stock_name": str(row.stock_name),
                    "change_pct": _float_or_none(row.change_pct),
                    "close_price": _float_or_none(row.close_price),
                    "amount_yuan": _float_or_none(row.amount_yuan),
                    "main_net_inflow": _float_or_none(row.main_net_inflow),
                    "is_limit_up": row.limit_up_stock_code is not None,
                }
            )
        return result

    async def limit_up_market_rows(self, trade_dates: list[date]) -> dict[tuple[date, str], dict]:
        if not trade_dates:
            return {}
        rows = await self.session.execute(
            select(
                LimitEventDaily.trade_date.label("trade_date"),
                Stock.stock_code.label("stock_code"),
                Stock.stock_name.label("stock_name"),
                DailyBar.close_price.label("close_price"),
                DailyBar.change_pct.label("change_pct"),
                DailyBar.amount_yuan.label("amount_yuan"),
                StockFundFlowDaily.main_net_inflow.label("main_net_inflow"),
                LimitEventDaily.limit_price.label("limit_price"),
                LimitEventDaily.open_count.label("open_count"),
            )
            .select_from(LimitEventDaily)
            .join(Stock, Stock.stock_code == LimitEventDaily.stock_code)
            .outerjoin(
                DailyBar,
                and_(DailyBar.stock_code == LimitEventDaily.stock_code, DailyBar.trade_date == LimitEventDaily.trade_date),
            )
            .outerjoin(
                StockFundFlowDaily,
                and_(StockFundFlowDaily.stock_code == LimitEventDaily.stock_code, StockFundFlowDaily.trade_date == LimitEventDaily.trade_date),
            )
            .where(
                LimitEventDaily.trade_date.in_(trade_dates),
                LimitEventDaily.event_type == "limit_up",
                *_active_stock_filters(),
            )
        )
        return {
            (row.trade_date, str(row.stock_code)): {
                "stock_code": str(row.stock_code),
                "stock_name": str(row.stock_name),
                "close_price": _float_or_none(row.close_price),
                "change_pct": _float_or_none(row.change_pct),
                "amount_yuan": _float_or_none(row.amount_yuan),
                "main_net_inflow": _float_or_none(row.main_net_inflow),
                "limit_price": _float_or_none(row.limit_price),
                "open_count": int(row.open_count or 0),
            }
            for row in rows
        }

    async def lhb_rows_for_limit_ups(self, *, trade_dates: list[date], stock_codes: list[str]) -> dict[tuple[date, str], list[dict]]:
        if not trade_dates or not stock_codes:
            return {}
        rows = await self.session.execute(
            select(
                LhbEvent.trade_date,
                LhbEvent.stock_code,
                LhbEvent.reason,
                LhbEvent.net_buy_amount,
                LhbEvent.turnover_amount,
            ).where(LhbEvent.trade_date.in_(trade_dates), LhbEvent.stock_code.in_(stock_codes))
        )
        result: dict[tuple[date, str], list[dict]] = {}
        for row in rows:
            result.setdefault((row.trade_date, str(row.stock_code)), []).append(
                {
                    "reason": str(row.reason),
                    "net_buy_amount": _float_or_none(row.net_buy_amount),
                    "turnover_amount": _float_or_none(row.turnover_amount),
                }
            )
        return result

    async def announcements_for_limit_ups(self, *, stock_codes: list[str], start_date: date, end_date: date) -> dict[str, list[dict]]:
        if not stock_codes:
            return {}
        rows = await self.session.execute(
            select(
                Announcement.stock_code,
                Announcement.title,
                Announcement.category,
                Announcement.published_at,
                Announcement.url,
            )
            .where(
                Announcement.stock_code.in_(stock_codes),
                cast(Announcement.published_at, Date).between(start_date, end_date),
            )
            .order_by(Announcement.stock_code, Announcement.published_at.desc())
        )
        result: dict[str, list[dict]] = {}
        for row in rows:
            entries = result.setdefault(str(row.stock_code), [])
            if len(entries) < 3:
                entries.append(
                    {
                        "title": str(row.title),
                        "category": row.category,
                        "published_at": row.published_at,
                        "url": row.url,
                    }
                )
        return result

    async def concept_memberships_for_stocks(self, stock_codes: list[str]) -> dict[str, list[dict]]:
        if not stock_codes:
            return {}
        rows = await self.session.execute(
            select(
                SectorComponent.stock_code,
                SectorBasic.sector_code,
                SectorBasic.sector_name,
                SectorComponent.start_date,
                SectorComponent.end_date,
            )
            .join(SectorBasic, SectorBasic.sector_code == SectorComponent.sector_code)
            .where(
                SectorComponent.stock_code.in_(stock_codes),
                SectorBasic.sector_type == "concept",
                SectorBasic.source.like("tushare:%"),
            )
            .distinct()
        )
        result: dict[str, list[dict]] = {}
        for row in rows:
            result.setdefault(str(row.stock_code), []).append(
                {
                    "sector_code": str(row.sector_code),
                    "sector_name": str(row.sector_name),
                    "start_date": row.start_date,
                    "end_date": row.end_date,
                }
            )
        return result

    async def raw_capabilities_by_date(self, *, trade_dates: list[date], normalized_table: str) -> dict[date, set[str]]:
        if not trade_dates:
            return {}
        rows = await self.session.execute(
            select(ProviderRawRecord.normalized_pk, ProviderRawRecord.capability).where(
                ProviderRawRecord.status == "captured",
                ProviderRawRecord.normalized_table == normalized_table,
                ProviderRawRecord.normalized_pk.in_([item.isoformat() for item in trade_dates]),
            )
        )
        result: dict[date, set[str]] = {}
        for date_key, capability in rows:
            try:
                result.setdefault(date.fromisoformat(str(date_key)), set()).add(str(capability))
            except ValueError:
                continue
        return result

    async def upsert_sector_heat_rows(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        for offset in range(0, len(rows), 500):
            statement = insert(MarketSectorHeatDaily).values(rows[offset : offset + 500])
            await self.session.execute(
                statement.on_conflict_do_update(
                    index_elements=[
                        MarketSectorHeatDaily.trade_date,
                        MarketSectorHeatDaily.sector_code,
                        MarketSectorHeatDaily.calculation_version,
                    ],
                    set_={
                        "sector_name": statement.excluded.sector_name,
                        "status": statement.excluded.status,
                        "heat_score": statement.excluded.heat_score,
                        "heat_rank": statement.excluded.heat_rank,
                        "metrics": statement.excluded.metrics,
                        "components": statement.excluded.components,
                        "leaders": statement.excluded.leaders,
                        "coverage": statement.excluded.coverage,
                        "source_facts": statement.excluded.source_facts,
                        "calculated_at": func.now(),
                        "updated_at": func.now(),
                    },
                )
            )
        return len(rows)

    async def upsert_limit_up_evidence_rows(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        for offset in range(0, len(rows), 500):
            statement = insert(MarketLimitUpEvidenceDaily).values(rows[offset : offset + 500])
            await self.session.execute(
                statement.on_conflict_do_update(
                    index_elements=[
                        MarketLimitUpEvidenceDaily.trade_date,
                        MarketLimitUpEvidenceDaily.stock_code,
                        MarketLimitUpEvidenceDaily.calculation_version,
                    ],
                    set_={
                        "stock_name": statement.excluded.stock_name,
                        "status": statement.excluded.status,
                        "board_count": statement.excluded.board_count,
                        "market_snapshot": statement.excluded.market_snapshot,
                        "sector_context": statement.excluded.sector_context,
                        "evidence": statement.excluded.evidence,
                        "coverage": statement.excluded.coverage,
                        "source_facts": statement.excluded.source_facts,
                        "calculated_at": func.now(),
                        "updated_at": func.now(),
                    },
                )
            )
        return len(rows)

    async def list_sector_heats(self, *, trade_date: date, calculation_version: str, limit: int) -> list[MarketSectorHeatDaily]:
        rows = await self.session.execute(
            select(MarketSectorHeatDaily)
            .where(
                MarketSectorHeatDaily.trade_date == trade_date,
                MarketSectorHeatDaily.calculation_version == calculation_version,
                MarketSectorHeatDaily.status == "ready",
            )
            .order_by(MarketSectorHeatDaily.heat_rank.asc().nulls_last(), MarketSectorHeatDaily.sector_name)
            .limit(limit)
        )
        return list(rows.scalars().all())

    async def list_limit_up_evidence(self, *, trade_date: date, calculation_version: str, limit: int) -> list[MarketLimitUpEvidenceDaily]:
        rows = await self.session.execute(
            select(MarketLimitUpEvidenceDaily)
            .where(
                MarketLimitUpEvidenceDaily.trade_date == trade_date,
                MarketLimitUpEvidenceDaily.calculation_version == calculation_version,
                MarketLimitUpEvidenceDaily.status == "ready",
            )
            .order_by(MarketLimitUpEvidenceDaily.board_count.desc().nulls_last(), MarketLimitUpEvidenceDaily.stock_code)
            .limit(limit)
        )
        return list(rows.scalars().all())

    async def review_row_counts(self, *, trade_date: date, calculation_version: str) -> dict[str, int]:
        sector_count = await self.session.execute(
            select(func.count()).select_from(MarketSectorHeatDaily).where(
                MarketSectorHeatDaily.trade_date == trade_date,
                MarketSectorHeatDaily.calculation_version == calculation_version,
                MarketSectorHeatDaily.status == "ready",
            )
        )
        evidence_count = await self.session.execute(
            select(func.count()).select_from(MarketLimitUpEvidenceDaily).where(
                MarketLimitUpEvidenceDaily.trade_date == trade_date,
                MarketLimitUpEvidenceDaily.calculation_version == calculation_version,
                MarketLimitUpEvidenceDaily.status == "ready",
            )
        )
        return {
            "sector_heat_count": int(sector_count.scalar_one() or 0),
            "limit_up_evidence_count": int(evidence_count.scalar_one() or 0),
        }

    async def commit(self) -> None:
        await self.session.commit()


def _float_or_none(value) -> float | None:
    return float(value) if value is not None else None
