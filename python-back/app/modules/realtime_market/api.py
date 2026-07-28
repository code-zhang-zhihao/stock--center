import asyncio
import json
from datetime import date

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.core.response import ApiResponse
from app.modules.realtime_market.service import realtime_market_service


router = APIRouter()


@router.get("/status")
async def status():
    return ApiResponse.ok(await realtime_market_service.status())


@router.post("/refresh")
async def refresh(force: bool = Query(default=False)):
    try:
        return ApiResponse.ok(await realtime_market_service.refresh_once(force=force))
    except Exception as exc:
        return ApiResponse.fail(code="realtime_refresh_failed", message=str(exc))


@router.get("/market-overview")
async def market_overview():
    return ApiResponse.ok(await realtime_market_service.market_overview())


@router.get("/market-timeline")
async def market_timeline(limit: int = Query(default=180, ge=1, le=260)):
    return ApiResponse.ok(await realtime_market_service.market_timeline(limit=limit))


@router.get("/market-events")
async def market_events(limit: int = Query(default=80, ge=1, le=120)):
    return ApiResponse.ok(await realtime_market_service.market_events(limit=limit))


@router.get("/post-close-structure")
async def post_close_structure(trade_date: date | None = Query(default=None)):
    """Completed daily limit-event facts for the market overview page."""
    return ApiResponse.ok(await realtime_market_service.post_close_structure(trade_date=trade_date))


@router.get("/quotes")
async def quotes(stock_codes: str | None = Query(default=None)):
    codes = [item.strip() for item in (stock_codes or "").split(",") if item.strip()]
    return ApiResponse.ok(await realtime_market_service.quotes(codes or None))


@router.get("/decision-targets")
async def decision_targets():
    return ApiResponse.ok(await realtime_market_service.decision_targets())


@router.get("/depth")
async def depth(stock_codes: str | None = Query(default=None)):
    codes = [item.strip() for item in (stock_codes or "").split(",") if item.strip()]
    return ApiResponse.ok(await realtime_market_service.depth(codes or None))


@router.get("/pools/{pool_code}")
async def pool(pool_code: str):
    payload = await realtime_market_service.pool(pool_code)
    if payload is None:
        return ApiResponse.fail(code="realtime_pool_not_found", message=f"实时股票池不存在或尚未加载: {pool_code}")
    return ApiResponse.ok(payload)


@router.get("/pools")
async def pools(limit: int = Query(default=200, ge=1, le=500)):
    return ApiResponse.ok(await realtime_market_service.pools(limit=limit))


@router.get("/sectors")
async def sectors(
    sector_type: str | None = Query(default=None, pattern="^(concept|industry)$"),
    limit: int = Query(default=50, ge=1, le=500),
):
    return ApiResponse.ok(await realtime_market_service.sectors(sector_type=sector_type, limit=limit))


@router.get("/stocks/{stock_code}")
async def stock(stock_code: str):
    return ApiResponse.ok(await realtime_market_service.stock(stock_code))


@router.get("/stream")
async def stream(topics: str = Query(default="market_overview")):
    requested_topics = {item.strip() for item in topics.split(",") if item.strip()}

    async def events():
        async for event in realtime_market_service.subscribe(requested_topics):
            yield f"event: {event['topic']}\ndata: {json.dumps(event['data'], ensure_ascii=False, default=str)}\n\n"
            await asyncio.sleep(0)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
