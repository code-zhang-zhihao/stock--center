from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def created_at_column():
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def updated_at_column():
    return mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class SchedulerJob(Base):
    __tablename__ = "t_scheduler_job"
    __table_args__ = (UniqueConstraint("job_code", name="uq_t_scheduler_job_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_code: Mapped[str] = mapped_column(String(120), nullable=False)
    job_name: Mapped[str] = mapped_column(String(160), nullable=False)
    job_type: Mapped[str] = mapped_column(String(80), nullable=False, default="maintenance")
    description: Mapped[str | None] = mapped_column(Text)
    parameter_schema: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    trigger_type: Mapped[str] = mapped_column(String(40), nullable=False, default="cron")
    cron_expr: Mapped[str | None] = mapped_column(String(120))
    timezone: Mapped[str] = mapped_column(String(80), nullable=False, default="Asia/Shanghai")
    default_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    max_instances: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    misfire_grace_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    timeout_seconds: Mapped[int | None] = mapped_column(Integer)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at = created_at_column()
    updated_at = updated_at_column()


class SchedulerJobRun(Base):
    __tablename__ = "t_scheduler_job_run"
    __table_args__ = (UniqueConstraint("run_id", name="uq_t_scheduler_job_run_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String(80), nullable=False)
    job_code: Mapped[str] = mapped_column(String(120), nullable=False)
    trigger_source: Mapped[str] = mapped_column(String(40), nullable=False, default="manual")
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    affected_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(Text)
    result_summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at = created_at_column()
