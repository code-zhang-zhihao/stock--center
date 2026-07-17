"""Canonical market-data contracts shared by providers and services."""

from app.modules.market_data.contracts.adapters import CanonicalMappingResult, ProviderAdapter
from app.modules.market_data.contracts.fields import (
    ADJUST_MODES,
    INTERVALS,
    UNIT_AMOUNT_YUAN,
    UNIT_PERCENT_POINT,
    UNIT_PRICE_YUAN,
    UNIT_RATIO,
    UNIT_VOLUME_SHARES,
)
from app.modules.market_data.contracts.query_params import CanonicalDateRange, CanonicalStockQuery

__all__ = [
    "ADJUST_MODES",
    "INTERVALS",
    "UNIT_AMOUNT_YUAN",
    "UNIT_PERCENT_POINT",
    "UNIT_PRICE_YUAN",
    "UNIT_RATIO",
    "UNIT_VOLUME_SHARES",
    "CanonicalDateRange",
    "CanonicalMappingResult",
    "CanonicalStockQuery",
    "ProviderAdapter",
]
