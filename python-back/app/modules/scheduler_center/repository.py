from datetime import datetime, timezone

from sqlalchemy import case, delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.scheduler_center.models import SchedulerJob, SchedulerJobRun, SchedulerJobTag, SchedulerTag

_UNSET = object()


class SchedulerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_jobs(
        self,
        *,
        include_hidden: bool = False,
        tag_code: str | None = None,
    ) -> list[SchedulerJob]:
        stmt = select(SchedulerJob)
        if not include_hidden:
            stmt = stmt.where(SchedulerJob.is_hidden.is_(False))
        if tag_code:
            stmt = stmt.where(
                SchedulerJob.job_code.in_(
                    select(SchedulerJobTag.job_code).where(SchedulerJobTag.tag_code == tag_code)
                )
            )
        result = await self.session.execute(stmt.order_by(SchedulerJob.job_type, SchedulerJob.job_code))
        return list(result.scalars().all())

    async def list_job_tags(self, job_codes: list[str]) -> dict[str, list[dict]]:
        if not job_codes:
            return {}
        rows = await self.session.execute(
            select(
                SchedulerJobTag.job_code,
                SchedulerTag.tag_code,
                SchedulerTag.tag_name,
                SchedulerTag.sort_order,
            )
            .join(SchedulerTag, SchedulerTag.tag_code == SchedulerJobTag.tag_code)
            .where(SchedulerJobTag.job_code.in_(job_codes))
            .order_by(SchedulerJobTag.job_code, SchedulerTag.sort_order, SchedulerTag.tag_code)
        )
        tags_by_job: dict[str, list[dict]] = {}
        for row in rows.mappings():
            tags_by_job.setdefault(str(row["job_code"]), []).append(
                {
                    "tag_code": row["tag_code"],
                    "tag_name": row["tag_name"],
                    "sort_order": row["sort_order"],
                }
            )
        return tags_by_job

    async def list_tags(self, *, include_disabled: bool = False) -> list[dict]:
        stmt = (
            select(
                SchedulerTag.id,
                SchedulerTag.tag_code,
                SchedulerTag.tag_name,
                SchedulerTag.sort_order,
                SchedulerTag.is_enabled,
                SchedulerTag.metadata_json.label("metadata"),
                func.count(SchedulerJobTag.job_code).label("job_count"),
            )
            .outerjoin(SchedulerJobTag, SchedulerJobTag.tag_code == SchedulerTag.tag_code)
            .group_by(
                SchedulerTag.id,
                SchedulerTag.tag_code,
                SchedulerTag.tag_name,
                SchedulerTag.sort_order,
                SchedulerTag.is_enabled,
                SchedulerTag.metadata_json,
            )
            .order_by(SchedulerTag.sort_order, SchedulerTag.tag_code)
        )
        if not include_disabled:
            stmt = stmt.where(SchedulerTag.is_enabled.is_(True))
        rows = await self.session.execute(stmt)
        return [dict(row) for row in rows.mappings().all()]

    async def list_enabled_cron_jobs(self) -> list[SchedulerJob]:
        result = await self.session.execute(
            select(SchedulerJob)
            .where(
                SchedulerJob.is_enabled.is_(True),
                SchedulerJob.trigger_type == "cron",
                SchedulerJob.cron_expr.is_not(None),
            )
            .order_by(SchedulerJob.job_code)
        )
        return list(result.scalars().all())

    async def get_job(self, job_code: str) -> SchedulerJob | None:
        result = await self.session.execute(select(SchedulerJob).where(SchedulerJob.job_code == job_code))
        return result.scalar_one_or_none()

    async def upsert_job(self, values: dict) -> SchedulerJob:
        now = datetime.now(timezone.utc)
        values = {**values, "updated_at": now}
        insert_stmt = insert(SchedulerJob).values(**values)
        stmt = (
            insert_stmt.on_conflict_do_update(
                index_elements=[SchedulerJob.job_code],
                set_={
                    "job_name": insert_stmt.excluded.job_name,
                    "job_type": insert_stmt.excluded.job_type,
                    "description": insert_stmt.excluded.description,
                    "parameter_schema": insert_stmt.excluded.parameter_schema,
                    "trigger_type": insert_stmt.excluded.trigger_type,
                    "cron_expr": insert_stmt.excluded.cron_expr,
                    "timezone": insert_stmt.excluded.timezone,
                    "default_payload": insert_stmt.excluded.default_payload,
                    "max_instances": insert_stmt.excluded.max_instances,
                    "misfire_grace_seconds": insert_stmt.excluded.misfire_grace_seconds,
                    "timeout_seconds": insert_stmt.excluded.timeout_seconds,
                    "retry_count": insert_stmt.excluded.retry_count,
                    "retry_interval_seconds": insert_stmt.excluded.retry_interval_seconds,
                    "is_enabled": insert_stmt.excluded.is_enabled,
                    "is_hidden": insert_stmt.excluded.is_hidden,
                    "metadata": insert_stmt.excluded["metadata"],
                    "updated_at": now,
                },
            )
            .returning(SchedulerJob)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def update_job(self, job_code: str, values: dict) -> SchedulerJob | None:
        if not values:
            return await self.get_job(job_code)
        values["updated_at"] = datetime.now(timezone.utc)
        result = await self.session.execute(
            update(SchedulerJob).where(SchedulerJob.job_code == job_code).values(**values).returning(SchedulerJob)
        )
        return result.scalar_one_or_none()

    async def delete_job(self, job_code: str) -> SchedulerJob | None:
        result = await self.session.execute(
            delete(SchedulerJob)
            .where(SchedulerJob.job_code == job_code, SchedulerJob.is_system.is_(False))
            .returning(SchedulerJob)
        )
        return result.scalar_one_or_none()

    async def set_job_enabled(self, job_code: str, enabled: bool) -> SchedulerJob | None:
        values = {"is_enabled": enabled, "updated_at": datetime.now(timezone.utc)}
        if not enabled:
            values["next_run_at"] = None
        result = await self.session.execute(
            update(SchedulerJob).where(SchedulerJob.job_code == job_code).values(**values).returning(SchedulerJob)
        )
        return result.scalar_one_or_none()

    async def clear_all_next_run_at(self) -> None:
        await self.session.execute(update(SchedulerJob).values(next_run_at=None, updated_at=datetime.now(timezone.utc)))

    async def update_job_runtime(
        self,
        job_code: str,
        *,
        next_run_at: datetime | None | object = _UNSET,
        last_run_at: datetime | None | object = _UNSET,
    ) -> None:
        values = {"updated_at": datetime.now(timezone.utc)}
        if next_run_at is not _UNSET:
            values["next_run_at"] = next_run_at
        if last_run_at is not _UNSET:
            values["last_run_at"] = last_run_at
        await self.session.execute(update(SchedulerJob).where(SchedulerJob.job_code == job_code).values(**values))

    async def record_run(self, values: dict) -> SchedulerJobRun:
        result = await self.session.execute(insert(SchedulerJobRun).values(**values).returning(SchedulerJobRun))
        return result.scalar_one()

    async def get_run(self, run_id: str) -> SchedulerJobRun | None:
        result = await self.session.execute(select(SchedulerJobRun).where(SchedulerJobRun.run_id == run_id))
        return result.scalar_one_or_none()

    async def update_run(self, run_id: str, values: dict) -> SchedulerJobRun | None:
        if not values:
            return await self.get_run(run_id)
        result = await self.session.execute(
            update(SchedulerJobRun)
            .where(SchedulerJobRun.run_id == run_id)
            .values(**values)
            .returning(SchedulerJobRun)
        )
        return result.scalar_one_or_none()

    async def cancel_running_run(self, run_id: str, *, error_code: str, error_message: str) -> SchedulerJobRun | None:
        result = await self.session.execute(
            update(SchedulerJobRun)
            .where(SchedulerJobRun.run_id == run_id, SchedulerJobRun.status == "running")
            .values(
                status="cancelled",
                finished_at=datetime.now(timezone.utc),
                error_code=error_code,
                error_message=error_message,
            )
            .returning(SchedulerJobRun)
        )
        return result.scalar_one_or_none()

    async def mark_orphaned_running_runs(self, *, error_code: str, error_message: str) -> int:
        result = await self.session.execute(
            update(SchedulerJobRun)
            .where(SchedulerJobRun.status == "running")
            .values(
                status="failed",
                finished_at=datetime.now(timezone.utc),
                error_code=error_code,
                error_message=error_message,
            )
        )
        return int(result.rowcount or 0)

    async def list_runs_for_api(
        self,
        *,
        job_code: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        error_bytes = func.coalesce(func.octet_length(SchedulerJobRun.error_message), 0)
        stmt = select(
            SchedulerJobRun.id,
            SchedulerJobRun.run_id,
            SchedulerJobRun.job_code,
            SchedulerJobRun.trigger_source,
            SchedulerJobRun.status,
            SchedulerJobRun.payload,
            SchedulerJobRun.affected_rows,
            SchedulerJobRun.started_at,
            SchedulerJobRun.finished_at,
            SchedulerJobRun.created_at,
            SchedulerJobRun.error_code,
            case((SchedulerJobRun.error_message.is_not(None), True), else_=False).label("has_error"),
            error_bytes.label("error_message_bytes"),
            func.substring(SchedulerJobRun.error_message, 1, 240).label("error_message_preview"),
            func.pg_column_size(SchedulerJobRun.result_summary).label("result_summary_bytes"),
        )
        if job_code:
            stmt = stmt.where(SchedulerJobRun.job_code == job_code)
        result = await self.session.execute(
            stmt.order_by(SchedulerJobRun.started_at.desc(), SchedulerJobRun.id.desc()).limit(limit)
        )
        return [dict(row) for row in result.mappings().all()]

    async def try_advisory_lock(self, job_code: str) -> bool:
        result = await self.session.execute(
            text("SELECT pg_try_advisory_lock(hashtext(:lock_key)::bigint)").bindparams(
                lock_key=f"scheduler:{job_code}"
            )
        )
        return bool(result.scalar_one())

    async def advisory_unlock(self, job_code: str) -> None:
        await self.session.execute(
            text("SELECT pg_advisory_unlock(hashtext(:lock_key)::bigint)").bindparams(lock_key=f"scheduler:{job_code}")
        )

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
