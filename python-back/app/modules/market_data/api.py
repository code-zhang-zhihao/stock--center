from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import ApiResponse
from app.db.session import get_session
from app.modules.market_data.repository import MarketDataRepository
from app.modules.market_data.schemas import QueryMode
from app.modules.market_data.sector_analysis import SectorAnalysisError, SectorAnalysisService
from app.modules.market_data.service import MarketDataQueryService
from app.modules.market_data.stock_analysis import StockAnalysisError, StockAnalysisService
from app.modules.realtime_market.service import realtime_market_service


router = APIRouter()


def service(session: AsyncSession) -> MarketDataQueryService:
    return MarketDataQueryService(MarketDataRepository(session))


def sector_analysis_service(session: AsyncSession) -> SectorAnalysisService:
    return SectorAnalysisService(MarketDataRepository(session))


def stock_analysis_service(session: AsyncSession) -> StockAnalysisService:
    return StockAnalysisService(MarketDataRepository(session))


@router.get("/browse/sectors")
async def browse_sectors(
    sector_type: str = Query(default="concept", pattern="^(concept|industry)$"),
    provider: str = Query(default="tushare", pattern="^(tushare|akshare|all)$"),
    keyword: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=10, le=200),
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(
            await service(session).browse_sectors(
                sector_type=sector_type,
                provider=provider,
                keyword=keyword,
                page=page,
                page_size=page_size,
            )
        )
    except Exception as exc:
        return ApiResponse.fail(code="sector_browse_failed", message=str(exc))


@router.get("/browse/sectors/{sector_code}/stocks")
async def browse_sector_stocks(
    sector_code: str,
    keyword: str | None = None,
    status: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=10, le=200),
    session: AsyncSession = Depends(get_session),
):
    try:
        result = await service(session).browse_sector_stocks(
            sector_code=sector_code,
            keyword=keyword,
            status=status,
            page=page,
            page_size=page_size,
        )
        if result is None:
            return ApiResponse.fail(code="sector_not_found", message=f"sector not found: {sector_code}")
        return ApiResponse.ok(result)
    except Exception as exc:
        return ApiResponse.fail(code="sector_stock_browse_failed", message=str(exc))


@router.get("/sector-analysis/search")
async def search_sector_analysis(
    keyword: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(await sector_analysis_service(session).search(keyword=keyword, limit=limit))
    except Exception as exc:
        return ApiResponse.fail(code="sector_analysis_search_failed", message=str(exc))


@router.get("/sector-analysis/dashboard")
async def sector_analysis_dashboard(
    sector_type: str = Query(default="concept", pattern="^(concept|industry)$"),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(await sector_analysis_service(session).dashboard(sector_type=sector_type, limit=limit))
    except Exception as exc:
        return ApiResponse.fail(code="sector_dashboard_failed", message=str(exc))


@router.get("/sector-analysis/{sector_code}/overview")
async def sector_analysis_overview(
    sector_code: str,
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(await sector_analysis_service(session).overview(sector_code))
    except SectorAnalysisError as exc:
        return ApiResponse.fail(code=exc.code, message=str(exc))
    except Exception as exc:
        return ApiResponse.fail(code="sector_analysis_failed", message=str(exc))


@router.get("/sector-analysis/{sector_code}/bars")
async def sector_analysis_bars(
    sector_code: str,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = Query(default=120, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(
            await sector_analysis_service(session).bars(
                sector_code,
                start_date=start_date,
                end_date=end_date,
                limit=limit,
            )
        )
    except SectorAnalysisError as exc:
        return ApiResponse.fail(code=exc.code, message=str(exc))
    except Exception as exc:
        return ApiResponse.fail(code="sector_bars_analysis_failed", message=str(exc))


@router.get("/sector-analysis/{sector_code}/money-flow")
async def sector_analysis_money_flow(
    sector_code: str,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = Query(default=120, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(
            await sector_analysis_service(session).money_flow(
                sector_code,
                start_date=start_date,
                end_date=end_date,
                limit=limit,
            )
        )
    except SectorAnalysisError as exc:
        return ApiResponse.fail(code=exc.code, message=str(exc))
    except Exception as exc:
        return ApiResponse.fail(code="sector_money_flow_analysis_failed", message=str(exc))


@router.get("/sector-analysis/{sector_code}/leaders")
async def sector_analysis_leaders(
    sector_code: str,
    limit: int = Query(default=30, ge=1, le=120),
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(await sector_analysis_service(session).leaders(sector_code, limit=limit))
    except SectorAnalysisError as exc:
        return ApiResponse.fail(code=exc.code, message=str(exc))
    except Exception as exc:
        return ApiResponse.fail(code="sector_leaders_analysis_failed", message=str(exc))


@router.get("/sector-analysis/{sector_code}/stocks")
async def sector_analysis_stocks(
    sector_code: str,
    keyword: str | None = None,
    status: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=10, le=200),
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(
            await sector_analysis_service(session).stocks(
                sector_code,
                keyword=keyword,
                status=status,
                page=page,
                page_size=page_size,
            )
        )
    except SectorAnalysisError as exc:
        return ApiResponse.fail(code=exc.code, message=str(exc))
    except Exception as exc:
        return ApiResponse.fail(code="sector_stock_analysis_failed", message=str(exc))


@router.get("/stock-analysis/search")
async def stock_analysis_search(
    keyword: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(await stock_analysis_service(session).search(keyword=keyword, limit=limit))
    except Exception as exc:
        return ApiResponse.fail(code="stock_analysis_search_failed", message=str(exc))


@router.get("/stock-analysis/{stock_code}/overview")
async def stock_analysis_overview(
    stock_code: str,
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(await stock_analysis_service(session).overview(stock_code))
    except StockAnalysisError as exc:
        return ApiResponse.fail(code=exc.code, message=str(exc))
    except Exception as exc:
        return ApiResponse.fail(code="stock_analysis_overview_failed", message=str(exc))


@router.get("/stock-analysis/{stock_code}/realtime")
async def stock_analysis_realtime(
    stock_code: str,
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(await realtime_market_service.stock(stock_code))
    except Exception as exc:
        return ApiResponse.fail(code="stock_analysis_realtime_failed", message=str(exc))


@router.get("/stock-analysis/{stock_code}/daily-bars")
async def stock_analysis_daily_bars(
    stock_code: str,
    limit: int = Query(default=250, ge=1, le=2000),
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(await stock_analysis_service(session).daily_bars(stock_code, limit=limit))
    except Exception as exc:
        return ApiResponse.fail(code="stock_analysis_daily_bars_failed", message=str(exc))


@router.get("/stock-analysis/{stock_code}/minute-bars")
async def stock_analysis_minute_bars(
    stock_code: str,
    trade_date: date | None = None,
    limit: int = Query(default=2000, ge=1, le=5000),
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(await stock_analysis_service(session).minute_bars(stock_code, trade_date=trade_date, limit=limit))
    except Exception as exc:
        return ApiResponse.fail(code="stock_analysis_minute_bars_failed", message=str(exc))


@router.get("/stock-analysis/{stock_code}/factors")
async def stock_analysis_factors(
    stock_code: str,
    trade_date: date | None = None,
    lookback: int = Query(default=60, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(await stock_analysis_service(session).factors(stock_code, trade_date=trade_date, lookback=lookback))
    except Exception as exc:
        return ApiResponse.fail(code="stock_analysis_factors_failed", message=str(exc))


@router.get("/stock-analysis/{stock_code}/fund-flow")
async def stock_analysis_fund_flow(
    stock_code: str,
    lookback: int = Query(default=60, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(await stock_analysis_service(session).fund_flow(stock_code, lookback=lookback))
    except Exception as exc:
        return ApiResponse.fail(code="stock_analysis_fund_flow_failed", message=str(exc))


@router.get("/stock-analysis/{stock_code}/events")
async def stock_analysis_events(
    stock_code: str,
    lookback: int = Query(default=60, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(await stock_analysis_service(session).events(stock_code, lookback=lookback))
    except Exception as exc:
        return ApiResponse.fail(code="stock_analysis_events_failed", message=str(exc))


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
