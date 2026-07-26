from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class RealtimeSettings(BaseModel):
    enabled: bool = False
    quote_provider: Literal["tickflow", "mootdx"] = "tickflow"
    full_market_interval_seconds: int = Field(default=60, ge=15, le=600)
    quote_batch_size: int = Field(default=80, ge=1, le=80)
    quote_provider_pool_size: int = Field(default=2, ge=1, le=4)
    minute_provider_pool_size: int = Field(default=4, ge=1, le=8)
    minute_refresh_interval_seconds: int = Field(default=60, ge=30, le=600)
    minute_guaranteed_target_count: int = Field(default=200, ge=1, le=500)
    minute_registered_target_limit: int = Field(default=500, ge=1, le=1000)
    strong_candidate_limit: int = Field(default=80, ge=0, le=300)
    stale_after_seconds: int = Field(default=180, ge=30, le=1800)
    round_failure_threshold: float = Field(default=0.05, ge=0, le=1)
    reference_refresh_seconds: int = Field(default=600, ge=60, le=3600)
    cache_ttl_seconds: int = Field(default=180, ge=30, le=1800)


class RealtimeRoundMeta(BaseModel):
    round_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    provider: str = "tickflow"
    expected_count: int = 0
    received_count: int = 0
    missing_count: int = 0
    failed_batch_count: int = 0
    duration_ms: int | None = None
    degraded: bool = False
    error_samples: list[str] = Field(default_factory=list)


class RealtimeMinuteMeta(BaseModel):
    selected_count: int = 0
    registered_count: int = 0
    updated_count: int = 0
    no_intraday_data_count: int = 0
    failed_count: int = 0
    duration_ms: int | None = None
    error_samples: list[str] = Field(default_factory=list)


class RealtimeStatus(BaseModel):
    running: bool
    enabled: bool
    market_session: bool
    quote_provider: str = "tickflow"
    minute_provider: str = "mootdx"
    cache_backend: str
    cache_prefix: str
    quote_cache_count: int = 0
    quote_stale_count: int = 0
    minute_cache_count: int = 0
    minute_registered_count: int = 0
    minute_guaranteed_count: int = 0
    reference_loaded_at: datetime | None = None
    last_quote_round: RealtimeRoundMeta = Field(default_factory=RealtimeRoundMeta)
    last_minute_round: RealtimeMinuteMeta = Field(default_factory=RealtimeMinuteMeta)
    error: str | None = None
