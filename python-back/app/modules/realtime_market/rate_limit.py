from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
import time


@dataclass
class RealtimeRateBudget:
    """A small sliding-window request budget with observable server cooldown.

    The configured vendor quota stays visible as ``purchased_limit`` while
    dispatch uses the lower, safety-adjusted limit.  It intentionally counts
    provider requests rather than symbols because TickFlow bills/limits the
    documented endpoints by request frequency.
    """

    name: str
    purchased_limit: int
    safety_ratio: float = 0.8
    window_seconds: float = 60.0
    _request_times: deque[float] = field(default_factory=deque)
    _cooldown_until: float = 0.0
    _rate_limited_count: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def safe_limit(self) -> int:
        return max(1, int(self.purchased_limit * self.safety_ratio))

    async def acquire(self) -> None:
        while True:
            delay = await self.next_delay()
            if delay <= 0:
                async with self._lock:
                    now = time.monotonic()
                    self._trim(now)
                    if now >= self._cooldown_until and len(self._request_times) < self.safe_limit:
                        self._request_times.append(now)
                        return
                continue
            await asyncio.sleep(delay)

    async def next_delay(self) -> float:
        async with self._lock:
            now = time.monotonic()
            self._trim(now)
            cooldown_delay = self._cooldown_until - now
            if cooldown_delay > 0:
                return cooldown_delay
            if len(self._request_times) < self.safe_limit:
                return 0.0
            return max(0.001, self._request_times[0] + self.window_seconds - now)

    async def record_rate_limit(self, cooldown_seconds: float | None) -> None:
        async with self._lock:
            self._rate_limited_count += 1
            cooldown = max(0.0, float(cooldown_seconds or 0.0))
            self._cooldown_until = max(self._cooldown_until, time.monotonic() + cooldown)

    async def snapshot(self) -> dict:
        async with self._lock:
            now = time.monotonic()
            self._trim(now)
            return {
                "purchased_limit_per_minute": self.purchased_limit,
                "safety_ratio": self.safety_ratio,
                "safe_budget_per_minute": self.safe_limit,
                "used_requests_in_window": len(self._request_times),
                "remaining_requests_in_window": max(0, self.safe_limit - len(self._request_times)),
                "cooldown_remaining_seconds": max(0, round(self._cooldown_until - now, 3)),
                "rate_limited_count": self._rate_limited_count,
            }

    def _trim(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._request_times and self._request_times[0] <= cutoff:
            self._request_times.popleft()
