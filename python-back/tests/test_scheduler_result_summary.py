from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from app.modules.scheduler_center.service import SchedulerService


def test_finish_run_json_encodes_result_summary_values() -> None:
    class Repository:
        def __init__(self) -> None:
            self.values = None

        async def update_run(self, _run_id, values):
            self.values = values
            return SimpleNamespace(
                id=1,
                run_id="run-1",
                job_code="daily_market_close_ingest",
                trigger_source="manual",
                status=values["status"],
                payload={},
                affected_rows=values["affected_rows"],
                started_at=datetime(2026, 6, 27, tzinfo=timezone.utc),
                finished_at=values["finished_at"],
                error_code=values["error_code"],
                error_message=values["error_message"],
                result_summary=values["result_summary"],
                created_at=datetime(2026, 6, 27, tzinfo=timezone.utc),
            )

        async def commit(self):
            return None

    repository = Repository()
    service = SchedulerService(repository)
    asyncio.run(
        service._finish_run(
            "run-1",
            status="success",
            affected_rows=1,
            result_summary={
                "trade_date": date(2026, 6, 26),
                "finished_at": datetime(2026, 6, 27, 10, 30, tzinfo=timezone.utc),
                "amount": Decimal("12.34"),
            },
        )
    )

    assert repository.values["result_summary"] == {
        "trade_date": "2026-06-26",
        "finished_at": "2026-06-27T10:30:00+00:00",
        "amount": 12.34,
    }
