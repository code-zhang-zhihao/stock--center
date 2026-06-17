from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


QueryMode = Literal["db_first", "provider_first", "db_only", "provider_only", "refresh"]
Capability = Literal[
    "stock_basic",
    "daily_bars",
    "minute_bars",
    "quote",
    "ticks",
    "sectors",
    "sector_components",
    "stock_sectors",
    "sector_bars",
    "indexes",
    "index_components",
    "index_bars",
    "fund_flow",
    "lhb",
    "announcements",
    "indicators",
]


class QueryMeta(BaseModel):
    query_mode: QueryMode
    engine_priority: list[str]
    resolved_source: str | None = None
    fallback_used: bool = False
    attempted_engines: list[str] = Field(default_factory=list)
    missing_ranges: list[dict] = Field(default_factory=list)
    staleness: dict = Field(default_factory=dict)
    raw_ref: dict | None = None
    persisted: bool = False
    errors: list[str] = Field(default_factory=list)


class QueryResult(BaseModel):
    capability: Capability
    stock_code: str
    data: dict | list[dict] | None
    meta: QueryMeta


class StockRead(BaseModel):
    stock_code: str
    stock_name: str
    market: str
    exchange: str | None = None
    list_date: date | None = None
    delist_date: date | None = None
    status: str
    industry: str | None = None
    area: str | None = None


class DailyBarRead(BaseModel):
    stock_code: str
    trade_date: date
    source: str
    adjust_mode: str
    open_price: float | None = None
    high_price: float | None = None
    low_price: float | None = None
    close_price: float | None = None
    volume_hand: int | None = None
    volume_share: int | None = None
    amount_yuan: float | None = None
    turnover_rate: float | None = None


class MinuteBarRead(BaseModel):
    stock_code: str
    bar_time: datetime
    interval: str
    source: str
    price: float | None = None
    avg_price: float | None = None
    volume_hand: int | None = None
    volume_share: int | None = None
    amount_yuan: float | None = None


class QuoteRead(BaseModel):
    stock_code: str
    quote_time: datetime
    source: str
    last_price: float | None = None
    pre_close_price: float | None = None
    change_amount: float | None = None
    change_pct: float | None = None
    open_price: float | None = None
    high_price: float | None = None
    low_price: float | None = None
    volume_hand: int | None = None
    amount_yuan: float | None = None
    order_book: dict = Field(default_factory=dict)
