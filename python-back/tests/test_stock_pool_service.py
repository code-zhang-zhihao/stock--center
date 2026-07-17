from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from app.modules.stock_pool.schemas import StockPoolCreate, StockPoolMemberBatchCreate, StockPoolUpdate
from app.modules.stock_pool.service import StockPoolError, StockPoolService


class FakeRepository:
    def __init__(self) -> None:
        now = datetime.now(timezone.utc)
        self.pools = {
            "candidate": SimpleNamespace(
                id=1,
                pool_code="candidate",
                pool_name="候选观察池",
                pool_type="candidate",
                description=None,
                is_system=True,
                is_enabled=True,
                is_dynamic=False,
                dynamic_rule=None,
                sort_order=10,
                created_at=now,
                updated_at=now,
            ),
        }
        self.stock_codes = {"000001", "600519"}
        self.member_codes = {"000001"}
        self.candidates = [
            {"stock_code": "000001", "stock_name": "平安银行", "is_member": True},
            {"stock_code": "600519", "stock_name": "贵州茅台", "is_member": False},
        ]
        self.committed = 0

    async def list_pools(self): return [{"pool": pool, "member_count": 0} for pool in self.pools.values()]
    async def get_pool(self, pool_code): return self.pools.get(pool_code)
    async def create_pool(self, values):
        now = datetime.now(timezone.utc)
        pool = SimpleNamespace(id=2, created_at=now, updated_at=now, **values)
        self.pools[pool.pool_code] = pool
        return pool
    async def update_pool(self, pool_code, values):
        pool = self.pools[pool_code]
        for key, value in values.items(): setattr(pool, key, value)
        return pool
    async def delete_pool(self, pool_code): return self.pools.pop(pool_code, None)
    async def existing_stock_codes(self, stock_codes): return set(stock_codes) & self.stock_codes
    async def search_candidate_stocks(self, pool_id, keyword, limit):
        return [item for item in self.candidates if keyword in item["stock_code"] or keyword in item["stock_name"]][:limit]
    async def existing_member_codes(self, pool_id, stock_codes): return set(stock_codes) & self.member_codes
    async def add_members(self, pool_id, stock_codes):
        self.member_codes.update(stock_codes)
        return len(stock_codes)
    async def delete_member(self, pool_id, stock_code):
        if stock_code not in self.member_codes: return False
        self.member_codes.remove(stock_code)
        return True
    async def commit(self): self.committed += 1


def test_custom_pool_is_created_with_custom_type() -> None:
    async def run() -> None:
        repository = FakeRepository()
        service = StockPoolService(repository)
        pool = await service.create_pool(StockPoolCreate(pool_code="my_watchlist", pool_name="我的观察池"))
        assert pool["pool_type"] == "custom"
        assert pool["is_system"] is False
        assert repository.committed == 1

    asyncio.run(run())


def test_system_pool_name_is_protected_but_enabled_state_can_change() -> None:
    async def run() -> None:
        repository = FakeRepository()
        service = StockPoolService(repository)
        try:
            await service.update_pool("candidate", StockPoolUpdate(pool_name="改名"))
        except StockPoolError as exc:
            assert exc.code == "system_stock_pool_protected"
        else:
            raise AssertionError("system pool rename must fail")
        updated = await service.update_pool("candidate", StockPoolUpdate(is_enabled=False))
        assert updated["is_enabled"] is False

    asyncio.run(run())


def test_unknown_codes_reject_the_whole_batch_and_existing_members_are_skipped() -> None:
    async def run() -> None:
        repository = FakeRepository()
        service = StockPoolService(repository)
        try:
            await service.add_members(pool_code="candidate", payload=StockPoolMemberBatchCreate(stock_codes=["000001", "999999"]))
        except StockPoolError as exc:
            assert exc.code == "stock_codes_not_found"
            assert exc.details["unknown_codes"] == ["999999"]
        else:
            raise AssertionError("unknown codes must reject the batch")
        assert repository.member_codes == {"000001"}

        result = await service.add_members(pool_code="candidate", payload=StockPoolMemberBatchCreate(stock_codes=["000001", "600519", "600519"]))
        assert result["added_count"] == 1
        assert result["existing_codes"] == ["000001"]
        assert repository.member_codes == {"000001", "600519"}

    asyncio.run(run())


def test_candidate_search_marks_existing_pool_members() -> None:
    async def run() -> None:
        service = StockPoolService(FakeRepository())
        candidates = await service.search_candidate_stocks(pool_code="candidate", keyword="平安", limit=20)
        assert candidates == [{"stock_code": "000001", "stock_name": "平安银行", "is_member": True}]

    asyncio.run(run())
