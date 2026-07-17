from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.market_data.models import SectorBasic, SectorComponent, Stock, TradeCalendar
from app.modules.stock_pool.models import StockPool, StockPoolMember


class RealtimeMarketRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def active_stock_reference(self) -> tuple[list[str], dict[str, str]]:
        rows = await self.session.execute(
            select(Stock.stock_code, Stock.stock_name)
            .where(
                Stock.status == "active",
                Stock.exchange.in_(("SH", "SZ", "SSE", "SZSE")),
            )
            .order_by(Stock.stock_code)
        )
        pairs = rows.all()
        return [row.stock_code for row in pairs], {row.stock_code: row.stock_name for row in pairs}

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
                SectorBasic.sector_type.in_(("concept", "industry")),
                Stock.status == "active",
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
                select(StockPool)
                .where(StockPool.is_enabled.is_(True))
                .order_by(StockPool.sort_order, StockPool.pool_code)
            )
        ).scalars().all()
        members = (
            await self.session.execute(
                select(StockPool.pool_code, StockPoolMember.stock_code)
                .join(StockPoolMember, StockPoolMember.pool_id == StockPool.id)
            )
        ).all()
        member_map: dict[str, list[str]] = {}
        for pool_code, stock_code in members:
            member_map.setdefault(pool_code, []).append(stock_code)
        active_set = set(active_stock_codes)
        result: dict[str, dict] = {}
        for pool in pools:
            if pool.is_dynamic and pool.dynamic_rule == "active_a_share":
                codes = active_stock_codes
            else:
                codes = [code for code in member_map.get(pool.pool_code, []) if code in active_set]
            result[pool.pool_code] = {
                "pool_code": pool.pool_code,
                "pool_name": pool.pool_name,
                "pool_type": pool.pool_type,
                "is_dynamic": pool.is_dynamic,
                "stock_codes": codes,
            }
        return result
