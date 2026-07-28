"""Auditable V2 post-close dual-score market emotion.

The service has no Provider, HTTP or LLM dependency.  It transforms settled
canonical/derived facts into immutable per-model daily observations.  All
normalisation is a trailing, same-model percentile: neither score nor stage
can see a later trading day.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import mean
from time import perf_counter
from typing import Any, Awaitable, Callable, Iterable

from fastapi.encoders import jsonable_encoder

from app.modules.market_insight.models import MarketEmotionDaily, MarketEmotionModel
from app.modules.market_insight.repository import MarketInsightRepository
from app.modules.market_insight.service import (
    LIMIT_EVENT_COMPLETION_CAPABILITIES,
    MARKET_SENTIMENT_UNIVERSE_CODE,
    MIN_DAILY_BAR_COVERAGE_PCT,
    _pct,
)


EMOTION_MODEL_CODE_DEFAULT = "cn_a_emotion_v2"
EMOTION_STAGE_LABELS = {
    "pending": "数据待完成",
    "insufficient_history": "历史样本不足",
    "ice_point": "冰点",
    "recovery": "修复",
    "active": "活跃",
    "climax": "高潮",
    "retreat": "退潮",
}
EMOTION_AUXILIARY_LABELS = {
    "trial": "试错",
    "ferment": "发酵",
    "acceleration": "加速",
    "divergence": "分歧",
    "rotation": "混沌轮动",
    "panic_release": "恐慌释放",
    "none": "无明显辅助状态",
}


METRIC_META: dict[str, dict[str, str]] = {
    "natural_limit_up_count": {"label": "换手自然涨停", "unit": "家", "direction": "positive", "formula": "收盘涨停且非一字板；一字板要求开盘=涨停价且 open_count=0"},
    "qualified_limit_down_count": {"label": "合格跌停", "unit": "家", "direction": "negative", "formula": "合格范围内的 limit_down 事件数"},
    "limit_break_rate": {"label": "炸板率", "unit": "%", "direction": "negative", "formula": "炸板 ÷（全部合格涨停 + 炸板）× 100"},
    "board_promotion_rate": {"label": "连板晋级率", "unit": "%", "direction": "positive", "formula": "当日 2 板及以上涨停股 ÷ 前一日涨停股"},
    "board_structure": {"label": "连板高度及梯队", "unit": "板", "direction": "positive", "formula": "最高连板高度 + 多板梯队数量的结构指标"},
    "up_ratio_pct": {"label": "上涨比例", "unit": "%", "direction": "positive", "formula": "上涨股票数 ÷ 合格日线股票数 × 100"},
    "median_change_pct": {"label": "中位涨跌幅", "unit": "%", "direction": "positive", "formula": "合格股票当日涨跌幅中位数"},
    "wide_move_ratio": {"label": "宽幅涨跌比", "unit": "%", "direction": "positive", "formula": "涨幅≥5% 家数 ÷（涨幅≥5% + 跌幅≤-5%）× 100"},
    "previous_limit_up_premium": {"label": "昨日涨停溢价", "unit": "%", "direction": "positive", "formula": "上一开市日涨停股在当日的平均涨跌幅"},
    "theme_limit_up_density": {"label": "热点概念涨停密度", "unit": "%", "direction": "positive", "formula": "当日热度最高概念的涨停成分股 ÷ 有行情成分股 × 100"},
    "theme_persistence": {"label": "热点持续性", "unit": "%", "direction": "positive", "formula": "前一日热点概念仍位于当日热度前列的比例"},
    "leader_strength": {"label": "龙头强度", "unit": "分", "direction": "positive", "formula": "当日最高概念热度分"},
    "amount_vs_5d_average": {"label": "成交额相对 5 日均值", "unit": "倍", "direction": "positive", "formula": "全市场成交额 ÷ 前 5 个有效交易日均额"},
    "main_net_inflow_strength": {"label": "全市场主力资金净流入", "unit": "元", "direction": "positive", "formula": "合格股票主力净流入合计"},
    "north_money": {"label": "北向资金净流入", "unit": "Provider 原始单位", "direction": "positive", "formula": "moneyflow_hsgt.north_money；未发布不以零替代"},
    "above_ma20_ratio": {"label": "站上 MA20 比例", "unit": "%", "direction": "positive", "formula": "收盘价≥MA20 股票数 ÷ 已有日频因子股票数 × 100"},
    "above_ma60_ratio": {"label": "站上 MA60 比例", "unit": "%", "direction": "positive", "formula": "收盘价≥MA60 股票数 ÷ 已有日频因子股票数 × 100"},
    "new_high_low_spread": {"label": "20 日创新高减创新低", "unit": "百分点", "direction": "positive", "formula": "20 日创新高占比 − 20 日创新低占比"},
    "turnover_volume_expansion": {"label": "换手/量能扩散", "unit": "比率", "direction": "positive", "formula": "当日平均换手率与日频 amount_ratio 的组合"},
    "core_index_trend": {"label": "核心指数趋势", "unit": "%", "direction": "positive", "formula": "已沉淀核心指数日线的平均涨跌幅"},
    "index_amplitude": {"label": "指数振幅", "unit": "%", "direction": "negative", "formula": "核心指数（high-low）÷ close 的平均值"},
    "qualified_limit_down_density": {"label": "跌停密度", "unit": "%", "direction": "negative", "formula": "合格跌停家数 ÷ 合格日线股票数 × 100"},
    "volatility_20d": {"label": "20 日波动率", "unit": "%", "direction": "negative", "formula": "合格股票日频因子的平均 20 日波动率"},
}


@dataclass(slots=True)
class EmotionCalculation:
    model_code: str
    mode: str
    requested_trade_dates: list[date]
    rows: list[dict]
    upserted_rows: int
    calibration_summary: dict | None = None

    @property
    def ready_count(self) -> int:
        return sum(item["status"] in {"ready", "degraded"} for item in self.rows)

    def summary(self) -> dict:
        return {
            "model_code": self.model_code,
            "mode": self.mode,
            "requested_trade_dates": [item.isoformat() for item in self.requested_trade_dates],
            "ready_count": self.ready_count,
            "pending_count": len(self.rows) - self.ready_count,
            "upserted_rows": self.upserted_rows,
            "calibration_summary": self.calibration_summary,
        }


class MarketEmotionService:
    """Compute/read V2 emotion without changing legacy V1 reports."""

    def __init__(self, repository: MarketInsightRepository) -> None:
        self.repository = repository

    async def calculate(
        self,
        *,
        model_code: str | None = None,
        mode: str = "daily",
        trade_date: date | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        progress_reporter: Callable[[dict], Awaitable[None]] | None = None,
    ) -> EmotionCalculation:
        if mode not in {"daily", "baseline"}:
            raise ValueError("emotion_mode 只能为 daily 或 baseline")
        model = await self._resolve_model(model_code=model_code, mode=mode)
        validate_emotion_model_parameters(model.parameter_json or {})
        target_dates = await self._target_dates(
            model=model,
            mode=mode,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
        )
        if not target_dates:
            return EmotionCalculation(model.model_code, mode, [], [], 0)

        # The baseline needs exactly one percentile window before its first
        # target date, not a broad calendar-sized pre-window.  The old 620
        # natural-day range caused every input aggregate to read hundreds of
        # unnecessary dates before any progress could be persisted.
        lookback_trade_days = int(model.percentile_window_days) if mode == "baseline" else 21
        context_dates = await self.repository.open_trade_dates_before(
            before_date=target_dates[0],
            limit=lookback_trade_days,
        )
        all_dates = list(dict.fromkeys([*context_dates, *target_dates]))
        if mode == "baseline":
            await self._set_baseline_progress(
                model,
                phase="loading_inputs",
                target_total=len(target_dates),
                target_completed=0,
                context_trade_days=len(context_dates),
                first_trade_date=target_dates[0],
                last_trade_date=target_dates[-1],
            )
        await self._report_progress(
            progress_reporter,
            {
                "phase": "loading_inputs",
                "mode": mode,
                "target_total": len(target_dates),
                "target_completed": 0,
                "context_trade_days": len(context_dates),
                "input_trade_days": len(all_dates),
                "first_trade_date": target_dates[0].isoformat(),
                "last_trade_date": target_dates[-1].isoformat(),
            },
        )
        inputs = await self._load_inputs(all_dates, mode=mode, progress_reporter=progress_reporter)
        active_stock_count = await self.repository.active_stock_count()
        raw_by_date = _build_raw_metrics(all_dates=all_dates, inputs=inputs)
        completion = inputs["completion"]
        target_set = set(target_dates)
        historical_metrics: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=int(model.percentile_window_days)))
        existing = await self.repository.emotion_rows_before(
            model_code=model.model_code,
            trade_date=target_dates[0],
            limit=max(int(model.percentile_window_days), 5),
        )
        if mode == "daily":
            for historic_row in existing:
                for key, detail in (historic_row.metrics or {}).items():
                    if not isinstance(detail, dict):
                        continue
                    numeric = _number(detail.get("raw_value"))
                    if numeric is not None:
                        historical_metrics[key].append(numeric)
        prior_short_scores: deque[float] = deque(
            [float(row.short_term_score) for row in existing if row.short_term_score is not None], maxlen=5
        )
        rows: list[dict] = []
        pending_upsert: list[dict] = []
        upserted = 0
        completed_targets = 0
        for current_date in all_dates:
            raw = raw_by_date.get(current_date, {})
            if current_date in target_set:
                row = _build_emotion_row(
                    trade_date=current_date,
                    model=model,
                    raw=raw,
                    metric_history={key: list(values) for key, values in historical_metrics.items()},
                    active_stock_count=active_stock_count,
                    limit_event_complete=bool(LIMIT_EVENT_COMPLETION_CAPABILITIES.intersection(completion.get(current_date, set()))),
                    completion_capabilities=sorted(completion.get(current_date, set())),
                    previous_short_scores=list(prior_short_scores),
                    external_confirmations=inputs["external_confirmations"],
                )
                rows.append(row)
                pending_upsert.append(row)
                completed_targets += 1
                if row["short_term_score"] is not None:
                    prior_short_scores.append(float(row["short_term_score"]))
            if mode == "baseline" or current_date in target_set:
                for key, value in raw.items():
                    numeric = _number(value)
                    if numeric is not None:
                        historical_metrics[key].append(numeric)

            # Keep the write transaction bounded and expose a genuine
            # checkpoint.  A timeout after a later batch now leaves useful
            # immutable rows and an exact resume point rather than 0 rows.
            if len(pending_upsert) >= 20:
                upserted += await self.repository.upsert_emotion_daily_rows(pending_upsert)
                await self.repository.commit()
                pending_upsert.clear()
                await self._checkpoint_progress(
                    model=model,
                    mode=mode,
                    progress_reporter=progress_reporter,
                    completed_targets=completed_targets,
                    target_total=len(target_dates),
                    upserted_rows=upserted,
                )
        if pending_upsert:
            upserted += await self.repository.upsert_emotion_daily_rows(pending_upsert)
            await self.repository.commit()
            await self._checkpoint_progress(
                model=model,
                mode=mode,
                progress_reporter=progress_reporter,
                completed_targets=completed_targets,
                target_total=len(target_dates),
                upserted_rows=upserted,
            )

        calibration_summary = None
        if mode == "baseline":
            calibration_summary = _calibration_summary(
                rows,
                model=model,
                target_dates=target_dates,
                raw_by_date=raw_by_date,
            )
            await self.repository.update_emotion_model(
                model,
                {
                    "status": "ready" if calibration_summary["baseline_complete"] else "calibrating",
                    "calibration_summary": calibration_summary,
                },
            )
            await self.repository.commit()
        return EmotionCalculation(model.model_code, mode, target_dates, rows, upserted, calibration_summary)

    async def read(
        self,
        *,
        trade_date: date | None = None,
        model_code: str | None = None,
        history_limit: int = 60,
    ) -> dict:
        model = await (self.repository.get_emotion_model(model_code) if model_code else self.repository.active_emotion_model())
        if model is None:
            return {
                "available": False,
                "reason": "market_emotion_model_not_active",
                "trade_date": trade_date.isoformat() if trade_date else None,
            }
        row = await self.repository.emotion_daily(model_code=model.model_code, trade_date=trade_date)
        if row is None:
            return {
                "available": False,
                "reason": "market_emotion_not_calculated",
                "model": serialize_emotion_model(model),
                "trade_date": trade_date.isoformat() if trade_date else None,
            }
        # The post-close page keeps its compact 60-day default.  The model
        # center requests the calibrated baseline (up to 1,000 days) so its
        # curve is a validation view rather than a misleading short excerpt.
        normalized_history_limit = max(20, min(int(history_limit), 1000))
        history = await self.repository.emotion_trend_history(model_code=model.model_code, limit=normalized_history_limit)
        payload = serialize_emotion_daily(row)
        return {
            "available": row.status in {"ready", "degraded"},
            **payload,
            "model": serialize_emotion_model(model),
            "trend": [
                {
                    "trade_date": item["trade_date"].isoformat(),
                    "short_term_score": _number(item["short_term_score"]),
                    "market_risk_on_score": _number(item["market_risk_on_score"]),
                    "primary_stage_code": item["primary_stage_code"],
                    "auxiliary_state_code": item["auxiliary_state_code"],
                    "status": item["status"],
                }
                for item in history
            ],
        }

    async def validation_preview(
        self,
        *,
        model_code: str | None = None,
        history_limit: int = 1000,
    ) -> dict:
        """Evaluate persisted scores against later settled market facts.

        This is intentionally a read-only research view.  It uses the raw
        inputs retained on each already-scored V2 row, so a revised canonical
        fact cannot silently change an old validation result, and no future
        observation can flow back into that date's score or stage.
        """
        model = await (
            self.repository.get_emotion_model(model_code)
            if model_code
            else self.repository.active_emotion_model()
        )
        if model is None:
            return {
                "available": False,
                "reason": "market_emotion_model_not_found",
                "model_code": model_code,
            }
        normalized_history_limit = max(60, min(int(history_limit), 1000))
        rows = await self.repository.emotion_validation_history(
            model_code=model.model_code,
            limit=normalized_history_limit,
        )
        if not rows:
            return {
                "available": False,
                "reason": "market_emotion_not_calculated",
                "model": serialize_emotion_model(model),
            }

        first_trade_date = rows[0]["trade_date"]
        last_trade_date = rows[-1]["trade_date"]
        calendar_dates = await self.repository.open_trade_dates_between(
            start_date=first_trade_date,
            end_date=last_trade_date,
        )
        raw_by_date = {
            row["trade_date"]: {
                "up_ratio_pct": _number(row.get("up_ratio_pct")),
                "core_index_trend": _number(row.get("core_index_trend")),
            }
            for row in rows
        }
        validation = _forward_validation(
            rows=rows,
            target_dates=calendar_dates,
            raw_by_date=raw_by_date,
        )
        return {
            "available": bool(validation["eligible_score_days"]),
            "model": serialize_emotion_model(model),
            "history_start_trade_date": first_trade_date.isoformat(),
            "history_end_trade_date": last_trade_date.isoformat(),
            "stored_row_count": len(rows),
            "calendar_trade_day_count": len(calendar_dates),
            "validation": validation,
        }

    async def list_models(self) -> list[dict]:
        return [serialize_emotion_model(item) for item in await self.repository.list_emotion_models()]

    async def create_draft(self, *, model_code: str, model_name: str, clone_from: str | None = None) -> dict:
        normalized_code = _validate_model_code(model_code)
        if await self.repository.get_emotion_model(normalized_code):
            raise ValueError("模型代码已存在")
        source = await self.repository.get_emotion_model(clone_from) if clone_from else None
        params = dict((source.parameter_json if source else default_emotion_parameters()) or {})
        validate_emotion_model_parameters(params)
        model = await self.repository.create_emotion_model(
            {
                "model_code": normalized_code,
                "model_name": str(model_name or "").strip() or normalized_code,
                "status": "draft",
                "percentile_window_days": int(source.percentile_window_days if source else 120),
                "minimum_history_days": int(source.minimum_history_days if source else 60),
                "baseline_trade_days": int(source.baseline_trade_days if source else 250),
                "parameter_json": params,
                "calibration_summary": {},
            }
        )
        await self.repository.commit()
        return serialize_emotion_model(model)

    async def update_draft(self, *, model_code: str, values: dict) -> dict:
        model = await self.repository.get_emotion_model(model_code)
        if model is None:
            raise ValueError("模型不存在")
        if model.status != "draft":
            raise ValueError("只有草稿模型可以编辑；请克隆当前模型生成草稿")
        allowed = {"model_name", "percentile_window_days", "minimum_history_days", "baseline_trade_days", "parameter_json"}
        update = {key: value for key, value in values.items() if key in allowed and value is not None}
        parameters = update.get("parameter_json", model.parameter_json or {})
        validate_emotion_model_parameters(parameters)
        window = int(update.get("percentile_window_days", model.percentile_window_days))
        minimum = int(update.get("minimum_history_days", model.minimum_history_days))
        baseline = int(update.get("baseline_trade_days", model.baseline_trade_days))
        if minimum < 20 or window < 60 or minimum > window or baseline < window:
            raise ValueError("窗口必须满足：baseline ≥ percentile ≥ 60，且 20 ≤ minimum ≤ percentile")
        update["parameter_json"] = parameters
        await self.repository.update_emotion_model(model, update)
        await self.repository.commit()
        return serialize_emotion_model(model)

    async def start_calibration(self, *, model_code: str) -> dict:
        model = await self.repository.get_emotion_model(model_code)
        if model is None:
            raise ValueError("模型不存在")
        if model.status not in {"draft", "calibrating", "ready"}:
            raise ValueError("归档或已启用模型不可重新校准；请先克隆为草稿")
        validate_emotion_model_parameters(model.parameter_json or {})
        await self.repository.update_emotion_model(model, {"status": "calibrating", "calibration_summary": {"status": "running"}})
        await self.repository.commit()
        return {
            "model": serialize_emotion_model(model),
            "job_code": "calculate_market_daily_sentiment",
            "payload": {"emotion_mode": "baseline", "emotion_model_code": model.model_code, "include_report_facts": False},
        }

    async def activate(self, *, model_code: str) -> dict:
        model = await self.repository.get_emotion_model(model_code)
        if model is None:
            raise ValueError("模型不存在")
        summary = model.calibration_summary or {}
        if model.status != "ready" or not summary.get("baseline_complete"):
            raise ValueError("模型必须完成 250 日基线校准与验证预览后才能启用")
        await self.repository.activate_emotion_model(model)
        await self.repository.commit()
        return serialize_emotion_model(model)

    async def _resolve_model(self, *, model_code: str | None, mode: str) -> MarketEmotionModel:
        model = await self.repository.get_emotion_model(model_code) if model_code else await self.repository.active_emotion_model()
        if model is None:
            raise ValueError("没有可用 V2 情绪模型；请先创建草稿并完成基线校准")
        if mode == "daily" and model.status != "active":
            raise ValueError("日常计算只能使用已启用的 V2 情绪模型")
        if mode == "baseline" and model.status not in {"draft", "calibrating", "ready"}:
            raise ValueError("基线校准只能使用草稿、校准中或待发布模型")
        return model

    async def _target_dates(
        self,
        *,
        model: MarketEmotionModel,
        mode: str,
        trade_date: date | None,
        start_date: date | None,
        end_date: date | None,
    ) -> list[date]:
        if start_date is not None or end_date is not None:
            if start_date is None or end_date is None:
                raise ValueError("start_date 和 end_date 必须同时提供")
            return await self.repository.open_trade_dates_between(start_date=start_date, end_date=end_date)
        latest = trade_date or await self.repository.latest_daily_bar_trade_date()
        if latest is None:
            return []
        if mode == "daily":
            return await self.repository.open_trade_dates_between(start_date=latest, end_date=latest)
        dates = await self.repository.open_trade_dates_between(
            start_date=latest - timedelta(days=850), end_date=latest
        )
        return dates[-int(model.baseline_trade_days) :]

    async def _load_inputs(
        self,
        all_dates: list[date],
        *,
        mode: str,
        progress_reporter: Callable[[dict], Awaitable[None]] | None,
    ) -> dict[str, Any]:
        """Load V2 fact blocks sequentially and make each block observable.

        A single AsyncSession must not execute these aggregates concurrently.
        The checkpoints identify the exact slow block without compromising the
        existing transaction/session model.
        """
        async def market_progress(progress: dict) -> None:
            await self._report_progress(
                progress_reporter,
                {
                    "phase": "loading_inputs",
                    "mode": mode,
                    "current_block": "market",
                    "block_index": 1,
                    "block_total": 8,
                    "input_trade_days": len(all_dates),
                    **progress,
                },
            )

        loaders: tuple[tuple[str, Callable[[], Awaitable[Any]]], ...] = (
            (
                "market",
                lambda: self.repository.v2_market_metrics(all_dates, progress_reporter=market_progress),
            ),
            ("events", lambda: self.repository.v2_limit_event_rows(all_dates)),
            ("completion", lambda: self.repository.limit_event_completion_capabilities(all_dates)),
            ("premiums", lambda: self.repository.previous_limit_up_premiums(all_dates)),
            ("themes", lambda: self.repository.v2_theme_metrics(all_dates)),
            ("north", lambda: self.repository.v2_north_flows(all_dates)),
            ("indices", lambda: self.repository.v2_index_metrics(all_dates)),
            ("external_confirmations", lambda: self.repository.v2_external_confirmations(up_to=all_dates[-1])),
        )
        inputs: dict[str, Any] = {}
        for index, (block, loader) in enumerate(loaders, start=1):
            await self._report_progress(
                progress_reporter,
                {
                    "phase": "loading_inputs",
                    "mode": mode,
                    "current_block": block,
                    "block_index": index,
                    "block_total": len(loaders),
                    "input_trade_days": len(all_dates),
                },
            )
            started = perf_counter()
            inputs[block] = await loader()
            await self._report_progress(
                progress_reporter,
                {
                    "phase": "loading_inputs",
                    "mode": mode,
                    "current_block": block,
                    "block_index": index,
                    "block_total": len(loaders),
                    "block_status": "completed",
                    "elapsed_ms": int((perf_counter() - started) * 1000),
                    "input_trade_days": len(all_dates),
                },
            )
        return inputs

    async def _checkpoint_progress(
        self,
        *,
        model: MarketEmotionModel,
        mode: str,
        progress_reporter: Callable[[dict], Awaitable[None]] | None,
        completed_targets: int,
        target_total: int,
        upserted_rows: int,
    ) -> None:
        progress = {
            "phase": "scoring_and_persisting",
            "mode": mode,
            "target_completed": completed_targets,
            "target_total": target_total,
            "upserted_rows": upserted_rows,
        }
        if mode == "baseline":
            await self._set_baseline_progress(model, **progress)
        await self._report_progress(progress_reporter, progress)

    async def _set_baseline_progress(self, model: MarketEmotionModel, **progress: Any) -> None:
        # JSONB does not accept Python ``date`` objects.  The initial baseline
        # checkpoint intentionally carries its first/last trade dates, so
        # normalise the whole progress payload at this persistence boundary.
        calibration_summary = jsonable_encoder({"status": "running", **progress})
        await self.repository.update_emotion_model(
            model,
            {
                "status": "calibrating",
                "calibration_summary": calibration_summary,
            },
        )
        await self.repository.commit()

    @staticmethod
    async def _report_progress(
        progress_reporter: Callable[[dict], Awaitable[None]] | None,
        progress: dict,
    ) -> None:
        if progress_reporter is not None:
            await progress_reporter(progress)


def default_emotion_parameters() -> dict:
    """Return a new default parameter payload; callers may safely edit it."""
    return {
        "universe": {"exclude_st": True, "exclude_bse": True, "exclude_first_trade_days": 5},
        "short_term": {
            "natural_limit_up_count": 8, "qualified_limit_down_count": 6, "limit_break_rate": 8,
            "board_promotion_rate": 9, "board_structure": 9, "up_ratio_pct": 6,
            "median_change_pct": 6, "wide_move_ratio": 7, "previous_limit_up_premium": 6,
            "theme_limit_up_density": 7, "theme_persistence": 7, "leader_strength": 6,
            "amount_vs_5d_average": 6, "main_net_inflow_strength": 5, "north_money": 4,
        },
        "risk_on": {
            "up_ratio_pct": 10, "median_change_pct": 10, "wide_move_ratio": 10,
            "above_ma20_ratio": 8, "above_ma60_ratio": 8, "new_high_low_spread": 9,
            "amount_vs_5d_average": 8, "main_net_inflow_strength": 8, "north_money": 4,
            "turnover_volume_expansion": 5, "core_index_trend": 8, "index_amplitude": 5,
            "qualified_limit_down_density": 4, "volatility_20d": 3,
        },
        "stage_thresholds": {"ice_point": 28, "recovery": 48, "active": 65, "climax": 82, "retreat": 42},
    }


def validate_emotion_model_parameters(parameters: dict) -> None:
    if not isinstance(parameters, dict):
        raise ValueError("parameter_json 必须为对象")
    for card in ("short_term", "risk_on"):
        values = parameters.get(card)
        if not isinstance(values, dict) or not values:
            raise ValueError(f"{card} 评分卡不能为空")
        unsupported = sorted(set(values) - set(METRIC_META))
        if unsupported:
            raise ValueError(f"{card} 包含未知指标：{', '.join(unsupported)}")
        total = sum(_number(value) or 0 for value in values.values())
        if round(total, 6) != 100:
            raise ValueError(f"{card} 评分卡权重必须合计 100%，当前为 {total:g}%")
        if any((_number(value) is None or _number(value) < 0) for value in values.values()):
            raise ValueError(f"{card} 权重必须为非负数")
    thresholds = parameters.get("stage_thresholds") or {}
    required = ("ice_point", "retreat", "recovery", "active", "climax")
    if any(_number(thresholds.get(key)) is None for key in required):
        raise ValueError("阶段阈值不完整")
    if not (thresholds["ice_point"] < thresholds["retreat"] < thresholds["recovery"] < thresholds["active"] < thresholds["climax"]):
        raise ValueError("阶段阈值必须满足：冰点 < 退潮 < 修复 < 活跃 < 高潮")


def _build_raw_metrics(*, all_dates: list[date], inputs: dict[str, Any]) -> dict[date, dict]:
    result: dict[date, dict] = {}
    board_streaks: dict[str, int] = {}
    previous_limit_up_codes: set[str] = set()
    previous_theme_codes: set[str] = set()
    amount_history: deque[float] = deque(maxlen=5)
    for current_date in all_dates:
        market = inputs["market"].get(current_date, {})
        events = inputs["events"].get(current_date, [])
        limit_ups = [item for item in events if item["event_type"] == "limit_up"]
        one_word = [item for item in limit_ups if _is_one_word_limit(item)]
        natural = [item for item in limit_ups if not _is_one_word_limit(item)]
        limit_downs = [item for item in events if item["event_type"] == "limit_down"]
        limit_breaks = [item for item in events if item["event_type"] == "limit_break"]
        current_codes = {str(item["stock_code"]) for item in limit_ups}
        next_streaks = {code: board_streaks.get(code, 0) + 1 for code in current_codes}
        high_board = max(next_streaks.values(), default=0)
        multi_board_count = sum(value >= 2 for value in next_streaks.values())
        promotion = _pct(sum(code in previous_limit_up_codes for code in current_codes), len(previous_limit_up_codes))
        themes = inputs["themes"].get(current_date, [])
        top_theme = themes[0] if themes else None
        top_codes = {str(item["sector_code"]) for item in themes[:5]}
        amount = _number(market.get("total_amount_yuan"))
        amount_baseline = mean(amount_history) if len(amount_history) >= 5 else None
        factor_count = int(market.get("factor_count") or 0)
        raw = {
            "daily_bar_count": int(market.get("daily_bar_count") or 0),
            "natural_limit_up_count": len(natural),
            "all_qualified_limit_up_count": len(limit_ups),
            "one_word_limit_up_count": len(one_word),
            "qualified_limit_down_count": len(limit_downs),
            "qualified_limit_down_density": _pct(len(limit_downs), int(market.get("daily_bar_count") or 0)),
            "limit_break_count": len(limit_breaks),
            "limit_break_rate": _pct(len(limit_breaks), len(limit_ups) + len(limit_breaks)),
            "board_promotion_rate": promotion,
            "board_structure": float(high_board * 10 + min(multi_board_count, 10)),
            "highest_board_count": high_board,
            "multi_board_stock_count": multi_board_count,
            "up_ratio_pct": _pct(int(market.get("up_count") or 0), int(market.get("daily_bar_count") or 0)),
            "median_change_pct": _number(market.get("median_change_pct")),
            "wide_move_ratio": _pct(int(market.get("wide_up_count") or 0), int(market.get("wide_up_count") or 0) + int(market.get("wide_down_count") or 0)),
            "previous_limit_up_premium": _number((inputs["premiums"].get(current_date) or {}).get("average_change_pct")),
            "theme_limit_up_density": _pct(int((top_theme or {}).get("limit_up_stock_count") or 0), int((top_theme or {}).get("priced_component_count") or 0)),
            "theme_persistence": _pct(len(top_codes.intersection(previous_theme_codes)), len(previous_theme_codes)) if previous_theme_codes else None,
            "leader_strength": _number((top_theme or {}).get("heat_score")),
            "amount_vs_5d_average": round(amount / amount_baseline, 4) if amount is not None and amount_baseline else None,
            "main_net_inflow_strength": _number(market.get("main_net_inflow")),
            "north_money": _number((inputs["north"].get(current_date) or {}).get("north_money")),
            "above_ma20_ratio": _pct(int(market.get("above_ma20_count") or 0), factor_count),
            "above_ma60_ratio": _pct(int(market.get("above_ma60_count") or 0), factor_count),
            "new_high_low_spread": _new_high_low_spread(market),
            "turnover_volume_expansion": _combine_expansion(market),
            "core_index_trend": _number((inputs["indices"].get(current_date) or {}).get("core_index_change_pct")),
            "index_amplitude": _number((inputs["indices"].get(current_date) or {}).get("index_amplitude_pct")),
            "volatility_20d": _number(market.get("volatility_20d")),
            "factor_coverage_pct": _pct(factor_count, int(market.get("daily_bar_count") or 0)),
            "north_money_source": (inputs["north"].get(current_date) or {}).get("source"),
            "north_money_unit": (inputs["north"].get(current_date) or {}).get("value_unit"),
        }
        result[current_date] = raw
        board_streaks = next_streaks
        previous_limit_up_codes = current_codes
        previous_theme_codes = top_codes
        if amount is not None:
            amount_history.append(amount)
    return result


def _build_emotion_row(
    *,
    trade_date: date,
    model: MarketEmotionModel,
    raw: dict,
    metric_history: dict[str, list[float]],
    active_stock_count: int,
    limit_event_complete: bool,
    completion_capabilities: list[str],
    previous_short_scores: list[float],
    external_confirmations: dict,
) -> dict:
    daily_bar_count = int(raw.get("daily_bar_count") or 0)
    coverage_pct = _pct(daily_bar_count, active_stock_count)
    reasons: list[str] = []
    if active_stock_count <= 0:
        reasons.append("active_universe_empty")
    if coverage_pct is None or coverage_pct < MIN_DAILY_BAR_COVERAGE_PCT:
        reasons.append("daily_bar_coverage_below_threshold")
    if not limit_event_complete:
        reasons.append("limit_event_ingest_incomplete")
    coverage = {
        "universe_code": MARKET_SENTIMENT_UNIVERSE_CODE,
        "exclude_st": True,
        "exclude_bse": True,
        "exclude_first_trade_days": 5,
        "active_stock_count": active_stock_count,
        "daily_bar_count": daily_bar_count,
        "daily_bar_coverage_pct": coverage_pct,
        "minimum_daily_bar_coverage_pct": MIN_DAILY_BAR_COVERAGE_PCT,
        "limit_event_complete": limit_event_complete,
        "completion_capabilities": completion_capabilities,
        "factor_coverage_pct": raw.get("factor_coverage_pct"),
        "unavailable_reasons": reasons,
    }
    metric_payload = _metric_payload(raw=raw, metric_history=metric_history, model=model)
    base = {
        "trade_date": trade_date,
        "model_code": model.model_code,
        "metrics": metric_payload,
        "coverage": coverage,
        "parameter_snapshot": {
            "model_code": model.model_code,
            "percentile_window_days": model.percentile_window_days,
            "minimum_history_days": model.minimum_history_days,
            "baseline_trade_days": model.baseline_trade_days,
            "parameters": model.parameter_json or {},
        },
        "external_confirmations": _serialize_external_confirmations(external_confirmations, trade_date),
    }
    if reasons:
        return {**base, "status": "pending", "short_term_score": None, "market_risk_on_score": None, "primary_stage_code": "pending", "auxiliary_state_code": "none", "scorecards": {}, "stage_evidence": []}

    parameters = model.parameter_json or {}
    short_card = _scorecard("short_term", parameters["short_term"], metric_payload)
    risk_card = _scorecard("risk_on", parameters["risk_on"], metric_payload)
    if short_card["score"] is None or risk_card["score"] is None:
        return {**base, "status": "insufficient_history", "short_term_score": short_card["score"], "market_risk_on_score": risk_card["score"], "primary_stage_code": "insufficient_history", "auxiliary_state_code": "none", "scorecards": {"short_term": short_card, "risk_on": risk_card}, "stage_evidence": []}
    short_score, risk_score = float(short_card["score"]), float(risk_card["score"])
    primary, evidence = _primary_stage(
        short_score=short_score,
        risk_score=risk_score,
        raw=raw,
        previous_short_scores=previous_short_scores,
        thresholds=parameters["stage_thresholds"],
    )
    auxiliary, aux_evidence = _auxiliary_state(raw=raw, short_score=short_score, previous_short_scores=previous_short_scores)
    degraded = [key for key in ("north_money", "above_ma20_ratio", "above_ma60_ratio", "new_high_low_spread", "core_index_trend") if not metric_payload.get(key, {}).get("available")]
    coverage["degraded_metric_keys"] = degraded
    return {
        **base,
        "status": "degraded" if degraded else "ready",
        "short_term_score": short_score,
        "market_risk_on_score": risk_score,
        "primary_stage_code": primary,
        "auxiliary_state_code": auxiliary,
        "scorecards": {"short_term": short_card, "risk_on": risk_card},
        "stage_evidence": evidence + aux_evidence,
    }


def _metric_payload(*, raw: dict, metric_history: dict[str, list[float]], model: MarketEmotionModel) -> dict:
    result: dict = {}
    for key, meta in METRIC_META.items():
        value = _number(raw.get(key))
        history = metric_history.get(key, [])[-int(model.percentile_window_days) :]
        percentile = _rolling_percentile(value, history, direction=meta["direction"])
        result[key] = {
            "label": meta["label"],
            "raw_value": _round(value, 6),
            "unit": raw.get(f"{key}_unit") or meta["unit"],
            "direction": meta["direction"],
            "percentile_120d": _round(percentile, 2),
            "history_sample_count": len(history),
            "score": _round(percentile, 2),
            "available": value is not None and len(history) >= int(model.minimum_history_days),
            "formula": meta["formula"],
            "source": _metric_source(key),
            "freshness": "same_trade_date" if value is not None else "not_published_or_missing",
        }
    # Keep unscored raw audit values visible to the page too.
    for key in ("all_qualified_limit_up_count", "one_word_limit_up_count", "limit_break_count", "highest_board_count", "multi_board_stock_count", "factor_coverage_pct"):
        result[key] = {"raw_value": _round(_number(raw.get(key)), 6), "unit": "家" if key.endswith("count") else "%", "available": _number(raw.get(key)) is not None, "source": "canonical_daily_facts"}
    return result


def _scorecard(name: str, weights: dict, metrics: dict) -> dict:
    available = [
        (key, float(weight), metrics.get(key) or {})
        for key, weight in weights.items()
        if (metrics.get(key) or {}).get("available")
    ]
    total_weight = sum(weight for _, weight, _ in available)
    items: dict = {}
    for key, weight in weights.items():
        detail = dict(metrics.get(key) or {})
        normalized_weight = float(weight) / total_weight * 100 if total_weight else None
        contribution = (float(detail["score"]) * normalized_weight / 100) if detail.get("available") and normalized_weight is not None else None
        detail.update({"weight": float(weight), "effective_weight": _round(normalized_weight, 4), "contribution": _round(contribution, 4), "included": bool(detail.get("available"))})
        items[key] = detail
    score = sum(float(item["contribution"]) for item in items.values() if item.get("contribution") is not None)
    return {
        "label": "短线接力情绪分" if name == "short_term" else "大盘风险偏好分",
        "score": _round(score, 2) if total_weight else None,
        "configured_weight_total": round(sum(float(value) for value in weights.values()), 6),
        "available_weight_total": _round(total_weight, 4),
        "items": items,
    }


def _primary_stage(*, short_score: float, risk_score: float, raw: dict, previous_short_scores: list[float], thresholds: dict) -> tuple[str, list[dict]]:
    recent_high = max(previous_short_scores[-5:] or [short_score])
    short_slope = short_score - (previous_short_scores[-1] if previous_short_scores else short_score)
    evidence: list[dict] = []
    # Priority is intentional and documented: ice -> retreat -> climax -> recovery -> active.
    if short_score <= float(thresholds["ice_point"]) and risk_score <= float(thresholds["retreat"]) and short_slope <= 0:
        evidence.append({"rule": "ice_point", "detail": f"短线 {short_score:.1f}、风险偏好 {risk_score:.1f}，且短线分未回升"})
        return "ice_point", evidence
    if short_score < float(thresholds["retreat"]) and (short_slope < 0 or int(raw.get("qualified_limit_down_count") or 0) > int(raw.get("natural_limit_up_count") or 0)):
        evidence.append({"rule": "retreat", "detail": f"短线 {short_score:.1f}，较前日 {short_slope:+.1f}；跌停与自然涨停结构走弱"})
        return "retreat", evidence
    if short_score >= float(thresholds["climax"]) and risk_score >= float(thresholds["active"]) and int(raw.get("natural_limit_up_count") or 0) > 0:
        evidence.append({"rule": "climax", "detail": f"双分高位：短线 {short_score:.1f}、风险偏好 {risk_score:.1f}，自然涨停 {int(raw.get('natural_limit_up_count') or 0)} 家"})
        return "climax", evidence
    if short_score >= float(thresholds["recovery"]) and short_slope > 0 and risk_score >= float(thresholds["retreat"]):
        evidence.append({"rule": "recovery", "detail": f"短线较前日回升 {short_slope:.1f} 分，双分已越过修复门槛"})
        return "recovery", evidence
    evidence.append({"rule": "active", "detail": f"未命中冰点/退潮/高潮/修复优先条件；短线 {short_score:.1f}，风险偏好 {risk_score:.1f}"})
    return "active", evidence


def _auxiliary_state(*, raw: dict, short_score: float, previous_short_scores: list[float]) -> tuple[str, list[dict]]:
    high = max(previous_short_scores[-5:] or [short_score])
    decline = high - short_score
    break_rate = _number(raw.get("limit_break_rate"))
    promotion = _number(raw.get("board_promotion_rate"))
    if break_rate is not None and break_rate >= 40 and decline >= 12:
        return "divergence", [{"rule": "divergence", "detail": f"炸板率 {break_rate:.1f}%，短线分较 5 日高点回落 {decline:.1f} 分"}]
    if int(raw.get("qualified_limit_down_count") or 0) >= max(8, int(raw.get("natural_limit_up_count") or 0)) and short_score < 40:
        return "panic_release", [{"rule": "panic_release", "detail": "跌停压力显著高于自然涨停，短线分处于低位"}]
    if promotion is not None and promotion >= 35 and int(raw.get("highest_board_count") or 0) >= 3:
        return "acceleration", [{"rule": "acceleration", "detail": f"连板晋级率 {promotion:.1f}%，最高 {int(raw.get('highest_board_count') or 0)} 板"}]
    if _number(raw.get("theme_persistence")) is not None and _number(raw.get("theme_persistence")) >= 40:
        return "ferment", [{"rule": "ferment", "detail": f"热点前列延续率 {_number(raw.get('theme_persistence')):.1f}%"}]
    if short_score < 50 and (_number(raw.get("theme_persistence")) or 0) < 20:
        return "rotation", [{"rule": "rotation", "detail": "热点延续性弱，处于混沌轮动结构"}]
    return "trial", [{"rule": "trial", "detail": "未形成明显主线加速或恐慌释放，观察试错信号"}]


def _calibration_summary(
    rows: list[dict],
    *,
    model: MarketEmotionModel,
    target_dates: list[date],
    raw_by_date: dict[date, dict],
) -> dict:
    ready = [row for row in rows if row["status"] in {"ready", "degraded"}]
    stages: dict[str, int] = defaultdict(int)
    for row in ready:
        stages[str(row["primary_stage_code"])] += 1
    scores = [float(row["short_term_score"]) for row in ready if row["short_term_score"] is not None]
    return {
        "status": "completed",
        "baseline_trade_days_requested": int(model.baseline_trade_days),
        "baseline_trade_days_processed": len(rows),
        "ready_or_degraded_days": len(ready),
        "baseline_complete": len(rows) >= int(model.baseline_trade_days) and len(ready) >= int(model.baseline_trade_days),
        "short_term_score_min": min(scores) if scores else None,
        "short_term_score_max": max(scores) if scores else None,
        "short_term_score_average": _round(mean(scores), 2) if scores else None,
        "stage_days": dict(stages),
        "validation": _forward_validation(rows=rows, target_dates=target_dates, raw_by_date=raw_by_date),
    }


def _forward_validation(*, rows: list[dict], target_dates: list[date], raw_by_date: dict[date, dict]) -> dict:
    """Summarise score-conditioned T+1/T+3 market outcomes.

    The forward path is built only after all score rows are constructed.  In
    particular, T+3 is a three-trading-day *cumulative* equally weighted core
    index change, rather than the unrelated change on only the third day.
    Nothing returned here enters scorecards, percentiles or stage rules.
    """
    row_by_date = {row["trade_date"]: row for row in rows}
    samples: dict[str, dict[int, list[dict[str, float | None]]]] = {
        "short_term": {1: [], 3: []},
        "risk_on": {1: [], 3: []},
    }
    eligible_score_days = 0
    for index, current_date in enumerate(target_dates):
        row = row_by_date.get(current_date)
        if not row or row.get("status") not in {"ready", "degraded"}:
            continue
        scores = {
            "short_term": _number(row.get("short_term_score")),
            "risk_on": _number(row.get("market_risk_on_score")),
        }
        if not any(value is not None for value in scores.values()):
            continue
        eligible_score_days += 1
        for horizon in (1, 3):
            if index + horizon >= len(target_dates):
                continue
            path_dates = target_dates[index + 1 : index + horizon + 1]
            path = [raw_by_date.get(item, {}) for item in path_dates]
            final_breadth = _number(path[-1].get("up_ratio_pct")) if path else None
            daily_core_changes = [_number(item.get("core_index_trend")) for item in path]
            core_cumulative_return = (
                _compound_pct(daily_core_changes)
                if path and all(value is not None for value in daily_core_changes)
                else None
            )
            if final_breadth is None and core_cumulative_return is None:
                continue
            for score_name, score in scores.items():
                if score is not None:
                    samples[score_name][horizon].append(
                        {
                            "score": score,
                            "market_breadth_pct": final_breadth,
                            "core_index_cumulative_return_pct": core_cumulative_return,
                        }
                    )

    return {
        "method_version": "v2_persisted_forward_outcome",
        "eligible_score_days": eligible_score_days,
        "short_term": {
            "t_plus_1": _forward_outcome_summary(samples["short_term"][1]),
            "t_plus_3": _forward_outcome_summary(samples["short_term"][3]),
        },
        "risk_on": {
            "t_plus_1": _forward_outcome_summary(samples["risk_on"][1]),
            "t_plus_3": _forward_outcome_summary(samples["risk_on"][3]),
        },
        "outcome_definition": {
            "market_breadth_pct": "目标日合格股票上涨比例",
            "core_index_cumulative_return_pct": "从 T 后第 1 个开市日至 T+N 的七个核心指数日均涨跌幅复利累计值",
            "score_groups": "低分 [0,40)，中分 [40,70)，高分 [70,100]",
        },
        "note": "仅用于历史环境区分度验证；后续事实不参与任一当日分数、分位或阶段判定，也不代表候选股策略收益或买卖建议。",
    }


def _forward_outcome_summary(samples: list[dict[str, float | None]]) -> dict:
    """Return transparent score buckets and rank relationships for one horizon."""
    groups = (
        ("low", "低分", "[0,40)", 0.0, 40.0),
        ("middle", "中分", "[40,70)", 40.0, 70.0),
        ("high", "高分", "[70,100]", 70.0, 100.000001),
    )
    buckets: list[dict] = []
    by_code: dict[str, dict] = {}
    for code, label, score_range, lower, upper in groups:
        values = [item for item in samples if lower <= float(item["score"] or 0) < upper]
        breadth = _sample_mean(values, "market_breadth_pct")
        core_return = _sample_mean(values, "core_index_cumulative_return_pct", digits=4)
        bucket = {
            "code": code,
            "label": label,
            "score_range": score_range,
            "sample_count": len(values),
            "average_market_breadth_pct": breadth,
            "average_core_index_cumulative_return_pct": core_return,
            "market_breadth_above_50_pct": _sample_rate(values, "market_breadth_pct", threshold=50),
            "core_index_positive_pct": _sample_rate(values, "core_index_cumulative_return_pct", threshold=0),
        }
        buckets.append(bucket)
        by_code[code] = bucket

    high, low = by_code["high"], by_code["low"]
    high_low = {
        "breadth_pct_point_difference": _difference(
            high["average_market_breadth_pct"], low["average_market_breadth_pct"], digits=2
        ),
        "core_index_return_pct_point_difference": _difference(
            high["average_core_index_cumulative_return_pct"], low["average_core_index_cumulative_return_pct"], digits=4
        ),
        "high_sample_count": high["sample_count"],
        "low_sample_count": low["sample_count"],
    }
    return {
        "sample_count": len(samples),
        "average_market_breadth_pct": _sample_mean(samples, "market_breadth_pct"),
        "average_core_index_cumulative_return_pct": _sample_mean(samples, "core_index_cumulative_return_pct", digits=4),
        "market_breadth_rank_correlation": _spearman(samples, "score", "market_breadth_pct"),
        "core_index_return_rank_correlation": _spearman(samples, "score", "core_index_cumulative_return_pct"),
        "buckets": buckets,
        "high_low_difference": high_low,
        "relationship": _relationship(high_low),
    }


def _compound_pct(values: list[float | None]) -> float | None:
    if not values or any(value is None for value in values):
        return None
    result = 1.0
    for value in values:
        result *= 1 + float(value or 0) / 100
    return _round((result - 1) * 100, 4)


def _sample_mean(samples: list[dict[str, float | None]], key: str, *, digits: int = 2) -> float | None:
    values = [float(item[key]) for item in samples if item.get(key) is not None]
    return _round(mean(values), digits) if values else None


def _sample_rate(samples: list[dict[str, float | None]], key: str, *, threshold: float) -> float | None:
    values = [float(item[key]) for item in samples if item.get(key) is not None]
    return _round(sum(value > threshold for value in values) / len(values) * 100, 2) if values else None


def _difference(high: float | None, low: float | None, *, digits: int) -> float | None:
    return _round(high - low, digits) if high is not None and low is not None else None


def _relationship(high_low: dict) -> str:
    if int(high_low["high_sample_count"] or 0) < 15 or int(high_low["low_sample_count"] or 0) < 15:
        return "insufficient_samples"
    breadth = _number(high_low.get("breadth_pct_point_difference"))
    core_return = _number(high_low.get("core_index_return_pct_point_difference"))
    if breadth is None and core_return is None:
        return "insufficient_outcomes"
    if (breadth is None or breadth >= 0) and (core_return is None or core_return >= 0):
        return "positive"
    if (breadth is None or breadth <= 0) and (core_return is None or core_return <= 0):
        return "inverse"
    return "mixed"


def _spearman(samples: list[dict[str, float | None]], x_key: str, y_key: str) -> float | None:
    pairs = [
        (float(item[x_key]), float(item[y_key]))
        for item in samples
        if item.get(x_key) is not None and item.get(y_key) is not None
    ]
    if len(pairs) < 3:
        return None
    x_ranks = _midranks([item[0] for item in pairs])
    y_ranks = _midranks([item[1] for item in pairs])
    x_mean, y_mean = mean(x_ranks), mean(y_ranks)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_ranks, y_ranks, strict=True))
    denominator_left = sum((x - x_mean) ** 2 for x in x_ranks)
    denominator_right = sum((y - y_mean) ** 2 for y in y_ranks)
    if denominator_left <= 0 or denominator_right <= 0:
        return None
    return _round(numerator / (denominator_left * denominator_right) ** 0.5, 4)


def _midranks(values: list[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(ordered):
        end = start + 1
        while end < len(ordered) and ordered[end][1] == ordered[start][1]:
            end += 1
        rank = (start + 1 + end) / 2
        for index, _value in ordered[start:end]:
            ranks[index] = rank
        start = end
    return ranks


def serialize_emotion_model(model: MarketEmotionModel) -> dict:
    return {
        "model_code": model.model_code,
        "model_name": model.model_name,
        "status": model.status,
        "percentile_window_days": int(model.percentile_window_days),
        "minimum_history_days": int(model.minimum_history_days),
        "baseline_trade_days": int(model.baseline_trade_days),
        "parameter_json": model.parameter_json or {},
        "calibration_summary": model.calibration_summary or {},
        "published_at": model.published_at.isoformat() if model.published_at else None,
        "updated_at": model.updated_at.isoformat() if model.updated_at else None,
    }


def serialize_emotion_daily(row: MarketEmotionDaily) -> dict:
    primary = str(row.primary_stage_code or "pending")
    auxiliary = str(row.auxiliary_state_code or "none")
    return {
        "trade_date": row.trade_date.isoformat(),
        "model_code": row.model_code,
        "status": row.status,
        "short_term_score": _number(row.short_term_score),
        "market_risk_on_score": _number(row.market_risk_on_score),
        "primary_stage_code": primary,
        "primary_stage_label": EMOTION_STAGE_LABELS.get(primary, primary),
        "auxiliary_state_code": auxiliary,
        "auxiliary_state_label": EMOTION_AUXILIARY_LABELS.get(auxiliary, auxiliary),
        "metrics": row.metrics or {},
        "scorecards": row.scorecards or {},
        "stage_evidence": row.stage_evidence or [],
        "coverage": row.coverage or {},
        "parameter_snapshot": row.parameter_snapshot or {},
        "external_confirmations": row.external_confirmations or {},
        "calculated_at": row.calculated_at.isoformat() if row.calculated_at else None,
    }


def _rolling_percentile(value: float | None, history: Iterable[float], *, direction: str) -> float | None:
    values = [float(item) for item in history if item is not None]
    if value is None or not values:
        return None
    lower = sum(item < value for item in values)
    equal = sum(item == value for item in values)
    percentile = (lower + equal * 0.5) / len(values) * 100
    return 100 - percentile if direction == "negative" else percentile


def _is_one_word_limit(item: dict) -> bool:
    limit_price, open_price = _number(item.get("limit_price")), _number(item.get("open_price"))
    return bool(limit_price is not None and open_price is not None and abs(limit_price - open_price) < 0.0001 and item.get("open_count") == 0)


def _combine_expansion(market: dict) -> float | None:
    amount_ratio = _number(market.get("amount_ratio"))
    turnover = _number(market.get("turnover_rate"))
    if amount_ratio is None and turnover is None:
        return None
    if amount_ratio is None:
        return turnover
    if turnover is None:
        return amount_ratio
    return (amount_ratio + turnover) / 2


def _new_high_low_spread(market: dict) -> float | None:
    total = int(market.get("twenty_day_stock_count") or 0)
    if total <= 0:
        return None
    return _pct(int(market.get("new_high_20_count") or 0), total) - _pct(int(market.get("new_low_20_count") or 0), total)


def _metric_source(key: str) -> str:
    if key in {"north_money"}:
        return "t_market_north_flow_daily"
    if key in {"theme_limit_up_density", "theme_persistence", "leader_strength"}:
        return "t_market_sector_heat_daily(v1)"
    if key in {"core_index_trend", "index_amplitude"}:
        return "t_index_bar"
    if key in {"natural_limit_up_count", "qualified_limit_down_count", "limit_break_rate", "board_promotion_rate", "board_structure", "previous_limit_up_premium"}:
        return "t_limit_event_daily + t_daily_bar + t_trade_calendar"
    return "t_daily_bar + t_stock_factor_daily + t_stock_fund_flow_daily"


def _serialize_external_confirmations(values: dict, trade_date: date) -> dict:
    result = dict(values or {})
    for key in ("north_hold_latest_trade_date", "margin_latest_trade_date"):
        value = result.get(key)
        result[key] = value.isoformat() if hasattr(value, "isoformat") else value
    result["as_of_trade_date"] = trade_date.isoformat()
    result["scoring_included"] = False
    result["note"] = "北向持仓与两融按实际披露日展示，仅作延迟确认，不参与当日核心分数"
    return result


def _validate_model_code(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > 80 or not all(char.isalnum() or char in {"-", "_", "."} for char in normalized):
        raise ValueError("模型代码只能包含字母、数字、连字符、下划线和点，长度不超过 80")
    return normalized


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _round(value: float | None, digits: int = 2) -> float | None:
    return round(float(value), digits) if value is not None else None
