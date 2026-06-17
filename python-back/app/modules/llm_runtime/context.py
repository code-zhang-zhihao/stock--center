from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.market_data.repository import MarketDataRepository
from app.modules.market_data.schemas import QueryMode, QueryResult
from app.modules.market_data.service import MarketDataQueryService
from app.modules.llm_runtime.schemas import LlmAnalysisRequest, LlmContextBlock, LlmContextPack


class LlmContextProvider(ABC):
    code: str

    @abstractmethod
    async def build(self, request: LlmAnalysisRequest) -> LlmContextPack:
        raise NotImplementedError


class MarketDataContextProvider(LlmContextProvider):
    code = "market_data"

    def __init__(self, session: AsyncSession) -> None:
        self.market_data = MarketDataQueryService(MarketDataRepository(session))

    async def build(self, request: LlmAnalysisRequest) -> LlmContextPack:
        query_mode = self._effective_query_mode(request.query_mode, request.allow_provider_refresh)
        blocks: list[LlmContextBlock] = []
        for block_code in request.context_blocks:
            blocks.append(await self._build_block(block_code, request, query_mode))
        return LlmContextPack(
            task_type=request.task_type,
            stock_code=request.stock_code,
            query_mode=query_mode,
            allow_provider_refresh=request.allow_provider_refresh,
            blocks=blocks,
            extra_context=request.extra_context,
            created_at=datetime.now(timezone.utc),
        )

    async def _build_block(self, block_code: str, request: LlmAnalysisRequest, query_mode: QueryMode) -> LlmContextBlock:
        try:
            result = await self._query_block(block_code, request, query_mode)
            return self._result_block(block_code, result)
        except Exception as exc:
            return LlmContextBlock(
                block_code=block_code,
                success=False,
                error={"code": "context_block_failed", "message": str(exc)},
            )

    async def _query_block(self, block_code: str, request: LlmAnalysisRequest, query_mode: QueryMode) -> QueryResult:
        stock_code = request.stock_code
        limit = self._limit(request, block_code)
        if block_code in {
            "stock_basic",
            "daily_bars",
            "minute_bars",
            "quote",
            "sectors",
            "fund_flow",
            "lhb",
            "announcements",
            "indicators",
        } and not stock_code and block_code != "sectors":
            raise ValueError(f"context block requires stock_code: {block_code}")

        if block_code == "stock_basic":
            return await self.market_data.query_stock_basic(stock_code, query_mode=query_mode)
        if block_code == "daily_bars":
            return await self.market_data.query_daily_bars(stock_code, query_mode=query_mode, limit=limit)
        if block_code == "minute_bars":
            return await self.market_data.query_minute_bars(stock_code, query_mode=query_mode, limit=limit)
        if block_code == "quote":
            return await self.market_data.query_quote(stock_code, query_mode=query_mode)
        if block_code == "sectors":
            if stock_code:
                return await self.market_data.query_stock_sectors(stock_code, query_mode="db_only", limit=limit)
            return await self.market_data.query_sectors(query_mode=query_mode, limit=limit)
        if block_code == "fund_flow":
            return await self.market_data.query_fund_flow(stock_code=stock_code, query_mode=query_mode, limit=limit)
        if block_code == "lhb":
            return await self.market_data.query_lhb(stock_code=stock_code, query_mode=query_mode, limit=limit)
        if block_code == "announcements":
            return await self.market_data.query_announcements(stock_code, query_mode=query_mode, limit=limit)
        if block_code == "indicators":
            return await self.market_data.query_indicators(stock_code, query_mode="db_only", limit=limit)
        raise ValueError(f"unsupported context block: {block_code}")

    def _result_block(self, block_code: str, result: QueryResult) -> LlmContextBlock:
        return LlmContextBlock(
            block_code=block_code,
            success=not bool(result.meta.errors),
            data=result.data,
            meta=result.meta.model_dump(mode="json"),
            error={"code": "market_data_errors", "message": "; ".join(result.meta.errors)} if result.meta.errors else None,
        )

    def _effective_query_mode(self, requested: QueryMode, allow_provider_refresh: bool) -> QueryMode:
        if allow_provider_refresh:
            return requested
        if requested in {"refresh", "provider_first", "provider_only"}:
            return "db_first"
        return requested

    def _limit(self, request: LlmAnalysisRequest, block_code: str) -> int:
        defaults = {
            "daily_bars": 60,
            "minute_bars": 120,
            "sectors": 100,
            "fund_flow": 60,
            "lhb": 30,
            "announcements": 30,
            "indicators": 60,
        }
        return max(1, min(int(request.context_limits.get(block_code, defaults.get(block_code, 20))), 500))
