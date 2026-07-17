import asyncio

from app.modules.realtime_market.schemas import RealtimeSettings
from app.modules.realtime_market.service import RealtimeMarketService
from app.modules.market_data.providers import MootdxProvider


def test_minute_target_selection_keeps_fixed_priority_and_rotates_remainder():
    service = RealtimeMarketService()
    service._pools = {
        "holding": {"stock_codes": ["600001", "600002"]},
        "focus": {"stock_codes": ["600003"]},
    }
    service._page_targets = {"600004": 9_999_999_999.0}
    registered = [f"6{code:05d}" for code in range(1, 501)]
    settings = RealtimeSettings(minute_guaranteed_target_count=200, minute_registered_target_limit=500)

    first = service._select_minute_targets(registered, settings)
    second = service._select_minute_targets(registered, settings)

    assert len(first) == 200
    assert first[:4] == ["600001", "600002", "600003", "600004"]
    assert second[:4] == first[:4]
    assert first[4:] != second[4:]


def test_minute_registration_falls_back_to_active_universe_when_quotes_are_degraded():
    service = RealtimeMarketService()
    service._active_codes = [f"6{code:05d}" for code in range(1, 601)]
    settings = RealtimeSettings(minute_guaranteed_target_count=200, minute_registered_target_limit=500)

    registered = service._registered_minute_targets(settings)
    selected = service._select_minute_targets(registered, settings)

    assert len(registered) == 500
    assert len(selected) == 200


def test_minute_features_do_not_invent_amount_or_vwap():
    features = RealtimeMarketService._minute_features(
        [
            {"price": 10.0, "volume_share": 100},
            {"price": 10.1, "volume_share": 200},
            {"price": 10.2, "volume_share": 300},
        ]
    )

    assert features["minute_return_1m"] == 0.9901
    assert features["vwap"] is None
    assert features["amount_based_features_available"] is False
    assert features["minute_volume"] == 300


def test_stock_cache_meta_marks_empty_cache_and_disabled_runtime():
    service = RealtimeMarketService()
    errors = service._stock_cache_errors("600519", RealtimeSettings(enabled=False))

    assert errors == ["realtime_runtime_disabled"]
    service._settings = RealtimeSettings(enabled=True)
    assert service._stock_cache_errors("600519", service._settings) == ["realtime_cache_miss"]


def test_on_demand_fetch_fills_individual_quote_and_minute_cache(monkeypatch):
    class QuoteProvider:
        async def quote(self, stock_code):
            return {
                "stock_code": stock_code,
                "quote_time": __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                "last_price": 10.2,
                "pre_close_price": 10.0,
                "change_amount": 0.2,
                "change_pct": 2.0,
                "open_price": 10.0,
                "high_price": 10.3,
                "low_price": 9.9,
                "volume_hand": 100,
                "amount_yuan": 100000,
            }, []

        def close(self):
            pass

    class MinuteProvider:
        async def minute_bars(self, stock_code):
            return [{
                "stock_code": stock_code,
                "bar_time": __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                "price": 10.2,
                "volume_hand": 100,
                "volume_share": 10000,
                "amount_yuan": None,
            }], []

        def close(self):
            pass

    async def run() -> None:
        service = RealtimeMarketService()
        providers = [QuoteProvider(), MinuteProvider()]
        service._new_realtime_provider = lambda: providers.pop(0)
        service._persist_minute_cache = lambda *_args, **_kwargs: asyncio.sleep(0)
        async def fake_key(*parts):
            return ":".join(parts)
        async def ignore_cache_write(*_args, **_kwargs):
            return True
        monkeypatch.setattr("app.modules.realtime_market.service.redis_client.key", fake_key)
        monkeypatch.setattr("app.modules.realtime_market.service.redis_client.set_json", ignore_cache_write)
        result = await service._fetch_stock_on_demand("600519", RealtimeSettings(enabled=True))

        assert result == "on_demand"
        assert service._quotes["600519"]["last_price"] == 10.2
        assert service._minute_meta_by_stock["600519"]["status"] == "available"
        assert len(service._minutes["600519"]) == 1

    asyncio.run(run())


def test_empty_quote_batch_is_a_degraded_input_not_a_successful_round():
    class EmptyQuoteProvider:
        async def quote_batch(self, stock_codes):
            return [], []

    async def run() -> None:
        service = RealtimeMarketService()
        service._active_codes = ["600519"]
        service._quote_providers = [EmptyQuoteProvider()]
        rows, errors, transport_failed = await service._fetch_quotes(RealtimeSettings(quote_provider_pool_size=1))
        assert rows == []
        assert errors == ["quote_batch[600519..600519]: no_quote_data"]
        assert transport_failed is False

    asyncio.run(run())


def test_mootdx_quote_retries_next_server_when_first_response_is_empty():
    provider = MootdxProvider()
    attempts: list[str] = []

    class Client:
        def __init__(self, label: str) -> None:
            self.label = label

    provider._server_candidates = lambda: [("first", ("127.0.0.1", 1)), ("second", ("127.0.0.1", 2))]
    provider._quote_client = lambda *, server=None, bestip=None: Client("first" if server[1] == 1 else "second")
    provider._close_client = lambda: setattr(provider, "_client", None)

    def operation(client):
        attempts.append(client.label)
        return [] if client.label == "first" else [{"code": "600519"}]

    result = provider._call_quotes(operation, require_records=True)
    assert result == [{"code": "600519"}]
    assert attempts == ["first", "second"]
