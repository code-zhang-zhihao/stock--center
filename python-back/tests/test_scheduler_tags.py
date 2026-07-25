from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from app.modules.scheduler_center.service import SchedulerService


def _job(job_code: str = "daily_close_core_ingest") -> SimpleNamespace:
    now = datetime(2026, 7, 25, tzinfo=timezone.utc)
    return SimpleNamespace(
        id=1,
        job_code=job_code,
        job_name="每日收盘核心数据沉淀",
        job_type="market_data",
        description="test",
        parameter_schema={},
        trigger_type="cron",
        cron_expr="0 18 * * 1-5",
        timezone="Asia/Shanghai",
        default_payload={},
        max_instances=1,
        misfire_grace_seconds=300,
        timeout_seconds=3600,
        retry_count=1,
        retry_interval_seconds=300,
        next_run_at=None,
        last_run_at=None,
        is_enabled=True,
        is_system=True,
        is_hidden=False,
        metadata_json={},
        created_at=now,
        updated_at=now,
    )


def test_list_jobs_filters_by_tag_and_returns_job_tags() -> None:
    class Repository:
        async def list_jobs(self, *, include_hidden, tag_code):
            assert include_hidden is False
            assert tag_code == "daily"
            return [_job()]

        async def list_job_tags(self, job_codes):
            assert job_codes == ["daily_close_core_ingest"]
            return {
                "daily_close_core_ingest": [
                    {"tag_code": "daily", "tag_name": "每日", "sort_order": 20}
                ]
            }

    rows = asyncio.run(SchedulerService(Repository()).list_jobs(tag_code="daily"))

    assert len(rows) == 1
    assert rows[0].job_code == "daily_close_core_ingest"
    assert [(tag.tag_code, tag.tag_name) for tag in rows[0].tags] == [("daily", "每日")]


def test_job_read_keeps_empty_tag_list_for_unclassified_job() -> None:
    result = SchedulerService._job_read(_job("refresh_data_asset_health"))

    assert result.tags == []
