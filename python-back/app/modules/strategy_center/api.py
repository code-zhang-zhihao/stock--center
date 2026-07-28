from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import ApiResponse
from app.db.session import get_session
from app.modules.strategy_center.repository import StrategyCenterRepository
from app.modules.strategy_center.schemas import (
    StrategyBacktestCreate,
    StrategyDefinitionCreate,
    StrategyDefinitionUpdate,
    StrategyVersionCreate,
    StrategyVersionUpdate,
)
from app.modules.strategy_center.service import StrategyCenterError, StrategyCenterService


router = APIRouter()


def service(session: AsyncSession) -> StrategyCenterService:
    return StrategyCenterService(StrategyCenterRepository(session))


@router.get("/dashboard")
async def dashboard(session: AsyncSession = Depends(get_session)):
    return await _run(lambda: service(session).dashboard())


@router.get("/templates")
async def builtin_templates(session: AsyncSession = Depends(get_session)):
    return await _run(lambda: service(session).builtin_templates())


@router.post("/bootstrap-builtins")
async def bootstrap_builtin_definitions(session: AsyncSession = Depends(get_session)):
    return await _run(lambda: service(session).bootstrap_builtin_definitions())


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


@router.get("/{strategy_code}/versions")
async def versions(strategy_code: str, session: AsyncSession = Depends(get_session)):
    return await _run(lambda: service(session).versions(strategy_code))


@router.get("/{strategy_code}/backtests")
async def backtests(
    strategy_code: str,
    limit: int = Query(default=20, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
):
    return await _run(lambda: service(session).backtests(strategy_code=strategy_code, limit=limit))


@router.post("/{strategy_code}/versions")
async def create_version(
    strategy_code: str,
    payload: StrategyVersionCreate,
    session: AsyncSession = Depends(get_session),
):
    return await _run(lambda: service(session).create_version(strategy_code, payload))


@router.patch("/{strategy_code}/versions/{version_no}")
async def update_version(
    strategy_code: str,
    version_no: int,
    payload: StrategyVersionUpdate,
    session: AsyncSession = Depends(get_session),
):
    return await _run(lambda: service(session).update_version(strategy_code, version_no, payload))


@router.post("/{strategy_code}/versions/{version_no}/backtests")
async def run_backtest(
    strategy_code: str,
    version_no: int,
    payload: StrategyBacktestCreate,
    session: AsyncSession = Depends(get_session),
):
    return await _run(
        lambda: service(session).run_backtest(
            strategy_code=strategy_code,
            version_no=version_no,
            start_date=payload.start_date,
            end_date=payload.end_date,
            fee_rate=payload.fee_rate,
            slippage_bps=payload.slippage_bps,
        )
    )


@router.post("/{strategy_code}/versions/{version_no}/promote-paper")
async def promote_version_to_paper(
    strategy_code: str,
    version_no: int,
    session: AsyncSession = Depends(get_session),
):
    return await _run(lambda: service(session).promote_version_to_paper(strategy_code, version_no))


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
