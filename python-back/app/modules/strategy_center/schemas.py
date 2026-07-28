from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


STRATEGY_CODE_PATTERN = r"^[a-z][a-z0-9_]{0,59}$"
StrategyStatus = Literal["draft", "research", "paper", "archived"]
StrategyEntryMode = Literal["auction", "open", "intraday"]
StrategyVersionStatus = Literal["draft", "backtest_ready", "paper", "retired"]


class StrategyDefinitionCreate(BaseModel):
    strategy_code: str = Field(pattern=STRATEGY_CODE_PATTERN, max_length=60)
    strategy_name: str = Field(min_length=1, max_length=160)
    implementation_code: str | None = Field(default=None, pattern=STRATEGY_CODE_PATTERN, max_length=80)
    description: str | None = Field(default=None, max_length=4000)
    entry_mode: StrategyEntryMode = "auction"
    max_holding_trade_days: int = Field(default=3, ge=1, le=20)
    rule_config: dict = Field(default_factory=dict)
    risk_config: dict = Field(default_factory=dict)


class StrategyDefinitionUpdate(BaseModel):
    strategy_name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    status: StrategyStatus | None = None
    entry_mode: StrategyEntryMode | None = None
    max_holding_trade_days: int | None = Field(default=None, ge=1, le=20)
    rule_config: dict | None = None
    risk_config: dict | None = None


class StrategyVersionCreate(BaseModel):
    implementation_code: str = Field(pattern=STRATEGY_CODE_PATTERN, max_length=80)
    rule_config: dict = Field(default_factory=dict)
    risk_config: dict = Field(default_factory=dict)


class StrategyVersionUpdate(BaseModel):
    implementation_code: str | None = Field(default=None, pattern=STRATEGY_CODE_PATTERN, max_length=80)
    rule_config: dict | None = None
    risk_config: dict | None = None


class StrategyBacktestCreate(BaseModel):
    version_no: int = Field(ge=1)
    start_date: date
    end_date: date
    fee_rate: float = Field(default=0.0005, ge=0, le=0.05)
    slippage_bps: float = Field(default=10, ge=0, le=1000)


class StrategyDefinitionRead(BaseModel):
    strategy_code: str
    strategy_name: str
    description: str | None = None
    status: StrategyStatus
    strategy_type: str
    entry_mode: StrategyEntryMode
    max_holding_trade_days: int
    rule_config: dict = Field(default_factory=dict)
    risk_config: dict = Field(default_factory=dict)
    pool_code: str | None = None
    pool_name: str | None = None
    candidate_summary: dict = Field(default_factory=dict)
    trade_summary: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class StrategyVersionRead(BaseModel):
    version_no: int
    implementation_code: str
    status: StrategyVersionStatus
    rule_config: dict = Field(default_factory=dict)
    risk_config: dict = Field(default_factory=dict)
    validation_summary: dict = Field(default_factory=dict)
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class StrategyCandidateRead(BaseModel):
    id: int
    strategy_code: str
    strategy_name: str
    signal_trade_date: date
    stock_code: str
    stock_name: str | None = None
    candidate_status: str
    score: float | None = None
    rank_no: int | None = None
    confirmation_deadline: date | None = None
    candidate_snapshot: dict = Field(default_factory=dict)
    entry_plan: dict = Field(default_factory=dict)
    outcome_note: str | None = None
    confirmed_at: datetime | None = None
    paper_trade: dict | None = None


class StrategyDashboardRead(BaseModel):
    definitions: list[StrategyDefinitionRead] = Field(default_factory=list)
    latest_signal_trade_date: date | None = None
    candidate_counts: dict = Field(default_factory=dict)
    paper_trade_counts: dict = Field(default_factory=dict)
    execution_ready: bool = False
    execution_readiness_reason: str
