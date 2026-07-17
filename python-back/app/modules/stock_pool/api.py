from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import ApiResponse
from app.db.session import get_session
from app.modules.stock_pool.repository import StockPoolRepository
from app.modules.stock_pool.schemas import StockPoolCreate, StockPoolMemberBatchCreate, StockPoolUpdate
from app.modules.stock_pool.service import StockPoolError, StockPoolService


router = APIRouter()


def service(session: AsyncSession) -> StockPoolService:
    return StockPoolService(StockPoolRepository(session))


@router.get("")
async def list_stock_pools(session: AsyncSession = Depends(get_session)):
    try:
        return ApiResponse.ok(await service(session).list_pools())
    except Exception as exc:
        return ApiResponse.fail(code="stock_pools_query_failed", message=str(exc))


@router.post("")
async def create_stock_pool(payload: StockPoolCreate, session: AsyncSession = Depends(get_session)):
    return await _run(lambda: service(session).create_pool(payload))


@router.patch("/{pool_code}")
async def update_stock_pool(pool_code: str, payload: StockPoolUpdate, session: AsyncSession = Depends(get_session)):
    return await _run(lambda: service(session).update_pool(pool_code, payload))


@router.delete("/{pool_code}")
async def delete_stock_pool(pool_code: str, session: AsyncSession = Depends(get_session)):
    return await _run(lambda: service(session).delete_pool(pool_code))


@router.get("/{pool_code}/members")
async def list_stock_pool_members(
    pool_code: str,
    keyword: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=10, le=200),
    session: AsyncSession = Depends(get_session),
):
    return await _run(lambda: service(session).list_members(pool_code=pool_code, keyword=keyword, page=page, page_size=page_size))


@router.get("/{pool_code}/candidate-stocks")
async def search_stock_pool_candidates(
    pool_code: str,
    keyword: str = Query(min_length=1, max_length=120),
    limit: int = Query(default=20, ge=1, le=20),
    session: AsyncSession = Depends(get_session),
):
    return await _run(lambda: service(session).search_candidate_stocks(pool_code=pool_code, keyword=keyword, limit=limit))


@router.post("/{pool_code}/members/batch")
async def add_stock_pool_members(
    pool_code: str,
    payload: StockPoolMemberBatchCreate,
    session: AsyncSession = Depends(get_session),
):
    return await _run(lambda: service(session).add_members(pool_code=pool_code, payload=payload))


@router.delete("/{pool_code}/members/{stock_code}")
async def delete_stock_pool_member(pool_code: str, stock_code: str, session: AsyncSession = Depends(get_session)):
    async def run():
        await service(session).delete_member(pool_code=pool_code, stock_code=stock_code)
        return {"pool_code": pool_code, "stock_code": stock_code, "deleted": True}

    return await _run(run)


@router.get("/{pool_code}/members/{stock_code}/detail")
async def stock_pool_member_detail(pool_code: str, stock_code: str, session: AsyncSession = Depends(get_session)):
    return await _run(lambda: service(session).member_detail(pool_code=pool_code, stock_code=stock_code))


async def _run(callback):
    try:
        return ApiResponse.ok(await callback())
    except StockPoolError as exc:
        return ApiResponse.fail(code=exc.code, message=exc.message, details=exc.details)
    except Exception as exc:
        return ApiResponse.fail(code="stock_pool_operation_failed", message=str(exc))
