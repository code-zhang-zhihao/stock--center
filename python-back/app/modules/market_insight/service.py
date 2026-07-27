from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import mean

from app.modules.market_insight.models import MarketSentimentDaily
from app.modules.market_insight.repository import MarketInsightRepository


MARKET_SENTIMENT_CALCULATION_VERSION = "v1"
MARKET_SENTIMENT_UNIVERSE_CODE = "cn_a_active_non_st"
MIN_DAILY_BAR_COVERAGE_PCT = 95.0
LIMIT_EVENT_COMPLETION_CAPABILITIES = {
    "daily_market_close_stock_limit",
    "stock_limit_event_history_backfill",
}

STAGE_LABELS = {
    "ice_point": "冰点期",
    "retreat": "退潮期",
    "chaos": "混沌期",
    "recovery": "修复期",
    "active": "活跃期",
    "main_up": "主升期",
    "pending": "待完成",
}


@dataclass(slots=True)
class MarketSentimentCalculation:
    calculation_version: str
    universe_code: str
    requested_trade_dates: list[date]
    results: list[dict]
    upserted_rows: int

    @property
    def ready_count(self) -> int:
        return sum(1 for item in self.results if item["status"] == "ready")

    @property
    def pending_count(self) -> int:
        return sum(1 for item in self.results if item["status"] != "ready")

    def summary(self) -> dict:
        return {
            "calculation_version": self.calculation_version,
            "universe_code": self.universe_code,
            "requested_trade_dates": [item.isoformat() for item in self.requested_trade_dates],
            "ready_count": self.ready_count,
            "pending_count": self.pending_count,
            "upserted_rows": self.upserted_rows,
            "results": [serialize_sentiment_payload(item) for item in self.results],
        }


class MarketSentimentService:
    """Builds a deterministic post-close market-state fact from canonical rows.

    This service deliberately contains no external Provider or LLM call.  Its
    inputs are the already-settled day bars, calendar and limit-event facts.
    A missing completion marker yields a persisted ``pending`` result rather
    than a zero-filled score.
    """

    def __init__(self, repository: MarketInsightRepository) -> None:
        self.repository = repository

    async def calculate(
        self,
        *,
        trade_date: date | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        calculation_version: str = MARKET_SENTIMENT_CALCULATION_VERSION,
    ) -> MarketSentimentCalculation:
        calculation_version = _validate_calculation_version(calculation_version)
        target_dates = await self._target_dates(trade_date=trade_date, start_date=start_date, end_date=end_date)
        if not target_dates:
            return MarketSentimentCalculation(
                calculation_version=calculation_version,
                universe_code=MARKET_SENTIMENT_UNIVERSE_CODE,
                requested_trade_dates=[],
                results=[],
                upserted_rows=0,
            )

        # Amount comparison and board height need a small preceding window.
        context_start = target_dates[0] - timedelta(days=45)
        context_dates = await self.repository.open_trade_dates_between(
            start_date=context_start,
            end_date=target_dates[-1],
        )
        all_dates = list(dict.fromkeys(context_dates))
        target_set = set(target_dates)
        active_stock_count = await self.repository.active_stock_count()
        daily_metrics, event_metrics, limit_up_codes, completion, premiums = await self._load_inputs(all_dates, target_dates)
        board_heights = _board_heights(all_dates, limit_up_codes, completion)

        previous_scores = deque(
            reversed(
                await self.repository.sentiment_scores_before(
                    trade_date=target_dates[0],
                    universe_code=MARKET_SENTIMENT_UNIVERSE_CODE,
                    calculation_version=calculation_version,
                    limit=2,
                )
            ),
            maxlen=2,
        )
        amount_history: deque[float] = deque(maxlen=5)
        rows: list[dict] = []
        for current_date in all_dates:
            metrics = daily_metrics.get(current_date, {})
            if current_date in target_set:
                row = self._build_row(
                    trade_date=current_date,
                    active_stock_count=active_stock_count,
                    daily_metrics=metrics,
                    event_metrics=event_metrics.get(current_date, {}),
                    limit_event_capabilities=completion.get(current_date, set()),
                    highest_board_count=board_heights.get(current_date, 0),
                    premium=premiums.get(current_date),
                    previous_amounts=list(amount_history),
                    previous_scores=list(previous_scores),
                    calculation_version=calculation_version,
                )
                rows.append(row)
                if row["status"] == "ready" and row["sentiment_score"] is not None:
                    previous_scores.append(float(row["sentiment_score"]))
            total_amount = _number_or_none(metrics.get("total_amount_yuan"))
            if total_amount is not None:
                amount_history.append(total_amount)

        upserted_rows = await self.repository.upsert_sentiments(rows)
        if upserted_rows:
            await self.repository.commit()
        return MarketSentimentCalculation(
            calculation_version=calculation_version,
            universe_code=MARKET_SENTIMENT_UNIVERSE_CODE,
            requested_trade_dates=target_dates,
            results=rows,
            upserted_rows=upserted_rows,
        )

    async def read(
        self,
        *,
        trade_date: date | None = None,
        calculation_version: str = MARKET_SENTIMENT_CALCULATION_VERSION,
    ) -> dict:
        calculation_version = _validate_calculation_version(calculation_version)
        row = await self.repository.latest_sentiment(
            universe_code=MARKET_SENTIMENT_UNIVERSE_CODE,
            calculation_version=calculation_version,
            trade_date=trade_date,
        )
        if row is None:
            return {
                "available": False,
                "reason": "market_sentiment_not_calculated",
                "trade_date": trade_date.isoformat() if trade_date else None,
                "calculation_version": calculation_version,
                "universe_code": MARKET_SENTIMENT_UNIVERSE_CODE,
            }
        payload = serialize_sentiment_model(row)
        return {"available": payload["status"] == "ready", **payload}

    async def _target_dates(
        self,
        *,
        trade_date: date | None,
        start_date: date | None,
        end_date: date | None,
    ) -> list[date]:
        if start_date is not None or end_date is not None:
            if start_date is None or end_date is None:
                raise ValueError("start_date 和 end_date 必须同时提供")
            if trade_date is not None:
                raise ValueError("trade_date 不能与 start_date/end_date 同时提供")
            return await self.repository.open_trade_dates_between(start_date=start_date, end_date=end_date)
        target_date = trade_date or await self.repository.latest_daily_bar_trade_date()
        if target_date is None:
            return []
        return await self.repository.open_trade_dates_between(start_date=target_date, end_date=target_date)

    async def _load_inputs(self, all_dates: list[date], target_dates: list[date]):
        # All reads share one AsyncSession.  Keep them sequential instead of
        # overlapping DB operations on the same connection; each is grouped
        # by date and therefore remains small even during historical backfill.
        return (
            await self.repository.daily_bar_metrics(all_dates),
            await self.repository.limit_event_metrics(all_dates),
            await self.repository.limit_up_codes(all_dates),
            await self.repository.limit_event_completion_capabilities(all_dates),
            await self.repository.previous_limit_up_premiums(target_dates),
        )

    @staticmethod
    def _build_row(
        *,
        trade_date: date,
        active_stock_count: int,
        daily_metrics: dict,
        event_metrics: dict,
        limit_event_capabilities: set[str],
        highest_board_count: int,
        premium: dict | None,
        previous_amounts: list[float],
        previous_scores: list[float],
        calculation_version: str,
    ) -> dict:
        daily_bar_count = int(daily_metrics.get("daily_bar_count") or 0)
        coverage_pct = _pct(daily_bar_count, active_stock_count)
        completed_capabilities = sorted(limit_event_capabilities)
        limit_event_complete = bool(LIMIT_EVENT_COMPLETION_CAPABILITIES.intersection(limit_event_capabilities))
        unavailable_reasons: list[str] = []
        if active_stock_count <= 0:
            unavailable_reasons.append("active_universe_empty")
        if coverage_pct is None or coverage_pct < MIN_DAILY_BAR_COVERAGE_PCT:
            unavailable_reasons.append("daily_bar_coverage_below_threshold")
        if not limit_event_complete:
            unavailable_reasons.append("limit_event_ingest_incomplete")

        metrics = _metrics_payload(
            active_stock_count=active_stock_count,
            daily_metrics=daily_metrics,
            event_metrics=event_metrics,
            highest_board_count=highest_board_count,
            premium=premium,
            previous_amounts=previous_amounts,
        )
        coverage = {
            "active_stock_count": active_stock_count,
            "daily_bar_count": daily_bar_count,
            "daily_bar_coverage_pct": coverage_pct,
            "minimum_daily_bar_coverage_pct": MIN_DAILY_BAR_COVERAGE_PCT,
            "limit_event_complete": limit_event_complete,
            "completion_capabilities": completed_capabilities,
            "unavailable_reasons": unavailable_reasons,
        }
        source_facts = {
            "daily_bar_table": "t_daily_bar",
            "limit_event_table": "t_limit_event_daily",
            "trade_calendar_table": "t_trade_calendar",
            "completion_table": "t_provider_raw_record",
            "universe_definition": "t_stock.status=active AND is_st=false AND exchange in (SH,SZ,SSE,SZSE)",
        }
        base = {
            "trade_date": trade_date,
            "universe_code": MARKET_SENTIMENT_UNIVERSE_CODE,
            "calculation_version": calculation_version,
            "metrics": metrics,
            "coverage": coverage,
            "source_facts": source_facts,
        }
        if unavailable_reasons:
            return {
                **base,
                "status": "pending",
                "sentiment_score": None,
                "stage_code": "pending",
                "components": {},
            }

        components = _score_components(metrics)
        available_components = [item for item in components.values() if item["available"]]
        total_weight = sum(float(item["weight"]) for item in available_components)
        score = round(
            sum(float(item["score"]) * float(item["weight"]) for item in available_components) / total_weight,
            2,
        ) if total_weight else None
        stage_code = _stage_code(score, previous_scores=previous_scores, metrics=metrics)
        return {
            **base,
            "status": "ready",
            "sentiment_score": score,
            "stage_code": stage_code,
            "components": components,
        }


def _metrics_payload(
    *,
    active_stock_count: int,
    daily_metrics: dict,
    event_metrics: dict,
    highest_board_count: int,
    premium: dict | None,
    previous_amounts: list[float],
) -> dict:
    up_count = int(daily_metrics.get("up_count") or 0)
    down_count = int(daily_metrics.get("down_count") or 0)
    flat_count = int(daily_metrics.get("flat_count") or 0)
    limit_up_count = int(event_metrics.get("limit_up_count") or 0)
    limit_down_count = int(event_metrics.get("limit_down_count") or 0)
    limit_break_count = int(event_metrics.get("limit_break_count") or 0)
    total_amount = _number_or_none(daily_metrics.get("total_amount_yuan"))
    amount_baseline = mean(previous_amounts) if len(previous_amounts) >= 3 else None
    amount_ratio = total_amount / amount_baseline if total_amount is not None and amount_baseline else None
    seal_denominator = limit_up_count + limit_break_count
    return {
        "active_stock_count": active_stock_count,
        "up_count": up_count,
        "down_count": down_count,
        "flat_count": flat_count,
        "up_ratio_pct": _pct(up_count, active_stock_count),
        "down_ratio_pct": _pct(down_count, active_stock_count),
        "average_change_pct": _number_or_none(daily_metrics.get("average_change_pct")),
        "median_change_pct": _number_or_none(daily_metrics.get("median_change_pct")),
        "total_amount_yuan": total_amount,
        "amount_5d_average_yuan": round(amount_baseline, 2) if amount_baseline is not None else None,
        "amount_vs_5d_average": round(amount_ratio, 4) if amount_ratio is not None else None,
        "limit_up_count": limit_up_count,
        "limit_down_count": limit_down_count,
        "limit_break_count": limit_break_count,
        "seal_rate_pct": _pct(limit_up_count, seal_denominator),
        "highest_board_count": highest_board_count,
        "previous_limit_up_premium_pct": _number_or_none((premium or {}).get("average_change_pct")),
        "previous_limit_up_premium_stock_count": int((premium or {}).get("stock_count") or 0),
    }


def _score_components(metrics: dict) -> dict:
    up_ratio = _number_or_none(metrics.get("up_ratio_pct"))
    median_change = _number_or_none(metrics.get("median_change_pct"))
    active_count = int(metrics.get("active_stock_count") or 0)
    limit_up_count = int(metrics.get("limit_up_count") or 0)
    seal_rate = _number_or_none(metrics.get("seal_rate_pct"))
    premium = _number_or_none(metrics.get("previous_limit_up_premium_pct"))
    amount_ratio = _number_or_none(metrics.get("amount_vs_5d_average"))
    return {
        "breadth": _component("上涨扩散", 0.30, up_ratio, up_ratio, "上涨家数 ÷ active 股票数 × 100"),
        "median_return": _component("中位涨跌", 0.20, median_change, _clamp(50 + median_change * 12.5) if median_change is not None else None, "中位涨跌幅按 -4% 到 +4% 映射为 0–100"),
        "limit_heat": _component(
            "涨停热度",
            0.20,
            limit_up_count,
            _clamp(limit_up_count / active_count * 5000) if active_count else None,
            "涨停家数占 active 股票 2% 时记为 100 分",
        ),
        "seal_rate": _component("封板质量", 0.10, seal_rate, seal_rate, "涨停 ÷（涨停 + 炸板）× 100；无涨停/炸板时不参与加权"),
        "limit_premium": _component("昨日涨停溢价", 0.12, premium, _clamp(50 + premium * 10) if premium is not None else None, "昨日涨停股今日平均涨跌幅按 -5% 到 +5% 映射为 0–100"),
        "liquidity": _component("成交活跃度", 0.08, amount_ratio, _clamp((amount_ratio - 0.6) / 0.8 * 100) if amount_ratio is not None else None, "当日成交额相对前 5 个有效日均值，0.6 倍到 1.4 倍映射为 0–100"),
    }


def _component(label: str, weight: float, raw_value: float | int | None, score: float | None, formula: str) -> dict:
    return {
        "label": label,
        "weight": weight,
        "raw_value": round(float(raw_value), 4) if raw_value is not None else None,
        "score": round(float(score), 2) if score is not None else None,
        "available": score is not None,
        "formula": formula,
    }


def _board_heights(
    trade_dates: list[date],
    limit_up_codes: dict[date, set[str]],
    completion: dict[date, set[str]],
) -> dict[date, int]:
    current_streaks: dict[str, int] = {}
    result: dict[date, int] = {}
    for trade_date in trade_dates:
        if not LIMIT_EVENT_COMPLETION_CAPABILITIES.intersection(completion.get(trade_date, set())):
            current_streaks = {}
            result[trade_date] = 0
            continue
        next_streaks = {
            stock_code: current_streaks.get(stock_code, 0) + 1
            for stock_code in limit_up_codes.get(trade_date, set())
        }
        result[trade_date] = max(next_streaks.values(), default=0)
        current_streaks = next_streaks
    return result


def _stage_code(score: float | None, *, previous_scores: list[float], metrics: dict) -> str:
    if score is None:
        return "pending"
    if score <= 25:
        return "ice_point"
    if score < 40:
        return "retreat"
    if score < 60:
        return "chaos"
    if score < 75:
        return "recovery"
    if (
        len(previous_scores) >= 2
        and all(item >= 70 for item in previous_scores[-2:])
        and int(metrics.get("highest_board_count") or 0) >= 3
        and (_number_or_none(metrics.get("previous_limit_up_premium_pct")) or 0) >= 0
    ):
        return "main_up"
    return "active"


def serialize_sentiment_model(row: MarketSentimentDaily) -> dict:
    return serialize_sentiment_payload(
        {
            "trade_date": row.trade_date,
            "universe_code": row.universe_code,
            "calculation_version": row.calculation_version,
            "status": row.status,
            "sentiment_score": _number_or_none(row.sentiment_score),
            "stage_code": row.stage_code,
            "components": row.components or {},
            "metrics": row.metrics or {},
            "coverage": row.coverage or {},
            "source_facts": row.source_facts or {},
            "calculated_at": row.calculated_at,
        }
    )


def serialize_sentiment_payload(payload: dict) -> dict:
    stage_code = str(payload.get("stage_code") or "pending")
    trade_date = payload.get("trade_date")
    calculated_at = payload.get("calculated_at")
    return {
        "trade_date": trade_date.isoformat() if isinstance(trade_date, date) else trade_date,
        "universe_code": payload.get("universe_code"),
        "calculation_version": payload.get("calculation_version"),
        "status": payload.get("status"),
        "sentiment_score": _number_or_none(payload.get("sentiment_score")),
        "stage_code": stage_code,
        "stage_label": STAGE_LABELS.get(stage_code, stage_code),
        "components": payload.get("components") or {},
        "metrics": payload.get("metrics") or {},
        "coverage": payload.get("coverage") or {},
        "source_facts": payload.get("source_facts") or {},
        "calculated_at": calculated_at.isoformat() if hasattr(calculated_at, "isoformat") else calculated_at,
    }


def _number_or_none(value) -> float | None:
    return float(value) if value is not None else None


def _pct(numerator: int | float, denominator: int | float) -> float | None:
    if not denominator:
        return None
    return round(float(numerator) / float(denominator) * 100, 4)


def _clamp(value: float, lower: float = 0, upper: float = 100) -> float:
    return max(lower, min(upper, value))


def _validate_calculation_version(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > 40 or not all(item.isalnum() or item in {"-", "_", "."} for item in normalized):
        raise ValueError("calculation_version 只能包含字母、数字、连字符、下划线和点，长度不超过 40")
    return normalized
