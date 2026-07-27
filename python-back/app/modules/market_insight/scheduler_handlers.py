from __future__ import annotations

from datetime import date

from app.db.session import get_sessionmaker
from app.modules.market_insight.repository import MarketInsightRepository
from app.modules.market_insight.service import MARKET_SENTIMENT_CALCULATION_VERSION, MarketSentimentService
from app.modules.scheduler_center.handlers import JobExecutionContext, job_handler_registry
from app.modules.scheduler_center.schemas import JobResult


class CalculateMarketDailySentimentHandler:
    """Calculate only from already persisted daily facts; never calls a Provider."""

    job_code = "calculate_market_daily_sentiment"
    job_type = "market_insight"
    parameter_schema = {
        "trade_date": {
            "label": "指定交易日期",
            "type": "string",
            "required": False,
            "description": "为空时计算最新已有日 K 的交易日。",
        },
        "start_date": {
            "label": "历史开始日期",
            "type": "string",
            "required": False,
            "description": "与历史结束日期同时填写时，按开市日范围计算历史情绪事实。",
        },
        "end_date": {
            "label": "历史结束日期",
            "type": "string",
            "required": False,
            "description": "与历史开始日期同时填写时，按开市日范围计算历史情绪事实。",
        },
        "calculation_version": {
            "label": "计算版本",
            "type": "string",
            "default": MARKET_SENTIMENT_CALCULATION_VERSION,
            "required": False,
            "description": "算法版本；修改版本会保留旧版本行，不覆盖既有日报或回测口径。",
        },
    }
    default_payload = {"calculation_version": MARKET_SENTIMENT_CALCULATION_VERSION}
    force_async = True

    async def run(self, context: JobExecutionContext) -> JobResult:
        payload = {**self.default_payload, **context.payload}
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            result = await MarketSentimentService(MarketInsightRepository(session)).calculate(
                trade_date=_parse_date(payload.get("trade_date")),
                start_date=_parse_date(payload.get("start_date")),
                end_date=_parse_date(payload.get("end_date")),
                calculation_version=str(payload.get("calculation_version") or MARKET_SENTIMENT_CALCULATION_VERSION),
            )
        return JobResult(
            status="success" if result.ready_count else "skipped",
            affected_rows=result.upserted_rows,
            summary=result.summary(),
        )


def register_market_insight_jobs() -> None:
    job_handler_registry.register(CalculateMarketDailySentimentHandler())


def _parse_date(value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))
