from datetime import date

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.market_data.models import (
    DailyBar,
    LimitEventDaily,
    MarketUniverse,
    MarketUniverseMember,
    ProviderRawRecord,
    SectorBasic,
    SectorComponent,
    Stock,
    StockFactorDaily,
    TradeCalendar,
)
from app.modules.stock_pool.models import StockPool, StockPoolMember, StockPoolRealtimePolicy
from app.modules.strategy_center.models import StrategyCandidate, StrategyDefinition, StrategyPaperTrade, StrategyVersion


class RealtimeMarketRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def active_stock_reference(self) -> tuple[list[str], dict[str, str]]:
        rows = await self.session.execute(
            select(Stock.stock_code, Stock.stock_name)
            .where(
                Stock.status == "active",
                Stock.is_st.is_(False),
                Stock.exchange.in_(("SH", "SZ", "SSE", "SZSE")),
            )
            .order_by(Stock.stock_code)
        )
        pairs = rows.all()
        return [row.stock_code for row in pairs], {row.stock_code: row.stock_name for row in pairs}

    async def latest_daily_factor_reference(self) -> tuple[date | None, dict[str, dict]]:
        """Return the latest completed daily MA reference for the active universe.

        The realtime service compares a live Quote with the most recently
        persisted daily factor values.  It does not calculate MA from an
        incomplete intraday bar and does not promote this read-only reference
        into a realtime fact table.
        """
        trade_date = (
            await self.session.execute(
                select(func.max(StockFactorDaily.trade_date)).where(StockFactorDaily.source == "system:daily_close")
            )
        ).scalar_one_or_none()
        if trade_date is None:
            return None, {}
        rows = await self.session.execute(
            select(
                StockFactorDaily.stock_code,
                StockFactorDaily.ma5,
                StockFactorDaily.ma20,
                StockFactorDaily.ma60,
            )
            .join(Stock, Stock.stock_code == StockFactorDaily.stock_code)
            .where(
                StockFactorDaily.trade_date == trade_date,
                StockFactorDaily.source == "system:daily_close",
                Stock.status == "active",
                Stock.is_st.is_(False),
                Stock.exchange.in_(("SH", "SZ", "SSE", "SZSE")),
            )
        )
        return trade_date, {
            stock_code: {"ma5": ma5, "ma20": ma20, "ma60": ma60}
            for stock_code, ma5, ma20, ma60 in rows.all()
        }

    async def latest_post_close_limit_events(
        self,
        *,
        trade_date: date | None = None,
        lookback_trade_days: int = 20,
    ) -> dict:
        """Read one trading day's completed limit-event facts for the board ladder.

        The caller receives the provider completion evidence separately from
        event rows.  This is important because a legitimate zero-row
        `limit_list_d` response is different from a date that was never
        ingested.
        """
        active_filters = (
            Stock.status == "active",
            Stock.is_st.is_(False),
            Stock.exchange.in_(("SH", "SZ", "SSE", "SZSE")),
        )
        # The default must remain an index-friendly latest-date lookup.  An
        # explicit date is used by the historical post-close report: all of
        # its cards must read the same persisted trading-day facts rather than
        # independently choosing their own newest available date.
        target_date = trade_date
        if target_date is None:
            target_date = (await self.session.execute(select(func.max(DailyBar.trade_date)))).scalar_one_or_none()
        if target_date is None:
            return {
                "trade_date": None,
                "trade_dates": [],
                "active_count": 0,
                "daily_bar_count": 0,
                "limit_event_complete": False,
                "completion_capabilities": [],
                "events": [],
            }

        trade_dates = (
            await self.session.execute(
                select(TradeCalendar.trade_date)
                .where(
                    TradeCalendar.market == "CN",
                    TradeCalendar.is_open.is_(True),
                    TradeCalendar.trade_date <= target_date,
                )
                .order_by(TradeCalendar.trade_date.desc())
                .limit(max(2, lookback_trade_days))
            )
        ).scalars().all()
        if target_date not in trade_dates:
            trade_dates = [target_date, *trade_dates]
        trade_dates = list(dict.fromkeys(trade_dates))[: max(2, lookback_trade_days)]

        completion_rows = await self.session.execute(
            select(ProviderRawRecord.capability).where(
                ProviderRawRecord.status == "captured",
                ProviderRawRecord.normalized_table == "t_limit_event_daily",
                ProviderRawRecord.normalized_pk == target_date.isoformat(),
            )
        )
        completion_capabilities = sorted({str(value) for value in completion_rows.scalars().all() if value})
        limit_event_complete = bool(
            {"daily_market_close_stock_limit", "stock_limit_event_history_backfill"}.intersection(completion_capabilities)
        )

        active_count = (
            await self.session.execute(select(func.count()).select_from(Stock).where(*active_filters))
        ).scalar_one()
        daily_bar_count = (
            await self.session.execute(
                select(func.count())
                .select_from(DailyBar)
                .join(Stock, Stock.stock_code == DailyBar.stock_code)
                .where(DailyBar.trade_date == target_date, *active_filters)
            )
        ).scalar_one()
        rows = await self.session.execute(
            select(
                LimitEventDaily.stock_code,
                Stock.stock_name,
                LimitEventDaily.trade_date,
                LimitEventDaily.event_type,
                LimitEventDaily.close_price,
                LimitEventDaily.limit_price,
                LimitEventDaily.first_time,
                LimitEventDaily.last_time,
                LimitEventDaily.open_count,
                LimitEventDaily.turnover_amount,
                DailyBar.change_pct,
                DailyBar.amount_yuan,
            )
            .join(Stock, Stock.stock_code == LimitEventDaily.stock_code)
            .outerjoin(
                DailyBar,
                and_(
                    DailyBar.stock_code == LimitEventDaily.stock_code,
                    DailyBar.trade_date == LimitEventDaily.trade_date,
                ),
            )
            .where(
                LimitEventDaily.trade_date.in_(trade_dates),
                LimitEventDaily.event_type.in_(("limit_up", "limit_down", "limit_break")),
                *active_filters,
            )
            .order_by(LimitEventDaily.trade_date.desc(), LimitEventDaily.event_type, LimitEventDaily.stock_code)
        )
        return {
            "trade_date": target_date,
            "trade_dates": trade_dates,
            "active_count": int(active_count or 0),
            "daily_bar_count": int(daily_bar_count or 0),
            "limit_event_complete": limit_event_complete,
            "completion_capabilities": completion_capabilities,
            "events": [
                {
                    "stock_code": stock_code,
                    "stock_name": stock_name,
                    "trade_date": trade_date,
                    "event_type": event_type,
                    "close_price": close_price,
                    "limit_price": limit_price,
                    "first_time": first_time,
                    "last_time": last_time,
                    "open_count": open_count,
                    "turnover_amount": turnover_amount,
                    "change_pct": change_pct,
                    "amount_yuan": amount_yuan,
                }
                for (
                    stock_code,
                    stock_name,
                    trade_date,
                    event_type,
                    close_price,
                    limit_price,
                    first_time,
                    last_time,
                    open_count,
                    turnover_amount,
                    change_pct,
                    amount_yuan,
                ) in rows.all()
            ],
        }

    async def sector_reference(self) -> tuple[dict[str, dict], dict[str, list[str]], dict[str, list[str]]]:
        rows = await self.session.execute(
            select(
                SectorBasic.sector_code,
                SectorBasic.sector_name,
                SectorBasic.sector_type,
                SectorComponent.stock_code,
            )
            .join(SectorComponent, SectorComponent.sector_code == SectorBasic.sector_code)
            .join(Stock, Stock.stock_code == SectorComponent.stock_code)
            .where(
                SectorBasic.source.like("tushare:%"),
                SectorComponent.source.like("tushare:%"),
                SectorComponent.end_date.is_(None),
                # The intraday taxonomy deliberately keeps THS concepts as
                # the topic layer.  Industry aggregation is supplied only by
                # the separately persisted TickFlow SW1/SW2/SW3 universes
                # below, so similarly named Tushare industries cannot blend
                # into a concept/industry dashboard ranking.
                SectorBasic.sector_type == "concept",
                Stock.status == "active",
                Stock.is_st.is_(False),
                Stock.exchange.in_(("SH", "SZ", "SSE", "SZSE")),
            )
            .order_by(SectorBasic.sector_code, SectorComponent.stock_code)
        )
        sector_info: dict[str, dict] = {}
        sector_members: dict[str, list[str]] = {}
        stock_sectors: dict[str, list[str]] = {}
        for sector_code, sector_name, sector_type, stock_code in rows.all():
            sector_info.setdefault(
                sector_code,
                {"sector_code": sector_code, "sector_name": sector_name, "sector_type": sector_type, "source": "tushare"},
            )
            sector_members.setdefault(sector_code, []).append(stock_code)
            stock_sectors.setdefault(stock_code, []).append(sector_code)
        return sector_info, sector_members, stock_sectors

    async def industry_universe_reference(self) -> tuple[dict[str, dict], dict[str, list[str]], dict[str, list[str]]]:
        """Return TickFlow SW groups without blending them into Tushare concepts.

        The persisted provider universe remains traceable by raw universe ID;
        display aggregation uses the explicit logical group key generated at
        weekly catalogue sync time.
        """
        rows = await self.session.execute(
            select(
                MarketUniverse.universe_id,
                MarketUniverse.universe_name,
                MarketUniverse.taxonomy_level,
                MarketUniverse.logical_group_key,
                MarketUniverseMember.stock_code,
            )
            .join(MarketUniverseMember, MarketUniverseMember.universe_row_id == MarketUniverse.id)
            .join(Stock, Stock.stock_code == MarketUniverseMember.stock_code)
            .where(
                MarketUniverse.provider_code == "tickflow",
                MarketUniverse.is_enabled.is_(True),
                MarketUniverseMember.valid_to.is_(None),
                MarketUniverse.taxonomy_level.in_(("sw1", "sw2", "sw3")),
                Stock.status == "active",
                Stock.is_st.is_(False),
                Stock.exchange.in_(("SH", "SZ", "SSE", "SZSE")),
            )
            .order_by(MarketUniverse.taxonomy_level, MarketUniverse.logical_group_key, MarketUniverseMember.stock_code)
        )
        info: dict[str, dict] = {}
        members: dict[str, list[str]] = {}
        stock_groups: dict[str, list[str]] = {}
        for universe_id, universe_name, taxonomy_level, logical_group_key, stock_code in rows.all():
            level = str(taxonomy_level or "industry")
            group_key = str(logical_group_key or f"{level}:{universe_name}")
            sector_code = f"tickflow:{group_key}"
            group = info.setdefault(
                sector_code,
                {
                    "sector_code": sector_code,
                    "sector_name": universe_name,
                    "sector_type": "industry",
                    "taxonomy_kind": level,
                    "source": "tickflow",
                    "raw_universe_ids": [],
                },
            )
            if universe_id not in group["raw_universe_ids"]:
                group["raw_universe_ids"].append(universe_id)
            members.setdefault(sector_code, []).append(stock_code)
            stock_groups.setdefault(stock_code, []).append(sector_code)
        return info, members, stock_groups

    async def is_open_trade_date(self, trade_date: date) -> bool:
        result = await self.session.execute(
            select(TradeCalendar.is_open).where(
                TradeCalendar.trade_date == trade_date,
                TradeCalendar.market == "CN",
            )
        )
        value = result.scalar_one_or_none()
        return bool(value)

    async def pool_reference(self, active_stock_codes: list[str]) -> dict[str, dict]:
        pools = (
            await self.session.execute(
                select(StockPool, StockPoolRealtimePolicy)
                .outerjoin(StockPoolRealtimePolicy, StockPoolRealtimePolicy.pool_id == StockPool.id)
                .where(StockPool.is_enabled.is_(True))
                .order_by(StockPool.sort_order, StockPool.pool_code)
            )
        ).all()
        members = (
            await self.session.execute(
                select(StockPool.pool_code, StockPoolMember.stock_code)
                .join(StockPoolMember, StockPoolMember.pool_id == StockPool.id)
            )
        ).all()
        member_map: dict[str, list[str]] = {}
        for pool_code, stock_code in members:
            member_map.setdefault(pool_code, []).append(stock_code)
        # A strategy pool is a view over auditable candidate/trade facts, not
        # a static member list.  Loading it here keeps paper candidates inside
        # the existing hot Quote / depth / minute target policy without a
        # second realtime provider loop.
        strategy_members = await self.session.execute(
            select(StockPool.pool_code, StrategyCandidate.stock_code)
            .join(StrategyDefinition, StrategyDefinition.id == StrategyCandidate.strategy_id)
            .join(StrategyVersion, StrategyVersion.id == StrategyCandidate.strategy_version_id)
            .outerjoin(StrategyPaperTrade, StrategyPaperTrade.candidate_id == StrategyCandidate.id)
            .join(StockPool, StockPool.id == StrategyDefinition.pool_id)
            .where(
                StockPool.is_dynamic.is_(True),
                StockPool.dynamic_rule == "strategy_candidates",
                StrategyDefinition.status == "paper",
                StrategyVersion.status == "paper",
                or_(
                    and_(
                        StrategyCandidate.candidate_status.in_(("pending_confirmation", "watching")),
                        StrategyCandidate.confirmation_deadline >= date.today(),
                    ),
                    StrategyCandidate.candidate_status == "entry_triggered",
                    StrategyPaperTrade.trade_status == "open",
                ),
            )
        )
        for pool_code, stock_code in strategy_members.all():
            member_map.setdefault(pool_code, []).append(stock_code)
        active_set = set(active_stock_codes)
        result: dict[str, dict] = {}
        for pool, policy in pools:
            if pool.is_dynamic and pool.dynamic_rule == "active_a_share":
                codes = active_stock_codes
            elif pool.is_dynamic and pool.dynamic_rule == "strategy_candidates":
                codes = sorted(set(code for code in member_map.get(pool.pool_code, []) if code in active_set))
            else:
                codes = [code for code in member_map.get(pool.pool_code, []) if code in active_set]
            result[pool.pool_code] = {
                "pool_code": pool.pool_code,
                "pool_name": pool.pool_name,
                "pool_type": pool.pool_type,
                "is_dynamic": pool.is_dynamic,
                "stock_codes": codes,
                "realtime_policy": {
                    "is_enabled": bool(policy.is_enabled) if policy is not None else False,
                    "priority": int(policy.priority) if policy is not None else 1000,
                    "quote_lane": str(policy.quote_lane) if policy is not None else "off",
                    "minute_lane": str(policy.minute_lane) if policy is not None else "off",
                },
            }
        return result
