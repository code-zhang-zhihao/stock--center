from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

from app.modules.strategy_center.builtins import default_rule_config
from app.modules.strategy_center.optimization import (
    OptimizationRequirements,
    build_trials,
    optimization_summary,
)


def _baseline_trades() -> list[SimpleNamespace]:
    """Create a broad synthetic baseline with facts frozen per candidate."""

    start = date(2025, 1, 2)
    rows: list[SimpleNamespace] = []
    for day_offset in range(120):
        signal_date = start + timedelta(days=day_offset)
        for stock_offset in range(4):
            rows.append(
                SimpleNamespace(
                    signal_trade_date=signal_date,
                    net_return_pct=1.0 + stock_offset * 0.01,
                    candidate_snapshot={
                        "daily_facts": {
                            "change_pct": 5.0,
                            "amount_ratio": 2.5,
                            "close_position": 0.9,
                        },
                        "emotion": {"status": "ready", "market_risk_on_score": 70},
                    },
                )
            )
    return rows


def test_optimizer_uses_chronological_holdout_and_preserves_sample_requirements():
    trades = _baseline_trades()
    train_end, trials, _ = build_trials(
        implementation_code="trend_breakout",
        baseline_trades=trades,
        requirements=OptimizationRequirements(),
        max_trials=500,
        base_rule_config=default_rule_config("trend_breakout"),
    )

    assert train_end == date(2025, 3, 26)
    assert all(item.train_summary["completed_trade_count"] >= 300 for item in trials if item.verdict == "eligible")
    assert all(item.validation_summary["completed_trade_count"] >= 120 for item in trials if item.verdict == "eligible")
    assert any(item.verdict == "eligible" for item in trials)
    summary = optimization_summary(
        trials,
        train_end_date=train_end,
        requirements=OptimizationRequirements(),
        baseline_trade_count=len(trades),
    )
    assert summary["eligible_trial_count"] > 0
    assert summary["recommended_trial_no"] is not None


def test_optimizer_never_expands_beyond_persisted_baseline_candidates():
    trades = _baseline_trades()
    _, trials, search_space = build_trials(
        implementation_code="trend_breakout",
        baseline_trades=trades,
        requirements=OptimizationRequirements(),
        max_trials=500,
        base_rule_config=default_rule_config("trend_breakout"),
    )

    assert search_space["mode"] == "restrictive_baseline_subset"
    amount_trials = [item for item in trials if (item.parameter_patch.get("signal") or {}).get("amount_ratio_min") == 2.5]
    assert amount_trials
    assert all(item.train_summary["completed_trade_count"] <= 336 for item in amount_trials)
    assert all(item.validation_summary["completed_trade_count"] <= 144 for item in amount_trials)
