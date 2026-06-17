from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import ApiResponse
from app.db.session import get_session
from app.modules.market_data.repository import MarketDataRepository
from app.modules.market_data.schemas import QueryMode
from app.modules.market_data.service import MarketDataQueryService


router = APIRouter()


def service(session: AsyncSession) -> MarketDataQueryService:
    return MarketDataQueryService(MarketDataRepository(session))


@router.get("/query/stock")
async def query_stock(
    stock_code: str,
    query_mode: QueryMode = "db_first",
    engine_priority: list[str] | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(await service(session).query_stock_basic(stock_code, query_mode=query_mode, engine_priority=engine_priority))
    except Exception as exc:
        return ApiResponse.fail(code="market_data_query_failed", message=str(exc))


@router.get("/query/daily-bars")
async def query_daily_bars(
    stock_code: str,
    query_mode: QueryMode = "db_first",
    engine_priority: list[str] | None = Query(default=None),
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = Query(default=120, ge=1, le=5000),
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(
            await service(session).query_daily_bars(
                stock_code,
                query_mode=query_mode,
                engine_priority=engine_priority,
                start_date=start_date,
                end_date=end_date,
                limit=limit,
            )
        )
    except Exception as exc:
        return ApiResponse.fail(code="market_data_query_failed", message=str(exc))


@router.get("/query/minute-bars")
async def query_minute_bars(
    stock_code: str,
    query_mode: QueryMode = "db_first",
    engine_priority: list[str] | None = Query(default=None),
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    limit: int = Query(default=240, ge=1, le=2000),
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(
            await service(session).query_minute_bars(
                stock_code,
                query_mode=query_mode,
                engine_priority=engine_priority,
                start_time=start_time,
                end_time=end_time,
                limit=limit,
            )
        )
    except Exception as exc:
        return ApiResponse.fail(code="market_data_query_failed", message=str(exc))


@router.get("/query/quote")
async def query_quote(
    stock_code: str,
    query_mode: QueryMode = "provider_first",
    engine_priority: list[str] | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(await service(session).query_quote(stock_code, query_mode=query_mode, engine_priority=engine_priority))
    except Exception as exc:
        return ApiResponse.fail(code="market_data_query_failed", message=str(exc))


@router.get("/query/ticks")
async def query_ticks(
    stock_code: str,
    query_mode: QueryMode = "db_first",
    engine_priority: list[str] | None = Query(default=None),
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    trade_date: date | None = None,
    limit: int = Query(default=800, ge=1, le=5000),
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(
            await service(session).query_ticks(
                stock_code,
                query_mode=query_mode,
                engine_priority=engine_priority,
                start_time=start_time,
                end_time=end_time,
                trade_date=trade_date,
                limit=limit,
            )
        )
    except Exception as exc:
        return ApiResponse.fail(code="market_data_query_failed", message=str(exc))


@router.get("/query/sectors")
async def query_sectors(
    sector_type: str = "industry",
    query_mode: QueryMode = "db_first",
    engine_priority: list[str] | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(
            await service(session).query_sectors(sector_type=sector_type, query_mode=query_mode, engine_priority=engine_priority, limit=limit)
        )
    except Exception as exc:
        return ApiResponse.fail(code="market_data_query_failed", message=str(exc))


@router.get("/query/sector-components")
async def query_sector_components(
    sector_code: str,
    sector_type: str = "industry",
    query_mode: QueryMode = "db_first",
    engine_priority: list[str] | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=5000),
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(
            await service(session).query_sector_components(
                sector_code,
                sector_type=sector_type,
                query_mode=query_mode,
                engine_priority=engine_priority,
                limit=limit,
            )
        )
    except Exception as exc:
        return ApiResponse.fail(code="market_data_query_failed", message=str(exc))


@router.get("/query/stock-sectors")
async def query_stock_sectors(
    stock_code: str,
    sector_type: str | None = None,
    query_mode: QueryMode = "db_only",
    limit: int = Query(default=500, ge=1, le=5000),
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(
            await service(session).query_stock_sectors(stock_code, sector_type=sector_type, query_mode=query_mode, limit=limit)
        )
    except Exception as exc:
        return ApiResponse.fail(code="market_data_query_failed", message=str(exc))


@router.get("/query/sector-bars")
async def query_sector_bars(
    sector_code: str,
    sector_type: str = "industry",
    query_mode: QueryMode = "db_first",
    engine_priority: list[str] | None = Query(default=None),
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = Query(default=240, ge=1, le=5000),
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(
            await service(session).query_sector_bars(
                sector_code,
                sector_type=sector_type,
                query_mode=query_mode,
                engine_priority=engine_priority,
                start_date=start_date,
                end_date=end_date,
                limit=limit,
            )
        )
    except Exception as exc:
        return ApiResponse.fail(code="market_data_query_failed", message=str(exc))


@router.get("/query/indexes")
async def query_indexes(
    index_code: str | None = None,
    query_mode: QueryMode = "db_first",
    engine_priority: list[str] | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(
            await service(session).query_indexes(index_code=index_code, query_mode=query_mode, engine_priority=engine_priority, limit=limit)
        )
    except Exception as exc:
        return ApiResponse.fail(code="market_data_query_failed", message=str(exc))


@router.get("/query/index-components")
async def query_index_components(
    index_code: str,
    query_mode: QueryMode = "db_first",
    engine_priority: list[str] | None = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=5000),
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(
            await service(session).query_index_components(index_code, query_mode=query_mode, engine_priority=engine_priority, limit=limit)
        )
    except Exception as exc:
        return ApiResponse.fail(code="market_data_query_failed", message=str(exc))


@router.get("/query/index-bars")
async def query_index_bars(
    index_code: str,
    query_mode: QueryMode = "db_first",
    engine_priority: list[str] | None = Query(default=None),
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = Query(default=240, ge=1, le=5000),
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(
            await service(session).query_index_bars(
                index_code,
                query_mode=query_mode,
                engine_priority=engine_priority,
                start_date=start_date,
                end_date=end_date,
                limit=limit,
            )
        )
    except Exception as exc:
        return ApiResponse.fail(code="market_data_query_failed", message=str(exc))


@router.get("/query/fund-flow")
async def query_fund_flow(
    stock_code: str | None = None,
    sector_type: str | None = None,
    query_mode: QueryMode = "db_first",
    engine_priority: list[str] | None = Query(default=None),
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = Query(default=240, ge=1, le=5000),
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(
            await service(session).query_fund_flow(
                stock_code=stock_code,
                sector_type=sector_type,
                query_mode=query_mode,
                engine_priority=engine_priority,
                start_date=start_date,
                end_date=end_date,
                limit=limit,
            )
        )
    except Exception as exc:
        return ApiResponse.fail(code="market_data_query_failed", message=str(exc))


@router.get("/query/lhb")
async def query_lhb(
    stock_code: str | None = None,
    query_mode: QueryMode = "db_first",
    engine_priority: list[str] | None = Query(default=None),
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = Query(default=200, ge=1, le=5000),
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(
            await service(session).query_lhb(
                stock_code=stock_code,
                query_mode=query_mode,
                engine_priority=engine_priority,
                start_date=start_date,
                end_date=end_date,
                limit=limit,
            )
        )
    except Exception as exc:
        return ApiResponse.fail(code="market_data_query_failed", message=str(exc))


@router.get("/query/announcements")
async def query_announcements(
    stock_code: str,
    query_mode: QueryMode = "db_first",
    engine_priority: list[str] | None = Query(default=None),
    start_date: date | None = None,
    end_date: date | None = None,
    keyword: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(
            await service(session).query_announcements(
                stock_code,
                query_mode=query_mode,
                engine_priority=engine_priority,
                start_date=start_date,
                end_date=end_date,
                keyword=keyword,
                limit=limit,
            )
        )
    except Exception as exc:
        return ApiResponse.fail(code="market_data_query_failed", message=str(exc))


@router.get("/query/indicators")
async def query_indicators(
    stock_code: str,
    query_mode: QueryMode = "db_only",
    limit: int = Query(default=60, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(await service(session).query_indicators(stock_code, query_mode=query_mode, limit=limit))
    except Exception as exc:
        return ApiResponse.fail(code="market_data_query_failed", message=str(exc))
