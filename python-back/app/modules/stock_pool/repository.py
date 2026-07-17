from datetime import datetime, timezone

from sqlalchemy import and_, case, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.market_data.models import SectorBasic, SectorComponent, Stock
from app.modules.stock_pool.models import StockPool, StockPoolMember


class StockPoolRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_pools(self) -> list[dict]:
        result = await self.session.execute(
            select(StockPool, func.count(StockPoolMember.id).label("member_count"))
            .outerjoin(StockPoolMember, StockPoolMember.pool_id == StockPool.id)
            .group_by(StockPool.id)
            .order_by(StockPool.is_system.desc(), StockPool.sort_order, StockPool.pool_code)
        )
        rows = []
        for pool, member_count in result.all():
            resolved_count = int(member_count)
            if pool.is_dynamic and pool.dynamic_rule == "active_a_share":
                resolved_count = int(await self.session.scalar(select(func.count()).select_from(Stock).where(Stock.status == "active")) or 0)
            rows.append({"pool": pool, "member_count": resolved_count})
        return rows

    async def get_pool(self, pool_code: str) -> StockPool | None:
        result = await self.session.execute(select(StockPool).where(StockPool.pool_code == pool_code))
        return result.scalar_one_or_none()

    async def create_pool(self, values: dict) -> StockPool:
        result = await self.session.execute(insert(StockPool).values(**values).returning(StockPool))
        return result.scalar_one()

    async def update_pool(self, pool_code: str, values: dict) -> StockPool | None:
        if not values:
            return await self.get_pool(pool_code)
        result = await self.session.execute(
            update(StockPool)
            .where(StockPool.pool_code == pool_code)
            .values(**values, updated_at=datetime.now(timezone.utc))
            .returning(StockPool)
        )
        return result.scalar_one_or_none()

    async def delete_pool(self, pool_code: str) -> StockPool | None:
        result = await self.session.execute(delete(StockPool).where(StockPool.pool_code == pool_code).returning(StockPool))
        return result.scalar_one_or_none()

    async def list_members(self, *, pool_id: int, keyword: str | None, page: int, page_size: int) -> tuple[list[dict], int]:
        filters = [StockPoolMember.pool_id == pool_id]
        if keyword:
            like = f"%{keyword}%"
            filters.append(or_(StockPoolMember.stock_code.ilike(like), Stock.stock_name.ilike(like)))
        total = int(
            await self.session.scalar(
                select(func.count())
                .select_from(StockPoolMember)
                .outerjoin(Stock, Stock.stock_code == StockPoolMember.stock_code)
                .where(*filters)
            )
            or 0
        )
        rows = (
            await self.session.execute(
                select(StockPoolMember.stock_code, Stock.stock_name, StockPoolMember.created_at)
                .outerjoin(Stock, Stock.stock_code == StockPoolMember.stock_code)
                .where(*filters)
                .order_by(StockPoolMember.created_at.desc(), StockPoolMember.stock_code)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).mappings().all()
        return [dict(row) for row in rows], total

    async def list_dynamic_active_members(self, *, keyword: str | None, page: int, page_size: int) -> tuple[list[dict], int]:
        filters = [Stock.status == "active"]
        if keyword:
            like = f"%{keyword}%"
            filters.append(or_(Stock.stock_code.ilike(like), Stock.stock_name.ilike(like)))
        total = int(await self.session.scalar(select(func.count()).select_from(Stock).where(*filters)) or 0)
        rows = (
            await self.session.execute(
                select(Stock.stock_code, Stock.stock_name, Stock.updated_at.label("created_at"))
                .where(*filters)
                .order_by(Stock.stock_code)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).mappings().all()
        return [dict(row) for row in rows], total

    async def search_candidate_stocks(self, *, pool_id: int, keyword: str, limit: int) -> list[dict]:
        like = f"%{keyword}%"
        prefix = f"{keyword}%"
        rows = (
            await self.session.execute(
                select(
                    Stock.stock_code,
                    Stock.stock_name,
                    StockPoolMember.id.is_not(None).label("is_member"),
                )
                .outerjoin(
                    StockPoolMember,
                    and_(
                        StockPoolMember.pool_id == pool_id,
                        StockPoolMember.stock_code == Stock.stock_code,
                    ),
                )
                .where(
                    Stock.status == "active",
                    or_(Stock.stock_code.ilike(like), Stock.stock_name.ilike(like)),
                )
                .order_by(
                    case(
                        (Stock.stock_code.ilike(prefix), 0),
                        (Stock.stock_name.ilike(prefix), 1),
                        else_=2,
                    ),
                    Stock.stock_code,
                )
                .limit(limit)
            )
        ).mappings().all()
        return [dict(row) for row in rows]

    async def existing_stock_codes(self, stock_codes: list[str]) -> set[str]:
        if not stock_codes:
            return set()
        result = await self.session.execute(select(Stock.stock_code).where(Stock.stock_code.in_(stock_codes)))
        return set(result.scalars().all())

    async def existing_member_codes(self, *, pool_id: int, stock_codes: list[str]) -> set[str]:
        if not stock_codes:
            return set()
        result = await self.session.execute(
            select(StockPoolMember.stock_code).where(
                StockPoolMember.pool_id == pool_id,
                StockPoolMember.stock_code.in_(stock_codes),
            )
        )
        return set(result.scalars().all())

    async def add_members(self, *, pool_id: int, stock_codes: list[str]) -> int:
        if not stock_codes:
            return 0
        result = await self.session.execute(
            insert(StockPoolMember)
            .values([{"pool_id": pool_id, "stock_code": stock_code} for stock_code in stock_codes])
            .on_conflict_do_nothing(index_elements=[StockPoolMember.pool_id, StockPoolMember.stock_code])
        )
        return int(result.rowcount or 0)

    async def delete_member(self, *, pool_id: int, stock_code: str) -> bool:
        result = await self.session.execute(
            delete(StockPoolMember)
            .where(StockPoolMember.pool_id == pool_id, StockPoolMember.stock_code == stock_code)
            .returning(StockPoolMember.id)
        )
        return result.scalar_one_or_none() is not None

    async def get_member_detail(self, *, pool_id: int, pool_code: str, stock_code: str) -> dict | None:
        stock = (
            await self.session.execute(
                select(Stock)
                .join(StockPoolMember, StockPoolMember.stock_code == Stock.stock_code)
                .where(StockPoolMember.pool_id == pool_id, Stock.stock_code == stock_code)
            )
        ).scalar_one_or_none()
        if stock is None:
            return None
        sector_rows = (
            await self.session.execute(
                select(
                    SectorBasic.sector_code,
                    SectorBasic.sector_name,
                    SectorBasic.sector_type,
                    SectorBasic.source,
                )
                .join(SectorComponent, SectorComponent.sector_code == SectorBasic.sector_code)
                .where(
                    SectorComponent.stock_code == stock_code,
                    SectorBasic.source.like("tushare:%"),
                    SectorComponent.source.like("tushare:%"),
                    SectorBasic.sector_type.in_(["concept", "industry"]),
                )
                .order_by(SectorBasic.sector_type, SectorBasic.sector_name, SectorBasic.sector_code)
            )
        ).mappings().all()
        concepts = [dict(row) for row in sector_rows if row["sector_type"] == "concept"]
        industries = [dict(row) for row in sector_rows if row["sector_type"] == "industry"]
        return {
            "pool_code": pool_code,
            "stock_code": stock.stock_code,
            "stock_name": stock.stock_name,
            "market": stock.market,
            "exchange": stock.exchange,
            "list_date": stock.list_date,
            "status": stock.status,
            "industry": stock.industry,
            "area": stock.area,
            "concepts": concepts,
            "industries": industries,
        }

    async def get_dynamic_member_detail(self, *, pool_code: str, stock_code: str) -> dict | None:
        stock = (await self.session.execute(select(Stock).where(Stock.stock_code == stock_code, Stock.status == "active"))).scalar_one_or_none()
        if stock is None:
            return None
        sector_rows = (
            await self.session.execute(
                select(SectorBasic.sector_code, SectorBasic.sector_name, SectorBasic.sector_type, SectorBasic.source)
                .join(SectorComponent, SectorComponent.sector_code == SectorBasic.sector_code)
                .where(
                    SectorComponent.stock_code == stock_code,
                    SectorBasic.source.like("tushare:%"),
                    SectorComponent.source.like("tushare:%"),
                    SectorBasic.sector_type.in_(["concept", "industry"]),
                )
                .order_by(SectorBasic.sector_type, SectorBasic.sector_name, SectorBasic.sector_code)
            )
        ).mappings().all()
        return {
            "pool_code": pool_code,
            "stock_code": stock.stock_code,
            "stock_name": stock.stock_name,
            "market": stock.market,
            "exchange": stock.exchange,
            "list_date": stock.list_date,
            "status": stock.status,
            "industry": stock.industry,
            "area": stock.area,
            "concepts": [dict(row) for row in sector_rows if row["sector_type"] == "concept"],
            "industries": [dict(row) for row in sector_rows if row["sector_type"] == "industry"],
        }

    async def commit(self) -> None:
        await self.session.commit()
