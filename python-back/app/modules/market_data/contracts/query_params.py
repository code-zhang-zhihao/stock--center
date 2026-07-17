from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class CanonicalDateRange(BaseModel):
    trade_date: date | None = None
    start_date: date | None = None
    end_date: date | None = None


class CanonicalStockQuery(CanonicalDateRange):
    stock_code: str = Field(..., min_length=6, max_length=20)
    interval: str | None = None
    adjust_mode: Literal["none", "qfq", "hfq"] = "none"
