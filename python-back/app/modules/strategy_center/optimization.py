"""Deterministic, no-look-ahead parameter research over completed baselines.

The optimiser only considers tighter selector thresholds from an already
completed baseline run.  This makes every trial replayable from persisted
candidate facts and prevents an LLM or a UI form from silently inventing new
signals.  A structurally wider rule or a different exit model needs its own
fresh baseline backtest instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from itertools import product
from math import sqrt
from statistics import mean, median
from typing import Any, Iterable

from app.modules.strategy_center.builtins import TunableParameterSpec, list_tunable_parameters


DEFAULT_TRAIN_RATIO = 0.70
MIN_TRAIN_TRADES = 300
MIN_VALIDATION_TRADES = 120
MIN_TRAIN_SIGNAL_DAYS = 80
MIN_VALIDATION_SIGNAL_DAYS = 30
MIN_TRAIN_WIN_RATE_PCT = 48.0
MIN_VALIDATION_WIN_RATE_PCT = 50.0
MIN_AVERAGE_RETURN_PCT = 0.0
MAX_WIN_RATE_DRIFT_PCT = 8.0


@dataclass(frozen=True)
class OptimizationRequirements:
    train_ratio: float = DEFAULT_TRAIN_RATIO
    min_train_trades: int = MIN_TRAIN_TRADES
    min_validation_trades: int = MIN_VALIDATION_TRADES
    min_train_signal_days: int = MIN_TRAIN_SIGNAL_DAYS
    min_validation_signal_days: int = MIN_VALIDATION_SIGNAL_DAYS
    min_train_win_rate_pct: float = MIN_TRAIN_WIN_RATE_PCT
    min_validation_win_rate_pct: float = MIN_VALIDATION_WIN_RATE_PCT
    min_average_return_pct: float = MIN_AVERAGE_RETURN_PCT
    max_win_rate_drift_pct: float = MAX_WIN_RATE_DRIFT_PCT

    def as_dict(self) -> dict[str, Any]:
        return {
            "train_ratio": self.train_ratio,
            "min_train_trades": self.min_train_trades,
            "min_validation_trades": self.min_validation_trades,
            "min_train_signal_days": self.min_train_signal_days,
            "min_validation_signal_days": self.min_validation_signal_days,
            "min_train_win_rate_pct": self.min_train_win_rate_pct,
            "min_validation_win_rate_pct": self.min_validation_win_rate_pct,
            "min_average_return_pct": self.min_average_return_pct,
            "max_win_rate_drift_pct": self.max_win_rate_drift_pct,
        }


@dataclass(frozen=True)
class OptimizationTrialResult:
    trial_no: int
    parameter_patch: dict[str, Any]
    train_summary: dict[str, Any]
    validation_summary: dict[str, Any]
    robustness_summary: dict[str, Any]
    verdict: str
    rank_no: int | None = None


def requirements_from_payload(*, train_ratio: float) -> OptimizationRequirements:
    if not 0.6 <= train_ratio <= 0.8:
        raise ValueError("train_ratio 必须在 0.60 到 0.80 之间，以保留足够的后验验证区间。")
    return OptimizationRequirements(train_ratio=train_ratio)


def split_train_end_date(trades: Iterable[Any], requirements: OptimizationRequirements) -> date:
    dates = sorted({item.signal_trade_date for item in trades})
    if len(dates) < requirements.min_train_signal_days + requirements.min_validation_signal_days:
        raise ValueError("基线有效信号交易日不足，不能进行训练/验证参数研究。")
    index = max(0, min(len(dates) - 2, int(len(dates) * requirements.train_ratio) - 1))
    return dates[index]


def build_trials(
    *,
    implementation_code: str,
    baseline_trades: list[Any],
    requirements: OptimizationRequirements,
    max_trials: int,
    base_rule_config: dict[str, Any] | None = None,
) -> tuple[date, list[OptimizationTrialResult], dict[str, Any]]:
    """Evaluate bounded stricter selector variants against a chronological split."""

    if max_trials < 1 or max_trials > 1_000:
        raise ValueError("max_trials 必须在 1 到 1000 之间。")
    parameter_specs = _version_parameter_specs(implementation_code, base_rule_config or {})
    if not parameter_specs:
        raise ValueError(f"策略 {implementation_code} 没有可审计的参数搜索空间。")
    if not baseline_trades:
        raise ValueError("基线回测没有已结束交易，不能优化。")
    train_end_date = split_train_end_date(baseline_trades, requirements)
    trial_patches = _parameter_patches(parameter_specs, max_trials=max_trials)
    results: list[OptimizationTrialResult] = []
    for trial_no, patch in enumerate(trial_patches, start=1):
        selected = [item for item in baseline_trades if _trial_matches(item.candidate_snapshot or {}, patch, parameter_specs)]
        train = [item for item in selected if item.signal_trade_date <= train_end_date]
        validation = [item for item in selected if item.signal_trade_date > train_end_date]
        train_summary = _sample_summary(train)
        validation_summary = _sample_summary(validation)
        robustness = _robustness_summary(train_summary, validation_summary)
        verdict = _verdict(train_summary, validation_summary, robustness, requirements)
        results.append(
            OptimizationTrialResult(
                trial_no=trial_no,
                parameter_patch=patch,
                train_summary=train_summary,
                validation_summary=validation_summary,
                robustness_summary=robustness,
                verdict=verdict,
            )
        )
    ranked = _rank_trials(results)
    search_space = {
        "mode": "restrictive_baseline_subset",
        "parameter_count": len(parameter_specs),
        "trial_count": len(ranked),
        "parameters": [
            {
                "key": item.key,
                "label": item.label,
                "source": item.source,
                "comparator": item.comparator,
                "candidates": list(item.candidates),
            }
            for item in parameter_specs
        ],
    }
    return train_end_date, ranked, search_space


def optimization_summary(
    trials: list[OptimizationTrialResult],
    *,
    train_end_date: date,
    requirements: OptimizationRequirements,
    baseline_trade_count: int,
) -> dict[str, Any]:
    eligible = [item for item in trials if item.verdict == "eligible"]
    return {
        "baseline_trade_count": baseline_trade_count,
        "train_end_date": train_end_date.isoformat(),
        "requirements": requirements.as_dict(),
        "trial_count": len(trials),
        "eligible_trial_count": len(eligible),
        "recommended_trial_no": eligible[0].trial_no if eligible else None,
        "recommendation": "存在通过训练/验证稳定性门槛的参数候选。" if eligible else "没有参数候选同时满足样本量、胜率、正收益和稳定性门槛；不得据此创建 paper 版本。",
    }


def _parameter_from_dict(raw: dict[str, Any]) -> TunableParameterSpec:
    return TunableParameterSpec(
        key=str(raw["key"]),
        label=str(raw["label"]),
        source=str(raw["source"]),
        comparator=str(raw["comparator"]),
        candidates=tuple(float(item) for item in raw["candidates"]),
    )


def _version_parameter_specs(implementation_code: str, base_rule_config: dict[str, Any]) -> list[TunableParameterSpec]:
    specs: list[TunableParameterSpec] = []
    for raw in list_tunable_parameters(implementation_code):
        spec = _parameter_from_dict(raw)
        baseline = _number(_nested_get(base_rule_config, spec.key))
        baseline = baseline if baseline is not None else spec.candidates[0]
        if spec.comparator == "gte":
            allowed = [value for value in spec.candidates if value >= baseline]
        elif spec.comparator in {"lte", "lt"}:
            allowed = [value for value in spec.candidates if value <= baseline]
        else:  # pragma: no cover - registry contract.
            raise ValueError(f"unsupported optimisation comparator: {spec.comparator}")
        candidates = tuple(dict.fromkeys((baseline, *allowed)))
        specs.append(
            TunableParameterSpec(
                key=spec.key,
                label=spec.label,
                source=spec.source,
                comparator=spec.comparator,
                candidates=candidates,
            )
        )
    return specs


def _parameter_patches(specs: list[TunableParameterSpec], *, max_trials: int) -> list[dict[str, Any]]:
    combinations = []
    for values in product(*(item.candidates for item in specs)):
        patch = _patch_from_values(specs, values)
        if _is_valid_patch(patch):
            changed = sum(value != item.candidates[0] for item, value in zip(specs, values))
            combinations.append((changed, patch))
    combinations.sort(key=lambda item: (item[0], _stable_patch_key(item[1])))
    return [patch for _, patch in combinations[:max_trials]]


def _patch_from_values(specs: list[TunableParameterSpec], values: tuple[float, ...]) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    for spec, value in zip(specs, values):
        target = patch
        parts = spec.key.split(".")
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = value
    return patch


def _is_valid_patch(patch: dict[str, Any]) -> bool:
    signal = patch.get("signal") or {}
    change_min = signal.get("change_min")
    change_max = signal.get("change_max")
    if change_min is not None and change_max is not None and float(change_min) >= float(change_max):
        return False
    board_min = signal.get("board_count_min")
    board_max = signal.get("board_count_max")
    return not (board_min is not None and board_max is not None and int(board_min) > int(board_max))


def _stable_patch_key(patch: dict[str, Any]) -> tuple:
    flattened: list[tuple[str, float]] = []
    for parent, values in sorted(patch.items()):
        for key, value in sorted((values or {}).items()):
            flattened.append((f"{parent}.{key}", float(value)))
    return tuple(flattened)


def _trial_matches(snapshot: dict[str, Any], patch: dict[str, Any], specs: list[TunableParameterSpec]) -> bool:
    for spec in specs:
        expected = _nested_get(patch, spec.key)
        if expected is None:
            continue
        # A historical baseline with unavailable emotion has intentionally
        # allowed that day; adding a score threshold must not rewrite the old
        # evaluator semantics retroactively.  A newly versioned rule may opt
        # into V2's ``degraded`` score, whose core facts are complete while
        # optional confirmations are delayed.
        if spec.key.startswith("market_gate."):
            emotion_status = str((snapshot.get("emotion") or {}).get("status") or "")
            market_gate = ((snapshot.get("rule_config") or {}).get("market_gate") or {})
            if emotion_status != "ready" and not (
                emotion_status == "degraded" and bool(market_gate.get("accept_degraded_score", False))
            ):
                continue
        actual = _snapshot_value(snapshot, spec.source)
        if actual is None:
            return False
        if spec.comparator == "gte" and actual < float(expected):
            return False
        if spec.comparator == "lte" and actual > float(expected):
            return False
        if spec.comparator == "lt" and actual >= float(expected):
            return False
    return True


def _nested_get(values: dict[str, Any], path: str) -> Any:
    current: Any = values
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _snapshot_value(snapshot: dict[str, Any], source: str) -> float | None:
    if source == "concept_context.best_heat_rank":
        values = [
            _number(item.get("heat_rank"))
            for item in list(snapshot.get("concept_context") or [])
            if _number(item.get("heat_rank")) is not None
        ]
        return min(values) if values else None
    current: Any = snapshot
    for part in source.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return _number(current)


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _sample_summary(rows: list[Any]) -> dict[str, Any]:
    returns = [float(item.net_return_pct) for item in rows]
    signal_dates = {item.signal_trade_date for item in rows}
    if not returns:
        return {
            "completed_trade_count": 0,
            "signal_trade_date_count": 0,
            "win_count": 0,
            "win_rate_pct": None,
            "average_net_return_pct": None,
            "median_net_return_pct": None,
            "profit_factor": None,
        }
    wins = [item for item in returns if item > 0]
    gains = sum(item for item in returns if item > 0)
    losses = -sum(item for item in returns if item < 0)
    return {
        "completed_trade_count": len(returns),
        "signal_trade_date_count": len(signal_dates),
        "win_count": len(wins),
        "win_rate_pct": round(len(wins) / len(returns) * 100, 4),
        "average_net_return_pct": round(mean(returns), 6),
        "median_net_return_pct": round(median(returns), 6),
        "profit_factor": round(gains / losses, 6) if losses else None,
    }


def _robustness_summary(train: dict[str, Any], validation: dict[str, Any]) -> dict[str, Any]:
    train_count = int(train.get("completed_trade_count") or 0)
    validation_count = int(validation.get("completed_trade_count") or 0)
    train_wins = int(train.get("win_count") or 0)
    validation_wins = int(validation.get("win_count") or 0)
    train_rate = float(train.get("win_rate_pct") or 0.0)
    validation_rate = float(validation.get("win_rate_pct") or 0.0)
    return {
        "train_validation_win_rate_drift_pct": round(abs(train_rate - validation_rate), 4),
        "validation_win_rate_lower_bound_pct": round(_wilson_lower_bound(validation_wins, validation_count) * 100, 4) if validation_count else None,
        "train_win_rate_lower_bound_pct": round(_wilson_lower_bound(train_wins, train_count) * 100, 4) if train_count else None,
        "both_average_positive": bool((train.get("average_net_return_pct") or 0) > 0 and (validation.get("average_net_return_pct") or 0) > 0),
    }


def _wilson_lower_bound(wins: int, total: int, *, z: float = 1.96) -> float:
    if total <= 0:
        return 0.0
    proportion = wins / total
    denominator = 1 + z * z / total
    centre = proportion + z * z / (2 * total)
    adjustment = z * sqrt((proportion * (1 - proportion) + z * z / (4 * total)) / total)
    return max(0.0, (centre - adjustment) / denominator)


def _verdict(
    train: dict[str, Any],
    validation: dict[str, Any],
    robustness: dict[str, Any],
    requirements: OptimizationRequirements,
) -> str:
    if (
        int(train.get("completed_trade_count") or 0) < requirements.min_train_trades
        or int(validation.get("completed_trade_count") or 0) < requirements.min_validation_trades
        or int(train.get("signal_trade_date_count") or 0) < requirements.min_train_signal_days
        or int(validation.get("signal_trade_date_count") or 0) < requirements.min_validation_signal_days
    ):
        return "data_insufficient"
    if (
        float(train.get("win_rate_pct") or 0) < requirements.min_train_win_rate_pct
        or float(validation.get("win_rate_pct") or 0) < requirements.min_validation_win_rate_pct
        or float(train.get("average_net_return_pct") or 0) <= requirements.min_average_return_pct
        or float(validation.get("average_net_return_pct") or 0) <= requirements.min_average_return_pct
        or float(robustness.get("train_validation_win_rate_drift_pct") or 0) > requirements.max_win_rate_drift_pct
    ):
        return "rejected"
    return "eligible"


def _rank_trials(results: list[OptimizationTrialResult]) -> list[OptimizationTrialResult]:
    def rank_key(item: OptimizationTrialResult):
        validation = item.validation_summary
        robustness = item.robustness_summary
        return (
            item.verdict == "eligible",
            float(robustness.get("validation_win_rate_lower_bound_pct") or 0),
            float(validation.get("average_net_return_pct") or -999),
            float(validation.get("median_net_return_pct") or -999),
            int(validation.get("completed_trade_count") or 0),
        )

    ordered = sorted(results, key=rank_key, reverse=True)
    ranked: list[OptimizationTrialResult] = []
    for index, item in enumerate(ordered, start=1):
        ranked.append(
            OptimizationTrialResult(
                trial_no=item.trial_no,
                parameter_patch=item.parameter_patch,
                train_summary=item.train_summary,
                validation_summary=item.validation_summary,
                robustness_summary=item.robustness_summary,
                verdict=item.verdict,
                rank_no=index,
            )
        )
    return ranked
