import asyncio
from datetime import datetime, timezone

from app.modules.realtime_market.tickflow_runtime import (
    TickflowCredentials,
    TickflowQuoteProvider,
    tickflow_symbol,
)


def test_tickflow_symbol_maps_shanghai_and_shenzhen_a_shares():
    assert tickflow_symbol("600519") == "600519.SH"
    assert tickflow_symbol("000001.SZ") == "000001.SZ"
    assert tickflow_symbol("300750") == "300750.SZ"


def test_tickflow_quote_provider_normalizes_quote_and_uses_batch_endpoint():
    calls: list[tuple[str, list[str]]] = []

    class Quotes:
        def get(self, *, symbols, as_dataframe=False):
            calls.append(("get", list(symbols)))
            return [
                {
                    "symbol": "600519.SH",
                    "name": "贵州茅台",
                    "last_price": 1500.0,
                    "prev_close": 1470.0,
                    "open": 1480.0,
                    "high": 1505.0,
                    "low": 1478.0,
                    "volume": 1200,
                    "amount": 1800000.0,
                    "timestamp": 1784860200000,
                    "session": "continuous",
                    "ext": {"change_amount": 30.0},
                }
            ]

        def get_by_symbols(self, symbols, *, as_dataframe=False):
            calls.append(("batch", list(symbols)))
            return self.get(symbols=symbols, as_dataframe=as_dataframe)

    class Client:
        def __init__(self):
            self.quotes = Quotes()
            self.closed = False

        def close(self):
            self.closed = True

    client = Client()
    credentials = TickflowCredentials(
        system_config_id=1,
        value_id=2,
        fingerprint="test",
        api_key="secret",
    )
    provider = TickflowQuoteProvider(credentials, client_factory=lambda _credentials: client)

    async def run() -> None:
        quote, _ = await provider.quote("600519")
        batch, _ = await provider.quote_batch(["600519", "000001"])

        assert quote is not None
        assert quote["stock_code"] == "600519"
        assert quote["source"] == "tickflow"
        assert quote["source_symbol"] == "600519.SH"
        assert quote["change_pct"] == round(30 / 1470 * 100, 6)
        assert quote["quote_time"] == datetime.fromtimestamp(1784860200, tz=timezone.utc)
        assert batch[0]["stock_code"] == "600519"

    asyncio.run(run())
    provider.close()

    assert calls == [
        ("get", ["600519.SH"]),
        ("batch", ["600519.SH", "000001.SZ"]),
        ("get", ["600519.SH", "000001.SZ"]),
    ]
    assert client.closed is True
