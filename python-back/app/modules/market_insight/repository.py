from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta, timezone
from statistics import median

from sqlalchemy import Date, and_, cast, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.market_data.index_contract import CORE_INDEX_CANONICAL_CODES
from app.modules.market_data.models import (
    Announcement,
    DailyBar,
    IndexBar,
    LhbEvent,
    LimitEventDaily,
    MarginSummaryDaily,
    MarketNorthFlowDaily,
    MarketSummaryDaily,
    ProviderIngestAudit,
    SectorBasic,
    SectorComponent,
    SectorFactorDaily,
    SectorLeaderDaily,
    Stock,
    StockDailyBasic,
    StockFactorDaily,
    StockFundFlowDaily,
    TradeCalendar,
)
from app.modules.market_insight.models import (
    MarketEmotionDaily,
    MarketEmotionModel,
    MarketLimitUpEvidenceDaily,
)


# The daily close pipeline settles exactly these seven broad/core indices.
# Reuse the canonical database contract rather than Provider symbols so future
# extra index history cannot enter the insight read model.
CORE_INDEX_CODES = CORE_INDEX_CANONICAL_CODES


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

        Baseline scoring only needs the percentile lookback before its
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
            StockFundFlowDaily.main_net_inflow_yuan,
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
            main_net_inflow = _float_or_none(row["main_net_inflow_yuan"])
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
                StockFundFlowDaily.main_net_inflow_yuan.label("main_net_inflow_yuan"),
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
                        "main_net_inflow": _float_or_none(row["main_net_inflow_yuan"]),
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
                StockFundFlowDaily.main_net_inflow_yuan.label("main_net_inflow_yuan"),
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
                "main_net_inflow": _float_or_none(row.main_net_inflow_yuan),
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

    async def refresh_market_summary_board_structure(self, trade_dates: list[date]) -> int:
        """Finalize board height/promotion after evidence streaks are persisted."""
        updated = 0
        for trade_date in sorted(set(trade_dates)):
            result = await self.session.execute(
                text(
                    """
                    WITH previous_trade AS (
                        SELECT max(trade_date) AS trade_date
                        FROM t_trade_calendar
                        WHERE market = 'CN' AND is_open IS TRUE AND trade_date < :trade_date
                    ), previous_limit AS (
                        SELECT count(DISTINCT event.stock_code) AS stock_count
                        FROM t_limit_event_daily event
                        CROSS JOIN previous_trade previous
                        WHERE event.trade_date = previous.trade_date
                          AND event.event_type = 'limit_up'
                    ), current_board AS (
                        SELECT max(board_count) AS highest_board,
                               count(*) FILTER (WHERE board_count >= 2) AS promoted_count
                        FROM t_market_limit_up_evidence_daily
                        WHERE trade_date = :trade_date AND status = 'ready'
                    )
                    UPDATE t_market_summary_daily summary
                    SET highest_board_count = current.highest_board,
                        promotion_rate = current.promoted_count::double precision
                            / nullif(previous.stock_count, 0),
                        calculated_at = now()
                    FROM current_board current CROSS JOIN previous_limit previous
                    WHERE summary.trade_date = :trade_date
                    RETURNING summary.trade_date
                    """
                ),
                {"trade_date": trade_date},
            )
            updated += len(result.all())
        return updated

    async def list_sector_factors(self, *, trade_date: date, limit: int) -> list[dict]:
        rows = list(
            (
                await self.session.execute(
                    select(SectorFactorDaily)
                    .where(
                        SectorFactorDaily.trade_date == trade_date,
                        SectorFactorDaily.heat_score.is_not(None),
                    )
                    .order_by(SectorFactorDaily.heat_rank.asc().nulls_last(), SectorFactorDaily.sector_name)
                    .limit(limit)
                )
            ).scalars().all()
        )
        if not rows:
            return []
        sector_codes = [item.sector_code for item in rows]
        leaders = await self.session.execute(
            select(SectorLeaderDaily)
            .where(
                SectorLeaderDaily.trade_date == trade_date,
                SectorLeaderDaily.sector_code.in_(sector_codes),
            )
            .order_by(SectorLeaderDaily.sector_code, SectorLeaderDaily.leader_rank)
        )
        leaders_by_sector: dict[str, list[dict]] = defaultdict(list)
        for leader in leaders.scalars().all():
            leaders_by_sector[leader.sector_code].append(
                {
                    "stock_code": leader.stock_code,
                    "stock_name": leader.stock_name,
                    "change_pct": _float_or_none(leader.change_pct),
                    "amount_yuan": _float_or_none(leader.amount_yuan),
                    "limit_board_count": leader.limit_board_count,
                    "leader_score": _float_or_none(leader.leader_score),
                    "is_limit_up": bool(leader.limit_board_count),
                }
            )
        return [
            {
                "trade_date": item.trade_date,
                "sector_code": item.sector_code,
                "sector_name": item.sector_name,
                "sector_type": item.sector_type,
                "heat_score": _float_or_none(item.heat_score),
                "heat_rank": item.heat_rank,
                "metrics": {
                    "average_change_pct": _float_or_none(item.average_change_pct),
                    "median_change_pct": _float_or_none(item.median_change_pct),
                    "priced_component_count": item.component_count,
                    "component_coverage_ratio": _float_or_none(item.component_coverage_ratio),
                    "rising_stock_count": item.rising_stock_count,
                    "falling_stock_count": item.falling_stock_count,
                    "limit_up_stock_count": item.limit_up_stock_count,
                    "limit_down_stock_count": item.limit_down_stock_count,
                    "limit_break_stock_count": item.limit_break_stock_count,
                    "main_net_inflow_yuan": _float_or_none(item.main_net_inflow_yuan),
                    "persistence_score": _float_or_none(item.persistence_score),
                    "leader_strength_score": _float_or_none(item.leader_strength_score),
                },
                "leaders": leaders_by_sector.get(item.sector_code, []),
                "quality_flags": list(item.quality_flags or []),
                "calculation_revision": item.calculation_revision,
                "calculated_at": item.updated_at,
            }
            for item in rows
        ]

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
            select(func.count()).select_from(SectorFactorDaily).where(
                SectorFactorDaily.trade_date == trade_date,
                SectorFactorDaily.heat_score.is_not(None),
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

    # Emotion model persistence ----------------------------------------------------

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
        """Fetch only fields needed to draw the official score curve."""
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

    async def market_summary_metrics(
        self,
        trade_dates: list[date],
        *,
        progress_reporter: Callable[[dict], Awaitable[None]] | None = None,
    ) -> dict[date, dict]:
        """Read the once-per-day official market aggregate for emotion scoring."""
        if not trade_dates:
            return {}
        rows = (
            await self.session.execute(
                select(MarketSummaryDaily)
                .where(MarketSummaryDaily.trade_date.in_(trade_dates))
                .order_by(MarketSummaryDaily.trade_date)
            )
        ).scalars().all()
        result: dict[date, dict] = {}
        for row in rows:
            factor_count = int(row.factor_count or 0)
            result[row.trade_date] = {
                "daily_bar_count": int(row.daily_bar_count or 0),
                "up_count": int(row.up_count or 0),
                "down_count": int(row.down_count or 0),
                "flat_count": int(row.flat_count or 0),
                "wide_up_count": int(row.up_5pct_count or 0),
                "wide_down_count": int(row.down_5pct_count or 0),
                "average_change_pct": _float_or_none(row.average_change_pct),
                "median_change_pct": _float_or_none(row.median_change_pct),
                "total_amount_yuan": _float_or_none(row.total_amount_yuan),
                "main_net_inflow": _float_or_none(row.main_net_inflow_yuan),
                "main_net_ratio": _float_or_none(row.main_net_inflow_ratio),
                "above_ma20_count": round((row.above_ma20_ratio or 0) * factor_count),
                "above_ma60_count": round((row.above_ma60_ratio or 0) * factor_count),
                "factor_count": factor_count,
                "twenty_day_stock_count": factor_count,
                "new_high_20_count": int(row.new_high_20d_count or 0),
                "new_low_20_count": int(row.new_low_20d_count or 0),
                "volatility_20d": _float_or_none(row.average_volatility_20d_pct),
                "amount_ratio": _float_or_none(row.amount_ratio_5d),
                "turnover_rate": _float_or_none(row.average_turnover_pct),
            }
        if progress_reporter is not None:
            await progress_reporter(
                {"subphase": "official_market_summary", "summary_trade_date_count": len(result)}
            )
        return result

    async def final_limit_event_rows(self, trade_dates: list[date]) -> dict[date, list[dict]]:
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

    async def market_summary_index_metrics(self, trade_dates: list[date]) -> dict[date, dict]:
        if not trade_dates:
            return {}
        rows = (
            await self.session.execute(
                select(MarketSummaryDaily).where(MarketSummaryDaily.trade_date.in_(trade_dates))
            )
        ).scalars().all()
        return {
            row.trade_date: {
                "index_count": int(row.core_index_ready_count or 0),
                "core_index_change_pct": _float_or_none(row.core_index_average_return_1d_pct),
                "index_amplitude_pct": _float_or_none(row.core_index_average_amplitude_pct),
            }
            for row in rows
        }

    async def final_north_flows(self, trade_dates: list[date]) -> dict[date, dict]:
        if not trade_dates:
            return {}
        rows = await self.session.execute(
            select(MarketNorthFlowDaily).where(MarketNorthFlowDaily.trade_date.in_(trade_dates))
        )
        return {
            row.trade_date: {
                "north_money": _float_or_none(row.north_money_yuan),
                "source": row.source,
                "value_unit": "yuan",
            }
            for row in rows.scalars().all()
        }

    async def final_theme_metrics(self, trade_dates: list[date]) -> dict[date, list[dict]]:
        if not trade_dates:
            return {}
        rows = await self.session.execute(
            select(SectorFactorDaily)
            .where(
                SectorFactorDaily.trade_date.in_(trade_dates),
                SectorFactorDaily.heat_score.is_not(None),
            )
            .order_by(SectorFactorDaily.trade_date, SectorFactorDaily.heat_rank.asc().nulls_last())
        )
        result: dict[date, list[dict]] = {}
        for row in rows.scalars().all():
            result.setdefault(row.trade_date, []).append(
                {
                    "sector_code": row.sector_code,
                    "heat_score": _float_or_none(row.heat_score),
                    "heat_rank": int(row.heat_rank) if row.heat_rank is not None else None,
                    "limit_up_stock_count": int(row.limit_up_stock_count or 0),
                    "priced_component_count": int(row.component_count or 0),
                    "average_change_pct": _float_or_none(row.average_change_pct),
                }
            )
        return result

    async def final_external_confirmations(self, *, up_to: date) -> dict:
        latest_north = (
            await self.session.execute(
                select(func.max(MarketNorthFlowDaily.trade_date)).where(MarketNorthFlowDaily.trade_date <= up_to)
            )
        ).scalar_one_or_none()
        latest_margin = (
            await self.session.execute(
                select(func.max(MarginSummaryDaily.trade_date)).where(MarginSummaryDaily.trade_date <= up_to)
            )
        ).scalar_one_or_none()
        payload: dict = {"north_flow_latest_trade_date": latest_north, "margin_latest_trade_date": latest_margin}
        if latest_north is not None:
            north = await self.session.execute(
                select(MarketNorthFlowDaily.north_money_yuan).where(MarketNorthFlowDaily.trade_date == latest_north)
            )
            payload["north_flow_yuan"] = _float_or_none(north.scalar_one_or_none())
        if latest_margin is not None:
            total = await self.session.execute(
                select(func.sum(MarginSummaryDaily.margin_total_balance_yuan)).where(MarginSummaryDaily.trade_date == latest_margin)
            )
            payload["margin_balance_yuan"] = _float_or_none(total.scalar_one_or_none())
        return payload

    async def commit(self) -> None:
        await self.session.commit()


def _float_or_none(value) -> float | None:
    return float(value) if value is not None else None
