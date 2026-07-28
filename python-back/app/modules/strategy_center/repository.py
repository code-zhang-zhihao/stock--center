from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.market_data.models import Stock
from app.modules.stock_pool.models import StockPool, StockPoolRealtimePolicy
from app.modules.strategy_center.models import StrategyCandidate, StrategyDefinition, StrategyPaperTrade


class StrategyCenterRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_definitions(self) -> list[dict]:
        rows = await self.session.execute(
            select(StrategyDefinition, StockPool.pool_code, StockPool.pool_name)
            .outerjoin(StockPool, StockPool.id == StrategyDefinition.pool_id)
            .order_by(StrategyDefinition.updated_at.desc(), StrategyDefinition.strategy_code)
        )
        definitions = [
            {"definition": definition, "pool_code": pool_code, "pool_name": pool_name}
            for definition, pool_code, pool_name in rows.all()
        ]
        if not definitions:
            return []
        strategy_ids = [item["definition"].id for item in definitions]
        candidate_rows = await self.session.execute(
            select(
                StrategyCandidate.strategy_id,
                func.count(StrategyCandidate.id).label("total_count"),
                func.max(StrategyCandidate.signal_trade_date).label("latest_signal_trade_date"),
                func.count(StrategyCandidate.id).filter(
                    StrategyCandidate.candidate_status.in_(("pending_confirmation", "watching"))
                ).label("awaiting_count"),
                func.count(StrategyCandidate.id).filter(
                    StrategyCandidate.candidate_status == "not_triggered"
                ).label("not_triggered_count"),
            )
            .where(StrategyCandidate.strategy_id.in_(strategy_ids))
            .group_by(StrategyCandidate.strategy_id)
        )
        candidate_summary = {
            row.strategy_id: {
                "total_count": int(row.total_count or 0),
                "latest_signal_trade_date": row.latest_signal_trade_date,
                "awaiting_count": int(row.awaiting_count or 0),
                "not_triggered_count": int(row.not_triggered_count or 0),
            }
            for row in candidate_rows
        }
        trade_rows = await self.session.execute(
            select(
                StrategyPaperTrade.strategy_id,
                func.count(StrategyPaperTrade.id).label("total_count"),
                func.count(StrategyPaperTrade.id).filter(StrategyPaperTrade.trade_status == "open").label("open_count"),
                func.count(StrategyPaperTrade.id).filter(StrategyPaperTrade.trade_status == "closed").label("closed_count"),
                func.avg(StrategyPaperTrade.realized_pnl_pct).filter(
                    StrategyPaperTrade.trade_status == "closed"
                ).label("average_realized_pnl_pct"),
            )
            .where(StrategyPaperTrade.strategy_id.in_(strategy_ids))
            .group_by(StrategyPaperTrade.strategy_id)
        )
        trade_summary = {
            row.strategy_id: {
                "total_count": int(row.total_count or 0),
                "open_count": int(row.open_count or 0),
                "closed_count": int(row.closed_count or 0),
                "average_realized_pnl_pct": _number_or_none(row.average_realized_pnl_pct),
            }
            for row in trade_rows
        }
        for item in definitions:
            strategy_id = item["definition"].id
            item["candidate_summary"] = candidate_summary.get(strategy_id, _empty_candidate_summary())
            item["trade_summary"] = trade_summary.get(strategy_id, _empty_trade_summary())
        return definitions

    async def get_definition(self, strategy_code: str) -> StrategyDefinition | None:
        return (
            await self.session.execute(
                select(StrategyDefinition).where(StrategyDefinition.strategy_code == strategy_code)
            )
        ).scalar_one_or_none()

    async def get_pool(self, pool_code: str) -> StockPool | None:
        return (await self.session.execute(select(StockPool).where(StockPool.pool_code == pool_code))).scalar_one_or_none()

    async def create_definition_with_pool(self, *, definition_values: dict, pool_code: str) -> StrategyDefinition:
        pool = StockPool(
            pool_code=pool_code,
            pool_name=f"{definition_values['strategy_name']}策略池",
            pool_type="strategy",
            description="由策略候选事实动态维护；不能手工修改成员。",
            is_system=True,
            is_enabled=True,
            is_dynamic=True,
            dynamic_rule="strategy_candidates",
            sort_order=50,
        )
        self.session.add(pool)
        await self.session.flush()
        self.session.add(
            StockPoolRealtimePolicy(
                pool_id=pool.id,
                is_enabled=False,
                priority=30,
                quote_lane="off",
                minute_lane="off",
            )
        )
        definition = StrategyDefinition(pool_id=pool.id, **definition_values)
        self.session.add(definition)
        await self.session.flush()
        return definition

    async def update_definition(self, definition: StrategyDefinition, values: dict) -> StrategyDefinition:
        for field, value in values.items():
            setattr(definition, field, value)
        definition.updated_at = datetime.now(timezone.utc)
        pool_values: dict = {"updated_at": definition.updated_at}
        if "strategy_name" in values:
            pool_values["pool_name"] = f"{definition.strategy_name}策略池"
        if "status" in values:
            # A strategy-owned pool is system managed. Archiving a strategy
            # removes stale candidates from active pool views; restoring a
            # draft/research definition makes its dedicated pool visible again.
            pool_values["is_enabled"] = definition.status != "archived"
        if definition.pool_id is not None:
            await self.session.execute(
                update(StockPool).where(StockPool.id == definition.pool_id).values(**pool_values)
            )
        await self.session.flush()
        return definition

    async def list_candidates(
        self,
        *,
        strategy_code: str | None,
        signal_trade_date: date | None,
        limit: int,
    ) -> list[dict]:
        statement = (
            select(
                StrategyCandidate,
                StrategyDefinition.strategy_code,
                StrategyDefinition.strategy_name,
                Stock.stock_name,
                StrategyPaperTrade,
            )
            .join(StrategyDefinition, StrategyDefinition.id == StrategyCandidate.strategy_id)
            .outerjoin(Stock, Stock.stock_code == StrategyCandidate.stock_code)
            .outerjoin(StrategyPaperTrade, StrategyPaperTrade.candidate_id == StrategyCandidate.id)
        )
        if strategy_code:
            statement = statement.where(StrategyDefinition.strategy_code == strategy_code)
        if signal_trade_date:
            statement = statement.where(StrategyCandidate.signal_trade_date == signal_trade_date)
        rows = await self.session.execute(
            statement.order_by(
                StrategyCandidate.signal_trade_date.desc(),
                StrategyCandidate.rank_no.asc().nulls_last(),
                StrategyCandidate.score.desc().nulls_last(),
                StrategyCandidate.stock_code,
            ).limit(limit)
        )
        return [
            {
                "candidate": candidate,
                "strategy_code": code,
                "strategy_name": name,
                "stock_name": stock_name,
                "paper_trade": paper_trade,
            }
            for candidate, code, name, stock_name, paper_trade in rows.all()
        ]

    async def dashboard_counts(self) -> tuple[date | None, dict, dict]:
        latest_signal_trade_date = await self.session.scalar(select(func.max(StrategyCandidate.signal_trade_date)))
        candidate_rows = await self.session.execute(
            select(StrategyCandidate.candidate_status, func.count(StrategyCandidate.id)).group_by(
                StrategyCandidate.candidate_status
            )
        )
        trade_rows = await self.session.execute(
            select(StrategyPaperTrade.trade_status, func.count(StrategyPaperTrade.id)).group_by(StrategyPaperTrade.trade_status)
        )
        return (
            latest_signal_trade_date,
            {str(status): int(count or 0) for status, count in candidate_rows.all()},
            {str(status): int(count or 0) for status, count in trade_rows.all()},
        )

    async def commit(self) -> None:
        await self.session.commit()


def _number_or_none(value) -> float | None:
    return float(value) if value is not None else None


def _empty_candidate_summary() -> dict:
    return {
        "total_count": 0,
        "latest_signal_trade_date": None,
        "awaiting_count": 0,
        "not_triggered_count": 0,
    }


def _empty_trade_summary() -> dict:
    return {
        "total_count": 0,
        "open_count": 0,
        "closed_count": 0,
        "average_realized_pnl_pct": None,
    }
