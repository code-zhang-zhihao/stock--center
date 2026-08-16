"""Canonical identifiers for the seven settled broad-market indices.

Provider requests use exchange-suffixed symbols such as ``000300.SH``.  The
canonical market-data tables deliberately store the normalized six-digit code,
so database consumers must use this contract instead of provider symbols.
"""

from __future__ import annotations


CORE_INDEX_CANONICAL_CODES: tuple[str, ...] = (
    "000001",
    "399001",
    "399006",
    "000300",
    "000905",
    "000852",
    "000016",
)

CSI300_CANONICAL_CODE = "000300"
