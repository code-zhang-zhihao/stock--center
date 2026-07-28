from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.modules.strategy_center.realtime_service import _entry_trigger, _exit_trigger, _window_state


SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_auction_entry_rejects_near_limit_up_queue_when_limit_is_verifiable():
    trigger = _entry_trigger(
        {"pre_close_price": 10, "metadata": {"ext": {"limit_up": 11}}},
        {"asks": [{"price": 11.0, "volume": 1000}]},
        {"gap_pct_range": [-1, 12], "reject_near_limit_up_queue": True},
    )
    assert trigger["triggered"] is False
    assert trigger["terminal"] is True
    assert trigger["reason"] == "near_limit_up_queue"


def test_entry_window_is_explicit_not_inferred_from_system_clock():
    confirmation = {"window": "09:20-09:25"}
    assert _window_state(datetime(2026, 7, 1, 9, 19, tzinfo=SHANGHAI), confirmation) == "before"
    assert _window_state(datetime(2026, 7, 1, 9, 22, tzinfo=SHANGHAI), confirmation) == "active"
    assert _window_state(datetime(2026, 7, 1, 9, 26, tzinfo=SHANGHAI), confirmation) == "after"


def test_trailing_stop_requires_a_real_peak_gain_then_drawdown():
    risk = {"hard_stop_loss_pct": -4, "trailing_stop": {"activate_return_pct": 6, "drawdown_pct": 3}}
    assert _exit_trigger(return_pct=1, entry_price=10, last_price=10.1, peak_price=10.2, risk=risk, holding_trade_days=1) is None
    assert _exit_trigger(return_pct=3, entry_price=10, last_price=10.3, peak_price=10.8, risk=risk, holding_trade_days=1) == "trailing_stop"
