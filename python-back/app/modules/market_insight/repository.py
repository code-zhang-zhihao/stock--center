from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta, timezone
from statistics import median

from sqlalchemy import Date, and_, bindparam, cast, func, or_, select, text
from sqlalchemy.dialects.postgresql import ARRAY, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.market_data.models import (
    Announcement,
    DailyBar,
    IndexBar,
    LhbEvent,
    LimitEventDaily,
    MarginSummaryDaily,
    MarketNorthFlowDaily,
    ProviderIngestAudit,
    SectorBasic,
    SectorComponent,
    Stock,
    StockDailyBasic,
    StockFactorDailyActive as StockFactorDaily,
    StockFundFlowDaily,
    StockNorthHoldDaily,
    TradeCalendar,
)
from app.modules.market_insight.models import (
    MarketEmotionDaily,
    MarketEmotionModel,
    MarketLimitUpEvidenceDaily,
    MarketSectorHeatDaily,
    MarketSentimentDaily,
)


# The daily close pipeline settles exactly these seven broad/core indices.
# Keep this list local to the insight read model rather than averaging any
# additional index history that may later be backfilled into ``t_index_bar``.
CORE_INDEX_CODES: tuple[str, ...] = (
    "000001.SH",
    "399001.SZ",
    "399006.SZ",
    "000300.SH",
    "000905.SH",
    "000852.SH",
    "000016.SH",
)


def _active_stock_filters() -> tuple:
    return (
        Stock.status == "active",
        Stock.is_st.is_(False),
        Stock.exchange.in_(("SH", "SZ", "SSE", "SZSE")),
    )


class MarketInsightRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        # A review backfill processes many adjacent trade dates in one
        # repository/session.  Concept membership changes slowly, so keep the
        # source-filtered membership snapshot in that bounded request scope
        # rather than repeatedly joining it to every date's full A-share bar.
        self._concept_memberships_cache: dict[str, list[tuple[str, str, date | None, date | None]]] | None = None

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

    async def open_trade_dates_before(self, *, before_date: date, limit: int) -> list[date]:
        """Return at most ``limit`` CN open dates strictly before a date.

        V2 baseline scoring only needs the percentile lookback before its
        first target date.  Reading a calendar-sized pre-window (previously
        620 natural days) made the initial aggregate unnecessarily large.
        """
        if limit <= 0:
            return []
        rows = await self.session.execute(
            select(TradeCalendar.trade_date)
            .where(
                TradeCalendar.market == "CN",
                TradeCalendar.is_open.is_(True),
                TradeCalendar.trade_date < before_date,
            )
            .order_by(TradeCalendar.trade_date.desc())
            .limit(limit)
        )
        return list(reversed(rows.scalars().all()))

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
        rows = await self.session.execute(
            select(ProviderIngestAudit.trade_date, ProviderIngestAudit.capability).where(
                ProviderIngestAudit.status.in_(("captured", "complete_zero")),
                ProviderIngestAudit.normalized_table == "t_limit_event_daily",
                ProviderIngestAudit.trade_date.in_(trade_dates),
            )
        )
        result: dict[date, set[str]] = {}
        for trade_date, capability in rows.all():
            if trade_date is not None:
                result.setdefault(trade_date, set()).add(str(capability))
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

        A direct SQL three-way aggregation is deceptively expensive on this
        schema: PostgreSQL can start with every concept board and rescan the
        full active-stock universe once per board.  Expand a small,
        source-filtered membership cache against the already-filtered daily
        facts instead.  It preserves historical membership validity, removes
        duplicate source snapshots per stock/board, and keeps a 20-day
        historical review batch bounded in application memory.
        """
        if not trade_dates:
            return {}
        memberships = await self._concept_memberships()
        if not memberships:
            return {}
        daily_statement = select(
            DailyBar.trade_date,
            DailyBar.stock_code,
            DailyBar.change_pct,
            StockFundFlowDaily.stock_code.label("fund_flow_stock_code"),
            StockFundFlowDaily.main_net_inflow,
            LimitEventDaily.stock_code.label("limit_up_stock_code"),
        )
        daily_rows = await self.session.execute(
            daily_statement
            .select_from(DailyBar)
            .join(Stock, Stock.stock_code == DailyBar.stock_code)
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
            .where(DailyBar.trade_date.in_(trade_dates), *_active_stock_filters())
        )
        aggregates: dict[tuple[date, str], dict] = {}
        for row in daily_rows.mappings():
            trade_date = row["trade_date"]
            stock_code = str(row["stock_code"])
            stock_memberships = memberships.get(stock_code) or []
            if not stock_memberships:
                continue
            change_pct = _float_or_none(row["change_pct"])
            main_net_inflow = _float_or_none(row["main_net_inflow"])
            has_limit_up = row["limit_up_stock_code"] is not None
            has_fund_flow = row["fund_flow_stock_code"] is not None
            seen_sector_codes: set[str] = set()
            for sector_code, sector_name, start_date, end_date in stock_memberships:
                if sector_code in seen_sector_codes:
                    continue
                if start_date is not None and start_date > trade_date:
                    continue
                if end_date is not None and end_date < trade_date:
                    continue
                seen_sector_codes.add(sector_code)
                aggregate = aggregates.setdefault(
                    (trade_date, sector_code),
                    {
                        "sector_name": sector_name,
                        "priced_component_count": 0,
                        "rising_stock_count": 0,
                        "falling_stock_count": 0,
                        "changes": [],
                        "limit_up_stock_count": 0,
                        "fund_flow_stock_count": 0,
                        "main_net_inflow": 0.0,
                        "has_main_net_inflow": False,
                    },
                )
                aggregate["priced_component_count"] += 1
                if change_pct is not None:
                    aggregate["changes"].append(change_pct)
                    if change_pct > 0:
                        aggregate["rising_stock_count"] += 1
                    elif change_pct < 0:
                        aggregate["falling_stock_count"] += 1
                if has_limit_up:
                    aggregate["limit_up_stock_count"] += 1
                if has_fund_flow:
                    aggregate["fund_flow_stock_count"] += 1
                if main_net_inflow is not None:
                    aggregate["main_net_inflow"] += main_net_inflow
                    aggregate["has_main_net_inflow"] = True

        result: dict[date, list[dict]] = {}
        for (trade_date, sector_code), aggregate in sorted(aggregates.items()):
            changes = aggregate["changes"]
            result.setdefault(trade_date, []).append(
                {
                    "sector_code": sector_code,
                    "sector_name": aggregate["sector_name"],
                    "priced_component_count": aggregate["priced_component_count"],
                    "rising_stock_count": aggregate["rising_stock_count"],
                    "falling_stock_count": aggregate["falling_stock_count"],
                    "average_change_pct": sum(changes) / len(changes) if changes else None,
                    "median_change_pct": float(median(changes)) if changes else None,
                    "limit_up_stock_count": aggregate["limit_up_stock_count"],
                    "fund_flow_stock_count": aggregate["fund_flow_stock_count"],
                    "main_net_inflow": aggregate["main_net_inflow"] if aggregate["has_main_net_inflow"] else None,
                }
            )
        return result

    async def _concept_memberships(self) -> dict[str, list[tuple[str, str, date | None, date | None]]]:
        if self._concept_memberships_cache is not None:
            return self._concept_memberships_cache
        rows = await self.session.execute(
            select(
                SectorComponent.stock_code,
                SectorBasic.sector_code,
                SectorBasic.sector_name,
                SectorComponent.start_date,
                SectorComponent.end_date,
            )
            .join(SectorBasic, SectorBasic.sector_code == SectorComponent.sector_code)
            .where(SectorBasic.sector_type == "concept", SectorBasic.source.like("tushare:%"))
        )
        memberships: dict[str, list[tuple[str, str, date | None, date | None]]] = defaultdict(list)
        for row in rows:
            memberships[str(row.stock_code)].append(
                (str(row.sector_code), str(row.sector_name), row.start_date, row.end_date)
            )
        self._concept_memberships_cache = dict(memberships)
        return self._concept_memberships_cache

    async def concept_leader_candidates(self, *, trade_dates: list[date], sector_codes: list[str]) -> dict[tuple[date, str], list[dict]]:
        if not trade_dates or not sector_codes:
            return {}
        target_sector_codes = {str(item) for item in sector_codes}
        memberships = await self._concept_memberships()
        if not memberships:
            return {}
        rows = await self.session.execute(
            select(
                DailyBar.trade_date.label("trade_date"),
                DailyBar.stock_code.label("stock_code"),
                Stock.stock_name.label("stock_name"),
                DailyBar.change_pct.label("change_pct"),
                DailyBar.close_price.label("close_price"),
                DailyBar.amount_yuan.label("amount_yuan"),
                StockFundFlowDaily.main_net_inflow.label("main_net_inflow"),
                LimitEventDaily.stock_code.label("limit_up_stock_code"),
            )
            .select_from(DailyBar)
            .join(Stock, Stock.stock_code == DailyBar.stock_code)
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
            .where(DailyBar.trade_date.in_(trade_dates), *_active_stock_filters())
        )
        result: dict[tuple[date, str], list[dict]] = {}
        for row in rows.mappings():
            trade_date = row["trade_date"]
            stock_code = str(row["stock_code"])
            seen_sector_codes: set[str] = set()
            for sector_code, _sector_name, start_date, end_date in memberships.get(stock_code) or []:
                if sector_code not in target_sector_codes or sector_code in seen_sector_codes:
                    continue
                if start_date is not None and start_date > trade_date:
                    continue
                if end_date is not None and end_date < trade_date:
                    continue
                seen_sector_codes.add(sector_code)
                result.setdefault((trade_date, sector_code), []).append(
                    {
                        "stock_code": stock_code,
                        "stock_name": str(row["stock_name"]),
                        "change_pct": _float_or_none(row["change_pct"]),
                        "close_price": _float_or_none(row["close_price"]),
                        "amount_yuan": _float_or_none(row["amount_yuan"]),
                        "main_net_inflow": _float_or_none(row["main_net_inflow"]),
                        "is_limit_up": row["limit_up_stock_code"] is not None,
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
            select(ProviderIngestAudit.trade_date, ProviderIngestAudit.capability).where(
                ProviderIngestAudit.status.in_(("captured", "complete_zero")),
                ProviderIngestAudit.normalized_table == normalized_table,
                ProviderIngestAudit.trade_date.in_(trade_dates),
            )
        )
        result: dict[date, set[str]] = {}
        for trade_date, capability in rows:
            if trade_date is not None:
                result.setdefault(trade_date, set()).add(str(capability))
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

    # V2 emotion model persistence -------------------------------------------------

    async def list_emotion_models(self) -> list[MarketEmotionModel]:
        rows = await self.session.execute(select(MarketEmotionModel).order_by(MarketEmotionModel.updated_at.desc()))
        return list(rows.scalars().all())

    async def get_emotion_model(self, model_code: str) -> MarketEmotionModel | None:
        return (
            await self.session.execute(select(MarketEmotionModel).where(MarketEmotionModel.model_code == model_code))
        ).scalar_one_or_none()

    async def active_emotion_model(self) -> MarketEmotionModel | None:
        return (
            await self.session.execute(
                select(MarketEmotionModel)
                .where(MarketEmotionModel.status == "active")
                .order_by(MarketEmotionModel.published_at.desc().nulls_last(), MarketEmotionModel.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def create_emotion_model(self, row: dict) -> MarketEmotionModel:
        model = MarketEmotionModel(**row)
        self.session.add(model)
        await self.session.flush()
        return model

    async def update_emotion_model(self, model: MarketEmotionModel, values: dict) -> MarketEmotionModel:
        for key, value in values.items():
            setattr(model, key, value)
        await self.session.flush()
        return model

    async def activate_emotion_model(self, model: MarketEmotionModel) -> MarketEmotionModel:
        active_models = await self.session.execute(
            select(MarketEmotionModel).where(
                MarketEmotionModel.status == "active",
                MarketEmotionModel.model_code != model.model_code,
            )
        )
        for active in active_models.scalars().all():
            active.status = "archived"
        model.status = "active"
        model.published_at = datetime.now(timezone.utc)
        await self.session.flush()
        return model

    async def emotion_rows_before(self, *, model_code: str, trade_date: date, limit: int) -> list[MarketEmotionDaily]:
        rows = await self.session.execute(
            select(MarketEmotionDaily)
            .where(
                MarketEmotionDaily.model_code == model_code,
                MarketEmotionDaily.trade_date < trade_date,
                MarketEmotionDaily.status.in_(("ready", "degraded")),
            )
            .order_by(MarketEmotionDaily.trade_date.desc())
            .limit(limit)
        )
        return list(reversed(rows.scalars().all()))

    async def upsert_emotion_daily_rows(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        for offset in range(0, len(rows), 100):
            statement = insert(MarketEmotionDaily).values(rows[offset : offset + 100])
            await self.session.execute(
                statement.on_conflict_do_update(
                    index_elements=[MarketEmotionDaily.trade_date, MarketEmotionDaily.model_code],
                    set_={
                        "status": statement.excluded.status,
                        "short_term_score": statement.excluded.short_term_score,
                        "market_risk_on_score": statement.excluded.market_risk_on_score,
                        "primary_stage_code": statement.excluded.primary_stage_code,
                        "auxiliary_state_code": statement.excluded.auxiliary_state_code,
                        "metrics": statement.excluded.metrics,
                        "scorecards": statement.excluded.scorecards,
                        "stage_evidence": statement.excluded.stage_evidence,
                        "coverage": statement.excluded.coverage,
                        "parameter_snapshot": statement.excluded.parameter_snapshot,
                        "external_confirmations": statement.excluded.external_confirmations,
                        "calculated_at": func.now(),
                        "updated_at": func.now(),
                    },
                )
            )
        return len(rows)

    async def emotion_daily(self, *, model_code: str, trade_date: date | None = None) -> MarketEmotionDaily | None:
        statement = select(MarketEmotionDaily).where(MarketEmotionDaily.model_code == model_code)
        if trade_date is not None:
            statement = statement.where(MarketEmotionDaily.trade_date == trade_date)
        return (
            await self.session.execute(statement.order_by(MarketEmotionDaily.trade_date.desc()).limit(1))
        ).scalar_one_or_none()

    async def emotion_history(self, *, model_code: str, limit: int = 60) -> list[MarketEmotionDaily]:
        """Return complete historic rows for internal callers that need JSON audits.

        UI curve and validation callers must use one of the lean projections
        below.  Loading all JSON scorecards for a 250-day curve is needlessly
        expensive across a remote PostgreSQL connection.
        """
        rows = await self.session.execute(
            select(MarketEmotionDaily)
            .where(MarketEmotionDaily.model_code == model_code)
            .order_by(MarketEmotionDaily.trade_date.desc())
            .limit(limit)
        )
        return list(reversed(rows.scalars().all()))

    async def emotion_trend_history(self, *, model_code: str, limit: int = 60) -> list[dict]:
        """Fetch only fields needed to draw the V2 score curve."""
        rows = await self.session.execute(
            select(
                MarketEmotionDaily.trade_date,
                MarketEmotionDaily.short_term_score,
                MarketEmotionDaily.market_risk_on_score,
                MarketEmotionDaily.primary_stage_code,
                MarketEmotionDaily.auxiliary_state_code,
                MarketEmotionDaily.status,
            )
            .where(MarketEmotionDaily.model_code == model_code)
            .order_by(MarketEmotionDaily.trade_date.desc())
            .limit(limit)
        )
        return [
            {
                "trade_date": row.trade_date,
                "short_term_score": _float_or_none(row.short_term_score),
                "market_risk_on_score": _float_or_none(row.market_risk_on_score),
                "primary_stage_code": row.primary_stage_code,
                "auxiliary_state_code": row.auxiliary_state_code,
                "status": row.status,
            }
            for row in reversed(rows.all())
        ]

    async def emotion_validation_history(self, *, model_code: str, limit: int = 1000) -> list[dict]:
        """Fetch the persisted score and outcome inputs used by validation only.

        The JSONB paths deliberately select just two raw facts.  Validation is
        a read-only UI query and must not transfer 250 complete scorecards,
        evidence arrays and parameter snapshots merely to recompute T+1/T+3
        aggregates.
        """
        rows = await self.session.execute(
            select(
                MarketEmotionDaily.trade_date,
                MarketEmotionDaily.status,
                MarketEmotionDaily.short_term_score,
                MarketEmotionDaily.market_risk_on_score,
                MarketEmotionDaily.metrics["up_ratio_pct"]["raw_value"].astext.label("up_ratio_pct"),
                MarketEmotionDaily.metrics["core_index_trend"]["raw_value"].astext.label("core_index_trend"),
            )
            .where(MarketEmotionDaily.model_code == model_code)
            .order_by(MarketEmotionDaily.trade_date.desc())
            .limit(limit)
        )
        return [
            {
                "trade_date": row.trade_date,
                "status": row.status,
                "short_term_score": _float_or_none(row.short_term_score),
                "market_risk_on_score": _float_or_none(row.market_risk_on_score),
                "up_ratio_pct": _float_or_none(row.up_ratio_pct),
                "core_index_trend": _float_or_none(row.core_index_trend),
            }
            for row in reversed(rows.all())
        ]

    async def v2_market_metrics(
        self,
        trade_dates: list[date],
        *,
        progress_reporter: Callable[[dict], Awaitable[None]] | None = None,
    ) -> dict[date, dict]:
        """Aggregate V2 inputs from a listing-day-aware eligible universe.

        The sixth and twentieth open dates are resolved once per eligible
        stock.  The market aggregate itself only reads the requested dates;
        20-day high/low uses the existing ``(stock_code, trade_date DESC)``
        index through a bounded LATERAL lookup.  It must not sort a broad
        history range with a window function for every calibration run.
        """
        if not trade_dates:
            return {}
        # Resolve listing-day cutoffs once per eligible stock.  Keeping the
        # correlated trade-calendar lookup inside a DailyBar history scan made
        # PostgreSQL execute it against millions of rows during calibration.
        sixth_open_date = self._open_date_after_listing(offset=5)
        twentieth_open_date = self._open_date_after_listing(offset=19)
        eligible_stocks = (
            select(
                Stock.stock_code.label("stock_code"),
                sixth_open_date.label("sixth_open_date"),
                twentieth_open_date.label("twentieth_open_date"),
            )
            .where(Stock.list_date.is_not(None), *_active_stock_filters())
            .cte("v2_eligible_stocks")
        )
        target_bars = (
            select(
                DailyBar.stock_code.label("stock_code"),
                DailyBar.trade_date.label("trade_date"),
                DailyBar.close_price.label("close_price"),
                DailyBar.change_pct.label("change_pct"),
                DailyBar.amount_yuan.label("amount_yuan"),
                eligible_stocks.c.twentieth_open_date.label("twentieth_open_date"),
            )
            .select_from(DailyBar)
            .join(eligible_stocks, eligible_stocks.c.stock_code == DailyBar.stock_code)
            .where(
                DailyBar.trade_date.in_(trade_dates),
                DailyBar.trade_date >= eligible_stocks.c.sixth_open_date,
            )
            .cte("v2_target_bars")
        )
        rows = await self.session.execute(
            select(
                target_bars.c.trade_date.label("trade_date"),
                func.count().label("daily_bar_count"),
                func.count().filter(target_bars.c.change_pct > 0).label("up_count"),
                func.count().filter(target_bars.c.change_pct < 0).label("down_count"),
                func.count().filter(target_bars.c.change_pct == 0).label("flat_count"),
                func.count().filter(target_bars.c.change_pct >= 5).label("wide_up_count"),
                func.count().filter(target_bars.c.change_pct <= -5).label("wide_down_count"),
                func.avg(target_bars.c.change_pct).label("average_change_pct"),
                func.percentile_cont(0.5).within_group(target_bars.c.change_pct.asc()).label("median_change_pct"),
                func.sum(target_bars.c.amount_yuan).label("total_amount_yuan"),
                func.sum(StockFundFlowDaily.main_net_inflow).label("main_net_inflow"),
                func.avg(StockFundFlowDaily.main_net_ratio).label("main_net_ratio"),
                func.count().filter(target_bars.c.close_price >= StockFactorDaily.ma20).label("above_ma20_count"),
                func.count().filter(target_bars.c.close_price >= StockFactorDaily.ma60).label("above_ma60_count"),
                func.count(StockFactorDaily.id).label("factor_count"),
                func.avg(StockFactorDaily.volatility_20d).label("volatility_20d"),
                func.avg(StockFactorDaily.amount_ratio).label("amount_ratio"),
                func.avg(StockDailyBasic.turnover_rate).label("turnover_rate"),
            )
            .select_from(target_bars)
            .outerjoin(
                StockFundFlowDaily,
                and_(
                    StockFundFlowDaily.stock_code == target_bars.c.stock_code,
                    StockFundFlowDaily.trade_date == target_bars.c.trade_date,
                ),
            )
            .outerjoin(
                StockFactorDaily,
                and_(
                    StockFactorDaily.stock_code == target_bars.c.stock_code,
                    StockFactorDaily.trade_date == target_bars.c.trade_date,
                    StockFactorDaily.source == "system:daily_close",
                ),
            )
            .outerjoin(
                StockDailyBasic,
                and_(
                    StockDailyBasic.stock_code == target_bars.c.stock_code,
                    StockDailyBasic.trade_date == target_bars.c.trade_date,
                ),
            )
            .group_by(target_bars.c.trade_date)
        )
        result = {
            row.trade_date: {
                "daily_bar_count": int(row.daily_bar_count or 0),
                "up_count": int(row.up_count or 0),
                "down_count": int(row.down_count or 0),
                "flat_count": int(row.flat_count or 0),
                "wide_up_count": int(row.wide_up_count or 0),
                "wide_down_count": int(row.wide_down_count or 0),
                "average_change_pct": _float_or_none(row.average_change_pct),
                "median_change_pct": _float_or_none(row.median_change_pct),
                "total_amount_yuan": _float_or_none(row.total_amount_yuan),
                "main_net_inflow": _float_or_none(row.main_net_inflow),
                "main_net_ratio": _float_or_none(row.main_net_ratio),
                "above_ma20_count": int(row.above_ma20_count or 0),
                "above_ma60_count": int(row.above_ma60_count or 0),
                "factor_count": int(row.factor_count or 0),
                "twenty_day_stock_count": 0,
                "new_high_20_count": 0,
                "new_low_20_count": 0,
                "volatility_20d": _float_or_none(row.volatility_20d),
                "amount_ratio": _float_or_none(row.amount_ratio),
                "turnover_rate": _float_or_none(row.turnover_rate),
            }
            for row in rows
        }
        # A per-target LATERAL lookup reads no more than twenty rows through
        # DailyBar's stock/date index.  Keep this compact PostgreSQL shape
        # explicit: SQLAlchemy's nested correlation form can instead
        # materialise the target CTE repeatedly on some PostgreSQL versions.
        high_low_statement = text(
            """
            WITH eligible AS MATERIALIZED (
                SELECT
                    stock.stock_code,
                    (
                        SELECT calendar.trade_date
                        FROM t_trade_calendar AS calendar
                        WHERE calendar.market = 'CN'
                          AND calendar.is_open = TRUE
                          AND calendar.trade_date >= stock.list_date
                        ORDER BY calendar.trade_date
                        OFFSET 5 LIMIT 1
                    ) AS sixth_open_date,
                    (
                        SELECT calendar.trade_date
                        FROM t_trade_calendar AS calendar
                        WHERE calendar.market = 'CN'
                          AND calendar.is_open = TRUE
                          AND calendar.trade_date >= stock.list_date
                        ORDER BY calendar.trade_date
                        OFFSET 19 LIMIT 1
                    ) AS twentieth_open_date
                FROM t_stock AS stock
                WHERE stock.list_date IS NOT NULL
                  AND stock.status = 'active'
                  AND stock.is_st = FALSE
                  AND stock.exchange IN ('SH', 'SZ', 'SSE', 'SZSE')
            ), target AS MATERIALIZED (
                SELECT bar.stock_code, bar.trade_date, bar.close_price, eligible.twentieth_open_date
                FROM t_daily_bar AS bar
                JOIN eligible ON eligible.stock_code = bar.stock_code
                WHERE bar.trade_date = ANY(:trade_dates)
                  AND bar.trade_date >= eligible.sixth_open_date
            )
            SELECT
                target.trade_date,
                count(*) FILTER (WHERE target.trade_date >= target.twentieth_open_date) AS twenty_day_stock_count,
                count(*) FILTER (
                    WHERE target.trade_date >= target.twentieth_open_date
                      AND target.close_price >= high_low.high_20
                ) AS new_high_20_count,
                count(*) FILTER (
                    WHERE target.trade_date >= target.twentieth_open_date
                      AND target.close_price <= high_low.low_20
                ) AS new_low_20_count
            FROM target
            JOIN LATERAL (
                SELECT max(sample.close_price) AS high_20, min(sample.close_price) AS low_20
                FROM (
                    SELECT history.close_price
                    FROM t_daily_bar AS history
                    WHERE history.stock_code = target.stock_code
                      AND history.trade_date <= target.trade_date
                    ORDER BY history.trade_date DESC
                    LIMIT 20
                ) AS sample
            ) AS high_low ON TRUE
            GROUP BY target.trade_date
            """
        ).bindparams(bindparam("trade_dates", type_=ARRAY(Date())))
        # Limit the index-probe part to 20 trade dates at a time.  This keeps
        # memory and one database statement bounded on the remote PostgreSQL
        # instance; a 370-date baseline can therefore surface progress every
        # short batch rather than appearing stuck in a single giant query.
        high_low_batch_size = 20
        high_low_batch_total = (len(trade_dates) + high_low_batch_size - 1) // high_low_batch_size
        for offset in range(0, len(trade_dates), high_low_batch_size):
            high_low_batch_index = offset // high_low_batch_size + 1
            high_low_rows = await self.session.execute(
                high_low_statement,
                {"trade_dates": trade_dates[offset : offset + high_low_batch_size]},
            )
            for row in high_low_rows:
                if row.trade_date not in result:
                    continue
                result[row.trade_date].update(
                    {
                        "twenty_day_stock_count": int(row.twenty_day_stock_count or 0),
                        "new_high_20_count": int(row.new_high_20_count or 0),
                        "new_low_20_count": int(row.new_low_20_count or 0),
                    }
                )
            if progress_reporter is not None:
                await progress_reporter(
                    {
                        "subphase": "twenty_day_high_low",
                        "high_low_batch_index": high_low_batch_index,
                        "high_low_batch_total": high_low_batch_total,
                        "high_low_batch_trade_date_count": len(trade_dates[offset : offset + high_low_batch_size]),
                    }
                )
        return result

    async def v2_limit_event_rows(self, trade_dates: list[date]) -> dict[date, list[dict]]:
        if not trade_dates:
            return {}
        sixth_open_date = self._open_date_after_listing(offset=5)
        rows = await self.session.execute(
            select(
                LimitEventDaily.trade_date,
                LimitEventDaily.stock_code,
                LimitEventDaily.event_type,
                LimitEventDaily.limit_price,
                LimitEventDaily.open_count,
                DailyBar.open_price,
                DailyBar.close_price,
            )
            .join(Stock, Stock.stock_code == LimitEventDaily.stock_code)
            .join(
                DailyBar,
                and_(
                    DailyBar.stock_code == LimitEventDaily.stock_code,
                    DailyBar.trade_date == LimitEventDaily.trade_date,
                ),
            )
            .where(
                LimitEventDaily.trade_date.in_(trade_dates),
                LimitEventDaily.event_type.in_(("limit_up", "limit_down", "limit_break")),
                Stock.list_date.is_not(None),
                LimitEventDaily.trade_date >= sixth_open_date,
                *_active_stock_filters(),
            )
        )
        result: dict[date, list[dict]] = {}
        for row in rows:
            result.setdefault(row.trade_date, []).append(
                {
                    "stock_code": str(row.stock_code),
                    "event_type": str(row.event_type),
                    "limit_price": _float_or_none(row.limit_price),
                    "open_count": int(row.open_count) if row.open_count is not None else None,
                    "open_price": _float_or_none(row.open_price),
                    "close_price": _float_or_none(row.close_price),
                }
            )
        return result

    @staticmethod
    def _open_date_after_listing(*, offset: int):
        return (
            select(TradeCalendar.trade_date)
            .where(
                TradeCalendar.market == "CN",
                TradeCalendar.is_open.is_(True),
                TradeCalendar.trade_date >= Stock.list_date,
            )
            .order_by(TradeCalendar.trade_date)
            .offset(offset)
            .limit(1)
            .correlate(Stock)
            .scalar_subquery()
        )

    async def v2_index_metrics(self, trade_dates: list[date]) -> dict[date, dict]:
        if not trade_dates:
            return {}
        rows = await self.session.execute(
            select(
                IndexBar.trade_date,
                func.count(IndexBar.id).label("index_count"),
                func.avg(IndexBar.change_pct).label("average_change_pct"),
                func.avg((IndexBar.high_price - IndexBar.low_price) / func.nullif(IndexBar.close_price, 0) * 100).label("amplitude_pct"),
            )
            .where(
                IndexBar.trade_date.in_(trade_dates),
                IndexBar.index_code.in_(CORE_INDEX_CODES),
            )
            .group_by(IndexBar.trade_date)
        )
        return {
            row.trade_date: {
                "index_count": int(row.index_count or 0),
                "core_index_change_pct": _float_or_none(row.average_change_pct),
                "index_amplitude_pct": _float_or_none(row.amplitude_pct),
            }
            for row in rows
        }

    async def v2_north_flows(self, trade_dates: list[date]) -> dict[date, dict]:
        if not trade_dates:
            return {}
        rows = await self.session.execute(
            select(MarketNorthFlowDaily).where(MarketNorthFlowDaily.trade_date.in_(trade_dates))
        )
        return {
            row.trade_date: {
                "north_money": _float_or_none(row.north_money),
                "source": row.source,
                "value_unit": (row.metadata_json or {}).get("value_unit", "provider_reported"),
            }
            for row in rows.scalars().all()
        }

    async def v2_theme_metrics(self, trade_dates: list[date]) -> dict[date, list[dict]]:
        if not trade_dates:
            return {}
        rows = await self.session.execute(
            select(MarketSectorHeatDaily)
            .where(
                MarketSectorHeatDaily.trade_date.in_(trade_dates),
                MarketSectorHeatDaily.calculation_version == "v1",
                MarketSectorHeatDaily.status == "ready",
            )
            .order_by(MarketSectorHeatDaily.trade_date, MarketSectorHeatDaily.heat_rank.asc().nulls_last())
        )
        result: dict[date, list[dict]] = {}
        for row in rows.scalars().all():
            result.setdefault(row.trade_date, []).append(
                {
                    "sector_code": row.sector_code,
                    "heat_score": _float_or_none(row.heat_score),
                    "heat_rank": int(row.heat_rank) if row.heat_rank is not None else None,
                    "limit_up_stock_count": int((row.metrics or {}).get("limit_up_stock_count") or 0),
                    "priced_component_count": int((row.metrics or {}).get("priced_component_count") or 0),
                    "average_change_pct": _float_or_none((row.metrics or {}).get("average_change_pct")),
                }
            )
        return result

    async def v2_external_confirmations(self, *, up_to: date) -> dict:
        latest_hold = (
            await self.session.execute(
                select(func.max(StockNorthHoldDaily.trade_date)).where(StockNorthHoldDaily.trade_date <= up_to)
            )
        ).scalar_one_or_none()
        latest_margin = (
            await self.session.execute(
                select(func.max(MarginSummaryDaily.trade_date)).where(MarginSummaryDaily.trade_date <= up_to)
            )
        ).scalar_one_or_none()
        payload: dict = {"north_hold_latest_trade_date": latest_hold, "margin_latest_trade_date": latest_margin}
        if latest_margin is not None:
            total = await self.session.execute(
                select(func.sum(MarginSummaryDaily.rzrqye)).where(MarginSummaryDaily.trade_date == latest_margin)
            )
            payload["margin_rzrqye"] = _float_or_none(total.scalar_one_or_none())
        return payload

    async def commit(self) -> None:
        await self.session.commit()


def _float_or_none(value) -> float | None:
    return float(value) if value is not None else None
