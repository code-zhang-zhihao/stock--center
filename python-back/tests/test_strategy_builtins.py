from __future__ import annotations

from datetime import date

from app.modules.strategy_center.builtins import evaluate_daily_candidate, list_builtin_specs, list_tunable_parameters, resolve_strategy_configs
from app.modules.strategy_center.repository import _backtest_prefilter_conditions
from app.modules.strategy_center.service import StrategyCenterService, _history_by_stock


def _base_context() -> dict:
    history = []
    for index in range(21):
        price = 10 + index * 0.1
        history.append(
            {
                "trade_date": f"2026-06-{index + 1:02d}",
                "open_price": price - 0.05,
                "high_price": price,
                "low_price": price - 0.2,
                "close_price": price - 0.02,
                "change_pct": 0.8,
                "amount_yuan": 120_000_000,
                "ma5": price - 0.2,
                "ma10": price - 0.35,
                "ma20": price - 0.5,
                "ma60": price - 1,
                "volume_ratio": 1.3,
                "amount_ratio": 1.4,
                "volatility_20d": 1.5,
                "close_position": 0.7,
                "turnover_rate": 9,
                "main_net_inflow": 100_000,
                "main_net_ratio": 3,
                "history_days": 80,
            }
        )
    current = {
        **history[-1],
        "trade_date": "2026-07-01",
        "open_price": 12.0,
        "high_price": 12.8,
        "low_price": 11.9,
        "close_price": 12.7,
        "change_pct": 4.0,
        "amount_yuan": 200_000_000,
        "ma5": 11.6,
        "ma10": 11.3,
        "ma20": 11.0,
        "ma60": 10.5,
        "volume_ratio": 2.2,
        "amount_ratio": 2.0,
        "volatility_20d": 1.5,
        "close_position": 0.85,
        "history_days": 81,
    }
    return {
        "trade_date": date(2026, 7, 1),
        "stock_code": "600001",
        "stock": {"stock_name": "测试股", "exchange": "SH", "status": "active", "is_st": False},
        "current": current,
        "previous": history[-1],
        "history": [*history, current],
        "emotion": {"status": "ready", "market_risk_on_score": 65, "primary_stage_code": "active"},
        "limit_event": {},
        "limit_evidence": {},
        "concept_context": [],
    }


def test_builtin_registry_has_only_auditable_implemented_templates():
    specs = list_builtin_specs()
    assert len(specs) == 11
    assert {spec.implementation_code for spec in specs} >= {"trend_breakout", "theme_first_board_relay", "broken_board_recovery"}
    assert all(spec.required_inputs for spec in specs)
    assert all(spec.supported_execution_models == ("next_open_daily",) for spec in specs)


def test_every_builtin_has_a_database_prefilter_with_python_evaluator_as_authority():
    for spec in list_builtin_specs():
        conditions = _backtest_prefilter_conditions(spec.implementation_code)
        assert conditions


def test_trend_breakout_requires_prior_high_volume_and_strong_close():
    context = _base_context()
    result = evaluate_daily_candidate("trend_breakout", context)
    assert result.matched is True
    assert result.score is not None and result.score > 60
    assert result.candidate_snapshot["implementation_code"] == "trend_breakout"
    assert result.entry_plan["t_plus_one"] is True


def test_missing_fact_rejects_a_strategy_instead_of_using_zero_default():
    context = _base_context()
    context["current"]["amount_ratio"] = None
    result = evaluate_daily_candidate("volume_price_surge", context)
    assert result.matched is False
    assert result.skip_code == "rule_not_matched"
    assert result.reasons[0]["code"] == "volume_price_surge_inputs"
    assert result.candidate_snapshot == {}
    assert result.entry_plan == {}


def test_resolved_configs_preserve_single_stock_evaluator_result():
    context = _base_context()
    direct = evaluate_daily_candidate("trend_breakout", context)
    rule, risk = resolve_strategy_configs("trend_breakout")
    batched = evaluate_daily_candidate(
        "trend_breakout",
        context,
        resolved_rule_config=rule,
        resolved_risk_config=risk,
    )
    assert batched == direct


def test_tunable_rule_parameters_change_the_evaluator_without_dynamic_code():
    context = _base_context()
    strict = evaluate_daily_candidate(
        "trend_breakout",
        context,
        rule_config={"signal": {"amount_ratio_min": 2.1}},
    )
    assert strict.matched is False
    assert any(item["code"] == "breakout_amount" and not item["passed"] for item in strict.reasons)
    parameters = list_tunable_parameters("trend_breakout")
    assert {item["key"] for item in parameters} >= {"signal.amount_ratio_min", "market_gate.minimum_market_risk_on_score"}


def test_theme_relay_requires_limit_evidence_and_hot_concept_context():
    context = _base_context()
    context["limit_event"] = {"event_type": "limit_up", "open_count": 1}
    context["limit_evidence"] = {"board_count": 1}
    context["concept_context"] = [{"sector_code": "ths_concept_x", "heat_rank": 3}]
    result = evaluate_daily_candidate("theme_first_board_relay", context)
    assert result.matched is True

    context["concept_context"] = []
    rejected = evaluate_daily_candidate("theme_first_board_relay", context)
    assert rejected.matched is False
    assert any(item["code"] == "first_board_theme" and not item["passed"] for item in rejected.reasons)


def test_daily_baseline_never_sells_on_the_same_entry_date():
    d0, d1, d2, d3 = (date(2026, 7, day) for day in range(1, 5))
    contexts = {
        d1: {"600001": {"current": {"open_price": 10.0, "close_price": 9.0}}},
        d2: {"600001": {"current": {"open_price": 8.8, "close_price": 8.7}}},
        d3: {"600001": {"current": {"open_price": 8.6, "close_price": 8.5}}},
    }
    trade = StrategyCenterService._simulate_next_open_daily_trade(
        candidate={"stock_code": "600001", "entry_plan": {"risk_plan": {"hard_stop_loss_pct": -4}}},
        signal_date=d0,
        full_calendar=[d0, d1, d2, d3],
        date_index={d0: 0, d1: 1, d2: 2, d3: 3},
        contexts=contexts,
        max_holding=3,
        fee_rate=0.0005,
        slippage_bps=0,
    )
    assert trade is not None
    assert trade["entry_trade_date"] == d1
    assert trade["exit_trade_date"] == d2
    assert trade["exit_trade_date"] > trade["entry_trade_date"]


def test_batch_history_keeps_actual_trade_dates_for_missing_bars():
    d1, d2, d3 = (date(2026, 7, day) for day in range(1, 4))
    histories = _history_by_stock(
        [d1, d2, d3],
        {
            d1: {"600001": {"current": {"close_price": 10.0}}},
            d3: {"600001": {"current": {"close_price": 11.0}}},
        },
    )
    assert histories["600001"] == [
        (d1, {"close_price": 10.0}),
        (d3, {"close_price": 11.0}),
    ]
