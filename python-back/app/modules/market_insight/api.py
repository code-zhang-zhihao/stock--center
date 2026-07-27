from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import ApiResponse
from app.db.session import get_session
from app.modules.market_insight.repository import MarketInsightRepository
from app.modules.market_insight.service import MARKET_SENTIMENT_CALCULATION_VERSION, MarketSentimentService


router = APIRouter()


@router.get("/daily-sentiment")
async def daily_sentiment(
    trade_date: date | None = None,
    calculation_version: str = Query(default=MARKET_SENTIMENT_CALCULATION_VERSION, min_length=1, max_length=40),
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(
            await MarketSentimentService(MarketInsightRepository(session)).read(
                trade_date=trade_date,
                calculation_version=calculation_version,
            )
        )
    except ValueError as exc:
        return ApiResponse.fail(code="market_sentiment_invalid_request", message=str(exc))
    except Exception as exc:
        return ApiResponse.fail(code="market_sentiment_read_failed", message=str(exc))
