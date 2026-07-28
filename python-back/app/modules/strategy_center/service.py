from __future__ import annotations

from app.modules.strategy_center.models import StrategyDefinition, StrategyPaperTrade
from app.modules.strategy_center.repository import StrategyCenterRepository
from app.modules.strategy_center.schemas import StrategyDefinitionCreate, StrategyDefinitionUpdate


class StrategyCenterError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class StrategyCenterService:
    """Manage only the auditable research surface of the strategy lifecycle.

    The evaluator, realtime confirmation and paper-trade writer intentionally
    remain absent in this first slice.  A definition may be placed in
    ``research`` but cannot be enabled until a tested evaluator exists.
    """

    def __init__(self, repository: StrategyCenterRepository) -> None:
        self.repository = repository

    async def dashboard(self) -> dict:
        definitions = [self._read_definition(item) for item in await self.repository.list_definitions()]
        latest_signal_trade_date, candidate_counts, paper_trade_counts = await self.repository.dashboard_counts()
        return {
            "definitions": definitions,
            "latest_signal_trade_date": latest_signal_trade_date,
            "candidate_counts": candidate_counts,
            "paper_trade_counts": paper_trade_counts,
            "execution_ready": False,
            "execution_readiness_reason": "策略 evaluator、次日确认和模拟成交执行器尚未实现；当前定义只能用于研究配置。",
        }

    async def create_definition(self, payload: StrategyDefinitionCreate) -> dict:
        if await self.repository.get_definition(payload.strategy_code):
            raise StrategyCenterError("strategy_code_exists", f"策略代码已存在: {payload.strategy_code}")
        pool_code = f"strategy_{payload.strategy_code}"
        if await self.repository.get_pool(pool_code):
            raise StrategyCenterError("strategy_pool_code_exists", f"策略专属股票池代码已存在: {pool_code}")
        definition = await self.repository.create_definition_with_pool(
            definition_values={
                **payload.model_dump(),
                "status": "draft",
                "strategy_type": "short_term",
            },
            pool_code=pool_code,
        )
        await self.repository.commit()
        return self._read_definition(
            {
                "definition": definition,
                "pool_code": pool_code,
                "pool_name": f"{definition.strategy_name}策略池",
                "candidate_summary": {},
                "trade_summary": {},
            }
        )

    async def update_definition(self, strategy_code: str, payload: StrategyDefinitionUpdate) -> dict:
        definition = await self._require_definition(strategy_code)
        values = payload.model_dump(exclude_unset=True)
        if values.get("status") == "enabled":
            raise StrategyCenterError(
                "strategy_evaluator_not_available",
                "当前尚未实现经过验证的策略 evaluator，不能启用策略或开始模拟成交。可先保存为研究状态。",
            )
        updated = await self.repository.update_definition(definition, values)
        await self.repository.commit()
        definitions = await self.repository.list_definitions()
        row = next((item for item in definitions if item["definition"].strategy_code == updated.strategy_code), None)
        if row is None:  # pragma: no cover - database consistency guard.
            raise StrategyCenterError("strategy_not_found", f"策略不存在: {strategy_code}")
        return self._read_definition(row)

    async def candidates(self, *, strategy_code: str | None, signal_trade_date, limit: int) -> list[dict]:
        rows = await self.repository.list_candidates(
            strategy_code=strategy_code,
            signal_trade_date=signal_trade_date,
            limit=limit,
        )
        return [self._read_candidate(item) for item in rows]

    async def _require_definition(self, strategy_code: str) -> StrategyDefinition:
        definition = await self.repository.get_definition(strategy_code)
        if definition is None:
            raise StrategyCenterError("strategy_not_found", f"策略不存在: {strategy_code}")
        return definition

    @staticmethod
    def _read_definition(row: dict) -> dict:
        definition: StrategyDefinition = row["definition"]
        return {
            "strategy_code": definition.strategy_code,
            "strategy_name": definition.strategy_name,
            "description": definition.description,
            "status": definition.status,
            "strategy_type": definition.strategy_type,
            "entry_mode": definition.entry_mode,
            "max_holding_trade_days": definition.max_holding_trade_days,
            "rule_config": definition.rule_config or {},
            "risk_config": definition.risk_config or {},
            "pool_code": row.get("pool_code"),
            "pool_name": row.get("pool_name"),
            "candidate_summary": row.get("candidate_summary") or {},
            "trade_summary": row.get("trade_summary") or {},
            "created_at": definition.created_at,
            "updated_at": definition.updated_at,
        }

    @staticmethod
    def _read_candidate(row: dict) -> dict:
        candidate = row["candidate"]
        paper_trade: StrategyPaperTrade | None = row.get("paper_trade")
        return {
            "id": candidate.id,
            "strategy_code": row["strategy_code"],
            "strategy_name": row["strategy_name"],
            "signal_trade_date": candidate.signal_trade_date,
            "stock_code": candidate.stock_code,
            "stock_name": row.get("stock_name"),
            "candidate_status": candidate.candidate_status,
            "score": candidate.score,
            "rank_no": candidate.rank_no,
            "confirmation_deadline": candidate.confirmation_deadline,
            "candidate_snapshot": candidate.candidate_snapshot or {},
            "entry_plan": candidate.entry_plan or {},
            "outcome_note": candidate.outcome_note,
            "confirmed_at": candidate.confirmed_at,
            "paper_trade": StrategyCenterService._read_paper_trade(paper_trade),
        }

    @staticmethod
    def _read_paper_trade(paper_trade: StrategyPaperTrade | None) -> dict | None:
        if paper_trade is None:
            return None
        return {
            "trade_status": paper_trade.trade_status,
            "entry_at": paper_trade.entry_at,
            "entry_price": paper_trade.entry_price,
            "quantity": paper_trade.quantity,
            "entry_amount": paper_trade.entry_amount,
            "exit_at": paper_trade.exit_at,
            "exit_price": paper_trade.exit_price,
            "exit_amount": paper_trade.exit_amount,
            "realized_pnl_amount": paper_trade.realized_pnl_amount,
            "realized_pnl_pct": paper_trade.realized_pnl_pct,
            "risk_plan": paper_trade.risk_plan or {},
        }
