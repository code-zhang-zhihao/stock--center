from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import TimeoutError as SqlAlchemyTimeoutError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import ApiResponse
from app.db.session import get_pool_status, get_session
from app.modules.scheduler_center.repository import SchedulerRepository
from app.modules.scheduler_center.runtime import scheduler_runtime
from app.modules.scheduler_center.schemas import (
    SchedulerJobCreate,
    SchedulerJobUpdate,
    SchedulerRunListItem,
    SchedulerRunPage,
    SchedulerRunRequest,
)
from app.modules.scheduler_center.handlers import job_handler_registry
from app.modules.scheduler_center.service import SchedulerError, SchedulerService

router = APIRouter()


def service(session: AsyncSession) -> SchedulerService:
    return SchedulerService(SchedulerRepository(session))


async def _reload_scheduler() -> None:
    await scheduler_runtime.reload()


@router.get("/jobs")
async def list_jobs(
    include_hidden: bool = False,
    tag_code: str | None = Query(default=None, min_length=1, max_length=64),
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(await service(session).list_jobs(include_hidden=include_hidden, tag_code=tag_code))
    except Exception as exc:
        return ApiResponse.fail(code="scheduler_jobs_query_failed", message=str(exc))


@router.get("/tags")
async def list_tags(session: AsyncSession = Depends(get_session)):
    try:
        return ApiResponse.ok(await service(session).list_tags())
    except Exception as exc:
        return ApiResponse.fail(code="scheduler_tags_query_failed", message=str(exc))


@router.get("/jobs/{job_code}")
async def get_job(job_code: str, session: AsyncSession = Depends(get_session)):
    try:
        job = await service(session).get_job(job_code)
        if job is None:
            return ApiResponse.fail(code="job_not_found", message=f"job not found: {job_code}")
        return ApiResponse.ok(job)
    except Exception as exc:
        return ApiResponse.fail(code="scheduler_job_query_failed", message=str(exc))


@router.post("/jobs")
async def create_or_update_job(payload: SchedulerJobCreate, session: AsyncSession = Depends(get_session)):
    try:
        job = await service(session).create_or_update_job(payload)
        await _reload_scheduler()
        return ApiResponse.ok(await service(session).get_job(job.job_code) or job)
    except SchedulerError as exc:
        return ApiResponse.fail(code=exc.code, message=exc.message)
    except Exception as exc:
        return ApiResponse.fail(code="scheduler_job_create_failed", message=str(exc))


@router.patch("/jobs/{job_code}")
async def update_job(job_code: str, payload: SchedulerJobUpdate, session: AsyncSession = Depends(get_session)):
    try:
        job = await service(session).update_job(job_code, payload)
        if job is None:
            return ApiResponse.fail(code="job_not_found", message=f"job not found: {job_code}")
        await _reload_scheduler()
        return ApiResponse.ok(await service(session).get_job(job_code) or job)
    except SchedulerError as exc:
        return ApiResponse.fail(code=exc.code, message=exc.message)
    except Exception as exc:
        return ApiResponse.fail(code="scheduler_job_update_failed", message=str(exc))


@router.delete("/jobs/{job_code}")
async def delete_job(job_code: str, session: AsyncSession = Depends(get_session)):
    try:
        job = await service(session).delete_job(job_code)
        if job is None:
            return ApiResponse.fail(code="job_not_found_or_system", message=f"job not found or system job: {job_code}")
        await _reload_scheduler()
        return ApiResponse.ok(job)
    except Exception as exc:
        return ApiResponse.fail(code="scheduler_job_delete_failed", message=str(exc))


@router.post("/jobs/{job_code}/pause")
async def pause_job(job_code: str, session: AsyncSession = Depends(get_session)):
    try:
        job = await service(session).set_job_enabled(job_code, False)
        if job is None:
            return ApiResponse.fail(code="job_not_found", message=f"job not found: {job_code}")
        await _reload_scheduler()
        return ApiResponse.ok(await service(session).get_job(job_code) or job)
    except Exception as exc:
        return ApiResponse.fail(code="scheduler_job_pause_failed", message=str(exc))


@router.post("/jobs/{job_code}/resume")
async def resume_job(job_code: str, session: AsyncSession = Depends(get_session)):
    try:
        job = await service(session).set_job_enabled(job_code, True)
        if job is None:
            return ApiResponse.fail(code="job_not_found", message=f"job not found: {job_code}")
        await _reload_scheduler()
        return ApiResponse.ok(await service(session).get_job(job_code) or job)
    except Exception as exc:
        return ApiResponse.fail(code="scheduler_job_resume_failed", message=str(exc))


@router.post("/jobs/{job_code}/run")
async def run_job(
    job_code: str,
    payload: SchedulerRunRequest,
    session: AsyncSession = Depends(get_session),
):
    try:
        svc = service(session)
        handler = job_handler_registry.get(job_code)
        should_run_async = payload.run_async or bool(getattr(handler, "force_async", False))
        if not should_run_async:
            return ApiResponse.ok(await svc.run_job(job_code, payload=payload.payload, trigger_source="manual"))
        run = await svc.start_job(job_code, payload=payload.payload, trigger_source="manual")
        scheduler_runtime.start_background_execution(run.run_id, job_code, run.payload)
        return ApiResponse.ok(run)
    except SchedulerError as exc:
        return ApiResponse.fail(code=exc.code, message=exc.message)
    except Exception as exc:
        return ApiResponse.fail(code="scheduler_job_run_failed", message=str(exc))


@router.get("/runs")
async def list_runs(
    job_code: str | None = None,
    limit: int = Query(default=20, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    try:
        rows = await SchedulerRepository(session).list_runs_for_api(job_code=job_code, limit=limit + 1)
        has_more = len(rows) > limit
        items = [SchedulerRunListItem(**row) for row in rows[:limit]]
        return ApiResponse.ok(SchedulerRunPage(items=items, limit=limit, has_more=has_more))
    except SqlAlchemyTimeoutError:
        return ApiResponse.fail(
            code="db_pool_timeout",
            message="数据库连接池繁忙，后台任务可能占用了过多连接，请稍后重试或查看 /api/v1/scheduler/db-pool/status。",
        )
    except Exception as exc:
        return ApiResponse.fail(code="scheduler_runs_query_failed", message=str(exc))


@router.get("/runs/{run_id}")
async def get_run(run_id: str, session: AsyncSession = Depends(get_session)):
    try:
        row = await SchedulerRepository(session).get_run(run_id)
        if row is None:
            return ApiResponse.fail(code="job_run_not_found", message=f"job run not found: {run_id}")
        return ApiResponse.ok(SchedulerService._run_read(row))
    except Exception as exc:
        return ApiResponse.fail(code="scheduler_run_query_failed", message=str(exc))


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str, session: AsyncSession = Depends(get_session)):
    try:
        cancel_requested = scheduler_runtime.cancel_run(run_id)
        svc = service(session)
        if cancel_requested:
            row = await SchedulerRepository(session).get_run(run_id)
            return ApiResponse.ok(
                {
                    "cancel_requested": True,
                    "active": True,
                    "run": SchedulerService._run_read(row) if row else None,
                }
            )
        run = await svc.cancel_run_record(
            run_id,
            error_code="job_cancelled_not_active",
            error_message="run was marked running but no active task exists in this process",
        )
        if run is None:
            return ApiResponse.fail(code="job_run_not_found", message=f"job run not found: {run_id}")
        return ApiResponse.ok({"cancel_requested": False, "active": False, "run": run})
    except Exception as exc:
        return ApiResponse.fail(code="scheduler_run_cancel_failed", message=str(exc))


@router.get("/status")
async def scheduler_status():
    return ApiResponse.ok(scheduler_runtime.status())


@router.post("/reload")
async def reload_scheduler():
    try:
        return ApiResponse.ok(await scheduler_runtime.reload())
    except Exception as exc:
        return ApiResponse.fail(code="scheduler_reload_failed", message=str(exc))


@router.get("/db-pool/status")
async def db_pool_status():
    return ApiResponse.ok({"status": get_pool_status()})
