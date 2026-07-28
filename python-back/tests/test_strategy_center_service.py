from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from app.modules.strategy_center.schemas import StrategyDefinitionCreate, StrategyDefinitionUpdate
from app.modules.strategy_center.service import StrategyCenterError, StrategyCenterService, _qualifies_for_paper_review


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

    async def create_version(self, **_kwargs):
        return SimpleNamespace(version_no=1)

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
                strategy_code="my_first_board_theme_relay",
                strategy_name="首板主线接力（研究）",
                implementation_code="theme_first_board_relay",
                entry_mode="auction",
                max_holding_trade_days=2,
            )
        )
        assert repository.created_pool_code == "strategy_my_first_board_theme_relay"
        assert created["status"] == "draft"
        assert created["pool_code"] == "strategy_my_first_board_theme_relay"
        assert repository.committed == 1

    asyncio.run(run())


def test_strategy_cannot_be_placed_in_paper_mode_without_version_validation() -> None:
    async def run() -> None:
        repository = FakeRepository()
        service = StrategyCenterService(repository)
        await service.create_definition(
            StrategyDefinitionCreate(
                strategy_code="my_trend_breakout",
                strategy_name="趋势突破（研究）",
                implementation_code="trend_breakout",
                entry_mode="open",
                max_holding_trade_days=5,
            )
        )
        try:
            await service.update_definition("my_trend_breakout", StrategyDefinitionUpdate(status="paper"))
        except StrategyCenterError as exc:
            assert exc.code == "strategy_status_invalid"
        else:
            raise AssertionError("strategy paper mode must require a validated version")

    asyncio.run(run())


def test_builtin_strategy_rejects_confirmation_mode_that_conflicts_with_implementation() -> None:
    async def run() -> None:
        service = StrategyCenterService(FakeRepository())
        try:
            await service.create_definition(
                StrategyDefinitionCreate(
                    strategy_code="wrong_mode_breakout",
                    strategy_name="错误确认时点",
                    implementation_code="trend_breakout",
                    entry_mode="auction",
                    max_holding_trade_days=5,
                )
            )
        except StrategyCenterError as exc:
            assert exc.code == "strategy_contract_mismatch"
        else:
            raise AssertionError("builtin execution contract must not be overridden by definition fields")

    asyncio.run(run())


def test_dashboard_states_that_no_execution_or_paper_trade_is_running() -> None:
    async def run() -> None:
        dashboard = await StrategyCenterService(FakeRepository()).dashboard()
        assert dashboard["execution_ready"] is False
        assert "完成 next_open_daily 基线回测" in dashboard["execution_readiness_reason"]
        assert dashboard["candidate_counts"] == {}
        assert dashboard["paper_trade_counts"] == {}

    asyncio.run(run())


def test_paper_review_requires_broad_history_as_well_as_closed_trades() -> None:
    assert not _qualifies_for_paper_review({"signal_trade_date_count": 10, "completed_trade_count": 500, "win_rate_pct": 60, "average_net_return_pct": 1})
    assert not _qualifies_for_paper_review({"signal_trade_date_count": 120, "completed_trade_count": 299, "win_rate_pct": 60, "average_net_return_pct": 1})
    assert not _qualifies_for_paper_review({"signal_trade_date_count": 120, "completed_trade_count": 300, "win_rate_pct": 49.9, "average_net_return_pct": 1})
    assert not _qualifies_for_paper_review({"signal_trade_date_count": 120, "completed_trade_count": 300, "win_rate_pct": 50, "average_net_return_pct": 0})
    assert _qualifies_for_paper_review({"signal_trade_date_count": 120, "completed_trade_count": 300, "win_rate_pct": 50, "average_net_return_pct": 0.01})
