import logging
from importlib.util import find_spec
from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.modules.scheduler_center.repository import SchedulerRepository
from app.modules.scheduler_center.schemas import SchedulerStatusRead
from app.modules.scheduler_center.service import SchedulerService

logger = logging.getLogger(__name__)

_CRONTAB_DOW_NAMES = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")


def _map_crontab_weekday(value: int) -> str:
    if value == 7:
        value = 0
    return _CRONTAB_DOW_NAMES[value]


def _expand_crontab_weekday_range(start: int, end: int, step: int = 1) -> list[str]:
    if start == 7:
        start = 0
    if end == 7:
        end = 0
    values = list(range(start, end + 1)) if start <= end else [*range(start, 7), *range(0, end + 1)]
    return [_map_crontab_weekday(value) for value in values[::step]]


def _normalize_crontab_weekday_token(token: str) -> str:
    if not token or any(char.isalpha() for char in token):
        return token
    base, separator, step_text = token.partition("/")
    step = int(step_text) if separator and step_text.isdigit() and int(step_text) > 0 else 1
    if base == "*":
        return token
    if "-" in base:
        start_text, end_text = base.split("-", 1)
        if start_text.isdigit() and end_text.isdigit():
            return ",".join(_expand_crontab_weekday_range(int(start_text), int(end_text), step))
        return token
    if base.isdigit():
        return _map_crontab_weekday(int(base))
    return token


def normalize_crontab_for_apscheduler(cron_expr: str) -> str:
    parts = cron_expr.split()
    if len(parts) != 5:
        return cron_expr
    weekday = parts[4]
    if weekday not in {"*", "?"}:
        parts[4] = ",".join(_normalize_crontab_weekday_token(token) for token in weekday.split(","))
    return " ".join(parts)


class SchedulerRuntime:
    def __init__(self) -> None:
        self._scheduler = None
        self._installed = False
        self._error: str | None = None

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
        await self.reload()

    async def stop(self) -> None:
        if self._scheduler is not None and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        self._scheduler = None

    async def reload(self) -> SchedulerStatusRead:
        if self._scheduler is None:
            await self.start()
            return self.status()
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
            try:
                await service.run_job(job_code, payload=job.default_payload or {}, trigger_source="cron")
            finally:
                aps_job = self._scheduler.get_job(job_code) if self._scheduler is not None else None
                await repository.update_job_runtime(
                    job_code,
                    next_run_at=aps_job.next_run_time if aps_job else None,
                    last_run_at=datetime.now(tz=ZoneInfo(job.timezone or "Asia/Shanghai")),
                )
                await repository.commit()


scheduler_runtime = SchedulerRuntime()
