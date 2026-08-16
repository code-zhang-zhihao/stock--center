from __future__ import annotations

from datetime import date

from app.db.session import get_sessionmaker
from app.modules.market_insight.emotion_service import MarketEmotionService
from app.modules.market_insight.report_service import (
    MARKET_REVIEW_CALCULATION_REVISION,
    MarketDailyReviewService,
)
from app.modules.market_insight.repository import MarketInsightRepository
from app.modules.scheduler_center.handlers import JobExecutionContext, job_handler_registry
from app.modules.scheduler_center.schemas import JobResult


REPORT_FACT_TRADE_DATES_PER_BATCH = 10


class CalculateMarketDailySentimentHandler:
    """Build the official dual-score emotion and post-close evidence facts."""

    # Keep the deployed job code stable; its implementation is now the single
    # official emotion model rather than the removed compatibility score.
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
            "description": "与结束日期同时填写时，按开市日范围计算。",
        },
        "end_date": {
            "label": "历史结束日期",
            "type": "string",
            "required": False,
            "description": "与开始日期同时填写时，按开市日范围计算。",
        },
        "include_report_facts": {
            "label": "生成涨停关联证据",
            "type": "boolean",
            "default": True,
            "required": False,
            "description": "板块热度直接读取正式板块因子；这里仅补充涨停关联证据。",
        },
        "emotion_model_code": {
            "label": "情绪模型代码",
            "type": "string",
            "required": False,
            "description": "仅基线校准模式使用，指定草稿或校准中的模型。",
        },
        "emotion_mode": {
            "label": "运行模式",
            "type": "string",
            "default": "daily",
            "required": False,
            "description": "daily 计算启用模型；baseline 分批校准指定模型。",
        },
    }
    default_payload = {"include_report_facts": True, "emotion_mode": "daily"}
    force_async = True

    async def run(self, context: JobExecutionContext) -> JobResult:
        payload = {**self.default_payload, **context.payload}
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            repository = MarketInsightRepository(session)
            mode = str(payload.get("emotion_mode") or "daily")
            try:
                emotion_result = await MarketEmotionService(repository).calculate(
                    model_code=str(payload.get("emotion_model_code") or "").strip() or None,
                    mode=mode,
                    trade_date=_parse_date(payload.get("trade_date")),
                    start_date=_parse_date(payload.get("start_date")),
                    end_date=_parse_date(payload.get("end_date")),
                    progress_reporter=context.report_progress,
                )
            except ValueError as exc:
                if mode != "daily":
                    raise
                return JobResult(
                    status="skipped",
                    affected_rows=0,
                    summary={"emotion": {"skipped": True, "reason": str(exc)}},
                )

            review_summary = None
            evidence_rows = 0
            if mode == "daily" and bool(payload.get("include_report_facts", True)):
                review_service = MarketDailyReviewService(repository)
                rows_by_date = {item["trade_date"]: item for item in emotion_result.rows}
                review_summary = {
                    "calculation_revision": MARKET_REVIEW_CALCULATION_REVISION,
                    "requested_trade_dates": [item.isoformat() for item in emotion_result.requested_trade_dates],
                    "sector_factor_rows": 0,
                    "limit_up_evidence_rows": 0,
                    "ready_trade_dates": 0,
                    "pending_trade_dates": 0,
                    "batch_size": REPORT_FACT_TRADE_DATES_PER_BATCH,
                    "batch_count": 0,
                }
                dates = emotion_result.requested_trade_dates
                for offset in range(0, len(dates), REPORT_FACT_TRADE_DATES_PER_BATCH):
                    batch_dates = dates[offset : offset + REPORT_FACT_TRADE_DATES_PER_BATCH]
                    batch = await review_service.calculate(
                        trade_dates=batch_dates,
                        emotion_rows=[rows_by_date[item] for item in batch_dates if item in rows_by_date],
                        calculation_version=MARKET_REVIEW_CALCULATION_REVISION,
                    )
                    summary = batch.summary()
                    review_summary["sector_factor_rows"] += summary["sector_heat_rows"]
                    review_summary["limit_up_evidence_rows"] += summary["limit_up_evidence_rows"]
                    review_summary["ready_trade_dates"] += summary["ready_trade_dates"]
                    review_summary["pending_trade_dates"] += summary["pending_trade_dates"]
                    review_summary["batch_count"] += 1
                    evidence_rows += summary["limit_up_evidence_rows"]
                    await context.report_progress(
                        {
                            "stage": "calculating_daily_review_evidence",
                            "completed_trade_date_count": min(offset + len(batch_dates), len(dates)),
                            "total_trade_date_count": len(dates),
                        }
                    )

        summary = {"emotion": emotion_result.summary()}
        if review_summary is not None:
            summary["daily_review"] = review_summary
        return JobResult(
            status="success" if emotion_result.ready_count else "skipped",
            affected_rows=emotion_result.upserted_rows + evidence_rows,
            summary=summary,
        )


def register_market_insight_jobs() -> None:
    job_handler_registry.register(CalculateMarketDailySentimentHandler())


def _parse_date(value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))
