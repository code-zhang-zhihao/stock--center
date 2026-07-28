from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import ApiResponse
from app.db.session import get_session
from app.modules.market_insight.report_service import MarketDailyReviewService
from app.modules.market_insight.repository import MarketInsightRepository
from app.modules.market_insight.service import MARKET_SENTIMENT_CALCULATION_VERSION, MarketSentimentService
from app.modules.market_insight.emotion_service import MarketEmotionService


router = APIRouter()


class EmotionModelCreateRequest(BaseModel):
    model_code: str = Field(min_length=1, max_length=80)
    model_name: str = Field(min_length=1, max_length=160)
    clone_from: str | None = Field(default=None, max_length=80)


class EmotionModelUpdateRequest(BaseModel):
    model_name: str | None = Field(default=None, min_length=1, max_length=160)
    percentile_window_days: int | None = Field(default=None, ge=60, le=500)
    minimum_history_days: int | None = Field(default=None, ge=20, le=500)
    baseline_trade_days: int | None = Field(default=None, ge=60, le=1000)
    parameter_json: dict[str, Any] | None = None


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


@router.get("/emotion-daily")
async def emotion_daily(
    trade_date: date | None = None,
    model_code: str | None = Query(default=None, min_length=1, max_length=80),
    history_limit: int = Query(default=60, ge=20, le=1000),
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(
            await MarketEmotionService(MarketInsightRepository(session)).read(
                trade_date=trade_date,
                model_code=model_code,
                history_limit=history_limit,
            )
        )
    except ValueError as exc:
        return ApiResponse.fail(code="market_emotion_invalid_request", message=str(exc))
    except Exception as exc:
        return ApiResponse.fail(code="market_emotion_read_failed", message=str(exc))


@router.get("/emotion-models")
async def emotion_models(session: AsyncSession = Depends(get_session)):
    try:
        return ApiResponse.ok({"items": await MarketEmotionService(MarketInsightRepository(session)).list_models()})
    except Exception as exc:
        return ApiResponse.fail(code="market_emotion_models_read_failed", message=str(exc))


@router.get("/emotion-models/{model_code}/validation")
async def emotion_model_validation(
    model_code: str,
    history_limit: int = Query(default=1000, ge=60, le=1000),
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(
            await MarketEmotionService(MarketInsightRepository(session)).validation_preview(
                model_code=model_code,
                history_limit=history_limit,
            )
        )
    except ValueError as exc:
        return ApiResponse.fail(code="market_emotion_validation_invalid_request", message=str(exc))
    except Exception as exc:
        return ApiResponse.fail(code="market_emotion_validation_read_failed", message=str(exc))


@router.get("/emotion-models/{model_code}")
async def emotion_model_detail(model_code: str, session: AsyncSession = Depends(get_session)):
    try:
        service = MarketEmotionService(MarketInsightRepository(session))
        items = await service.list_models()
        model = next((item for item in items if item["model_code"] == model_code), None)
        if model is None:
            return ApiResponse.fail(code="market_emotion_model_not_found", message="模型不存在")
        return ApiResponse.ok(model)
    except Exception as exc:
        return ApiResponse.fail(code="market_emotion_model_read_failed", message=str(exc))


@router.post("/emotion-models")
async def create_emotion_model(payload: EmotionModelCreateRequest, session: AsyncSession = Depends(get_session)):
    try:
        return ApiResponse.ok(
            await MarketEmotionService(MarketInsightRepository(session)).create_draft(
                model_code=payload.model_code,
                model_name=payload.model_name,
                clone_from=payload.clone_from,
            )
        )
    except ValueError as exc:
        return ApiResponse.fail(code="market_emotion_model_invalid", message=str(exc))
    except Exception as exc:
        return ApiResponse.fail(code="market_emotion_model_create_failed", message=str(exc))


@router.patch("/emotion-models/{model_code}")
async def update_emotion_model(
    model_code: str,
    payload: EmotionModelUpdateRequest,
    session: AsyncSession = Depends(get_session),
):
    try:
        return ApiResponse.ok(
            await MarketEmotionService(MarketInsightRepository(session)).update_draft(
                model_code=model_code,
                values=payload.model_dump(exclude_none=True),
            )
        )
    except ValueError as exc:
        return ApiResponse.fail(code="market_emotion_model_invalid", message=str(exc))
    except Exception as exc:
        return ApiResponse.fail(code="market_emotion_model_update_failed", message=str(exc))


@router.post("/emotion-models/{model_code}/calibrate")
async def calibrate_emotion_model(model_code: str, session: AsyncSession = Depends(get_session)):
    try:
        return ApiResponse.ok(
            await MarketEmotionService(MarketInsightRepository(session)).start_calibration(model_code=model_code)
        )
    except ValueError as exc:
        return ApiResponse.fail(code="market_emotion_model_invalid", message=str(exc))
    except Exception as exc:
        return ApiResponse.fail(code="market_emotion_model_calibration_failed", message=str(exc))


@router.post("/emotion-models/{model_code}/activate")
async def activate_emotion_model(model_code: str, session: AsyncSession = Depends(get_session)):
    try:
        return ApiResponse.ok(await MarketEmotionService(MarketInsightRepository(session)).activate(model_code=model_code))
    except ValueError as exc:
        return ApiResponse.fail(code="market_emotion_model_invalid", message=str(exc))
    except Exception as exc:
        return ApiResponse.fail(code="market_emotion_model_activation_failed", message=str(exc))
