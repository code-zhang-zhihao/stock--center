from __future__ import annotations

from datetime import date

from app.db.session import get_sessionmaker
from app.modules.scheduler_center.handlers import JobExecutionContext, job_handler_registry
from app.modules.scheduler_center.schemas import JobResult
from app.modules.strategy_center.repository import StrategyCenterRepository
from app.modules.strategy_center.service import StrategyCenterService


class EvaluateStrategyDailyCandidatesHandler:
    """Generate only T-day paper-strategy candidates from settled local facts."""

    job_code = "evaluate_strategy_daily_candidates"
    job_type = "strategy"
    parameter_schema = {
        "trade_date": {
            "label": "指定交易日期",
            "type": "string",
            "required": False,
            "description": "为空时使用最新完成的盘后报告事实日。",
        },
        "strategy_code": {
            "label": "指定策略代码",
            "type": "string",
            "required": False,
            "description": "为空时评估全部 paper 状态策略版本。",
        },
    }
    default_payload = {}
    force_async = True

    async def run(self, context: JobExecutionContext) -> JobResult:
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            result = await StrategyCenterService(StrategyCenterRepository(session)).evaluate_daily_candidates(
                trade_date=_parse_date(context.payload.get("trade_date")),
                strategy_code=str(context.payload.get("strategy_code") or "").strip() or None,
                progress_reporter=context.report_progress,
            )
        strategies = list(result.get("strategies") or [])
        affected = sum(
            int(item.get(key) or 0)
            for item in strategies
            for key in ("created", "refreshed", "cancelled")
        )
        return JobResult(
            status="success" if strategies else "skipped",
            affected_rows=affected,
            summary=result,
        )


class RunStrategyBacktestHandler:
    """Run one bounded, local-facts-only daily baseline backtest."""

    job_code = "run_strategy_backtest"
    job_type = "strategy"
    parameter_schema = {
        "strategy_code": {"label": "策略代码", "type": "string", "required": True},
        "version_no": {"label": "版本号", "type": "integer", "required": True},
        "start_date": {"label": "开始日期", "type": "string", "required": True},
        "end_date": {"label": "结束日期", "type": "string", "required": True},
        "fee_rate": {"label": "单边费率", "type": "number", "default": 0.0005, "required": False},
        "slippage_bps": {"label": "单边滑点（bps）", "type": "number", "default": 10, "required": False},
        "baseline_candidate_limit": {
            "label": "研究回测每日候选上限",
            "type": "integer",
            "required": False,
            "description": "仅用于参数研究；高于策略实际候选上限的回测不会解锁 paper。",
        },
    }
    default_payload = {"fee_rate": 0.0005, "slippage_bps": 10}
    force_async = True

    async def run(self, context: JobExecutionContext) -> JobResult:
        payload = {**self.default_payload, **context.payload}
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            result = await StrategyCenterService(StrategyCenterRepository(session)).run_backtest(
                strategy_code=str(payload.get("strategy_code") or "").strip(),
                version_no=int(payload.get("version_no")),
                start_date=_required_date(payload.get("start_date"), "start_date"),
                end_date=_required_date(payload.get("end_date"), "end_date"),
                fee_rate=float(payload.get("fee_rate") or 0.0005),
                slippage_bps=float(payload.get("slippage_bps") or 10),
                baseline_candidate_limit=(
                    int(payload["baseline_candidate_limit"])
                    if payload.get("baseline_candidate_limit") not in (None, "")
                    else None
                ),
                progress_reporter=context.report_progress,
            )
        summary = result.get("summary") or {}
        return JobResult(
            status="success",
            affected_rows=int(summary.get("completed_trade_count") or 0),
            summary=result,
        )


class OptimizeStrategyParametersHandler:
    """Research selector thresholds from an already completed baseline.

    This is intentionally a manual, local-facts-only job.  It never invokes
    a Provider or LLM and it cannot alter a version or move one into paper.
    """

    job_code = "optimize_strategy_parameters"
    job_type = "strategy"
    parameter_schema = {
        "strategy_code": {"label": "策略代码", "type": "string", "required": True},
        "version_no": {"label": "版本号", "type": "integer", "required": True},
        "baseline_run_code": {
            "label": "基线回测运行代码",
            "type": "string",
            "required": False,
            "description": "为空时选择该版本最近一条已完成的基线回测。",
        },
        "train_ratio": {
            "label": "训练样本比例",
            "type": "number",
            "default": 0.7,
            "required": False,
            "description": "按信号交易日顺序切分；余下日期仅用于样本外验证。",
        },
        "max_trials": {
            "label": "最大试验数",
            "type": "integer",
            "default": 500,
            "required": False,
        },
    }
    default_payload = {"train_ratio": 0.7, "max_trials": 500}
    force_async = True

    async def run(self, context: JobExecutionContext) -> JobResult:
        payload = {**self.default_payload, **context.payload}
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            result = await StrategyCenterService(StrategyCenterRepository(session)).optimize_parameters(
                strategy_code=str(payload.get("strategy_code") or "").strip(),
                version_no=int(payload.get("version_no")),
                baseline_run_code=str(payload.get("baseline_run_code") or "").strip() or None,
                train_ratio=float(payload.get("train_ratio") or 0.7),
                max_trials=int(payload.get("max_trials") or 500),
                progress_reporter=context.report_progress,
            )
        summary = result.get("summary") or {}
        return JobResult(
            status="success",
            affected_rows=int(summary.get("eligible_trial_count") or 0),
            summary=result,
        )


def register_strategy_center_jobs() -> None:
    job_handler_registry.register(EvaluateStrategyDailyCandidatesHandler())
    job_handler_registry.register(RunStrategyBacktestHandler())
    job_handler_registry.register(OptimizeStrategyParametersHandler())


def _parse_date(value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _required_date(value, field_name: str) -> date:
    parsed = _parse_date(value)
    if parsed is None:
        raise ValueError(f"{field_name} is required")
    return parsed
