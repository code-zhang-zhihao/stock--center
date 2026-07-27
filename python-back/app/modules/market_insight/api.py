from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import ApiResponse
from app.db.session import get_session
from app.modules.market_insight.report_service import MarketDailyReviewService
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


@router.get("/daily-review")
async def daily_review(
    trade_date: date | None = None,
    calculation_version: str = Query(default=MARKET_SENTIMENT_CALCULATION_VERSION, min_length=1, max_length=40),
    sector_limit: int = Query(default=12, ge=1, le=50),
    evidence_limit: int = Query(default=40, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(
            await MarketDailyReviewService(MarketInsightRepository(session)).read(
                trade_date=trade_date,
                calculation_version=calculation_version,
                sector_limit=sector_limit,
                evidence_limit=evidence_limit,
            )
        )
    except ValueError as exc:
        return ApiResponse.fail(code="market_daily_review_invalid_request", message=str(exc))
    except Exception as exc:
        return ApiResponse.fail(code="market_daily_review_read_failed", message=str(exc))
