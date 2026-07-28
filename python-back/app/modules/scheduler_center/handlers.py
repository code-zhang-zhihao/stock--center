from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol

from app.modules.scheduler_center.schemas import JobResult


@dataclass(slots=True)
class JobExecutionContext:
    run_id: str
    job_code: str
    trigger_source: str
    payload: dict
    progress_reporter: Callable[[dict], Awaitable[None]] | None = None

    async def report_progress(self, progress: dict) -> None:
        """Persist a small, best-effort progress snapshot for an active run.

        Handlers must never depend on this for correctness: the scheduler can
        still complete a job when the status write is temporarily unavailable.
        It exists so long-running manual jobs do not look indistinguishable
        from a stalled job in the task center.
        """
        if self.progress_reporter is not None:
            await self.progress_reporter(progress)


class JobHandler(Protocol):
    job_code: str
    job_type: str
    parameter_schema: dict
    default_payload: dict
    force_async: bool

    async def run(self, context: JobExecutionContext) -> JobResult:
        ...


class JobHandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, JobHandler] = {}

    def register(self, handler: JobHandler) -> None:
        self._handlers[handler.job_code] = handler

    def get(self, job_code: str) -> JobHandler | None:
        return self._handlers.get(job_code)

    def codes(self) -> list[str]:
        return sorted(self._handlers)


job_handler_registry = JobHandlerRegistry()
