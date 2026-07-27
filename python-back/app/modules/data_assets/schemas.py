from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class DataAssetMetric(BaseModel):
    label: str
    value: int | float | str | None
    unit: str | None = None


class DataAssetStatus(BaseModel):
    code: str
    label: str
    level: str


class DataAssetCoverage(BaseModel):
    scope: str
    trade_date: date | None = None
    expected_count: int
    actual_count: int
    exempt_count: int = 0
    missing_count: int
    completeness_pct: float | None = None
    effective_completeness_pct: float | None = None
    reason_breakdown: dict[str, int] = Field(default_factory=dict)


class DataAssetItem(BaseModel):
    asset_code: str
    asset_name: str
    category: str
    data_phase: str | None = None
    producer_job_codes: list[str] = Field(default_factory=list)
    table_name: str
    frequency: str
    row_count: int
    row_count_is_estimate: bool = False
    latest_trade_date: date | None = None
    earliest_trade_date: date | None = None
    latest_at: datetime | None = None
    latest_count: int | None = None
    stale_trade_days: int | None = None
    coverage: DataAssetCoverage | None = None
    status: DataAssetStatus
    metrics: list[DataAssetMetric] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DataAssetGapRow(BaseModel):
    stock_code: str
    stock_name: str | None = None
    exchange: str | None = None
    status: str | None = None
    reason: str
    reason_label: str


class DataAssetGapReport(BaseModel):
    asset_code: str
    asset_name: str
    table_name: str
    trade_date: date | None = None
    expected_count: int
    actual_count: int
    exempt_count: int
    missing_count: int
    reason_breakdown: dict[str, int] = Field(default_factory=dict)
    rows: list[DataAssetGapRow] = Field(default_factory=list)
    truncated: bool = False


class SchedulerRunBrief(BaseModel):
    job_code: str
    job_name: str | None = None
    status: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None


class DataAssetSummary(BaseModel):
    generated_at: datetime
    latest_open_trade_date: date | None = None
    totals: dict[str, int]
    assets: list[DataAssetItem]
    scheduler_runs: list[SchedulerRunBrief]
    notes: list[str] = Field(default_factory=list)


class DataAssetDailyHealthCell(BaseModel):
    asset_code: str
    asset_name: str
    expected_count: int
    actual_count: int
    exempt_count: int
    missing_count: int
    effective_completeness_pct: float | None = None
    status: DataAssetStatus


class DataAssetDailyHealthRow(BaseModel):
    trade_date: date
    cells: list[DataAssetDailyHealthCell]


class DataAssetDailyHealthReport(BaseModel):
    generated_at: datetime
    trade_dates: list[date]
    asset_codes: list[str]
    rows: list[DataAssetDailyHealthRow]


class DataAssetCacheStatusItem(BaseModel):
    snapshot_key: str
    status: str | None = None
    generated_at: datetime | None = None
    expires_at: datetime | None = None
    refreshed_at: datetime | None = None
    is_stale: bool = True
    has_last_good: bool = False
    refresh_in_progress: bool = False
    error_message: str | None = None


class DataAssetCacheStatusReport(BaseModel):
    generated_at: datetime
    items: list[DataAssetCacheStatusItem]


class DataAssetRefreshResult(BaseModel):
    refreshed_keys: list[str]
    failed_keys: list[str] = Field(default_factory=list)
    skipped_keys: list[str] = Field(default_factory=list)
    refresh_in_progress: bool = False
    summary_rows: int = 0
    daily_health_rows: int = 0
    generated_at: datetime


class DataAssetRefreshQueuedResult(BaseModel):
    accepted: bool = True
    snapshot_key: str
    days: int
    queued_at: datetime
    message: str


class AssetDefinition(BaseModel):
    asset_code: str
    asset_name: str
    category: str
    data_phase: str | None = None
    producer_job_codes: list[str] = Field(default_factory=list)
    table_name: str
    frequency: str
    date_column: str | None = None
    timestamp_column: str | None = None
    latest_count_column: str | None = None
    where_clause: str | None = None
    expected_lag_trade_days: int | None = None
    approximate_row_count: bool = False
    coverage_scope: str | None = None
    metric_sql: dict[str, str] = Field(default_factory=dict)
    metric_units: dict[str, str] = Field(default_factory=dict)


class TableStats(BaseModel):
    exists: bool
    row_count: int = 0
    latest_trade_date: date | None = None
    earliest_trade_date: date | None = None
    latest_at: datetime | None = None
    latest_count: int | None = None
    metrics: list[DataAssetMetric] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
