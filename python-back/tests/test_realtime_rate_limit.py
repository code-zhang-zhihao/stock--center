import asyncio

from app.modules.realtime_market.rate_limit import RealtimeRateBudget


def test_rate_budget_uses_configured_eighty_percent_safety_budget():
    async def run() -> None:
        budget = RealtimeRateBudget("depth", purchased_limit=60, safety_ratio=0.8)
        assert budget.safe_limit == 48
        for _ in range(3):
            await budget.acquire()
        snapshot = await budget.snapshot()
        assert snapshot["purchased_limit_per_minute"] == 60
        assert snapshot["safe_budget_per_minute"] == 48
        assert snapshot["used_requests_in_window"] == 3
        assert snapshot["remaining_requests_in_window"] == 45

    asyncio.run(run())


def test_rate_budget_retains_server_cooldown_for_following_requests():
    async def run() -> None:
        budget = RealtimeRateBudget("quote", purchased_limit=20, safety_ratio=0.8)
        await budget.record_rate_limit(2)
        snapshot = await budget.snapshot()
        assert snapshot["rate_limited_count"] == 1
        assert snapshot["cooldown_remaining_seconds"] > 0
        assert await budget.next_delay() > 0

    asyncio.run(run())
