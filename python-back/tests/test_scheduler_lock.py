from __future__ import annotations

import asyncio

import app.modules.scheduler_center.repository as scheduler_repository
from app.modules.scheduler_center.repository import SchedulerRepository


def test_advisory_unlock_failure_does_not_fail_job(monkeypatch) -> None:
    class FakeResult:
        @staticmethod
        def scalar_one() -> bool:
            return True

    class FakeConnection:
        unlock_called = False
        closed = False

        async def execute(self, statement):
            if "pg_advisory_unlock" in str(statement):
                self.unlock_called = True
                raise ConnectionError("connection is closed")
            return FakeResult()

        async def commit(self) -> None:
            return None

        async def close(self) -> None:
            self.closed = True

    class FakeEngine:
        def __init__(self, connection: FakeConnection) -> None:
            self.connection = connection

        async def connect(self) -> FakeConnection:
            return self.connection

    connection = FakeConnection()
    monkeypatch.setattr(scheduler_repository, "get_engine", lambda: FakeEngine(connection))
    repository = SchedulerRepository(session=None)  # type: ignore[arg-type]

    async def run() -> None:
        async with repository.hold_advisory_lock("backfill_sector_daily_factors") as locked:
            assert locked is True

    asyncio.run(run())
    assert connection.unlock_called is True
    assert connection.closed is True


def test_advisory_lock_connection_close_failure_is_swallowed(monkeypatch) -> None:
    class FakeResult:
        @staticmethod
        def scalar_one() -> bool:
            return False

    class FakeConnection:
        async def execute(self, _statement):
            return FakeResult()

        async def close(self) -> None:
            raise ConnectionError("close failed")

    class FakeEngine:
        def __init__(self, connection: FakeConnection) -> None:
            self.connection = connection

        async def connect(self) -> FakeConnection:
            return self.connection

    monkeypatch.setattr(scheduler_repository, "get_engine", lambda: FakeEngine(FakeConnection()))
    repository = SchedulerRepository(session=None)  # type: ignore[arg-type]

    async def run() -> None:
        async with repository.hold_advisory_lock("another_job") as locked:
            assert locked is False

    asyncio.run(run())
