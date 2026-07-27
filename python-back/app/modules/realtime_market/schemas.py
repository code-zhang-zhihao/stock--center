from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class RealtimeSettings(BaseModel):
    enabled: bool = False
    quote_provider: Literal["tickflow", "mootdx"] = "tickflow"
    full_market_interval_seconds: int = Field(default=60, ge=15, le=600)
    quote_batch_size: int = Field(default=50, ge=1, le=50)
    quote_provider_pool_size: int = Field(default=2, ge=1, le=4)
    minute_provider_pool_size: int = Field(default=6, ge=1, le=8)
    minute_refresh_interval_seconds: int = Field(default=60, ge=30, le=600)
    minute_guaranteed_target_count: int = Field(default=200, ge=1, le=500)
    minute_registered_target_limit: int = Field(default=500, ge=1, le=1000)
    strong_candidate_limit: int = Field(default=80, ge=0, le=300)
    stale_after_seconds: int = Field(default=180, ge=30, le=1800)
    round_failure_threshold: float = Field(default=0.05, ge=0, le=1)
    reference_refresh_seconds: int = Field(default=600, ge=60, le=3600)
    cache_ttl_seconds: int = Field(default=180, ge=30, le=1800)
    decision_target_limit: int = Field(default=200, ge=1, le=200)
    decision_quote_interval_seconds: int = Field(default=10, ge=5, le=120)
    warm_quote_interval_seconds: int = Field(default=60, ge=15, le=600)
    depth_refresh_interval_seconds: int = Field(default=10, ge=5, le=120)
    auction_depth_refresh_interval_seconds: int = Field(default=5, ge=3, le=60)
    depth_cache_ttl_seconds: int = Field(default=30, ge=10, le=300)
    leader_lease_seconds: int = Field(default=20, ge=5, le=120)


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


class RealtimeBlockMeta(RealtimeRoundMeta):
    block: Literal["market", "decision_quote", "depth", "minute"] = "market"
    request_count: int = 0
    coverage_pct: float | None = None
    cache_freshness_seconds: int | None = None
    rate_limited_count: int = 0
    network_error_count: int = 0
    degraded_reason: str | None = None


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
    market: RealtimeBlockMeta = Field(default_factory=lambda: RealtimeBlockMeta(block="market"))
    decision_quote: RealtimeBlockMeta = Field(default_factory=lambda: RealtimeBlockMeta(block="decision_quote"))
    depth: RealtimeBlockMeta = Field(default_factory=lambda: RealtimeBlockMeta(block="depth"))
    minute: RealtimeBlockMeta = Field(default_factory=lambda: RealtimeBlockMeta(block="minute"))
    rate_budgets: dict[str, dict] = Field(default_factory=dict)
    leader_active: bool = False
    depth_cache_count: int = 0
    decision_target_count: int = 0
    warm_target_count: int = 0
    error: str | None = None
