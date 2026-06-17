from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


JobStatus = Literal["queued", "running", "success", "failed", "timeout", "cancelled", "skipped"]
TriggerSource = Literal["manual", "cron", "retry", "system"]


class SchedulerJobCreate(BaseModel):
    job_code: str = Field(min_length=1, max_length=120)
    job_name: str = Field(min_length=1, max_length=160)
    job_type: str = Field(default="maintenance", min_length=1, max_length=80)
    description: str | None = None
    parameter_schema: dict = Field(default_factory=dict)
    trigger_type: str = Field(default="cron", pattern="^cron$")
    cron_expr: str | None = Field(default=None, min_length=1, max_length=120)
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=80)
    default_payload: dict = Field(default_factory=dict)
    max_instances: int = Field(default=1, ge=1, le=10)
    misfire_grace_seconds: int = Field(default=300, ge=1, le=86400)
    timeout_seconds: int | None = Field(default=None, ge=1, le=86400)
    retry_count: int = Field(default=0, ge=0, le=10)
    retry_interval_seconds: int = Field(default=60, ge=1, le=3600)
    is_enabled: bool = True
    is_hidden: bool = False
    metadata: dict = Field(default_factory=dict)


class SchedulerJobUpdate(BaseModel):
    job_name: str | None = Field(default=None, min_length=1, max_length=160)
    job_type: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = None
    parameter_schema: dict | None = None
    trigger_type: str | None = Field(default=None, pattern="^cron$")
    cron_expr: str | None = Field(default=None, min_length=1, max_length=120)
    timezone: str | None = Field(default=None, min_length=1, max_length=80)
    default_payload: dict | None = None
    max_instances: int | None = Field(default=None, ge=1, le=10)
    misfire_grace_seconds: int | None = Field(default=None, ge=1, le=86400)
    timeout_seconds: int | None = Field(default=None, ge=1, le=86400)
    retry_count: int | None = Field(default=None, ge=0, le=10)
    retry_interval_seconds: int | None = Field(default=None, ge=1, le=3600)
    is_enabled: bool | None = None
    is_hidden: bool | None = None
    metadata: dict | None = None


class SchedulerJobRead(BaseModel):
    id: int
    job_code: str
    job_name: str
    job_type: str
    description: str | None = None
    parameter_schema: dict = Field(default_factory=dict)
    trigger_type: str
    cron_expr: str | None = None
    timezone: str
    default_payload: dict = Field(default_factory=dict)
    max_instances: int
    misfire_grace_seconds: int
    timeout_seconds: int | None = None
    retry_count: int
    retry_interval_seconds: int
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    is_enabled: bool
    is_system: bool
    is_hidden: bool
    metadata: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class SchedulerRunRequest(BaseModel):
    payload: dict = Field(default_factory=dict)
    run_async: bool = False


class SchedulerRunRead(BaseModel):
    id: int
    run_id: str
    job_code: str
    trigger_source: str
    status: str
    payload: dict = Field(default_factory=dict)
    affected_rows: int
    started_at: datetime
    finished_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    result_summary: dict = Field(default_factory=dict)
    created_at: datetime


class SchedulerRunListItem(BaseModel):
    id: int
    run_id: str
    job_code: str
    trigger_source: str
    status: str
    payload: dict = Field(default_factory=dict)
    affected_rows: int
    started_at: datetime
    finished_at: datetime | None = None
    created_at: datetime
    has_error: bool = False
    error_code: str | None = None
    error_message_preview: str | None = None
    error_message_bytes: int = 0
    result_summary_bytes: int = 0


class SchedulerRunPage(BaseModel):
    items: list[SchedulerRunListItem]
    limit: int
    has_more: bool = False


class SchedulerStatusRead(BaseModel):
    enabled: bool
    installed: bool
    running: bool
    job_count: int = 0
    jobs: list[dict] = Field(default_factory=list)
    error: str | None = None


class JobResult(BaseModel):
    affected_rows: int = 0
    summary: dict = Field(default_factory=dict)
