from datetime import date, datetime, timezone
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import ApiResponse
from app.db.session import get_session, get_sessionmaker
from app.modules.data_assets.repository import DataAssetsRepository
from app.modules.data_assets.schemas import DataAssetRefreshQueuedResult
from app.modules.data_assets.service import DataAssetCacheMissError, DataAssetsService
from app.modules.realtime_market.service import realtime_market_service


router = APIRouter()
logger = logging.getLogger(__name__)


def service(session: AsyncSession) -> DataAssetsService:
    return DataAssetsService(DataAssetsRepository(session))


@router.get("/summary")
async def get_data_assets_summary(
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(await service(session).cached_summary())
    except DataAssetCacheMissError as exc:
        background_tasks.add_task(_refresh_data_assets_cache_background, 3, "all")
        return ApiResponse.fail(code="data_assets_cache_building", message=str(exc))
    except Exception as exc:
        return ApiResponse.fail(code="data_assets_summary_failed", message=str(exc))


@router.get("/daily-health")
async def get_data_assets_daily_health(
    background_tasks: BackgroundTasks,
    days: int = Query(default=3, ge=1, le=15),
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(await service(session).cached_daily_health(days=days))
    except DataAssetCacheMissError as exc:
        background_tasks.add_task(_refresh_data_assets_cache_background, days, "all")
        return ApiResponse.fail(code="data_assets_cache_building", message=str(exc))
    except Exception as exc:
        return ApiResponse.fail(code="data_assets_daily_health_failed", message=str(exc))


@router.get("/cache-status")
async def get_data_assets_cache_status(session: AsyncSession = Depends(get_session)):
    try:
        return ApiResponse.ok(await service(session).cache_status())
    except Exception as exc:
        return ApiResponse.fail(code="data_assets_cache_status_failed", message=str(exc))


@router.get("/realtime-health")
async def get_realtime_health():
    try:
        return ApiResponse.ok(await realtime_market_service.status())
    except Exception as exc:
        return ApiResponse.fail(code="data_assets_realtime_health_failed", message=str(exc))


@router.post("/refresh")
async def refresh_data_assets_cache(
    background_tasks: BackgroundTasks,
    days: int = Query(default=3, ge=1, le=15),
    snapshot_key: str = Query(default="all", pattern="^(all|summary|daily_health)$"),
    async_refresh: bool = Query(default=True, alias="async"),
    session: AsyncSession = Depends(get_session),
):
    try:
        if async_refresh:
            background_tasks.add_task(_refresh_data_assets_cache_background, days, snapshot_key)
            return ApiResponse.ok(
                DataAssetRefreshQueuedResult(
                    snapshot_key=snapshot_key,
                    days=days,
                    queued_at=datetime.now(timezone.utc),
                    message="数据资产缓存刷新已提交后台执行，请稍后查看缓存状态。",
                )
            )
        return ApiResponse.ok(await service(session).refresh_cache(days=days, snapshot_key=snapshot_key))
    except Exception as exc:
        return ApiResponse.fail(code="data_assets_refresh_failed", message=str(exc))


@router.get("/assets/{asset_code}/gaps")
async def get_data_asset_gaps(
    asset_code: str,
    trade_date: date | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(await service(session).stock_daily_gaps(asset_code, trade_date=trade_date, limit=limit))
    except ValueError as exc:
        return ApiResponse.fail(code="data_asset_gaps_not_supported", message=str(exc))
    except Exception as exc:
        return ApiResponse.fail(code="data_asset_gaps_failed", message=str(exc))


async def _refresh_data_assets_cache_background(days: int, snapshot_key: str) -> None:
    try:
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            await DataAssetsService(DataAssetsRepository(session)).refresh_cache(days=days, snapshot_key=snapshot_key)
    except Exception:
        logger.exception("data assets background cache refresh failed: snapshot_key=%s days=%s", snapshot_key, days)
