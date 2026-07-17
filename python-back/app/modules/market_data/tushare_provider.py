"""Deprecated compatibility import path for the raw Tushare transport."""

from app.modules.market_data.tushare.transport import TushareTransport, TushareTransportError

TushareProvider = TushareTransport
TushareProviderError = TushareTransportError

__all__ = ["TushareProvider", "TushareProviderError"]
