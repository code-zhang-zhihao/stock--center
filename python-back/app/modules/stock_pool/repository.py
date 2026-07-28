from datetime import datetime, timezone

from sqlalchemy import and_, case, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.market_data.models import MarketUniverse, MarketUniverseMember, SectorBasic, SectorComponent, Stock
from app.modules.stock_pool.models import StockPool, StockPoolMember, StockPoolRealtimePolicy
from app.modules.strategy_center.models import StrategyCandidate, StrategyDefinition


class StockPoolRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_pools(self) -> list[dict]:
        result = await self.session.execute(
            select(StockPool, StockPoolRealtimePolicy, func.count(StockPoolMember.id).label("member_count"))
            .outerjoin(StockPoolMember, StockPoolMember.pool_id == StockPool.id)
            .outerjoin(StockPoolRealtimePolicy, StockPoolRealtimePolicy.pool_id == StockPool.id)
            .group_by(StockPool.id, StockPoolRealtimePolicy.pool_id)
            .order_by(StockPool.is_system.desc(), StockPool.sort_order, StockPool.pool_code)
        )
        rows = []
        for pool, policy, member_count in result.all():
            resolved_count = int(member_count)
            if pool.is_dynamic and pool.dynamic_rule == "active_a_share":
                resolved_count = int(await self.session.scalar(select(func.count()).select_from(Stock).where(Stock.status == "active")) or 0)
            elif pool.is_dynamic and pool.dynamic_rule == "strategy_candidates":
                resolved_count = await self.strategy_candidate_member_count(pool_id=pool.id)
            rows.append({"pool": pool, "policy": policy, "member_count": resolved_count})
        return rows

    async def get_pool(self, pool_code: str) -> StockPool | None:
        result = await self.session.execute(select(StockPool).where(StockPool.pool_code == pool_code))
        return result.scalar_one_or_none()

    async def create_pool(self, values: dict) -> StockPool:
        result = await self.session.execute(insert(StockPool).values(**values).returning(StockPool))
        return result.scalar_one()

    async def create_realtime_policy(self, pool_id: int, values: dict | None = None) -> StockPoolRealtimePolicy:
        resolved_values = {
            "is_enabled": False,
            "priority": 1000,
            "quote_lane": "off",
            "minute_lane": "off",
            **(values or {}),
        }
        result = await self.session.execute(
            insert(StockPoolRealtimePolicy)
            .values(pool_id=pool_id, **resolved_values)
            .on_conflict_do_nothing(index_elements=[StockPoolRealtimePolicy.pool_id])
            .returning(StockPoolRealtimePolicy)
        )
        policy = result.scalar_one_or_none()
        if policy is not None:
            return policy
        existing = await self.get_realtime_policy(pool_id)
        if existing is None:  # pragma: no cover - database invariant guard.
            raise RuntimeError(f"realtime policy create failed for stock pool {pool_id}")
        return existing

    async def get_realtime_policy(self, pool_id: int) -> StockPoolRealtimePolicy | None:
        return await self.session.get(StockPoolRealtimePolicy, pool_id)

    async def update_realtime_policy(self, pool_id: int, values: dict) -> StockPoolRealtimePolicy:
        await self.create_realtime_policy(pool_id)
        result = await self.session.execute(
            update(StockPoolRealtimePolicy)
            .where(StockPoolRealtimePolicy.pool_id == pool_id)
            .values(**values, updated_at=datetime.now(timezone.utc))
            .returning(StockPoolRealtimePolicy)
        )
        policy = result.scalar_one_or_none()
        if policy is None:  # pragma: no cover - database invariant guard.
            raise RuntimeError(f"realtime policy update failed for stock pool {pool_id}")
        return policy

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

    async def strategy_candidate_member_count(self, *, pool_id: int) -> int:
        return int(
            await self.session.scalar(
                select(func.count(func.distinct(StrategyCandidate.stock_code)))
                .join(StrategyDefinition, StrategyDefinition.id == StrategyCandidate.strategy_id)
                .where(
                    StrategyDefinition.pool_id == pool_id,
                    StrategyDefinition.status != "archived",
                    StrategyCandidate.candidate_status.in_(("pending_confirmation", "watching")),
                )
            )
            or 0
        )

    async def list_strategy_candidate_members(
        self,
        *,
        pool_id: int,
        keyword: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[dict], int]:
        latest_per_stock = (
            select(
                StrategyCandidate.strategy_id,
                StrategyCandidate.stock_code,
                func.max(StrategyCandidate.signal_trade_date).label("signal_trade_date"),
            )
            .join(StrategyDefinition, StrategyDefinition.id == StrategyCandidate.strategy_id)
            .where(
                StrategyDefinition.pool_id == pool_id,
                StrategyDefinition.status != "archived",
                StrategyCandidate.candidate_status.in_(("pending_confirmation", "watching")),
            )
            .group_by(StrategyCandidate.strategy_id, StrategyCandidate.stock_code)
            .subquery()
        )
        filters = []
        if keyword:
            like = f"%{keyword}%"
            filters.append(or_(StrategyCandidate.stock_code.ilike(like), Stock.stock_name.ilike(like)))
        total = int(
            await self.session.scalar(
                select(func.count())
                .select_from(latest_per_stock)
                .join(
                    StrategyCandidate,
                    and_(
                        StrategyCandidate.strategy_id == latest_per_stock.c.strategy_id,
                        StrategyCandidate.stock_code == latest_per_stock.c.stock_code,
                        StrategyCandidate.signal_trade_date == latest_per_stock.c.signal_trade_date,
                    ),
                )
                .outerjoin(Stock, Stock.stock_code == StrategyCandidate.stock_code)
                .where(*filters)
            )
            or 0
        )
        rows = (
            await self.session.execute(
                select(
                    StrategyCandidate.stock_code,
                    Stock.stock_name,
                    StrategyCandidate.created_at,
                )
                .join(
                    latest_per_stock,
                    and_(
                        StrategyCandidate.strategy_id == latest_per_stock.c.strategy_id,
                        StrategyCandidate.stock_code == latest_per_stock.c.stock_code,
                        StrategyCandidate.signal_trade_date == latest_per_stock.c.signal_trade_date,
                    ),
                )
                .outerjoin(Stock, Stock.stock_code == StrategyCandidate.stock_code)
                .where(*filters)
                .order_by(StrategyCandidate.signal_trade_date.desc(), StrategyCandidate.rank_no.asc().nulls_last(), StrategyCandidate.stock_code)
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

    async def get_strategy_candidate_member_detail(self, *, pool_id: int, pool_code: str, stock_code: str) -> dict | None:
        exists = await self.session.scalar(
            select(StrategyCandidate.id)
            .join(StrategyDefinition, StrategyDefinition.id == StrategyCandidate.strategy_id)
            .where(
                StrategyDefinition.pool_id == pool_id,
                StrategyDefinition.status != "archived",
                StrategyCandidate.stock_code == stock_code,
                StrategyCandidate.candidate_status.in_(("pending_confirmation", "watching")),
            )
            .limit(1)
        )
        if exists is None:
            return None
        return await self.get_dynamic_member_detail(pool_code=pool_code, stock_code=stock_code)

    async def stock_profile(self, stock_code: str) -> dict | None:
        """Unified membership profile; categories remain intentionally separate."""
        stock = (await self.session.execute(select(Stock).where(Stock.stock_code == stock_code))).scalar_one_or_none()
        if stock is None:
            return None
        tushare_rows = (
            await self.session.execute(
                select(SectorBasic.sector_code, SectorBasic.sector_name, SectorBasic.sector_type, SectorBasic.source)
                .join(SectorComponent, SectorComponent.sector_code == SectorBasic.sector_code)
                .where(
                    SectorComponent.stock_code == stock_code,
                    SectorComponent.end_date.is_(None),
                    SectorBasic.source.like("tushare:%"),
                    SectorComponent.source.like("tushare:%"),
                    SectorBasic.sector_type.in_(["concept", "industry"]),
                )
                .order_by(SectorBasic.sector_type, SectorBasic.sector_name)
            )
        ).mappings().all()
        tickflow_rows = (
            await self.session.execute(
                select(
                    MarketUniverse.universe_id,
                    MarketUniverse.universe_name,
                    MarketUniverse.taxonomy_level,
                    MarketUniverse.logical_group_key,
                )
                .join(MarketUniverseMember, MarketUniverseMember.universe_row_id == MarketUniverse.id)
                .where(
                    MarketUniverse.provider_code == "tickflow",
                    MarketUniverseMember.stock_code == stock_code,
                    MarketUniverseMember.valid_to.is_(None),
                    MarketUniverse.taxonomy_level.in_(["sw1", "sw2", "sw3"]),
                )
                .order_by(MarketUniverse.taxonomy_level, MarketUniverse.universe_name, MarketUniverse.universe_id)
            )
        ).mappings().all()
        pool_rows = (
            await self.session.execute(
                select(
                    StockPool.pool_code,
                    StockPool.pool_name,
                    StockPool.pool_type,
                    StockPool.is_system,
                    StockPoolRealtimePolicy.is_enabled.label("realtime_enabled"),
                    StockPoolRealtimePolicy.priority.label("realtime_priority"),
                    StockPoolRealtimePolicy.quote_lane,
                    StockPoolRealtimePolicy.minute_lane,
                )
                .join(StockPoolMember, StockPoolMember.pool_id == StockPool.id)
                .outerjoin(StockPoolRealtimePolicy, StockPoolRealtimePolicy.pool_id == StockPool.id)
                .where(StockPoolMember.stock_code == stock_code, StockPool.is_enabled.is_(True))
                .order_by(StockPool.sort_order, StockPool.pool_code)
            )
        ).mappings().all()
        return {
            "stock_code": stock.stock_code,
            "stock_name": stock.stock_name,
            "market": stock.market,
            "exchange": stock.exchange,
            "status": stock.status,
            "is_st": stock.is_st,
            "tushare_industry": stock.industry,
            "eligible_for_emotion_and_strategy": stock.status == "active" and not stock.is_st and stock.exchange in {"SH", "SZ", "SSE", "SZSE"},
            "concepts": [dict(row) for row in tushare_rows if row["sector_type"] == "concept"],
            "tushare_industries": [dict(row) for row in tushare_rows if row["sector_type"] == "industry"],
            "sw_industries": [dict(row) for row in tickflow_rows],
            "stock_pools": [dict(row) for row in pool_rows],
        }

    async def list_catalog(self, *, scope: str | None = None) -> list[dict]:
        """List monitor pools, concepts and industries through one typed catalogue."""
        items: list[dict] = []
        if scope in {None, "system", "strategy", "user"}:
            for row in await self.list_pools():
                pool = row["pool"]
                policy = row["policy"]
                # A strategy-owned dynamic pool is system-managed so users
                # cannot mix manual members into its candidate set, but it is
                # still a strategy pool in the catalogue rather than a generic
                # system pool.
                category = "strategy" if pool.pool_type == "strategy" else ("system" if pool.is_system else "user")
                if scope not in {None, category}:
                    continue
                items.append(
                    {
                        "catalog_type": category,
                        "item_code": pool.pool_code,
                        "item_name": pool.pool_name,
                        "member_count": row["member_count"],
                        "source": "stock_pool",
                        "updated_at": pool.updated_at,
                        "is_enabled": pool.is_enabled,
                        "realtime_policy": self.realtime_policy_dict(policy),
                    }
                )
        if scope in {None, "topic"}:
            rows = await self.session.execute(
                select(SectorBasic.sector_code, SectorBasic.sector_name, func.count(SectorComponent.id), SectorBasic.source, SectorBasic.updated_at)
                .outerjoin(SectorComponent, and_(SectorComponent.sector_code == SectorBasic.sector_code, SectorComponent.end_date.is_(None)))
                .where(SectorBasic.sector_type == "concept", SectorBasic.source.like("tushare:%"))
                .group_by(SectorBasic.id)
                .order_by(SectorBasic.sector_name)
            )
            items.extend(
                {
                    "catalog_type": "topic",
                    "item_code": code,
                    "item_name": name,
                    "member_count": int(count),
                    "source": source,
                    "updated_at": updated_at,
                    "is_enabled": True,
                }
                for code, name, count, source, updated_at in rows.all()
            )
        if scope in {None, "industry"}:
            rows = await self.session.execute(
                select(
                    MarketUniverse.logical_group_key,
                    MarketUniverse.universe_name,
                    MarketUniverse.taxonomy_level,
                    func.count(MarketUniverseMember.id),
                    func.max(MarketUniverse.last_synced_at),
                )
                .join(MarketUniverseMember, MarketUniverseMember.universe_row_id == MarketUniverse.id)
                .where(
                    MarketUniverse.provider_code == "tickflow",
                    MarketUniverse.taxonomy_level.in_(["sw1", "sw2", "sw3"]),
                    MarketUniverseMember.valid_to.is_(None),
                )
                .group_by(MarketUniverse.logical_group_key, MarketUniverse.universe_name, MarketUniverse.taxonomy_level)
                .order_by(MarketUniverse.taxonomy_level, MarketUniverse.universe_name)
            )
            items.extend(
                {
                    "catalog_type": "industry",
                    "item_code": f"tickflow:{logical_group_key or f'{level}:{name}'}",
                    "item_name": name,
                    "member_count": int(count),
                    "source": f"tickflow:{level}",
                    "updated_at": updated_at,
                    "is_enabled": True,
                }
                for logical_group_key, name, level, count, updated_at in rows.all()
            )
        return items

    @staticmethod
    def realtime_policy_dict(policy: StockPoolRealtimePolicy | None) -> dict:
        return {
            "is_enabled": bool(policy.is_enabled) if policy is not None else False,
            "priority": int(policy.priority) if policy is not None else 1000,
            "quote_lane": str(policy.quote_lane) if policy is not None else "off",
            "minute_lane": str(policy.minute_lane) if policy is not None else "off",
            "updated_at": policy.updated_at if policy is not None else None,
        }

    async def commit(self) -> None:
        await self.session.commit()
