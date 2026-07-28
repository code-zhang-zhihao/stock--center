from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import ApiResponse
from app.db.session import get_session
from app.modules.strategy_center.repository import StrategyCenterRepository
from app.modules.strategy_center.schemas import StrategyDefinitionCreate, StrategyDefinitionUpdate
from app.modules.strategy_center.service import StrategyCenterError, StrategyCenterService


router = APIRouter()


def service(session: AsyncSession) -> StrategyCenterService:
    return StrategyCenterService(StrategyCenterRepository(session))


@router.get("/dashboard")
async def dashboard(session: AsyncSession = Depends(get_session)):
    return await _run(lambda: service(session).dashboard())


@router.post("")
async def create_definition(payload: StrategyDefinitionCreate, session: AsyncSession = Depends(get_session)):
    return await _run(lambda: service(session).create_definition(payload))


@router.patch("/{strategy_code}")
async def update_definition(
    strategy_code: str,
    payload: StrategyDefinitionUpdate,
    session: AsyncSession = Depends(get_session),
):
    return await _run(lambda: service(session).update_definition(strategy_code, payload))


@router.get("/candidates")
async def candidates(
    strategy_code: str | None = Query(default=None, min_length=1, max_length=60),
    signal_trade_date: date | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
):
    return await _run(
        lambda: service(session).candidates(
            strategy_code=strategy_code,
            signal_trade_date=signal_trade_date,
            limit=limit,
        )
    )


async def _run(callback):
    try:
        return ApiResponse.ok(await callback())
    except StrategyCenterError as exc:
        return ApiResponse.fail(code=exc.code, message=exc.message, details=exc.details)
    except Exception as exc:
        return ApiResponse.fail(code="strategy_center_operation_failed", message=str(exc))
