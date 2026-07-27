from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from app.modules.market_insight.models import MarketLimitUpEvidenceDaily, MarketSectorHeatDaily
from app.modules.market_insight.repository import MarketInsightRepository
from app.modules.market_insight.service import (
    LIMIT_EVENT_COMPLETION_CAPABILITIES,
    MARKET_SENTIMENT_CALCULATION_VERSION,
    MarketSentimentService,
    _number_or_none,
    _validate_calculation_version,
)


MIN_CONCEPT_COMPONENTS = 3
LEADER_CONTEXT_SECTOR_LIMIT = 24
HOT_SECTOR_WEIGHTS = {
    "relative_return": 0.35,
    "rising_breadth": 0.25,
    "limit_up_density": 0.25,
    "capital_inflow": 0.15,
}


@dataclass(slots=True)
class MarketDailyReviewCalculation:
    calculation_version: str
    requested_trade_dates: list[date]
    sector_heat_rows: int
    limit_up_evidence_rows: int
    ready_trade_dates: int
    pending_trade_dates: int

    def summary(self) -> dict:
        return {
            "calculation_version": self.calculation_version,
            "requested_trade_dates": [item.isoformat() for item in self.requested_trade_dates],
            "sector_heat_rows": self.sector_heat_rows,
            "limit_up_evidence_rows": self.limit_up_evidence_rows,
            "ready_trade_dates": self.ready_trade_dates,
            "pending_trade_dates": self.pending_trade_dates,
        }


class MarketDailyReviewService:
    """Create a reproducible post-close concept and limit-up evidence view.

    The report uses canonical component facts rather than ``ths_daily``.  This
    avoids a late THS board-bar publication making an otherwise complete stock
    market report unavailable.  Announcement and LHB records remain labelled
    as *associated evidence*, never as a causal explanation for a limit-up.
    """

    def __init__(self, repository: MarketInsightRepository) -> None:
        self.repository = repository

    async def calculate(
        self,
        *,
        trade_dates: list[date],
        sentiment_rows: list[dict],
        calculation_version: str = MARKET_SENTIMENT_CALCULATION_VERSION,
    ) -> MarketDailyReviewCalculation:
        calculation_version = _validate_calculation_version(calculation_version)
        target_dates = sorted(set(trade_dates))
        if not target_dates:
            return MarketDailyReviewCalculation(calculation_version, [], 0, 0, 0, 0)

        sentiment_status = {
            item["trade_date"]: item["status"] == "ready"
            for item in sentiment_rows
            if isinstance(item.get("trade_date"), date)
        }
        metric_rows = await self.repository.concept_metrics(target_dates)
        sector_rows, heat_lookup = _build_sector_heat_rows(
            target_dates=target_dates,
            metrics_by_date=metric_rows,
            sentiment_status=sentiment_status,
            calculation_version=calculation_version,
        )
        leader_sector_codes = sorted(
            {
                row["sector_code"]
                for row in sector_rows
                if row["status"] == "ready" and (row["heat_rank"] or 0) <= LEADER_CONTEXT_SECTOR_LIMIT
            }
        )
        leader_candidates = await self.repository.concept_leader_candidates(
            trade_dates=target_dates,
            sector_codes=leader_sector_codes,
        )
        _attach_sector_leaders(sector_rows, leader_candidates)

        limit_rows = await self.repository.limit_up_market_rows(target_dates)
        evidence_rows = await self._build_limit_up_evidence_rows(
            target_dates=target_dates,
            limit_rows=limit_rows,
            heat_lookup=heat_lookup,
            sentiment_status=sentiment_status,
            calculation_version=calculation_version,
        )
        sector_count = await self.repository.upsert_sector_heat_rows(sector_rows)
        evidence_count = await self.repository.upsert_limit_up_evidence_rows(evidence_rows)
        if sector_count or evidence_count:
            await self.repository.commit()
        ready_dates = sum(1 for item in target_dates if sentiment_status.get(item, False))
        return MarketDailyReviewCalculation(
            calculation_version=calculation_version,
            requested_trade_dates=target_dates,
            sector_heat_rows=sector_count,
            limit_up_evidence_rows=evidence_count,
            ready_trade_dates=ready_dates,
            pending_trade_dates=len(target_dates) - ready_dates,
        )

    async def _build_limit_up_evidence_rows(
        self,
        *,
        target_dates: list[date],
        limit_rows: dict[tuple[date, str], dict],
        heat_lookup: dict[tuple[date, str], dict],
        sentiment_status: dict[date, bool],
        calculation_version: str,
    ) -> list[dict]:
        stock_codes = sorted({stock_code for _, stock_code in limit_rows})
        lhb_rows = await self.repository.lhb_rows_for_limit_ups(
            trade_dates=target_dates,
            stock_codes=stock_codes,
        )
        announcements = await self.repository.announcements_for_limit_ups(
            stock_codes=stock_codes,
            start_date=min(target_dates) - timedelta(days=3),
            end_date=max(target_dates),
        )
        memberships = await self.repository.concept_memberships_for_stocks(stock_codes)
        lhb_capabilities = await self.repository.raw_capabilities_by_date(
            trade_dates=target_dates,
            normalized_table="t_lhb_event",
        )

        context_dates = await self.repository.open_trade_dates_between(
            start_date=min(target_dates) - timedelta(days=45),
            end_date=max(target_dates),
        )
        limit_up_codes = await self.repository.limit_up_codes(context_dates)
        completion = await self.repository.limit_event_completion_capabilities(context_dates)
        board_counts = _board_counts(context_dates, limit_up_codes, completion)

        rows: list[dict] = []
        for (trade_date, stock_code), market_snapshot in sorted(limit_rows.items()):
            ready = sentiment_status.get(trade_date, False)
            sector_context = _sector_context_for_stock(
                trade_date=trade_date,
                memberships=memberships.get(stock_code, []),
                heat_lookup=heat_lookup,
            )
            lhb_complete = "daily_market_close_lhb" in lhb_capabilities.get(trade_date, set())
            stored_announcements = [
                item for item in announcements.get(stock_code, [])
                if _announcement_date(item.get("published_at")) <= trade_date
            ]
            rows.append(
                {
                    "trade_date": trade_date,
                    "stock_code": stock_code,
                    "stock_name": market_snapshot.get("stock_name"),
                    "calculation_version": calculation_version,
                    "status": "ready" if ready else "pending",
                    "board_count": board_counts.get((trade_date, stock_code)) if ready else None,
                    "market_snapshot": market_snapshot,
                    "sector_context": sector_context,
                    "evidence": {
                        "lhb": {
                            "complete": lhb_complete,
                            "records": lhb_rows.get((trade_date, stock_code), []),
                            "note": "龙虎榜上榜条件，不等同于涨停原因。",
                        },
                        "announcements": {
                            "completeness": "unknown_no_daily_announcement_sync",
                            "records": [_serialize_announcement(item) for item in stored_announcements[:3]],
                            "note": "仅展示已沉淀公告；未接入全市场当日公告/新闻同步，不能据此断言无公告。",
                        },
                    },
                    "coverage": {
                        "market_facts_ready": ready,
                        "sector_context_count": len(sector_context),
                        "lhb_complete": lhb_complete,
                        "announcement_completeness": "unknown_no_daily_announcement_sync",
                    },
                    "source_facts": {
                        "limit_event_table": "t_limit_event_daily",
                        "daily_bar_table": "t_daily_bar",
                        "stock_fund_flow_table": "t_stock_fund_flow_daily",
                        "sector_component_table": "t_sector_component",
                        "lhb_table": "t_lhb_event",
                        "announcement_table": "t_announcement",
                        "interpretation_boundary": "关联证据，不构成涨停因果结论",
                    },
                }
            )
        return rows

    async def read(
        self,
        *,
        trade_date: date | None = None,
        calculation_version: str = MARKET_SENTIMENT_CALCULATION_VERSION,
        sector_limit: int = 12,
        evidence_limit: int = 40,
    ) -> dict:
        calculation_version = _validate_calculation_version(calculation_version)
        sentiment = await MarketSentimentService(self.repository).read(
            trade_date=trade_date,
            calculation_version=calculation_version,
        )
        resolved_date = sentiment.get("trade_date")
        if not resolved_date:
            return {
                "available": False,
                "reason": "market_sentiment_not_calculated",
                "trade_date": trade_date.isoformat() if trade_date else None,
                "calculation_version": calculation_version,
                "sentiment": sentiment,
                "sectors": [],
                "limit_up_evidence": [],
            }
        resolved_trade_date = date.fromisoformat(str(resolved_date))
        counts = await self.repository.review_row_counts(
            trade_date=resolved_trade_date,
            calculation_version=calculation_version,
        )
        sectors = await self.repository.list_sector_heats(
            trade_date=resolved_trade_date,
            calculation_version=calculation_version,
            limit=sector_limit,
        )
        evidence = await self.repository.list_limit_up_evidence(
            trade_date=resolved_trade_date,
            calculation_version=calculation_version,
            limit=evidence_limit,
        )
        expected_evidence_count = int((sentiment.get("metrics") or {}).get("limit_up_count") or 0)
        sector_ready = counts["sector_heat_count"] > 0
        evidence_ready = counts["limit_up_evidence_count"] >= expected_evidence_count
        reasons = []
        if not sentiment.get("available"):
            reasons.append("market_sentiment_pending")
        if not sector_ready:
            reasons.append("sector_heat_not_calculated")
        if not evidence_ready:
            reasons.append("limit_up_evidence_incomplete")
        return {
            "available": not reasons,
            "reason": reasons[0] if reasons else None,
            "trade_date": resolved_date,
            "calculation_version": calculation_version,
            "sentiment": sentiment,
            "coverage": {
                **counts,
                "limit_up_evidence_expected_count": expected_evidence_count,
                "sector_ready": sector_ready,
                "limit_up_evidence_ready": evidence_ready,
                "unavailable_reasons": reasons,
            },
            "sectors": [serialize_sector_heat_model(item) for item in sectors],
            "limit_up_evidence": [serialize_limit_up_evidence_model(item) for item in evidence],
        }


def _build_sector_heat_rows(
    *,
    target_dates: list[date],
    metrics_by_date: dict[date, list[dict]],
    sentiment_status: dict[date, bool],
    calculation_version: str,
) -> tuple[list[dict], dict[tuple[date, str], dict]]:
    rows: list[dict] = []
    heat_lookup: dict[tuple[date, str], dict] = {}
    for trade_date in target_dates:
        metrics = [item for item in metrics_by_date.get(trade_date, []) if item["priced_component_count"] >= MIN_CONCEPT_COMPONENTS]
        ready = sentiment_status.get(trade_date, False)
        value_scores = {
            "relative_return": _percentile_scores({item["sector_code"]: item.get("average_change_pct") for item in metrics}),
            "limit_up_density": _percentile_scores(
                {
                    item["sector_code"]: _ratio(item["limit_up_stock_count"], item["priced_component_count"])
                    for item in metrics
                }
            ),
            "capital_inflow": _percentile_scores(
                {
                    item["sector_code"]: item.get("main_net_inflow") if item.get("fund_flow_stock_count") else None
                    for item in metrics
                }
            ),
        }
        scored: list[dict] = []
        for metric in metrics:
            sector_code = metric["sector_code"]
            breadth = _ratio(metric["rising_stock_count"], metric["priced_component_count"], percent=True)
            components = {
                "relative_return": _component(
                    "成分股相对涨幅", HOT_SECTOR_WEIGHTS["relative_return"], metric.get("average_change_pct"), value_scores["relative_return"].get(sector_code), "概念内成分股平均涨跌幅在当日概念中所处分位",
                ),
                "rising_breadth": _component(
                    "上涨扩散", HOT_SECTOR_WEIGHTS["rising_breadth"], breadth, breadth, "上涨成分股 ÷ 有行情成分股 × 100",
                ),
                "limit_up_density": _component(
                    "涨停密度", HOT_SECTOR_WEIGHTS["limit_up_density"], _ratio(metric["limit_up_stock_count"], metric["priced_component_count"], percent=True), value_scores["limit_up_density"].get(sector_code), "涨停成分股密度在当日概念中所处分位",
                ),
                "capital_inflow": _component(
                    "主力净流入", HOT_SECTOR_WEIGHTS["capital_inflow"], metric.get("main_net_inflow"), value_scores["capital_inflow"].get(sector_code), "成分股主力净流入合计在当日概念中所处分位",
                ),
            }
            available = [item for item in components.values() if item["available"]]
            total_weight = sum(item["weight"] for item in available)
            heat_score = round(sum(item["score"] * item["weight"] for item in available) / total_weight, 2) if total_weight else None
            scored.append({"metric": metric, "components": components, "heat_score": heat_score})
        scored.sort(key=lambda item: (item["heat_score"] is not None, item["heat_score"] or -1, item["metric"]["average_change_pct"] or -999), reverse=True)
        for index, item in enumerate(scored, start=1):
            metric = item["metric"]
            sector_code = metric["sector_code"]
            status = "ready" if ready and item["heat_score"] is not None else "pending"
            coverage = {
                "market_facts_ready": ready,
                "priced_component_count": metric["priced_component_count"],
                "fund_flow_stock_count": metric["fund_flow_stock_count"],
                "minimum_component_count": MIN_CONCEPT_COMPONENTS,
                "unavailable_reasons": [] if status == "ready" else ["market_sentiment_pending" if not ready else "sector_metrics_unavailable"],
            }
            row = {
                "trade_date": trade_date,
                "sector_code": sector_code,
                "sector_name": metric["sector_name"],
                "calculation_version": calculation_version,
                "status": status,
                "heat_score": item["heat_score"] if status == "ready" else None,
                "heat_rank": index if status == "ready" else None,
                "metrics": {
                    **metric,
                    "rising_ratio_pct": _ratio(metric["rising_stock_count"], metric["priced_component_count"], percent=True),
                    "limit_up_density_pct": _ratio(metric["limit_up_stock_count"], metric["priced_component_count"], percent=True),
                },
                "components": item["components"] if status == "ready" else {},
                "leaders": [],
                "coverage": coverage,
                "source_facts": {
                    "daily_bar_table": "t_daily_bar",
                    "stock_fund_flow_table": "t_stock_fund_flow_daily",
                    "limit_event_table": "t_limit_event_daily",
                    "sector_component_table": "t_sector_component",
                    "sector_definition": "Tushare 同花顺概念板块；不使用 ths_daily 作为热度输入",
                    "universe_definition": "t_stock.status=active AND is_st=false AND exchange in (SH,SZ,SSE,SZSE)",
                },
            }
            rows.append(row)
            heat_lookup[(trade_date, sector_code)] = {
                "sector_code": sector_code,
                "sector_name": metric["sector_name"],
                "heat_score": row["heat_score"],
                "heat_rank": row["heat_rank"],
            }
    return rows, heat_lookup


def _attach_sector_leaders(rows: list[dict], candidates: dict[tuple[date, str], list[dict]]) -> None:
    for row in rows:
        values = candidates.get((row["trade_date"], row["sector_code"]), [])
        values.sort(
            key=lambda item: (
                bool(item.get("is_limit_up")),
                _number_or_none(item.get("change_pct")) or -999,
                _number_or_none(item.get("main_net_inflow")) or -float("inf"),
            ),
            reverse=True,
        )
        row["leaders"] = values[:3]


def _board_counts(
    trade_dates: list[date],
    limit_up_codes: dict[date, set[str]],
    completion: dict[date, set[str]],
) -> dict[tuple[date, str], int]:
    streaks: dict[str, int] = {}
    result: dict[tuple[date, str], int] = {}
    for trade_date in trade_dates:
        if not LIMIT_EVENT_COMPLETION_CAPABILITIES.intersection(completion.get(trade_date, set())):
            streaks = {}
            continue
        today = limit_up_codes.get(trade_date, set())
        next_streaks = {stock_code: streaks.get(stock_code, 0) + 1 for stock_code in today}
        for stock_code, board_count in next_streaks.items():
            result[(trade_date, stock_code)] = board_count
        streaks = next_streaks
    return result


def _sector_context_for_stock(*, trade_date: date, memberships: list[dict], heat_lookup: dict[tuple[date, str], dict]) -> list[dict]:
    items: list[dict] = []
    for membership in memberships:
        start_date = membership.get("start_date")
        end_date = membership.get("end_date")
        if start_date is not None and start_date > trade_date:
            continue
        if end_date is not None and end_date < trade_date:
            continue
        heat = heat_lookup.get((trade_date, membership["sector_code"]))
        if heat is not None:
            items.append(heat)
    return sorted(items, key=lambda item: (item.get("heat_rank") or 999999, item["sector_name"]))[:3]


def _percentile_scores(values: dict[str, float | None]) -> dict[str, float | None]:
    valid = sorted((float(value), key) for key, value in values.items() if value is not None)
    if not valid:
        return {key: None for key in values}
    if len(valid) == 1:
        return {key: 100.0 if value is not None else None for key, value in values.items()}
    positions: dict[str, float] = {}
    index = 0
    while index < len(valid):
        value = valid[index][0]
        end = index + 1
        while end < len(valid) and valid[end][0] == value:
            end += 1
        # Tied values must receive the same average rank.  Otherwise two
        # concepts with identical factual inputs would get artificial heat
        # differences merely because of their code ordering.
        score = round(((index + end - 1) / 2) / (len(valid) - 1) * 100, 2)
        for _, key in valid[index:end]:
            positions[key] = score
        index = end
    return {key: positions.get(key) for key in values}


def _component(label: str, weight: float, raw_value: float | None, score: float | None, formula: str) -> dict:
    return {
        "label": label,
        "weight": weight,
        "raw_value": round(float(raw_value), 4) if raw_value is not None else None,
        "score": round(float(score), 2) if score is not None else None,
        "available": score is not None,
        "formula": formula,
    }


def _ratio(numerator: int | float | None, denominator: int | float | None, *, percent: bool = False) -> float | None:
    if numerator is None or not denominator:
        return None
    value = float(numerator) / float(denominator)
    return round(value * 100, 4) if percent else value


def _announcement_date(value) -> date:
    return value.date() if hasattr(value, "date") else date.min


def _serialize_announcement(item: dict) -> dict:
    value = item.get("published_at")
    return {**item, "published_at": value.isoformat() if hasattr(value, "isoformat") else value}


def serialize_sector_heat_model(row: MarketSectorHeatDaily) -> dict:
    return {
        "trade_date": row.trade_date.isoformat(),
        "sector_code": row.sector_code,
        "sector_name": row.sector_name,
        "calculation_version": row.calculation_version,
        "status": row.status,
        "heat_score": _number_or_none(row.heat_score),
        "heat_rank": row.heat_rank,
        "metrics": row.metrics or {},
        "components": row.components or {},
        "leaders": row.leaders or [],
        "coverage": row.coverage or {},
        "source_facts": row.source_facts or {},
        "calculated_at": row.calculated_at.isoformat() if hasattr(row.calculated_at, "isoformat") else row.calculated_at,
    }


def serialize_limit_up_evidence_model(row: MarketLimitUpEvidenceDaily) -> dict:
    return {
        "trade_date": row.trade_date.isoformat(),
        "stock_code": row.stock_code,
        "stock_name": row.stock_name,
        "calculation_version": row.calculation_version,
        "status": row.status,
        "board_count": row.board_count,
        "market_snapshot": row.market_snapshot or {},
        "sector_context": row.sector_context or [],
        "evidence": row.evidence or {},
        "coverage": row.coverage or {},
        "source_facts": row.source_facts or {},
        "calculated_at": row.calculated_at.isoformat() if hasattr(row.calculated_at, "isoformat") else row.calculated_at,
    }
