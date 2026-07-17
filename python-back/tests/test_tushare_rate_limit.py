import asyncio
from time import monotonic

from app.modules.market_data.tushare.rate_limit import TushareRateCoordinator, TushareRateLimitTimeout


def test_shared_rate_gate_rejects_interactive_wait_beyond_budget() -> None:
    async def run() -> None:
        coordinator = TushareRateCoordinator()
        await coordinator.acquire(1, 1, 0)
        try:
            await coordinator.acquire(1, 1, 0)
        except TushareRateLimitTimeout as exc:
            assert exc.retry_after_seconds > 0
        else:
            raise AssertionError("second request must respect the shared window")

    asyncio.run(run())


def test_shared_rate_gate_releases_expired_window() -> None:
    async def run() -> None:
        coordinator = TushareRateCoordinator()
        coordinator._requests[7].append(monotonic() - 61)
        await coordinator.acquire(7, 1, 0)

    asyncio.run(run())


def test_shared_rate_gate_prefers_next_immediately_available_token() -> None:
    async def run() -> None:
        coordinator = TushareRateCoordinator()
        await coordinator.acquire(1, 1, 0)
        selected = await coordinator.reserve([(1, 1), (2, 1)], 0)
        assert selected == 2

    asyncio.run(run())
