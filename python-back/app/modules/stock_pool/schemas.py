from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


POOL_CODE_PATTERN = r"^[a-z][a-z0-9_]{0,79}$"


class StockPoolRealtimePolicyRead(BaseModel):
    is_enabled: bool = False
    priority: int = 1000
    quote_lane: Literal["hot", "warm", "off"] = "off"
    minute_lane: Literal["guaranteed", "rotating", "off"] = "off"
    updated_at: datetime | None = None


class StockPoolRealtimePolicyUpdate(BaseModel):
    is_enabled: bool
    priority: int = Field(ge=0, le=10_000)
    quote_lane: Literal["hot", "warm", "off"]
    minute_lane: Literal["guaranteed", "rotating", "off"]


class StockPoolRead(BaseModel):
    id: int
    pool_code: str
    pool_name: str
    pool_type: str
    description: str | None = None
    is_system: bool
    is_enabled: bool
    is_dynamic: bool = False
    dynamic_rule: str | None = None
    sort_order: int
    member_count: int = 0
    realtime_policy: StockPoolRealtimePolicyRead = Field(default_factory=StockPoolRealtimePolicyRead)
    created_at: datetime
    updated_at: datetime


class StockPoolCreate(BaseModel):
    pool_code: str = Field(pattern=POOL_CODE_PATTERN, max_length=80)
    pool_name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    realtime_policy: StockPoolRealtimePolicyUpdate | None = None


class StockPoolUpdate(BaseModel):
    pool_name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    is_enabled: bool | None = None
    realtime_policy: StockPoolRealtimePolicyUpdate | None = None


class StockPoolMemberRead(BaseModel):
    stock_code: str
    stock_name: str | None = None
    created_at: datetime


class StockPoolMemberPage(BaseModel):
    items: list[StockPoolMemberRead]
    total: int
    page: int
    page_size: int


class StockPoolCandidateRead(BaseModel):
    stock_code: str
    stock_name: str
    is_member: bool


class StockPoolMemberBatchCreate(BaseModel):
    stock_codes: list[str] = Field(min_length=1, max_length=1000)


class StockPoolMemberBatchResult(BaseModel):
    added_count: int
    existing_codes: list[str] = Field(default_factory=list)
    stock_codes: list[str] = Field(default_factory=list)


class StockPoolSectorRead(BaseModel):
    sector_code: str
    sector_name: str
    sector_type: str
    source: str | None = None


class StockPoolMemberDetail(BaseModel):
    pool_code: str
    stock_code: str
    stock_name: str
    market: str
    exchange: str | None = None
    list_date: date | None = None
    status: str
    industry: str | None = None
    area: str | None = None
    concepts: list[StockPoolSectorRead] = Field(default_factory=list)
    industries: list[StockPoolSectorRead] = Field(default_factory=list)
