from app.modules.stock_pool.models import StockPool, StockPoolRealtimePolicy
from app.modules.stock_pool.repository import StockPoolRepository
from app.modules.stock_pool.schemas import StockPoolCreate, StockPoolMemberBatchCreate, StockPoolRealtimePolicyUpdate, StockPoolUpdate


def _policy_read(policy: StockPoolRealtimePolicy | None) -> dict:
    return {
        "is_enabled": bool(policy.is_enabled) if policy is not None else False,
        "priority": int(policy.priority) if policy is not None else 1000,
        "quote_lane": str(policy.quote_lane) if policy is not None else "off",
        "minute_lane": str(policy.minute_lane) if policy is not None else "off",
        "updated_at": policy.updated_at if policy is not None else None,
    }


class StockPoolError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class StockPoolService:
    def __init__(self, repository: StockPoolRepository) -> None:
        self.repository = repository

    @staticmethod
    def _read(pool: StockPool, member_count: int = 0, policy: StockPoolRealtimePolicy | None = None) -> dict:
        return {
            "id": pool.id,
            "pool_code": pool.pool_code,
            "pool_name": pool.pool_name,
            "pool_type": pool.pool_type,
            "description": pool.description,
            "is_system": pool.is_system,
            "is_enabled": pool.is_enabled,
            "is_dynamic": pool.is_dynamic,
            "dynamic_rule": pool.dynamic_rule,
            "sort_order": pool.sort_order,
            "member_count": member_count,
            "realtime_policy": _policy_read(policy),
            "created_at": pool.created_at,
            "updated_at": pool.updated_at,
        }

    async def list_pools(self) -> list[dict]:
        rows = await self.repository.list_pools()
        return [self._read(row["pool"], row["member_count"], row["policy"]) for row in rows]

    async def create_pool(self, payload: StockPoolCreate) -> dict:
        if await self.repository.get_pool(payload.pool_code):
            raise StockPoolError("stock_pool_code_exists", f"股票池编码已存在: {payload.pool_code}")
        pool = await self.repository.create_pool(
            {
                "pool_code": payload.pool_code,
                "pool_name": payload.pool_name,
                "pool_type": "custom",
                "description": payload.description,
                "is_system": False,
                "is_enabled": True,
                "is_dynamic": False,
                "dynamic_rule": None,
                "sort_order": 1000,
            }
        )
        policy_values = payload.realtime_policy.model_dump() if payload.realtime_policy is not None else None
        self._assert_realtime_policy_allowed(pool, policy_values)
        policy = await self.repository.create_realtime_policy(pool.id, policy_values)
        await self.repository.commit()
        return self._read(pool, policy=policy)

    async def update_pool(self, pool_code: str, payload: StockPoolUpdate) -> dict:
        pool = await self._require_pool(pool_code)
        values = payload.model_dump(exclude_unset=True)
        policy_values = values.pop("realtime_policy", None)
        if pool.is_system and "pool_name" in values:
            raise StockPoolError("system_stock_pool_protected", f"系统股票池不可修改名称: {pool_code}")
        updated = await self.repository.update_pool(pool_code, values)
        self._assert_realtime_policy_allowed(pool, policy_values)
        policy = (
            await self.repository.update_realtime_policy(pool.id, policy_values)
            if policy_values is not None
            else await self.repository.get_realtime_policy(pool.id)
        )
        await self.repository.commit()
        return self._read(updated or pool, policy=policy)

    async def update_realtime_policy(self, pool_code: str, payload: StockPoolRealtimePolicyUpdate) -> dict:
        pool = await self._require_pool(pool_code)
        policy_values = payload.model_dump()
        self._assert_realtime_policy_allowed(pool, policy_values)
        policy = await self.repository.update_realtime_policy(pool.id, policy_values)
        await self.repository.commit()
        return self._read(pool, policy=policy)

    async def delete_pool(self, pool_code: str) -> dict:
        pool = await self._require_pool(pool_code)
        if pool.is_system:
            raise StockPoolError("system_stock_pool_protected", f"系统股票池不可删除: {pool_code}")
        deleted = await self.repository.delete_pool(pool_code)
        await self.repository.commit()
        return self._read(deleted or pool)

    async def list_members(self, *, pool_code: str, keyword: str | None, page: int, page_size: int) -> dict:
        pool = await self._require_pool(pool_code)
        if pool.is_dynamic and pool.dynamic_rule == "active_a_share":
            items, total = await self.repository.list_dynamic_active_members(keyword=keyword, page=page, page_size=page_size)
        elif pool.is_dynamic and pool.dynamic_rule == "strategy_candidates":
            items, total = await self.repository.list_strategy_candidate_members(
                pool_id=pool.id,
                keyword=keyword,
                page=page,
                page_size=page_size,
            )
        elif pool.is_dynamic:
            raise StockPoolError("dynamic_stock_pool_rule_unknown", f"未知动态股票池规则: {pool.dynamic_rule or '-'}")
        else:
            items, total = await self.repository.list_members(pool_id=pool.id, keyword=keyword, page=page, page_size=page_size)
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    async def search_candidate_stocks(self, *, pool_code: str, keyword: str, limit: int) -> list[dict]:
        pool = await self._require_pool(pool_code)
        self._assert_members_editable(pool)
        return await self.repository.search_candidate_stocks(pool_id=pool.id, keyword=keyword.strip(), limit=limit)

    async def add_members(self, *, pool_code: str, payload: StockPoolMemberBatchCreate) -> dict:
        pool = await self._require_pool(pool_code)
        self._assert_members_editable(pool)
        stock_codes = list(dict.fromkeys(code.strip().upper() for code in payload.stock_codes if code.strip()))
        if not stock_codes:
            raise StockPoolError("stock_codes_empty", "至少需要一个股票代码")
        existing_stocks = await self.repository.existing_stock_codes(stock_codes)
        unknown_codes = [code for code in stock_codes if code not in existing_stocks]
        if unknown_codes:
            raise StockPoolError(
                "stock_codes_not_found",
                "存在未同步的股票代码，未写入任何成员关系",
                {"unknown_codes": unknown_codes},
            )
        existing_members = await self.repository.existing_member_codes(pool_id=pool.id, stock_codes=stock_codes)
        to_add = [code for code in stock_codes if code not in existing_members]
        added_count = await self.repository.add_members(pool_id=pool.id, stock_codes=to_add)
        await self.repository.commit()
        return {"added_count": added_count, "existing_codes": sorted(existing_members), "stock_codes": stock_codes}

    async def delete_member(self, *, pool_code: str, stock_code: str) -> None:
        pool = await self._require_pool(pool_code)
        self._assert_members_editable(pool)
        if not await self.repository.delete_member(pool_id=pool.id, stock_code=stock_code):
            raise StockPoolError("stock_pool_member_not_found", f"股票池成员不存在: {pool_code}/{stock_code}")
        await self.repository.commit()

    async def member_detail(self, *, pool_code: str, stock_code: str) -> dict:
        pool = await self._require_pool(pool_code)
        if pool.is_dynamic and pool.dynamic_rule == "active_a_share":
            detail = await self.repository.get_dynamic_member_detail(pool_code=pool.pool_code, stock_code=stock_code)
        elif pool.is_dynamic and pool.dynamic_rule == "strategy_candidates":
            detail = await self.repository.get_strategy_candidate_member_detail(
                pool_id=pool.id,
                pool_code=pool.pool_code,
                stock_code=stock_code,
            )
        elif pool.is_dynamic:
            raise StockPoolError("dynamic_stock_pool_rule_unknown", f"未知动态股票池规则: {pool.dynamic_rule or '-'}")
        else:
            detail = await self.repository.get_member_detail(pool_id=pool.id, pool_code=pool.pool_code, stock_code=stock_code)
        if detail is None:
            raise StockPoolError("stock_pool_member_not_found", f"股票池成员不存在: {pool_code}/{stock_code}")
        return detail

    async def stock_profile(self, *, stock_code: str) -> dict:
        detail = await self.repository.stock_profile(stock_code)
        if detail is None:
            raise StockPoolError("stock_not_found", f"股票不存在: {stock_code}")
        return detail

    async def list_catalog(self, *, scope: str | None = None) -> list[dict]:
        return await self.repository.list_catalog(scope=scope)

    async def _require_pool(self, pool_code: str) -> StockPool:
        pool = await self.repository.get_pool(pool_code)
        if pool is None:
            raise StockPoolError("stock_pool_not_found", f"股票池不存在: {pool_code}")
        return pool

    @staticmethod
    def _assert_members_editable(pool: StockPool) -> None:
        if pool.is_dynamic:
            raise StockPoolError("dynamic_stock_pool_read_only", f"动态股票池由规则维护，不能手工修改成员: {pool.pool_code}")

    @staticmethod
    def _assert_realtime_policy_allowed(pool: StockPool, policy_values: dict | None) -> None:
        if (
            policy_values is not None
            and pool.is_dynamic
            and pool.dynamic_rule == "active_a_share"
            and policy_values["is_enabled"]
        ):
            raise StockPoolError(
                "dynamic_universe_realtime_policy_forbidden",
                "全市场动态范围只能用于全市场 Quote，不能作为候选或分钟线目标池",
            )
