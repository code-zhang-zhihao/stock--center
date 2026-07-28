from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from types import SimpleNamespace

from app.core.redis_client import RedisClient
from app.modules.data_assets import service as data_assets_service
from app.modules.data_assets.schemas import AssetDefinition, DataAssetCoverage, DataAssetSummary, TableStats
from app.modules.data_assets.service import DataAssetsService


class FakeRedis:
    def __init__(self, *, lease_acquired: bool = True) -> None:
        self.values: dict[str, dict] = {}
        self.lease_acquired = lease_acquired
        self.leases: dict[str, str] = {}

    async def runtime_config(self):
        return SimpleNamespace(
            data_asset_cache_enabled=True,
            ttl_for=lambda _snapshot_key: 60,
        )

    async def key(self, *parts: str) -> str:
        return ":".join(parts)

    async def get_json(self, key: str):
        return self.values.get(key)

    async def set_json(self, key: str, value: dict, *, ttl_seconds: int) -> bool:
        self.values[key] = value
        return True

    async def set_many_json(self, items):
        for key, value, _ttl_seconds in items:
            self.values[key] = value
        return True

    async def ttl(self, key: str) -> int:
        return 60 if key in self.values or key in self.leases else -2

    async def acquire_lease(self, key: str, owner: str, *, ttl_seconds: int) -> bool:
        if not self.lease_acquired:
            return False
        if key in self.leases:
            return False
        self.leases[key] = owner
        return True

    async def release_lease(self, key: str, owner: str) -> None:
        if self.leases.get(key) == owner:
            self.leases.pop(key, None)


def _summary_payload() -> dict:
    return DataAssetSummary(
        generated_at=datetime(2026, 7, 27, tzinfo=timezone.utc),
        latest_open_trade_date=date(2026, 7, 24),
        totals={"assets": 0, "ok": 0, "warning": 0, "empty": 0, "stale": 0, "missing": 0, "limited": 0, "partial": 0},
        assets=[],
        scheduler_runs=[],
    ).model_dump(mode="json")


def test_cached_summary_keeps_last_good_snapshot_after_fresh_ttl_expires(monkeypatch) -> None:
    async def run() -> None:
        fake_redis = FakeRedis()
        monkeypatch.setattr(data_assets_service, "redis_client", fake_redis)
        service = DataAssetsService(repository=SimpleNamespace())
        await service._write_success_snapshot("summary", _summary_payload())

        fake_redis.values.pop("data-assets:summary")
        fake_redis.values.pop("data-assets:summary:meta")

        cached = await service.cached_summary()
        status = await service.cache_status()
        assert cached.latest_open_trade_date == date(2026, 7, 24)
        assert status.items[0].status == "stale"
        assert status.items[0].has_last_good is True

    asyncio.run(run())


def test_refresh_cache_returns_in_progress_without_running_duplicate_query(monkeypatch) -> None:
    async def run() -> None:
        fake_redis = FakeRedis(lease_acquired=False)
        monkeypatch.setattr(data_assets_service, "redis_client", fake_redis)

        class Repository:
            async def latest_open_trade_date(self):
                raise AssertionError("duplicate refresh must not query the database")

        result = await DataAssetsService(Repository()).refresh_cache(days=3, snapshot_key="all")
        assert result.refresh_in_progress is True
        assert result.skipped_keys == ["summary", "daily_health"]

    asyncio.run(run())


def test_summary_batches_latest_coverage_for_all_assets(monkeypatch) -> None:
    async def run() -> None:
        target_date = date(2026, 7, 24)
        definitions = (
            AssetDefinition(
                asset_code="daily_bars",
                asset_name="日线",
                category="daily_fact",
                table_name="t_daily_bar",
                frequency="daily",
                date_column="trade_date",
                latest_count_column="stock_code",
                expected_lag_trade_days=2,
                coverage_scope="active_stock_daily",
            ),
            AssetDefinition(
                asset_code="daily_basic",
                asset_name="日度指标",
                category="daily_fact",
                table_name="t_stock_daily_basic",
                frequency="daily",
                date_column="trade_date",
                latest_count_column="stock_code",
                expected_lag_trade_days=2,
                approximate_row_count=True,
                coverage_scope="active_stock_daily",
            ),
        )
        monkeypatch.setattr(data_assets_service, "ASSET_DEFINITIONS", definitions)

        class Repository:
            def __init__(self) -> None:
                self.batch_calls = 0

            async def latest_open_trade_date(self):
                return target_date

            async def table_stats(self, definition, *, skip_latest_count):
                assert skip_latest_count is True
                return TableStats(exists=True, row_count=0, latest_trade_date=target_date)

            async def batch_stock_daily_coverages(self, requested_definitions, trade_dates):
                self.batch_calls += 1
                assert [item.asset_code for item in requested_definitions] == ["daily_bars", "daily_basic"]
                assert trade_dates == [target_date]
                return {
                    (item.asset_code, target_date): DataAssetCoverage(
                        scope="active_stock_daily",
                        trade_date=target_date,
                        expected_count=2,
                        actual_count=2,
                        exempt_count=0,
                        missing_count=0,
                        completeness_pct=100,
                        effective_completeness_pct=100,
                    )
                    for item in requested_definitions
                }

            async def open_trade_days_between(self, _start, _end):
                return 0

            async def latest_scheduler_runs(self, _codes):
                return []

        repository = Repository()
        summary = await DataAssetsService(repository).summary()
        assert repository.batch_calls == 1
        assert [item.latest_count for item in summary.assets] == [2, 2]
        assert [item.row_count for item in summary.assets] == [2, 2]
        assert summary.assets[1].row_count_is_estimate is True

    asyncio.run(run())


def test_redis_set_json_writes_when_remote_client_is_available(monkeypatch) -> None:
    class RemoteClient:
        def __init__(self) -> None:
            self.calls = []

        async def set(self, key, value, *, ex):
            self.calls.append((key, value, ex))

    async def run() -> None:
        client = RedisClient()
        remote = RemoteClient()

        async def get_client():
            return remote

        monkeypatch.setattr(client, "_get_client", get_client)
        assert await client.set_json("data-assets:summary", {"ok": True}, ttl_seconds=30) is True
        assert remote.calls == [("data-assets:summary", '{"ok": true}', 30)]

    asyncio.run(run())


def test_redis_bulk_json_writes_tickflow_depth_timestamp_as_iso_string(monkeypatch) -> None:
    class Pipeline:
        def __init__(self) -> None:
            self.calls = []

        def set(self, key, value, *, ex):
            self.calls.append(("set", key, value, ex))

        async def execute(self):
            self.calls.append(("execute",))

    class RemoteClient:
        def __init__(self) -> None:
            self.pipeline_instance = Pipeline()

        def pipeline(self, *, transaction):
            assert transaction is True
            return self.pipeline_instance

    async def run() -> None:
        client = RedisClient()
        remote = RemoteClient()

        async def get_client():
            return remote

        monkeypatch.setattr(client, "_get_client", get_client)
        depth_time = datetime(2026, 7, 28, 10, 14, 20, tzinfo=timezone.utc)
        assert await client.set_many_json(
            [("realtime:depth:300663", {"depth_time": depth_time}, 30)]
        ) is True
        assert remote.pipeline_instance.calls == [
            ("set", "realtime:depth:300663", '{"depth_time": "2026-07-28T10:14:20+00:00"}', 30),
            ("execute",),
        ]

    asyncio.run(run())


def test_redis_incremental_hash_cache_merges_only_changed_minute_fields(monkeypatch) -> None:
    async def run() -> None:
        client = RedisClient()

        async def memory_only_client():
            return None

        monkeypatch.setattr(client, "_get_client", memory_only_client)
        assert await client.hset_many_hashes_json(
            [
                ("realtime:minute-bars:600001", {"09:30": {"price": 10.0}, "__meta__": {"bar_count": 1}}, 30),
                ("realtime:minute-bars:600002", {"09:30": {"price": 20.0}}, 30),
            ]
        ) is True
        assert await client.hset_many_json(
            "realtime:minute-bars:600001",
            {"09:31": {"price": 10.1}, "__meta__": {"bar_count": 2}},
            ttl_seconds=30,
        ) is True

        first = await client.hgetall_json("realtime:minute-bars:600001")
        second = await client.hgetall_json("realtime:minute-bars:600002")
        assert first == {
            "09:30": {"price": 10.0},
            "09:31": {"price": 10.1},
            "__meta__": {"bar_count": 2},
        }
        assert second == {"09:30": {"price": 20.0}}

    asyncio.run(run())


def test_redis_incremental_hash_write_uses_remote_pipeline(monkeypatch) -> None:
    class Pipeline:
        def __init__(self) -> None:
            self.calls = []

        def hset(self, key, *, mapping):
            self.calls.append(("hset", key, mapping))

        def expire(self, key, ttl):
            self.calls.append(("expire", key, ttl))

        async def execute(self):
            self.calls.append(("execute",))

    class RemoteClient:
        def __init__(self) -> None:
            self.pipeline_instance = Pipeline()

        def pipeline(self, *, transaction):
            assert transaction is True
            return self.pipeline_instance

    async def run() -> None:
        client = RedisClient()
        remote = RemoteClient()

        async def get_client():
            return remote

        monkeypatch.setattr(client, "_get_client", get_client)
        assert await client.hset_many_json("realtime:minute-bars:600001", {"09:30": {"price": 10.0}}, ttl_seconds=30) is True
        assert remote.pipeline_instance.calls == [
            ("hset", "realtime:minute-bars:600001", {"09:30": '{"price": 10.0}'}),
            ("expire", "realtime:minute-bars:600001", 30),
            ("execute",),
        ]

    asyncio.run(run())
