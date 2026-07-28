from __future__ import annotations

from datetime import date

from app.db.session import get_sessionmaker
from app.modules.market_insight.emotion_service import MarketEmotionService
from app.modules.market_insight.report_service import MarketDailyReviewService
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
        "include_report_facts": {
            "label": "生成热点与涨停证据",
            "type": "boolean",
            "default": True,
            "required": False,
            "description": "默认同时沉淀概念热度、板块龙头和涨停关联证据；大范围历史情绪回填可关闭以缩短执行时间。",
        },
        "include_v2_emotion": {
            "label": "计算 V2 双分情绪",
            "type": "boolean",
            "default": True,
            "required": False,
            "description": "日常运行只计算已启用的 V2 模型；没有启用模型时跳过，不影响 V1 兼容报告。",
        },
        "emotion_model_code": {
            "label": "V2 模型代码",
            "type": "string",
            "required": False,
            "description": "仅基线校准模式使用，指定草稿或校准中的模型。",
        },
        "emotion_mode": {
            "label": "V2 运行模式",
            "type": "string",
            "default": "daily",
            "required": False,
            "description": "daily 计算启用模型的指定日；baseline 按模型基线交易日分批回填，期间不生成 V1 热点/证据。",
        },
    }
    default_payload = {
        "calculation_version": MARKET_SENTIMENT_CALCULATION_VERSION,
        "include_report_facts": True,
        "include_v2_emotion": True,
        "emotion_mode": "daily",
    }
    force_async = True

    async def run(self, context: JobExecutionContext) -> JobResult:
        payload = {**self.default_payload, **context.payload}
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            repository = MarketInsightRepository(session)
            emotion_mode = str(payload.get("emotion_mode") or "daily")
            if emotion_mode == "baseline":
                emotion_result = await MarketEmotionService(repository).calculate(
                    model_code=str(payload.get("emotion_model_code") or "").strip() or None,
                    mode="baseline",
                    trade_date=_parse_date(payload.get("trade_date")),
                    start_date=_parse_date(payload.get("start_date")),
                    end_date=_parse_date(payload.get("end_date")),
                    progress_reporter=context.report_progress,
                )
                return JobResult(
                    status="success" if emotion_result.ready_count else "skipped",
                    affected_rows=emotion_result.upserted_rows,
                    summary={"v2_emotion": emotion_result.summary()},
                )
            result = await MarketSentimentService(repository).calculate(
                trade_date=_parse_date(payload.get("trade_date")),
                start_date=_parse_date(payload.get("start_date")),
                end_date=_parse_date(payload.get("end_date")),
                calculation_version=str(payload.get("calculation_version") or MARKET_SENTIMENT_CALCULATION_VERSION),
            )
            review_summary = None
            if bool(payload.get("include_report_facts", True)):
                review_summary = (
                    await MarketDailyReviewService(repository).calculate(
                        trade_dates=result.requested_trade_dates,
                        sentiment_rows=result.results,
                        calculation_version=result.calculation_version,
                    )
                ).summary()
            emotion_summary = None
            if bool(payload.get("include_v2_emotion", True)):
                # The absence of an enabled V2 model is normal before an admin
                # finishes the baseline.  Preserve the V1 close report rather
                # than failing its daily task.
                try:
                    emotion_result = await MarketEmotionService(repository).calculate(
                        mode="daily",
                        trade_date=_parse_date(payload.get("trade_date")),
                        start_date=_parse_date(payload.get("start_date")),
                        end_date=_parse_date(payload.get("end_date")),
                        progress_reporter=context.report_progress,
                    )
                    emotion_summary = emotion_result.summary()
                except ValueError as exc:
                    emotion_summary = {"skipped": True, "reason": str(exc)}
        summary = result.summary()
        if review_summary is not None:
            summary["daily_review"] = review_summary
        if emotion_summary is not None:
            summary["v2_emotion"] = emotion_summary
        return JobResult(
            status="success" if result.ready_count else "skipped",
            affected_rows=result.upserted_rows + int((review_summary or {}).get("sector_heat_rows") or 0) + int((review_summary or {}).get("limit_up_evidence_rows") or 0) + int((emotion_summary or {}).get("upserted_rows") or 0),
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
