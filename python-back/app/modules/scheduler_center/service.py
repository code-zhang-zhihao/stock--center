import asyncio
import logging
from datetime import datetime, timezone
from uuid import uuid4

from fastapi.encoders import jsonable_encoder

from app.core.config import get_settings
from app.modules.scheduler_center.handlers import JobExecutionContext, job_handler_registry
from app.modules.scheduler_center.models import SchedulerJob, SchedulerJobRun
from app.modules.scheduler_center.repository import SchedulerRepository
from app.modules.scheduler_center.schemas import (
    JobResult,
    SchedulerJobCreate,
    SchedulerJobRead,
    SchedulerJobTagRead,
    SchedulerJobUpdate,
    SchedulerRunRead,
    SchedulerTagRead,
)
from app.modules.scheduler_center.validation import CronValidationError, PayloadValidationError, validate_cron_expr, validate_payload

_execution_semaphore: asyncio.Semaphore | None = None
logger = logging.getLogger(__name__)


class SchedulerError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _get_execution_semaphore() -> asyncio.Semaphore:
    global _execution_semaphore
    if _execution_semaphore is None:
        limit = max(int(get_settings().scheduler_max_concurrent_jobs or 1), 1)
        _execution_semaphore = asyncio.Semaphore(limit)
    return _execution_semaphore


class SchedulerService:
    def __init__(self, repository: SchedulerRepository) -> None:
        self.repository = repository

    async def list_jobs(
        self,
        *,
        include_hidden: bool = False,
        tag_code: str | None = None,
    ) -> list[SchedulerJobRead]:
        rows = await self.repository.list_jobs(include_hidden=include_hidden, tag_code=tag_code)
        tags_by_job = await self.repository.list_job_tags([row.job_code for row in rows])
        return [self._job_read(row, tags=tags_by_job.get(row.job_code, [])) for row in rows]

    async def list_tags(self) -> list[SchedulerTagRead]:
        return [SchedulerTagRead(**row) for row in await self.repository.list_tags()]

    async def get_job(self, job_code: str) -> SchedulerJobRead | None:
        row = await self.repository.get_job(job_code)
        if row is None:
            return None
        tags = (await self.repository.list_job_tags([job_code])).get(job_code, [])
        return self._job_read(row, tags=tags)

    async def create_or_update_job(self, payload: SchedulerJobCreate) -> SchedulerJobRead:
        values = self._job_create_values(payload)
        self._validate_job_configuration(values)
        row = await self.repository.upsert_job(values)
        await self.repository.commit()
        return self._job_read(row)

    async def update_job(self, job_code: str, payload: SchedulerJobUpdate) -> SchedulerJobRead | None:
        existing = await self.repository.get_job(job_code)
        if existing is None:
            return None
        values = self._job_update_values(payload)
        self._validate_job_configuration(values, existing=existing)
        row = await self.repository.update_job(job_code, values)
        await self.repository.commit()
        return self._job_read(row) if row else None

    async def delete_job(self, job_code: str) -> SchedulerJobRead | None:
        row = await self.repository.delete_job(job_code)
        await self.repository.commit()
        return self._job_read(row) if row else None

    async def set_job_enabled(self, job_code: str, enabled: bool) -> SchedulerJobRead | None:
        row = await self.repository.set_job_enabled(job_code, enabled)
        await self.repository.commit()
        return self._job_read(row) if row else None

    async def start_job(
        self,
        job_code: str,
        *,
        payload: dict | None = None,
        trigger_source: str = "manual",
    ) -> SchedulerRunRead:
        job = await self.repository.get_job(job_code)
        if job is None:
            raise SchedulerError("job_not_found", f"job not found: {job_code}")
        handler = job_handler_registry.get(job_code)
        if handler is None:
            raise SchedulerError("job_handler_not_found", f"job handler not found: {job_code}")
        run_payload = {**dict(job.default_payload or {}), **dict(payload or {})}
        self._validate_payload_for_job(job, run_payload)
        now = datetime.now(timezone.utc)
        run = await self.repository.record_run(
            {
                "run_id": uuid4().hex,
                "job_code": job_code,
                "trigger_source": trigger_source,
                "status": "running",
                "payload": run_payload,
                "affected_rows": 0,
                "started_at": now,
                "result_summary": {},
            }
        )
        await self.repository.update_job_runtime(job_code, last_run_at=now)
        await self.repository.commit()
        logger.info(
            "scheduler job started: run_id=%s job_code=%s trigger=%s payload_keys=%s",
            run.run_id,
            job_code,
            trigger_source,
            sorted(run_payload),
        )
        return self._run_read(run)

    async def run_job(
        self,
        job_code: str,
        *,
        payload: dict | None = None,
        trigger_source: str = "manual",
    ) -> SchedulerRunRead:
        run = await self.start_job(job_code, payload=payload, trigger_source=trigger_source)
        return await self.execute_started_job(run.run_id, job_code, run.payload)

    async def execute_started_job(self, run_id: str, job_code: str, payload: dict) -> SchedulerRunRead:
        job = await self.repository.get_job(job_code)
        if job is None:
            return await self._finish_run(
                run_id,
                status="failed",
                error_code="job_not_found",
                error_message=f"job not found: {job_code}",
            )
        handler = job_handler_registry.get(job_code)
        if handler is None:
            return await self._finish_run(
                run_id,
                status="failed",
                error_code="job_handler_not_found",
                error_message=f"job handler not found: {job_code}",
            )

        locked = False
        try:
            locked = await self.repository.try_advisory_lock(job_code)
            if not locked:
                logger.info("scheduler job skipped: run_id=%s job_code=%s reason=already_running", run_id, job_code)
                return await self._finish_run(
                    run_id,
                    status="skipped",
                    error_code="already_running",
                    error_message=f"job already running: {job_code}",
                )

            async with _get_execution_semaphore():
                run_row = await self.repository.get_run(run_id)
                trigger_source = run_row.trigger_source if run_row else "manual"
                result = await self._run_with_retry(run_id, job, payload, trigger_source)
                logger.info(
                    "scheduler job finished: run_id=%s job_code=%s status=%s affected_rows=%s",
                    run_id,
                    job_code,
                    result.status,
                    result.affected_rows,
                )
                return await self._finish_run(
                    run_id,
                    status=result.status,
                    affected_rows=result.affected_rows,
                    result_summary=result.summary,
                )
        except TimeoutError as exc:
            logger.warning("scheduler job timeout: run_id=%s job_code=%s error=%s", run_id, job_code, exc)
            return await self._finish_run(run_id, status="timeout", error_code="job_timeout", error_message=str(exc))
        except asyncio.CancelledError:
            logger.info("scheduler job cancelled: run_id=%s job_code=%s", run_id, job_code)
            try:
                await self.repository.rollback()
            except Exception:
                logger.exception("scheduler rollback failed before marking job cancelled: run_id=%s job_code=%s", run_id, job_code)
            return await asyncio.shield(
                self._finish_run(
                    run_id,
                    status="cancelled",
                    error_code="job_cancelled",
                    error_message="job cancellation requested",
                )
            )
        except Exception as exc:
            details = getattr(exc, "details", None)
            error_code = getattr(exc, "code", None) or "job_failed"
            logger.exception("scheduler job failed: run_id=%s job_code=%s error_code=%s", run_id, job_code, error_code)
            try:
                await self.repository.rollback()
            except Exception:
                logger.exception("scheduler rollback failed before marking job failed: run_id=%s job_code=%s", run_id, job_code)
            return await self._finish_run(
                run_id,
                status="failed",
                error_code=error_code if isinstance(error_code, str) else "job_failed",
                error_message=str(exc),
                result_summary=details if isinstance(details, dict) else None,
            )
        finally:
            if locked:
                try:
                    await self.repository.advisory_unlock(job_code)
                    await self.repository.commit()
                except Exception:
                    await self.repository.rollback()

    async def _run_with_retry(
        self,
        run_id: str,
        job: SchedulerJob,
        payload: dict,
        trigger_source: str,
    ) -> JobResult:
        attempts = 0
        max_attempts = max(int(job.retry_count or 0) + 1, 1)
        last_error: Exception | None = None
        while attempts < max_attempts:
            attempts += 1
            try:
                return await self._run_once(run_id, job, payload, trigger_source)
            except TimeoutError:
                raise
            except Exception as exc:
                last_error = exc
                if attempts >= max_attempts:
                    break
                logger.info(
                    "scheduler job retrying: run_id=%s job_code=%s attempt=%s next_delay_seconds=%s error=%s",
                    run_id,
                    job.job_code,
                    attempts,
                    int(job.retry_interval_seconds or 60),
                    exc,
                )
                await asyncio.sleep(int(job.retry_interval_seconds or 60))
        if last_error:
            raise last_error
        return JobResult()

    async def _run_once(self, run_id: str, job: SchedulerJob, payload: dict, trigger_source: str) -> JobResult:
        handler = job_handler_registry.get(job.job_code)
        if handler is None:
            raise SchedulerError("job_handler_not_found", f"job handler not found: {job.job_code}")
        context = JobExecutionContext(
            run_id=run_id,
            job_code=job.job_code,
            trigger_source=trigger_source,
            payload=payload,
        )
        timeout_seconds = int(job.timeout_seconds or 0)
        if timeout_seconds > 0:
            return await asyncio.wait_for(handler.run(context), timeout=timeout_seconds)
        return await handler.run(context)

    async def _finish_run(
        self,
        run_id: str,
        *,
        status: str,
        affected_rows: int = 0,
        error_code: str | None = None,
        error_message: str | None = None,
        result_summary: dict | None = None,
    ) -> SchedulerRunRead:
        values = {
            "status": status,
            "affected_rows": affected_rows,
            "finished_at": datetime.now(timezone.utc),
            "error_code": error_code,
            "error_message": error_message,
            "result_summary": jsonable_encoder(result_summary or {}),
        }
        try:
            row = await self._finish_run_with_repository(self.repository, run_id, values)
        except Exception:
            logger.exception(
                "scheduler finish run failed on current session, retrying with a fresh session: run_id=%s status=%s",
                run_id,
                status,
            )
            try:
                await self.repository.rollback()
            except Exception:
                logger.exception("scheduler rollback failed after finish-run connection error: run_id=%s", run_id)

            from app.db.session import get_sessionmaker

            async with get_sessionmaker() as session:
                row = await self._finish_run_with_repository(SchedulerRepository(session), run_id, values)
        if row is None:
            raise SchedulerError("job_run_not_found", f"job run not found: {run_id}")
        return self._run_read(row)

    @staticmethod
    async def _finish_run_with_repository(
        repository: SchedulerRepository,
        run_id: str,
        values: dict,
    ) -> SchedulerJobRun | None:
        row = await repository.update_run(run_id, values)
        await repository.commit()
        return row

    async def cancel_run_record(self, run_id: str, *, error_code: str, error_message: str) -> SchedulerRunRead | None:
        row = await self.repository.cancel_running_run(
            run_id,
            error_code=error_code,
            error_message=error_message,
        )
        await self.repository.commit()
        if row is not None:
            return self._run_read(row)
        existing = await self.repository.get_run(run_id)
        return self._run_read(existing) if existing else None

    @staticmethod
    def _job_create_values(payload: SchedulerJobCreate) -> dict:
        data = payload.model_dump()
        data["metadata_json"] = data.pop("metadata", {})
        data["is_system"] = False
        return data

    @staticmethod
    def _job_update_values(payload: SchedulerJobUpdate) -> dict:
        data = payload.model_dump(exclude_unset=True)
        if "metadata" in data:
            data["metadata_json"] = data.pop("metadata")
        return data

    @staticmethod
    def _validate_job_configuration(values: dict, *, existing: SchedulerJob | None = None) -> None:
        timezone = values.get("timezone") if "timezone" in values else getattr(existing, "timezone", "Asia/Shanghai")
        cron_expr = values.get("cron_expr") if "cron_expr" in values else getattr(existing, "cron_expr", None)
        schema = values.get("parameter_schema") if "parameter_schema" in values else getattr(existing, "parameter_schema", {})
        default_payload = values.get("default_payload") if "default_payload" in values else getattr(existing, "default_payload", {})
        legacy_unknown = set(getattr(existing, "default_payload", {}) or {}) - set(schema or {})
        try:
            validate_cron_expr(cron_expr, timezone=timezone or "Asia/Shanghai")
        except CronValidationError as exc:
            raise SchedulerError("invalid_cron_expr", str(exc)) from exc
        try:
            validate_payload(default_payload or {}, schema or {}, allowed_unknown_keys=legacy_unknown)
        except PayloadValidationError as exc:
            raise SchedulerError("invalid_job_payload", str(exc)) from exc

    @staticmethod
    def _validate_payload_for_job(job: SchedulerJob, payload: dict) -> None:
        legacy_unknown = set(job.default_payload or {}) - set(job.parameter_schema or {})
        try:
            validate_payload(payload, job.parameter_schema or {}, allowed_unknown_keys=legacy_unknown)
        except PayloadValidationError as exc:
            raise SchedulerError("invalid_job_payload", str(exc)) from exc

    @staticmethod
    def _job_read(row: SchedulerJob, *, tags: list[dict] | None = None) -> SchedulerJobRead:
        return SchedulerJobRead(
            id=row.id,
            job_code=row.job_code,
            job_name=row.job_name,
            job_type=row.job_type,
            description=row.description,
            parameter_schema=row.parameter_schema or {},
            trigger_type=row.trigger_type,
            cron_expr=row.cron_expr,
            timezone=row.timezone,
            default_payload=row.default_payload or {},
            max_instances=row.max_instances,
            misfire_grace_seconds=row.misfire_grace_seconds,
            timeout_seconds=row.timeout_seconds,
            retry_count=row.retry_count,
            retry_interval_seconds=row.retry_interval_seconds,
            next_run_at=row.next_run_at,
            last_run_at=row.last_run_at,
            is_enabled=row.is_enabled,
            is_system=row.is_system,
            is_hidden=row.is_hidden,
            tags=[SchedulerJobTagRead(**tag) for tag in (tags or [])],
            metadata=row.metadata_json or {},
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _run_read(row: SchedulerJobRun) -> SchedulerRunRead:
        return SchedulerRunRead(
            id=row.id,
            run_id=row.run_id,
            job_code=row.job_code,
            trigger_source=row.trigger_source,
            status=row.status,
            payload=row.payload or {},
            affected_rows=row.affected_rows,
            started_at=row.started_at,
            finished_at=row.finished_at,
            error_code=row.error_code,
            error_message=row.error_message,
            result_summary=row.result_summary or {},
            created_at=row.created_at,
        )
