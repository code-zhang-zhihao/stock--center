from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from app.modules.strategy_center.schemas import StrategyDefinitionCreate, StrategyDefinitionUpdate
from app.modules.strategy_center.service import StrategyCenterError, StrategyCenterService


class FakeRepository:
    def __init__(self) -> None:
        self.definition = None
        self.created_pool_code = None
        self.committed = 0

    async def get_definition(self, strategy_code):
        return self.definition if self.definition and self.definition.strategy_code == strategy_code else None

    async def get_pool(self, _pool_code):
        return None

    async def create_definition_with_pool(self, *, definition_values, pool_code):
        now = datetime.now(timezone.utc)
        self.created_pool_code = pool_code
        self.definition = SimpleNamespace(
            id=1,
            created_at=now,
            updated_at=now,
            pool_id=10,
            **definition_values,
        )
        return self.definition

    async def update_definition(self, definition, values):
        for key, value in values.items():
            setattr(definition, key, value)
        return definition

    async def list_definitions(self):
        if self.definition is None:
            return []
        return [{
            "definition": self.definition,
            "pool_code": self.created_pool_code,
            "pool_name": f"{self.definition.strategy_name}策略池",
            "candidate_summary": {},
            "trade_summary": {},
        }]

    async def dashboard_counts(self):
        return None, {}, {}

    async def list_candidates(self, **_kwargs):
        return []

    async def commit(self):
        self.committed += 1


def test_create_strategy_creates_a_dedicated_dynamic_pool_name() -> None:
    async def run() -> None:
        repository = FakeRepository()
        service = StrategyCenterService(repository)
        created = await service.create_definition(
            StrategyDefinitionCreate(
                strategy_code="first_board_theme_relay",
                strategy_name="首板主线接力（研究）",
                entry_mode="auction",
                max_holding_trade_days=3,
            )
        )
        assert repository.created_pool_code == "strategy_first_board_theme_relay"
        assert created["status"] == "draft"
        assert created["pool_code"] == "strategy_first_board_theme_relay"
        assert repository.committed == 1

    asyncio.run(run())


def test_strategy_cannot_be_enabled_before_evaluator_exists() -> None:
    async def run() -> None:
        repository = FakeRepository()
        service = StrategyCenterService(repository)
        await service.create_definition(
            StrategyDefinitionCreate(strategy_code="research_rule", strategy_name="研究规则")
        )
        try:
            await service.update_definition("research_rule", StrategyDefinitionUpdate(status="enabled"))
        except StrategyCenterError as exc:
            assert exc.code == "strategy_evaluator_not_available"
        else:
            raise AssertionError("strategy enable must be rejected before evaluator implementation")

    asyncio.run(run())


def test_dashboard_states_that_no_execution_or_paper_trade_is_running() -> None:
    async def run() -> None:
        dashboard = await StrategyCenterService(FakeRepository()).dashboard()
        assert dashboard["execution_ready"] is False
        assert "尚未实现" in dashboard["execution_readiness_reason"]
        assert dashboard["candidate_counts"] == {}
        assert dashboard["paper_trade_counts"] == {}

    asyncio.run(run())
