"""Auditable, data-backed short-term strategy implementations.

The module deliberately contains no dynamically executed user expressions.
Every supported implementation has a named, versioned Python function and a
published required-input contract.  This makes a candidate reproducible from
its frozen daily facts and prevents a half-configured strategy from silently
emitting recommendations.

These are research and paper-trading rules, not investment advice.  A rule is
eligible for paper mode only after its *specific version* has a completed
historical baseline in ``next_open_daily`` execution mode.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Callable


BUILTIN_STRATEGY_IMPLEMENTATION_VERSION = "2026.07.28.1"


@dataclass(frozen=True)
class BuiltinStrategySpec:
    implementation_code: str
    strategy_name: str
    description: str
    entry_mode: str
    max_holding_trade_days: int
    required_inputs: tuple[str, ...]
    supported_execution_models: tuple[str, ...] = ("next_open_daily",)

    def template(self) -> dict[str, Any]:
        return {
            "strategy_code": self.implementation_code,
            "strategy_name": self.strategy_name,
            "description": self.description,
            "entry_mode": self.entry_mode,
            "max_holding_trade_days": self.max_holding_trade_days,
            "rule_config": default_rule_config(self.implementation_code),
            "risk_config": default_risk_config(self.implementation_code),
            "implementation_version": BUILTIN_STRATEGY_IMPLEMENTATION_VERSION,
            "required_inputs": list(self.required_inputs),
            "supported_execution_models": list(self.supported_execution_models),
        }


@dataclass(frozen=True)
class EvaluationResult:
    matched: bool
    score: float | None
    reasons: list[dict[str, Any]]
    candidate_snapshot: dict[str, Any]
    entry_plan: dict[str, Any]
    skip_code: str | None = None


_SPECS: tuple[BuiltinStrategySpec, ...] = (
    BuiltinStrategySpec(
        "trend_breakout",
        "趋势突破",
        "收盘突破过去 20 个交易日高点，同时放量并保持强收盘。",
        "open",
        5,
        ("daily_bar", "daily_factor:ma20", "daily_factor:amount_ratio", "daily_factor:close_position"),
    ),
    BuiltinStrategySpec(
        "bullish_alignment",
        "均线多头排列",
        "MA5、MA10、MA20、MA60 依次向上，配合当日放量走强。",
        "open",
        5,
        ("daily_bar", "daily_factor:ma5,ma10,ma20,ma60,volume_ratio"),
    ),
    BuiltinStrategySpec(
        "ma_golden_cross",
        "MA5 上穿 MA10",
        "短均线上穿中短均线的日频交叉，要求量能确认。",
        "open",
        4,
        ("daily_bar", "daily_factor:ma5,ma10,volume_ratio", "previous_daily_factor:ma5,ma10"),
    ),
    BuiltinStrategySpec(
        "volume_price_surge",
        "量价齐升",
        "中等涨幅、显著放量、强收盘且未触及涨停的一般动量候选。",
        "open",
        3,
        ("daily_bar", "daily_factor:volume_ratio,amount_ratio,close_position"),
    ),
    BuiltinStrategySpec(
        "high_turnover_surge",
        "高换手资金突击",
        "高换手上涨、主力资金净流入且强收盘，排除无成交流动性标的。",
        "intraday",
        3,
        ("daily_bar", "daily_basic:turnover_rate", "daily_factor:close_position", "fund_flow:main_net_inflow,main_net_ratio"),
    ),
    BuiltinStrategySpec(
        "low_volatility_leader",
        "低波动趋势领涨",
        "低波动整理后站稳 MA20 的放量领涨候选。",
        "open",
        5,
        ("daily_bar", "daily_factor:ma20,volatility_20d,volume_ratio,close_position"),
    ),
    BuiltinStrategySpec(
        "pullback_ma20_bounce",
        "MA20 回踩反弹",
        "价格回踩 MA20 附近后收阳站回，要求趋势未破坏。",
        "intraday",
        4,
        ("daily_bar", "daily_factor:ma5,ma10,ma20,volume_ratio,close_position", "previous_daily_bar"),
    ),
    BuiltinStrategySpec(
        "n_day_low_reversal",
        "20 日低位反转",
        "触及过去 20 日低位附近后的强收盘反转；这是反转研究规则，必须单独回测。",
        "open",
        3,
        ("daily_bar", "daily_factor:close_position,volume_ratio", "history:20_daily_bars"),
    ),
    BuiltinStrategySpec(
        "theme_first_board_relay",
        "热点题材首板接力",
        "热点概念内的换手首板；候选只记录题材事实，不把新闻或公告写成涨停因果。",
        "auction",
        2,
        ("daily_bar", "limit_event:limit_up", "limit_up_evidence", "concept_heat"),
    ),
    BuiltinStrategySpec(
        "consecutive_limit_up_relay",
        "热点连板接力",
        "热点概念中 2–4 板的换手连板候选，次日必须由盘口/报价确认才产生模拟成交。",
        "auction",
        2,
        ("daily_bar", "limit_event:limit_up", "limit_up_evidence", "concept_heat"),
    ),
    BuiltinStrategySpec(
        "broken_board_recovery",
        "炸板回封修复",
        "当日有炸板事实但收盘仍强势，次日仅在报价与盘口恢复后观察。",
        "intraday",
        2,
        ("daily_bar", "limit_event:limit_break", "daily_factor:close_position,volume_ratio"),
    ),
)

_SPEC_BY_CODE = {item.implementation_code: item for item in _SPECS}


def list_builtin_specs() -> list[BuiltinStrategySpec]:
    return list(_SPECS)


def get_builtin_spec(implementation_code: str) -> BuiltinStrategySpec | None:
    return _SPEC_BY_CODE.get(str(implementation_code or "").strip())


def default_rule_config(implementation_code: str) -> dict[str, Any]:
    spec = get_builtin_spec(implementation_code)
    if spec is None:
        raise ValueError(f"unsupported builtin strategy implementation: {implementation_code}")
    return {
        "implementation_code": spec.implementation_code,
        "implementation_version": BUILTIN_STRATEGY_IMPLEMENTATION_VERSION,
        "universe": {
            "markets": ["SH", "SZ", "SSE", "SZSE"],
            "exclude_st": True,
            "exclude_bj": True,
            "minimum_listing_trade_days": 60,
            "minimum_amount_yuan": 80_000_000,
        },
        "market_gate": {
            "enabled": True,
            "minimum_market_risk_on_score": 35,
            "blocked_primary_stages": ["ice_point", "retreat"],
            "allow_when_emotion_unavailable": True,
        },
        "selection": {"max_candidates": 30},
        "entry_confirmation": _default_entry_confirmation(spec.entry_mode),
    }


def default_risk_config(implementation_code: str) -> dict[str, Any]:
    spec = get_builtin_spec(implementation_code)
    if spec is None:
        raise ValueError(f"unsupported builtin strategy implementation: {implementation_code}")
    return {
        "max_holding_trade_days": spec.max_holding_trade_days,
        # 10 手默认仓位使 50% 的第一止盈腿仍是有效的整手数量；实际
        # 模拟仓位可在草稿版本的风险配置中按个人资金规模调整。
        "initial_quantity": 1000,
        "hard_stop_loss_pct": -4.0,
        "take_profit_legs": [
            {"trigger_return_pct": 5.0, "sell_ratio": 0.5},
            {"trigger_return_pct": 8.0, "sell_ratio": 1.0},
        ],
        "trailing_stop": {"activate_return_pct": 6.0, "drawdown_pct": 3.0},
        "time_exit": {"enabled": True, "trade_days": spec.max_holding_trade_days},
        "t_plus_one": True,
    }


def evaluate_daily_candidate(
    implementation_code: str,
    context: dict[str, Any],
    *,
    rule_config: dict[str, Any] | None = None,
    risk_config: dict[str, Any] | None = None,
    resolved_rule_config: dict[str, Any] | None = None,
    resolved_risk_config: dict[str, Any] | None = None,
) -> EvaluationResult:
    """Evaluate one stock using facts persisted no later than ``trade_date``.

    ``context`` contains target-day data plus history sorted ascending.  The
    evaluator never queries a Provider, reads system time, or invokes an LLM.
    It therefore has exactly the same semantics for daily candidate generation
    and historical baseline evaluation.
    """

    spec = get_builtin_spec(implementation_code)
    if spec is None:
        return _skip("unsupported_implementation", context, implementation_code)
    # A backtest evaluates thousands of stock/date contexts using one version.
    # The caller may therefore resolve the immutable version config once per
    # batch.  Direct callers retain the same public behaviour.
    rule = resolved_rule_config if resolved_rule_config is not None else _deep_merge(default_rule_config(spec.implementation_code), rule_config or {})
    risk = resolved_risk_config if resolved_risk_config is not None else _deep_merge(default_risk_config(spec.implementation_code), risk_config or {})
    current = context.get("current") or {}
    history = list(context.get("history") or [])
    previous = context.get("previous") or (history[-2] if len(history) >= 2 else {})

    universe_reason = _check_universe(context, current, rule)
    if universe_reason:
        return _skip(universe_reason, context, implementation_code, rule, risk)
    market_reason = _check_market_gate(context.get("emotion") or {}, rule)
    if market_reason:
        return _skip(market_reason, context, implementation_code, rule, risk)

    matcher = _MATCHERS[spec.implementation_code]
    matched, score, reasons = matcher(current, previous, history, context)
    # Rejected candidates are never persisted.  Do not allocate a full audit
    # snapshot/risk plan for every rejected stock in a historical batch.
    if not matched:
        return EvaluationResult(
            matched=False,
            score=round(score, 4) if score is not None else None,
            reasons=reasons,
            candidate_snapshot={},
            entry_plan={},
            skip_code="rule_not_matched",
        )
    snapshot = _candidate_snapshot(context, spec, rule, risk, reasons)
    entry_plan = _entry_plan(spec, rule, risk)
    return EvaluationResult(
        matched=matched,
        score=round(score, 4) if score is not None else None,
        reasons=reasons,
        candidate_snapshot=snapshot,
        entry_plan=entry_plan,
        skip_code=None if matched else "rule_not_matched",
    )


def resolve_strategy_configs(
    implementation_code: str,
    *,
    rule_config: dict[str, Any] | None = None,
    risk_config: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve a strategy version's configs once for a batch evaluator."""

    spec = get_builtin_spec(implementation_code)
    if spec is None:
        raise ValueError(f"unsupported builtin strategy implementation: {implementation_code}")
    return (
        _deep_merge(default_rule_config(spec.implementation_code), rule_config or {}),
        _deep_merge(default_risk_config(spec.implementation_code), risk_config or {}),
    )


def _trend_breakout(current, previous, history, context):
    prior = history[:-1]
    prior_high = _max_num(prior[-20:], "high_price")
    close = _num(current, "close_price")
    change = _num(current, "change_pct")
    amount_ratio = _num(current, "amount_ratio")
    close_position = _num(current, "close_position")
    if None in (prior_high, close, change, amount_ratio, close_position):
        return _missing("trend_breakout_inputs")
    matched = close >= prior_high and 2.0 <= change < 9.5 and amount_ratio >= 1.5 and close_position >= 0.65
    score = min(100.0, 45 + min((close / prior_high - 1) * 1000, 20) + min(amount_ratio * 12, 20) + close_position * 18)
    return matched, score, _reasons(
        ("breakout_close", close >= prior_high, f"收盘 {close:.2f} / 前 20 日高点 {prior_high:.2f}"),
        ("breakout_change", 2.0 <= change < 9.5, f"涨跌幅 {change:.2f}%"),
        ("breakout_amount", amount_ratio >= 1.5, f"额比 {amount_ratio:.2f}"),
        ("breakout_close_position", close_position >= 0.65, f"收盘位置 {close_position:.2f}"),
    )


def _bullish_alignment(current, previous, history, context):
    close, ma5, ma10, ma20, ma60, volume_ratio, change = _nums(
        current, "close_price", "ma5", "ma10", "ma20", "ma60", "volume_ratio", "change_pct"
    )
    if None in (close, ma5, ma10, ma20, ma60, volume_ratio, change):
        return _missing("bullish_alignment_inputs")
    alignment = close > ma5 > ma10 > ma20 > ma60
    matched = alignment and change >= 1.0 and volume_ratio >= 1.2
    score = min(100.0, 40 + _pct_gap(close, ma60) * 2 + min(volume_ratio * 12, 20) + min(change * 3, 20))
    return matched, score, _reasons(
        ("bullish_alignment", alignment, "close > MA5 > MA10 > MA20 > MA60"),
        ("bullish_change", change >= 1.0, f"涨跌幅 {change:.2f}%"),
        ("bullish_volume", volume_ratio >= 1.2, f"量比 {volume_ratio:.2f}"),
    )


def _ma_golden_cross(current, previous, history, context):
    ma5, ma10, volume_ratio, change = _nums(current, "ma5", "ma10", "volume_ratio", "change_pct")
    prev_ma5, prev_ma10 = _nums(previous, "ma5", "ma10")
    if None in (ma5, ma10, prev_ma5, prev_ma10, volume_ratio, change):
        return _missing("ma_golden_cross_inputs")
    crossed = prev_ma5 <= prev_ma10 and ma5 > ma10
    matched = crossed and change > 0 and volume_ratio >= 1.2
    score = min(100.0, 55 + min(_pct_gap(ma5, ma10) * 10, 20) + min(volume_ratio * 10, 15) + min(change * 2, 10))
    return matched, score, _reasons(
        ("golden_cross", crossed, f"昨日 MA5/MA10 {prev_ma5:.2f}/{prev_ma10:.2f}，今日 {ma5:.2f}/{ma10:.2f}"),
        ("golden_cross_change", change > 0, f"涨跌幅 {change:.2f}%"),
        ("golden_cross_volume", volume_ratio >= 1.2, f"量比 {volume_ratio:.2f}"),
    )


def _volume_price_surge(current, previous, history, context):
    change, volume_ratio, amount_ratio, close_position = _nums(
        current, "change_pct", "volume_ratio", "amount_ratio", "close_position"
    )
    if None in (change, volume_ratio, amount_ratio, close_position):
        return _missing("volume_price_surge_inputs")
    matched = 3.0 <= change < 9.5 and volume_ratio >= 1.8 and amount_ratio >= 1.5 and close_position >= 0.70
    score = min(100.0, 35 + change * 4 + min(volume_ratio * 12, 25) + min(amount_ratio * 8, 15) + close_position * 15)
    return matched, score, _reasons(
        ("surge_change", 3.0 <= change < 9.5, f"涨跌幅 {change:.2f}%"),
        ("surge_volume", volume_ratio >= 1.8, f"量比 {volume_ratio:.2f}"),
        ("surge_amount", amount_ratio >= 1.5, f"额比 {amount_ratio:.2f}"),
        ("surge_close_position", close_position >= 0.70, f"收盘位置 {close_position:.2f}"),
    )


def _high_turnover_surge(current, previous, history, context):
    change, turnover, close_position, main_inflow, main_ratio = _nums(
        current, "change_pct", "turnover_rate", "close_position", "main_net_inflow", "main_net_ratio"
    )
    if None in (change, turnover, close_position, main_inflow, main_ratio):
        return _missing("high_turnover_surge_inputs")
    matched = 3.0 <= change < 9.5 and turnover >= 8.0 and main_inflow > 0 and main_ratio > 0 and close_position >= 0.65
    score = min(100.0, 30 + change * 3 + min(turnover * 2.5, 25) + min(main_ratio * 3, 20) + close_position * 15)
    return matched, score, _reasons(
        ("turnover_change", 3.0 <= change < 9.5, f"涨跌幅 {change:.2f}%"),
        ("turnover_rate", turnover >= 8.0, f"换手率 {turnover:.2f}%"),
        ("turnover_main_flow", main_inflow > 0 and main_ratio > 0, f"主力净流入 {main_inflow:.0f}，占比 {main_ratio:.2f}%"),
        ("turnover_close_position", close_position >= 0.65, f"收盘位置 {close_position:.2f}"),
    )


def _low_volatility_leader(current, previous, history, context):
    close, ma20, volatility, volume_ratio, close_position, change = _nums(
        current, "close_price", "ma20", "volatility_20d", "volume_ratio", "close_position", "change_pct"
    )
    if None in (close, ma20, volatility, volume_ratio, close_position, change):
        return _missing("low_volatility_leader_inputs")
    matched = close > ma20 and volatility <= 2.5 and change >= 2.0 and volume_ratio >= 1.3 and close_position >= 0.65
    score = min(100.0, 45 + _pct_gap(close, ma20) * 4 + max(0, 20 - volatility * 6) + min(volume_ratio * 8, 15) + min(change * 2, 12))
    return matched, score, _reasons(
        ("low_vol_trend", close > ma20, f"收盘 {close:.2f} / MA20 {ma20:.2f}"),
        ("low_volatility", volatility <= 2.5, f"20 日波动率 {volatility:.2f}%"),
        ("low_vol_change", change >= 2.0, f"涨跌幅 {change:.2f}%"),
        ("low_vol_volume", volume_ratio >= 1.3, f"量比 {volume_ratio:.2f}"),
    )


def _pullback_ma20_bounce(current, previous, history, context):
    low, close, open_price, ma5, ma10, ma20, volume_ratio, close_position = _nums(
        current, "low_price", "close_price", "open_price", "ma5", "ma10", "ma20", "volume_ratio", "close_position"
    )
    if None in (low, close, open_price, ma5, ma10, ma20, volume_ratio, close_position):
        return _missing("pullback_ma20_bounce_inputs")
    touched = low <= ma20 * 1.01
    recovered = close >= ma20 and close > open_price
    trend_intact = ma5 >= ma10 >= ma20
    matched = touched and recovered and trend_intact and volume_ratio >= 1.0 and close_position >= 0.60
    score = min(100.0, 45 + (10 if touched else 0) + (15 if recovered else 0) + min(volume_ratio * 8, 15) + close_position * 15)
    return matched, score, _reasons(
        ("ma20_touch", touched, f"最低 {low:.2f} / MA20 {ma20:.2f}"),
        ("ma20_recovery", recovered, f"收盘 {close:.2f} / 开盘 {open_price:.2f}"),
        ("ma20_trend", trend_intact, "MA5 ≥ MA10 ≥ MA20"),
        ("ma20_volume", volume_ratio >= 1.0, f"量比 {volume_ratio:.2f}"),
    )


def _n_day_low_reversal(current, previous, history, context):
    prior_low = _min_num(history[:-1][-20:], "low_price")
    low, close, open_price, change, close_position, volume_ratio = _nums(
        current, "low_price", "close_price", "open_price", "change_pct", "close_position", "volume_ratio"
    )
    if None in (prior_low, low, close, open_price, change, close_position, volume_ratio):
        return _missing("n_day_low_reversal_inputs")
    touched = low <= prior_low * 1.02
    reversal = close > open_price and change >= 2.0 and close_position >= 0.70
    matched = touched and reversal and volume_ratio >= 1.2
    score = min(100.0, 40 + (15 if touched else 0) + min(change * 4, 25) + min(volume_ratio * 10, 15) + close_position * 12)
    return matched, score, _reasons(
        ("low_reversal_touch", touched, f"最低 {low:.2f} / 前 20 日低点 {prior_low:.2f}"),
        ("low_reversal_price", reversal, f"开收 {open_price:.2f}/{close:.2f}，涨跌幅 {change:.2f}%"),
        ("low_reversal_volume", volume_ratio >= 1.2, f"量比 {volume_ratio:.2f}"),
    )


def _theme_first_board_relay(current, previous, history, context):
    event = context.get("limit_event") or {}
    evidence = context.get("limit_evidence") or {}
    concepts = list(context.get("concept_context") or [])
    is_limit_up = str(event.get("event_type") or "") == "limit_up"
    board_count = _int(evidence.get("board_count"))
    open_count = _int(event.get("open_count"))
    best_rank = _best_heat_rank(concepts)
    natural = is_limit_up and (open_count is None or open_count > 0)
    matched = natural and board_count == 1 and best_rank is not None and best_rank <= 20
    score = min(100.0, 55 + (20 if natural else 0) + max(0, 20 - (best_rank or 99)) + (5 if board_count == 1 else 0))
    return matched, score, _reasons(
        ("first_board_limit_up", is_limit_up, "当日涨停事实"),
        ("first_board_natural", natural, f"开板次数 {open_count if open_count is not None else '缺失'}"),
        ("first_board_count", board_count == 1, f"连板高度 {board_count if board_count is not None else '缺失'}"),
        ("first_board_theme", best_rank is not None and best_rank <= 20, f"最佳概念热度排名 {best_rank if best_rank is not None else '缺失'}"),
    )


def _consecutive_limit_up_relay(current, previous, history, context):
    event = context.get("limit_event") or {}
    evidence = context.get("limit_evidence") or {}
    concepts = list(context.get("concept_context") or [])
    is_limit_up = str(event.get("event_type") or "") == "limit_up"
    board_count = _int(evidence.get("board_count"))
    open_count = _int(event.get("open_count"))
    best_rank = _best_heat_rank(concepts)
    natural = is_limit_up and (open_count is None or open_count > 0)
    matched = natural and board_count is not None and 2 <= board_count <= 4 and best_rank is not None and best_rank <= 10
    score = min(100.0, 50 + (board_count or 0) * 8 + max(0, 18 - (best_rank or 99)) + (12 if natural else 0))
    return matched, score, _reasons(
        ("relay_limit_up", is_limit_up, "当日涨停事实"),
        ("relay_natural", natural, f"开板次数 {open_count if open_count is not None else '缺失'}"),
        ("relay_board_count", board_count is not None and 2 <= board_count <= 4, f"连板高度 {board_count if board_count is not None else '缺失'}"),
        ("relay_theme", best_rank is not None and best_rank <= 10, f"最佳概念热度排名 {best_rank if best_rank is not None else '缺失'}"),
    )


def _broken_board_recovery(current, previous, history, context):
    event = context.get("limit_event") or {}
    close_position, volume_ratio, change = _nums(current, "close_position", "volume_ratio", "change_pct")
    is_break = str(event.get("event_type") or "") == "limit_break"
    if None in (close_position, volume_ratio, change):
        return _missing("broken_board_recovery_inputs")
    matched = is_break and change >= 3.0 and close_position >= 0.72 and volume_ratio >= 1.5
    score = min(100.0, 35 + (25 if is_break else 0) + min(change * 3, 20) + min(volume_ratio * 8, 12) + close_position * 12)
    return matched, score, _reasons(
        ("broken_board_event", is_break, "当日炸板事实"),
        ("broken_board_change", change >= 3.0, f"涨跌幅 {change:.2f}%"),
        ("broken_board_close", close_position >= 0.72, f"收盘位置 {close_position:.2f}"),
        ("broken_board_volume", volume_ratio >= 1.5, f"量比 {volume_ratio:.2f}"),
    )


_MATCHERS: dict[str, Callable[[dict, dict, list[dict], dict], tuple[bool, float | None, list[dict[str, Any]]]]] = {
    "trend_breakout": _trend_breakout,
    "bullish_alignment": _bullish_alignment,
    "ma_golden_cross": _ma_golden_cross,
    "volume_price_surge": _volume_price_surge,
    "high_turnover_surge": _high_turnover_surge,
    "low_volatility_leader": _low_volatility_leader,
    "pullback_ma20_bounce": _pullback_ma20_bounce,
    "n_day_low_reversal": _n_day_low_reversal,
    "theme_first_board_relay": _theme_first_board_relay,
    "consecutive_limit_up_relay": _consecutive_limit_up_relay,
    "broken_board_recovery": _broken_board_recovery,
}


def _check_universe(context: dict[str, Any], current: dict[str, Any], rule: dict[str, Any]) -> str | None:
    universe = rule.get("universe") or {}
    stock = context.get("stock") or {}
    exchange = str(stock.get("exchange") or "").upper()
    if exchange not in set(universe.get("markets") or []):
        return "unsupported_exchange"
    if bool(universe.get("exclude_st", True)) and bool(stock.get("is_st")):
        return "st_excluded"
    if bool(universe.get("exclude_bj", True)) and (exchange in {"BJ", "BSE"} or str(context.get("stock_code") or "").endswith(".BJ")):
        return "bj_excluded"
    if str(stock.get("status") or "") != "active":
        return "inactive_stock"
    history_days = _int(current.get("history_days")) or len(context.get("history") or [])
    if history_days < int(universe.get("minimum_listing_trade_days") or 60):
        return "listing_history_insufficient"
    amount = _num(current, "amount_yuan")
    if amount is None:
        return "amount_unavailable"
    if amount < float(universe.get("minimum_amount_yuan") or 0):
        return "liquidity_insufficient"
    return None


def _check_market_gate(emotion: dict[str, Any], rule: dict[str, Any]) -> str | None:
    gate = rule.get("market_gate") or {}
    if not bool(gate.get("enabled", True)):
        return None
    status = str(emotion.get("status") or "")
    if status != "ready":
        return None if bool(gate.get("allow_when_emotion_unavailable", True)) else "market_emotion_unavailable"
    stage = str(emotion.get("primary_stage_code") or "")
    if stage in set(gate.get("blocked_primary_stages") or []):
        return f"market_stage_blocked:{stage}"
    score = _num(emotion, "market_risk_on_score")
    minimum = _num(gate, "minimum_market_risk_on_score")
    if score is not None and minimum is not None and score < minimum:
        return "market_risk_on_below_threshold"
    return None


def _candidate_snapshot(context: dict[str, Any], spec: BuiltinStrategySpec, rule: dict, risk: dict, reasons: list[dict]) -> dict[str, Any]:
    current = context.get("current") or {}
    return {
        "implementation_code": spec.implementation_code,
        "implementation_version": BUILTIN_STRATEGY_IMPLEMENTATION_VERSION,
        "trade_date": str(context.get("trade_date") or ""),
        "stock": {
            "stock_code": context.get("stock_code"),
            "stock_name": (context.get("stock") or {}).get("stock_name"),
            "exchange": (context.get("stock") or {}).get("exchange"),
            "is_st": bool((context.get("stock") or {}).get("is_st")),
        },
        "daily_facts": {
            key: current.get(key)
            for key in (
                "open_price", "high_price", "low_price", "close_price", "pre_close_price", "change_pct", "amount_yuan",
                "ma5", "ma10", "ma20", "ma30", "ma60", "volume_ratio", "amount_ratio", "volatility_20d",
                "close_position", "turnover_rate", "main_net_inflow", "main_net_ratio", "history_days",
            )
        },
        "limit_event": context.get("limit_event") or {},
        "limit_evidence": context.get("limit_evidence") or {},
        "concept_context": context.get("concept_context") or [],
        "emotion": context.get("emotion") or {},
        "rule_config": rule,
        "risk_config": risk,
        "reasons": reasons,
    }


def _entry_plan(spec: BuiltinStrategySpec, rule: dict, risk: dict) -> dict[str, Any]:
    return {
        "entry_mode": spec.entry_mode,
        "confirmation": rule.get("entry_confirmation") or {},
        "risk_plan": risk,
        "t_plus_one": True,
        "disclaimer": "仅在下一交易日满足确认规则后记录模拟成交；未触发不计为交易失败。",
    }


def _default_entry_confirmation(entry_mode: str) -> dict[str, Any]:
    if entry_mode == "auction":
        return {
            "window": "09:20-09:25",
            "minimum_depth_snapshots": 3,
            "gap_pct_range": [-1.0, 4.0],
            "require_executable_ask": True,
            "reject_near_limit_up_queue": True,
        }
    if entry_mode == "open":
        return {
            "window": "09:30-09:35",
            "gap_pct_range": [-2.0, 4.0],
            "minimum_quote_freshness_seconds": 15,
            "require_executable_ask": True,
        }
    return {
        "window": "09:35-14:50",
        "minimum_quote_freshness_seconds": 15,
        "minimum_minute_bars": 5,
        "require_executable_ask": True,
        "avoid_near_limit_up_queue": True,
    }


def _skip(code: str, context: dict[str, Any], implementation_code: str, rule: dict | None = None, risk: dict | None = None) -> EvaluationResult:
    return EvaluationResult(
        matched=False,
        score=None,
        reasons=[{"code": code, "passed": False, "detail": code}],
        candidate_snapshot={},
        entry_plan={},
        skip_code=code,
    )


def _missing(code: str) -> tuple[bool, float | None, list[dict[str, Any]]]:
    return False, None, [{"code": code, "passed": False, "detail": "所需日频事实缺失，拒绝以默认值代替。"}]


def _reasons(*items: tuple[str, bool, str]) -> list[dict[str, Any]]:
    return [{"code": code, "passed": bool(passed), "detail": detail} for code, passed, detail in items]


def _num(values: dict[str, Any], key: str) -> float | None:
    value = values.get(key)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _nums(values: dict[str, Any], *keys: str) -> tuple[float | None, ...]:
    return tuple(_num(values, key) for key in keys)


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _max_num(rows: list[dict], key: str) -> float | None:
    values = [value for row in rows if (value := _num(row, key)) is not None]
    return max(values) if values else None


def _min_num(rows: list[dict], key: str) -> float | None:
    values = [value for row in rows if (value := _num(row, key)) is not None]
    return min(values) if values else None


def _pct_gap(left: float, right: float) -> float:
    return ((left / right) - 1) * 100 if right else 0.0


def _best_heat_rank(concepts: list[dict[str, Any]]) -> int | None:
    ranks = [_int(item.get("heat_rank")) for item in concepts]
    values = [item for item in ranks if item is not None]
    return min(values) if values else None


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
