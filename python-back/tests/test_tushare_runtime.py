from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from app.core.config import get_settings
from app.core.security import SecretCipher, build_secret_fingerprint
from app.modules.market_data.tushare_provider import TushareProviderError
from app.modules.market_data.tushare_runtime import TushareProviderFactory


class FakeRepository:
    def __init__(self) -> None:
        cipher = SecretCipher(get_settings().config_master_key)
        self.config = SimpleNamespace(id=7, category_code="market_data", config_code="tushare_pro")
        self.values = [
            SimpleNamespace(id=1, system_config_id=7, encrypted_value=cipher.encrypt("first-token"), fingerprint=build_secret_fingerprint("first-token"), endpoint_url="http://first.example.test"),
            SimpleNamespace(id=2, system_config_id=7, encrypted_value=cipher.encrypt("second-token"), fingerprint=build_secret_fingerprint("second-token"), endpoint_url="http://second.example.test"),
        ]
        self.invalid: list[int] = []
        self.cooldowns: list[int] = []
        self.used: list[int] = []
        self.calls: list[dict] = []

    async def find_config(self, **_): return self.config
    async def get_config(self, _config_id): return self.config
    async def get_value(self, value_id): return next((value for value in self.values if value.id == value_id), None)
    async def release_expired_cooldowns(self): return None
    async def commit(self): return None
    async def list_options(self, *_args, **_kwargs):
        return [
            SimpleNamespace(option_key="api_url", option_value="http://example.test"),
            SimpleNamespace(option_key="timeout_seconds", option_value=3),
            SimpleNamespace(option_key="rate_limit_per_minute", option_value=60),
            SimpleNamespace(option_key="retry_count", option_value=0),
            SimpleNamespace(option_key="cooldown_seconds", option_value=10),
        ]
    async def list_values(self, *_args, **_kwargs): return self.values
    async def mark_value_invalid(self, value_id): self.invalid.append(value_id)
    async def mark_value_cooldown(self, value_id, _until): self.cooldowns.append(value_id)
    async def mark_value_failure(self, _value_id): return None
    async def mark_value_used(self, value_id): self.used.append(value_id)
    async def record_call(self, row): self.calls.append(row)


def test_invalid_tushare_token_falls_back_to_next_active_value() -> None:
    async def run() -> None:
        repository = FakeRepository()
        factory = TushareProviderFactory(repository)
        endpoints: list[str] = []

        async def operation(provider):
            endpoints.append(provider.api_url)
            if provider.token == "first-token":
                raise TushareProviderError("bad token", kind="token_invalid")
            return "ok"

        assert await factory.call("stock_basic", operation) == "ok"
        assert repository.invalid == [1]
        assert repository.used == [2]
        assert endpoints == ["http://first.example.test", "http://second.example.test"]
        assert [row["response_summary"]["fingerprint"] for row in repository.calls if row["status"] == "success"] == [build_secret_fingerprint("second-token")]
        assert all("first-token" not in str(row) and "second-token" not in str(row) for row in repository.calls)

    asyncio.run(run())


def test_rate_limited_tushare_token_enters_cooldown_then_falls_back() -> None:
    async def run() -> None:
        repository = FakeRepository()
        factory = TushareProviderFactory(repository)

        async def operation(provider):
            if provider.token == "first-token":
                raise TushareProviderError("rate limited", kind="rate_limit")
            return {"token_used": provider.token == "second-token"}

        assert await factory.call("daily_bars", operation) == {"token_used": True}
        assert repository.cooldowns == [1]
        assert repository.used == [2]
        assert all(row["finished_at"].tzinfo == timezone.utc for row in repository.calls)

    asyncio.run(run())


def test_token_endpoint_falls_back_to_config_default_when_override_is_empty() -> None:
    repository = FakeRepository()
    repository.values[0].endpoint_url = None
    provider = TushareProviderFactory(repository)._provider(repository.values[0], {
        "api_url": "https://default.example.test/",
        "timeout_seconds": 3,
        "rate_limit_per_minute": 60,
    })
    assert provider.api_url == "https://default.example.test"


def test_invalid_token_endpoint_falls_back_without_invalidating_token() -> None:
    async def run() -> None:
        repository = FakeRepository()
        repository.values[0].endpoint_url = "not-a-url"
        factory = TushareProviderFactory(repository)
        endpoints: list[str] = []

        async def operation(provider):
            endpoints.append(provider.api_url)
            return "ok"

        assert await factory.call("stock_basic", operation) == "ok"
        assert repository.invalid == []
        assert repository.used == [2]
        assert endpoints == ["http://second.example.test"]
        assert repository.calls[0]["error_code"] == "tushare_endpoint_configuration_error"

    asyncio.run(run())


def test_daily_connectivity_probe_makes_one_request_and_allows_empty_rows() -> None:
    class FakeDailyProvider:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def daily_connectivity(self, *, end_date):
            self.calls.append({"end_date": end_date})
            return SimpleNamespace(row_count=0)

    async def run() -> None:
        repository = FakeRepository()
        factory = TushareProviderFactory(repository)
        provider = FakeDailyProvider()
        factory._provider = lambda *_args: provider

        result = await factory.probe_value(1)

        assert result.available is True
        assert result.details["api_name"] == "daily"
        assert result.details["stock_code"] == "600519.SH"
        assert result.details["row_count"] == 0
        assert len(provider.calls) == 1
        assert repository.calls[-1]["capability"] == "tushare_daily_connectivity_test"
        assert repository.calls[-1]["status"] == "success"
        assert "first-token" not in str(repository.calls[-1])

    asyncio.run(run())


def test_daily_connectivity_probe_logs_provider_failure_without_leaking_token() -> None:
    class FailingDailyProvider:
        async def daily_connectivity(self, *, end_date):
            raise TushareProviderError("daily permission denied", kind="permission", api_name="daily")

    async def run() -> None:
        repository = FakeRepository()
        factory = TushareProviderFactory(repository)
        factory._provider = lambda *_args: FailingDailyProvider()

        result = await factory.probe_value(1)

        assert result.available is False
        assert result.error == "daily permission denied"
        assert repository.calls[-1]["capability"] == "tushare_daily_connectivity_test"
        assert repository.calls[-1]["error_code"] == "tushare_permission"
        assert "first-token" not in str(repository.calls[-1])

    asyncio.run(run())
