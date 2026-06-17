from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from app.modules.scheduler_center.schemas import JobResult


@dataclass(slots=True)
class JobExecutionContext:
    run_id: str
    job_code: str
    trigger_source: str
    payload: dict


class JobHandler(Protocol):
    job_code: str
    job_type: str
    parameter_schema: dict
    default_payload: dict
    force_async: bool

    async def run(self, context: JobExecutionContext) -> JobResult:
        ...


class SchedulerNoopHandler:
    job_code = "scheduler_noop"
    job_type = "maintenance"
    parameter_schema = {
        "echo": {
            "label": "回显内容",
            "type": "string",
            "required": False,
            "description": "调度中心 smoke test 使用的回显文本。",
        }
    }
    default_payload = {"echo": "ok"}
    force_async = False

    async def run(self, context: JobExecutionContext) -> JobResult:
        return JobResult(
            affected_rows=0,
            summary={
                "message": "scheduler noop executed",
                "payload": context.payload,
                "executed_at": datetime.now(timezone.utc).isoformat(),
            },
        )


class JobHandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, JobHandler] = {}
        self.register(SchedulerNoopHandler())

    def register(self, handler: JobHandler) -> None:
        self._handlers[handler.job_code] = handler

    def get(self, job_code: str) -> JobHandler | None:
        return self._handlers.get(job_code)

    def codes(self) -> list[str]:
        return sorted(self._handlers)


job_handler_registry = JobHandlerRegistry()
