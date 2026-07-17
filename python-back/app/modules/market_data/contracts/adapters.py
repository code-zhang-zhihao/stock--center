from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class CanonicalMappingResult:
    """Provider raw rows mapped to canonical write rows with diagnostics."""

    rows: list[dict[str, Any]]
    raw_count: int
    mapped_count: int
    missing_count: int = 0
    warnings: list[str] = field(default_factory=list)
    unit_conversions: dict[str, str] = field(default_factory=dict)
    provider_code: str = ""
    api_name: str = ""
    capability_code: str = ""
    request_range: dict[str, Any] = field(default_factory=dict)

    def log_summary(self) -> dict[str, Any]:
        return {
            "provider_code": self.provider_code,
            "api_name": self.api_name,
            "capability_code": self.capability_code,
            "request_range": self.request_range,
            "raw_row_count": self.raw_count,
            "mapped_count": self.mapped_count,
            "missing_count": self.missing_count,
            "unit_conversions": self.unit_conversions,
            "warning_samples": self.warnings[:10],
        }


class ProviderAdapter(ABC):
    """Base marker for raw-provider to canonical-field adapters."""

    provider_code: str
