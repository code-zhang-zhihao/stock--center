from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from time import monotonic


class TushareRateLimitTimeout(RuntimeError):
    def __init__(self, retry_after_seconds: float) -> None:
        super().__init__(f"Tushare local rate limit wait exceeds caller budget; retry after {retry_after_seconds:.1f}s")
        self.retry_after_seconds = retry_after_seconds


class TushareRateCoordinator:
    """Process-wide sliding-window limiter keyed by configured Token id."""

    def __init__(self) -> None:
        self._requests: dict[int, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def acquire(self, value_id: int, per_minute: int, max_wait_seconds: float) -> None:
        await self.reserve([(value_id, per_minute)], max_wait_seconds)

    async def reserve(self, candidates: list[tuple[int, int]], max_wait_seconds: float) -> int:
        """Reserve the first currently available token, waiting only when all are busy."""
        if not candidates or any(per_minute < 1 for _, per_minute in candidates):
            raise ValueError("rate_limit_per_minute must be positive and candidates must not be empty")
        deadline = monotonic() + max(max_wait_seconds, 0)
        while True:
            async with self._lock:
                now = monotonic()
                waits: list[float] = []
                for value_id, per_minute in candidates:
                    slots = self._requests[value_id]
                    while slots and now - slots[0] >= 60:
                        slots.popleft()
                    if len(slots) < per_minute:
                        slots.append(now)
                        return value_id
                    waits.append(max(60 - (now - slots[0]), 0))
                wait_seconds = min(waits)
            if now + wait_seconds > deadline:
                raise TushareRateLimitTimeout(wait_seconds)
            await asyncio.sleep(wait_seconds)


tushare_rate_coordinator = TushareRateCoordinator()
