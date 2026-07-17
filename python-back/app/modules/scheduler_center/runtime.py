import asyncio
import logging
from dataclasses import dataclass
from importlib.util import find_spec
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.modules.scheduler_center.repository import SchedulerRepository
from app.modules.scheduler_center.schemas import SchedulerStatusRead
from app.modules.scheduler_center.service import SchedulerService
from app.modules.scheduler_center.validation import normalize_crontab_for_apscheduler

logger = logging.getLogger(__name__)


@dataclass
class ActiveRunTask:
    run_id: str
    job_code: str
    task: asyncio.Task
    started_at: datetime
    cancel_requested: bool = False


class SchedulerRuntime:
    def __init__(self) -> None:
        self._scheduler = None
        self._installed = False
        self._error: str | None = None
        self._active_tasks: dict[str, ActiveRunTask] = {}

    async def start(self) -> None:
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
        except ImportError as exc:
            self._installed = False
            self._error = "APScheduler is not installed"
            logger.warning("APScheduler is not installed: %s", exc)
            return

        if self._scheduler is not None:
            return
        self._installed = True
        self._error = None
        self._scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
        self._scheduler.start(paused=False)
        try:
            await self.mark_orphaned_running_runs()
            await self.reload()
            if self._error:
                if self._scheduler is not None and self._scheduler.running:
                    self._scheduler.shutdown(wait=False)
                self._scheduler = None
        except Exception as exc:
            logger.exception("scheduler startup reload failed; scheduled jobs are disabled until reload succeeds")
            self._error = self._format_error("startup_reload_failed", exc)
            if self._scheduler is not None and self._scheduler.running:
                self._scheduler.shutdown(wait=False)
            self._scheduler = None

    async def stop(self) -> None:
        active_tasks = [active.task for active in self._active_tasks.values() if not active.task.done()]
        for active in list(self._active_tasks.values()):
            active.cancel_requested = True
            active.task.cancel()
        if active_tasks:
            done, pending = await asyncio.wait(active_tasks, timeout=10)
            if pending:
                logger.warning("scheduler shutdown left pending cancelled tasks: count=%s", len(pending))
        if self._scheduler is not None and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        self._scheduler = None

    async def mark_orphaned_running_runs(self) -> int:
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            repository = SchedulerRepository(session)
            count = await repository.mark_orphaned_running_runs(
                error_code="scheduler_orphaned_after_restart",
                error_message="application restarted while this scheduler run was still marked running",
            )
            await repository.commit()
        if count:
            logger.warning("marked orphaned scheduler runs after restart: count=%s", count)
        return count

    def start_background_execution(self, run_id: str, job_code: str, payload: dict) -> asyncio.Task:
        task = asyncio.create_task(
            self._execute_job_task(run_id, job_code, payload),
            name=f"scheduler:{job_code}:{run_id}",
        )
        self._track_task(run_id, job_code, task)
        return task

    def cancel_run(self, run_id: str) -> bool:
        active = self._active_tasks.get(run_id)
        if active is None or active.task.done():
            return False
        active.cancel_requested = True
        active.task.cancel()
        logger.info("scheduler run cancellation requested: run_id=%s job_code=%s", run_id, active.job_code)
        return True

    def is_run_active(self, run_id: str) -> bool:
        active = self._active_tasks.get(run_id)
        return active is not None and not active.task.done()

    async def reload(self) -> SchedulerStatusRead:
        if self._scheduler is None:
            await self.start()
            return self.status()
        try:
            self._scheduler.remove_all_jobs()
            self._error = None
            registered = 0
            sessionmaker = get_sessionmaker()
            async with sessionmaker() as session:
                repository = SchedulerRepository(session)
                await repository.clear_all_next_run_at()
                jobs = await repository.list_enabled_cron_jobs()
                for job in jobs:
                    try:
                        self._register_job(job)
                        aps_job = self._scheduler.get_job(job.job_code)
                        await repository.update_job_runtime(
                            job.job_code,
                            next_run_at=aps_job.next_run_time if aps_job else None,
                        )
                        registered += 1
                    except Exception as exc:
                        logger.exception("failed to register scheduled job %s", job.job_code)
                        self._error = f"{job.job_code}: {exc}"
                await repository.commit()
            logger.info("registered %s scheduled jobs", registered)
        except Exception as exc:
            logger.exception("scheduler reload failed")
            self._error = self._format_error("reload_failed", exc)
            if self._scheduler is not None:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown(wait=False)
                self._scheduler = None
        return self.status()

    def status(self) -> SchedulerStatusRead:
        settings = get_settings()
        installed = self._installed or find_spec("apscheduler") is not None
        if self._scheduler is None:
            return SchedulerStatusRead(
                enabled=settings.scheduler_enabled,
                installed=installed,
                running=False,
                job_count=0,
                jobs=[],
                active_runs=self._active_run_summaries(),
                error=self._error,
            )
        jobs = [
            {
                "job_code": job.id,
                "name": job.name,
                "next_run_at": job.next_run_time.isoformat() if job.next_run_time else None,
                "trigger": str(job.trigger),
            }
            for job in self._scheduler.get_jobs()
        ]
        return SchedulerStatusRead(
            enabled=settings.scheduler_enabled,
            installed=installed,
            running=self._scheduler.running,
            job_count=len(jobs),
            jobs=jobs,
            active_runs=self._active_run_summaries(),
            error=self._error,
        )

    def _register_job(self, job) -> None:
        from apscheduler.triggers.cron import CronTrigger

        timezone = ZoneInfo(job.timezone or "Asia/Shanghai")
        trigger = CronTrigger.from_crontab(normalize_crontab_for_apscheduler(job.cron_expr), timezone=timezone)
        self._scheduler.add_job(
            self._run_job,
            trigger=trigger,
            id=job.job_code,
            name=job.job_name,
            args=[job.job_code],
            max_instances=job.max_instances,
            misfire_grace_time=job.misfire_grace_seconds,
            replace_existing=True,
        )

    async def _run_job(self, job_code: str) -> None:
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            repository = SchedulerRepository(session)
            job = await repository.get_job(job_code)
            if job is None or not job.is_enabled:
                return
            service = SchedulerService(repository)
            run = None
            try:
                run = await service.start_job(job_code, payload=job.default_payload or {}, trigger_source="cron")
                current_task = asyncio.current_task()
                if current_task is not None:
                    self._track_task(run.run_id, job_code, current_task)
                await service.execute_started_job(run.run_id, job_code, run.payload)
            finally:
                if run is not None:
                    self._active_tasks.pop(run.run_id, None)
                aps_job = self._scheduler.get_job(job_code) if self._scheduler is not None else None
                await repository.update_job_runtime(
                    job_code,
                    next_run_at=aps_job.next_run_time if aps_job else None,
                    last_run_at=datetime.now(tz=ZoneInfo(job.timezone or "Asia/Shanghai")),
                )
                await repository.commit()

    async def _execute_job_task(self, run_id: str, job_code: str, payload: dict) -> None:
        sessionmaker = get_sessionmaker()
        try:
            async with sessionmaker() as session:
                await SchedulerService(SchedulerRepository(session)).execute_started_job(run_id, job_code, payload)
        finally:
            self._active_tasks.pop(run_id, None)

    def _track_task(self, run_id: str, job_code: str, task: asyncio.Task) -> None:
        self._active_tasks[run_id] = ActiveRunTask(
            run_id=run_id,
            job_code=job_code,
            task=task,
            started_at=datetime.now(timezone.utc),
        )
        task.add_done_callback(lambda _task: self._active_tasks.pop(run_id, None))

    def _active_run_summaries(self) -> list[dict]:
        return [
            {
                "run_id": active.run_id,
                "job_code": active.job_code,
                "started_at": active.started_at.isoformat(),
                "cancel_requested": active.cancel_requested,
            }
            for active in self._active_tasks.values()
            if not active.task.done()
        ]

    @staticmethod
    def _format_error(prefix: str, exc: Exception) -> str:
        return f"{prefix}: {type(exc).__name__}: {str(exc).splitlines()[0]}"


scheduler_runtime = SchedulerRuntime()
