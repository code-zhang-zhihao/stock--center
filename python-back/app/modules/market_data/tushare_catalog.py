"""Backward-compatible catalog import path.

The actual A-share catalog is split by the official Tushare stock/index
directories under ``tushare.catalog``. Keep this module thin while older
callers migrate to the package-level imports.
"""

from app.modules.market_data.tushare.catalog import TUSHARE_A_SHARE_CATALOG
from app.modules.market_data.tushare.contracts import (
    TushareApiRequest,
    TushareApiResponse,
    TushareApiSpec,
    TushareFieldSpec,
    TushareParamSpec,
    validate_tushare_request as _validate_tushare_request,
)


def tushare_api_spec(api_name: str) -> TushareApiSpec:
    try:
        return TUSHARE_A_SHARE_CATALOG[api_name]
    except KeyError as exc:
        raise ValueError(f"Unsupported Tushare A-share API: {api_name}") from exc


def validate_tushare_request(request: TushareApiRequest) -> TushareApiRequest:
    return _validate_tushare_request(request, TUSHARE_A_SHARE_CATALOG)


__all__ = [
    "TUSHARE_A_SHARE_CATALOG",
    "TushareApiRequest",
    "TushareApiResponse",
    "TushareApiSpec",
    "TushareFieldSpec",
    "TushareParamSpec",
    "tushare_api_spec",
    "validate_tushare_request",
]
