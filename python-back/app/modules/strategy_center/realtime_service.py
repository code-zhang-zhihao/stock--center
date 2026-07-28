"""T+1 paper confirmation and exit execution over the shared realtime cache.

No provider is called here.  The realtime market runtime passes its most
recent TickFlow Quote/depth and MooTDX minute cache to this service after the
normal polling blocks complete.  This preserves the purchased rate budget and
creates one audit event only when a candidate/trade state changes.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from app.db.session import get_sessionmaker
from app.modules.strategy_center.models import StrategyCandidate, StrategyDefinition, StrategyPaperTrade, StrategyVersion
from app.modules.strategy_center.repository import StrategyCenterRepository


SHANGHAI = ZoneInfo("Asia/Shanghai")


class StrategyRealtimeService:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._last_summary: dict[str, Any] = {
            "as_of": None,
            "candidate_count": 0,
            "open_trade_count": 0,
            "triggered_count": 0,
            "exit_count": 0,
            "skipped_count": 0,
            "degraded_count": 0,
        }

    @property
    def last_summary(self) -> dict[str, Any]:
        return dict(self._last_summary)

    async def process(
        self,
        *,
        now: datetime,
        quotes: dict[str, dict],
        depths: dict[str, dict],
        depth_history: dict[str, list[dict]],
        minutes: dict[str, list[dict]],
        block_status: dict[str, dict],
    ) -> dict:
        """Evaluate only existing paper candidates/open paper trades.

        A missing/stale cache produces a ``degraded`` audit outcome during the
        relevant confirmation window; it never falls back to a fresh provider
        call and never fabricates a fill from the last price.
        """

        local_now = now.astimezone(SHANGHAI)
        if not _in_trade_hours(local_now):
            return self.last_summary
        async with self._lock:
            summary = {
                "as_of": local_now.isoformat(),
                "candidate_count": 0,
                "open_trade_count": 0,
                "triggered_count": 0,
                "exit_count": 0,
                "skipped_count": 0,
                "degraded_count": 0,
            }
            sessionmaker = get_sessionmaker()
            async with sessionmaker() as session:
                repository = StrategyCenterRepository(session)
                candidates = await repository.list_runtime_candidates(trade_date=local_now.date())
                summary["candidate_count"] = len(candidates)
                for item in candidates:
                    outcome = await self._process_candidate(
                        repository=repository,
                        now=local_now,
                        quote=quotes.get(item["candidate"].stock_code),
                        depth=depths.get(item["candidate"].stock_code),
                        depth_history=depth_history.get(item["candidate"].stock_code, []),
                        minute_bars=minutes.get(item["candidate"].stock_code, []),
                        blocks=block_status,
                        **item,
                    )
                    if outcome in summary:
                        summary[outcome] += 1
                open_trades = await repository.list_open_paper_trades()
                summary["open_trade_count"] = len(open_trades)
                for item in open_trades:
                    outcome = await self._process_open_trade(
                        repository=repository,
                        now=local_now,
                        quote=quotes.get(item["paper_trade"].stock_code),
                        depth=depths.get(item["paper_trade"].stock_code),
                        **item,
                    )
                    if outcome == "exit":
                        summary["exit_count"] += 1
                    elif outcome == "degraded":
                        summary["degraded_count"] += 1
                await repository.commit()
            self._last_summary = summary
            return dict(summary)

    async def _process_candidate(
        self,
        *,
        repository: StrategyCenterRepository,
        candidate: StrategyCandidate,
        definition: StrategyDefinition,
        version: StrategyVersion,
        now: datetime,
        quote: dict | None,
        depth: dict | None,
        depth_history: list[dict],
        minute_bars: list[dict],
        blocks: dict[str, dict],
    ) -> str | None:
        confirmation = dict((candidate.entry_plan or {}).get("confirmation") or {})
        state = _window_state(now, confirmation)
        if state == "before":
            return None
        if state == "after":
            await self._not_triggered(
                repository, candidate, definition, version, now, "confirmation_window_closed", "确认窗口结束前没有形成可执行买点。"
            )
            return "skipped"
        phase = _phase_for_entry_mode(definition.entry_mode)
        readiness = _confirmation_readiness(
            entry_mode=definition.entry_mode,
            now=now,
            quote=quote,
            depth=depth,
            depth_history=depth_history,
            minute_bars=minute_bars,
            blocks=blocks,
            confirmation=confirmation,
        )
        if not readiness["ready"]:
            # Only record once per reason/window.  The fingerprinted event is
            # idempotent, so subsequent 5/10-second polls do not grow audit
            # storage while the service waits for a healthy snapshot.
            await repository.record_signal_event(
                strategy_id=definition.id,
                strategy_version_id=version.id,
                candidate_id=candidate.id,
                stock_code=candidate.stock_code,
                trade_date=now.date(),
                market_phase=phase,
                event_type="entry_data_degraded",
                decision="degraded",
                reason_code=readiness["reason"],
                evidence=readiness,
                event_time=now,
            )
            return "degraded"
        trigger = _entry_trigger(quote or {}, depth or {}, confirmation)
        if not trigger["triggered"]:
            if trigger["terminal"]:
                await self._not_triggered(
                    repository, candidate, definition, version, now, trigger["reason"], trigger["detail"], evidence=trigger
                )
                return "skipped"
            if candidate.candidate_status == "pending_confirmation":
                await repository.mark_candidate_status(candidate, status="watching", outcome_note="确认窗口内，等待满足买点。")
            return None
        risk_plan = dict((candidate.entry_plan or {}).get("risk_plan") or version.risk_config or {})
        quantity = _lot_quantity(risk_plan.get("initial_quantity"))
        entry_price = float(trigger["execution_price"])
        evidence = {
            "phase": phase,
            "quote": _compact_quote(quote or {}),
            "depth": _compact_depth(depth or {}),
            "depth_history_count": len(depth_history),
            "trigger": trigger,
            "candidate_snapshot": candidate.candidate_snapshot or {},
        }
        try:
            trade = await repository.create_paper_trade_with_entry(
                candidate=candidate,
                definition=definition,
                entry_at=now,
                entry_price=entry_price,
                quantity=quantity,
                evidence=evidence,
                risk_plan=risk_plan,
            )
        except Exception as exc:
            # Candidate's unique paper-trade constraint protects against a
            # double fill if a process restarts precisely at a trigger.  Do
            # not change candidate state on an ambiguous insert failure.
            await repository.record_signal_event(
                strategy_id=definition.id,
                strategy_version_id=version.id,
                candidate_id=candidate.id,
                stock_code=candidate.stock_code,
                trade_date=now.date(),
                market_phase=phase,
                event_type="entry_write_failed",
                decision="degraded",
                reason_code=type(exc).__name__,
                evidence={"message": str(exc)[:500]},
                event_time=now,
            )
            return "degraded"
        await repository.mark_candidate_status(
            candidate,
            status="entry_triggered",
            outcome_note="已满足确认条件，已生成模拟买入。",
            confirmed_at=now,
        )
        await repository.record_signal_event(
            strategy_id=definition.id,
            strategy_version_id=version.id,
            candidate_id=candidate.id,
            paper_trade_id=trade.id,
            stock_code=candidate.stock_code,
            trade_date=now.date(),
            market_phase=phase,
            event_type="paper_entry_executed",
            decision="executed",
            reason_code="entry_confirmation_matched",
            evidence=evidence,
            event_time=now,
        )
        return "triggered"

    async def _not_triggered(
        self,
        repository: StrategyCenterRepository,
        candidate: StrategyCandidate,
        definition: StrategyDefinition,
        version: StrategyVersion,
        now: datetime,
        reason: str,
        detail: str,
        *,
        evidence: dict | None = None,
    ) -> None:
        await repository.mark_candidate_status(candidate, status="not_triggered", outcome_note=detail)
        await repository.record_signal_event(
            strategy_id=definition.id,
            strategy_version_id=version.id,
            candidate_id=candidate.id,
            stock_code=candidate.stock_code,
            trade_date=now.date(),
            market_phase=_phase_for_entry_mode(definition.entry_mode),
            event_type="entry_not_triggered",
            decision="skipped",
            reason_code=reason,
            evidence=evidence or {"detail": detail},
            event_time=now,
        )

    async def _process_open_trade(
        self,
        *,
        repository: StrategyCenterRepository,
        paper_trade: StrategyPaperTrade,
        candidate: StrategyCandidate,
        definition: StrategyDefinition,
        version: StrategyVersion,
        now: datetime,
        quote: dict | None,
        depth: dict | None,
    ) -> str | None:
        # A-share T+1: an entry today cannot be closed today, even if a stop
        # appears in the polling cache after the simulated buy.
        if paper_trade.entry_at.astimezone(SHANGHAI).date() >= now.date():
            return None
        if not _quote_depth_fresh(quote, depth, now):
            return "degraded"
        execution_price = _best_bid(depth or {})
        last_price = _number((quote or {}).get("last_price"))
        if execution_price is None or last_price is None:
            return "degraded"
        risk = dict(paper_trade.risk_plan or {})
        runtime_state = dict(risk.get("runtime_state") or {})
        peak = max(float(runtime_state.get("peak_price") or paper_trade.entry_price), last_price)
        runtime_state["peak_price"] = peak
        risk["runtime_state"] = runtime_state
        paper_trade.risk_plan = risk
        return_pct = (last_price / float(paper_trade.entry_price) - 1) * 100
        trigger = _exit_trigger(
            return_pct=return_pct,
            entry_price=float(paper_trade.entry_price),
            last_price=last_price,
            peak_price=peak,
            risk=risk,
            holding_trade_days=await repository.count_open_trade_days(
                start_date=paper_trade.entry_at.astimezone(SHANGHAI).date(), end_date=now.date()
            ),
        )
        if trigger is None:
            return None
        quantity = _exit_quantity(paper_trade.open_quantity, trigger, risk)
        paper_trade.risk_plan = risk
        if quantity <= 0:
            return None
        evidence = {
            "quote": _compact_quote(quote or {}),
            "depth": _compact_depth(depth or {}),
            "return_pct_at_trigger": round(return_pct, 6),
            "peak_price": peak,
            "trigger_code": trigger,
        }
        updated = await repository.append_paper_sell_leg(
            trade=paper_trade,
            execution_at=now,
            price=execution_price,
            quantity=quantity,
            trigger_code=trigger,
            evidence=evidence,
        )
        await repository.record_signal_event(
            strategy_id=definition.id,
            strategy_version_id=version.id,
            candidate_id=candidate.id,
            paper_trade_id=updated.id,
            stock_code=updated.stock_code,
            trade_date=now.date(),
            market_phase="exit",
            event_type="paper_exit_executed",
            decision="executed",
            reason_code=trigger,
            evidence={**evidence, "sell_quantity": quantity, "remaining_quantity": updated.open_quantity},
            event_time=now,
        )
        return "exit"


def _in_trade_hours(now: datetime) -> bool:
    current = now.timetz().replace(tzinfo=None)
    return time(9, 20) <= current <= time(11, 30) or time(13, 0) <= current <= time(15, 0)


def _window_state(now: datetime, confirmation: dict) -> str:
    try:
        start_raw, end_raw = str(confirmation.get("window") or "").split("-", maxsplit=1)
        start = time.fromisoformat(start_raw)
        end = time.fromisoformat(end_raw)
    except ValueError:
        return "after"
    current = now.timetz().replace(tzinfo=None)
    if current < start:
        return "before"
    if current > end:
        return "after"
    return "active"


def _phase_for_entry_mode(entry_mode: str) -> str:
    return {"auction": "auction", "open": "open", "intraday": "intraday"}.get(entry_mode, "system")


def _confirmation_readiness(
    *,
    entry_mode: str,
    now: datetime,
    quote: dict | None,
    depth: dict | None,
    depth_history: list[dict],
    minute_bars: list[dict],
    blocks: dict[str, dict],
    confirmation: dict,
) -> dict:
    if not _quote_is_fresh(quote, now, int(confirmation.get("minimum_quote_freshness_seconds") or 15)):
        return {"ready": False, "reason": "quote_stale_or_missing"}
    if not _depth_is_fresh(depth, now, 20):
        return {"ready": False, "reason": "depth_stale_or_missing"}
    if bool((blocks.get("depth") or {}).get("degraded")):
        return {"ready": False, "reason": "depth_block_degraded"}
    if not _best_ask(depth or {}):
        return {"ready": False, "reason": "executable_ask_missing"}
    if entry_mode == "auction":
        required = int(confirmation.get("minimum_depth_snapshots") or 3)
        if len(depth_history) < required:
            return {"ready": False, "reason": "auction_depth_history_insufficient", "required": required, "received": len(depth_history)}
    if entry_mode == "intraday":
        required = int(confirmation.get("minimum_minute_bars") or 5)
        if len(minute_bars) < required:
            return {"ready": False, "reason": "minute_history_insufficient", "required": required, "received": len(minute_bars)}
        if bool((blocks.get("minute") or {}).get("degraded")):
            return {"ready": False, "reason": "minute_block_degraded"}
    return {"ready": True}


def _entry_trigger(quote: dict, depth: dict, confirmation: dict) -> dict:
    ask = _best_ask(depth)
    pre_close = _number(quote.get("pre_close_price"))
    if ask is None or pre_close is None or pre_close <= 0:
        return {"triggered": False, "terminal": False, "reason": "entry_price_unavailable", "detail": "缺少可执行卖一或昨收。"}
    execution_price = ask
    gap_pct = (execution_price / pre_close - 1) * 100
    lower, upper = _gap_range(confirmation)
    if gap_pct < lower:
        return {"triggered": False, "terminal": False, "reason": "gap_below_range", "detail": f"拟成交涨幅 {gap_pct:.2f}% 低于确认下限。", "gap_pct": gap_pct}
    if gap_pct > upper:
        return {"triggered": False, "terminal": True, "reason": "gap_above_range", "detail": f"拟成交涨幅 {gap_pct:.2f}% 超出确认上限。", "gap_pct": gap_pct}
    metadata = quote.get("metadata") if isinstance(quote.get("metadata"), dict) else {}
    ext = metadata.get("ext") if isinstance(metadata.get("ext"), dict) else {}
    limit_up = _number(ext.get("limit_up"))
    if bool(confirmation.get("reject_near_limit_up_queue") or confirmation.get("avoid_near_limit_up_queue")) and limit_up is not None and execution_price >= limit_up * 0.9998:
        return {"triggered": False, "terminal": True, "reason": "near_limit_up_queue", "detail": "卖一接近涨停价，按不可执行追板队列处理。", "gap_pct": gap_pct}
    return {"triggered": True, "terminal": False, "reason": "entry_confirmation_matched", "detail": "报价、五档和窗口条件满足。", "execution_price": execution_price, "gap_pct": gap_pct}


def _exit_trigger(
    *,
    return_pct: float,
    entry_price: float,
    last_price: float,
    peak_price: float,
    risk: dict,
    holding_trade_days: int,
) -> str | None:
    if return_pct <= float(risk.get("hard_stop_loss_pct") or -4.0):
        return "hard_stop"
    trailing = risk.get("trailing_stop") or {}
    activate = float(trailing.get("activate_return_pct") or 6.0)
    drawdown = float(trailing.get("drawdown_pct") or 3.0)
    peak_return = (peak_price / max(0.000001, entry_price) - 1) * 100
    pullback = (peak_price - last_price) / max(0.000001, peak_price) * 100
    if peak_return >= activate and pullback >= drawdown:
        return "trailing_stop"
    legs = list(risk.get("take_profit_legs") or [])
    next_leg = int((risk.get("runtime_state") or {}).get("take_profit_leg_index") or 0)
    if 0 <= next_leg < len(legs):
        try:
            threshold = float(legs[next_leg].get("trigger_return_pct"))
            if return_pct >= threshold:
                return f"take_profit_{next_leg + 1}"
        except (TypeError, ValueError, AttributeError):
            pass
    if bool((risk.get("time_exit") or {}).get("enabled", True)):
        max_days = int((risk.get("time_exit") or {}).get("trade_days") or risk.get("max_holding_trade_days") or 3)
        if holding_trade_days >= max_days:
            return "time_exit"
    return None


def _exit_quantity(open_quantity: int, trigger: str, risk: dict) -> int:
    if trigger.startswith("take_profit_"):
        try:
            index = int(trigger.rsplit("_", 1)[-1]) - 1
            ratio = float((risk.get("take_profit_legs") or [])[index].get("sell_ratio"))
        except (TypeError, ValueError, IndexError, AttributeError):
            ratio = 1.0
        quantity = int(open_quantity * min(max(ratio, 0), 1.0) // 100 * 100)
        quantity = quantity or open_quantity
        runtime_state = dict(risk.get("runtime_state") or {})
        runtime_state["take_profit_leg_index"] = index + 1
        risk["runtime_state"] = runtime_state
        return min(open_quantity, quantity)
    return open_quantity


def _lot_quantity(value: Any) -> int:
    try:
        quantity = max(100, int(value))
    except (TypeError, ValueError):
        quantity = 1000
    return max(100, quantity // 100 * 100)


def _gap_range(confirmation: dict) -> tuple[float, float]:
    raw = list(confirmation.get("gap_pct_range") or [-2, 4])
    try:
        return float(raw[0]), float(raw[1])
    except (TypeError, ValueError, IndexError):
        return -2.0, 4.0


def _quote_depth_fresh(quote: dict | None, depth: dict | None, now: datetime) -> bool:
    return _quote_is_fresh(quote, now, 20) and _depth_is_fresh(depth, now, 20) and _best_bid(depth or {}) is not None


def _quote_is_fresh(quote: dict | None, now: datetime, max_age_seconds: int) -> bool:
    return _timestamp_fresh((quote or {}).get("quote_time"), now, max_age_seconds)


def _depth_is_fresh(depth: dict | None, now: datetime, max_age_seconds: int) -> bool:
    return _timestamp_fresh((depth or {}).get("depth_time"), now, max_age_seconds)


def _timestamp_fresh(value: Any, now: datetime, max_age_seconds: int) -> bool:
    if not value:
        return False
    try:
        timestamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=ZoneInfo("UTC"))
        return abs((now.astimezone(ZoneInfo("UTC")) - timestamp.astimezone(ZoneInfo("UTC"))).total_seconds()) <= max_age_seconds
    except (TypeError, ValueError):
        return False


def _best_ask(depth: dict) -> float | None:
    asks = depth.get("asks") if isinstance(depth.get("asks"), list) else []
    return _number((asks[0] if asks else {}).get("price"))


def _best_bid(depth: dict) -> float | None:
    bids = depth.get("bids") if isinstance(depth.get("bids"), list) else []
    return _number((bids[0] if bids else {}).get("price"))


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _compact_quote(quote: dict) -> dict:
    return {key: quote.get(key) for key in ("stock_code", "quote_time", "last_price", "pre_close_price", "change_pct", "open_price", "high_price", "low_price", "amount_yuan")}


def _compact_depth(depth: dict) -> dict:
    return {
        "stock_code": depth.get("stock_code"),
        "depth_time": depth.get("depth_time"),
        "bids": list(depth.get("bids") or [])[:5],
        "asks": list(depth.get("asks") or [])[:5],
        "features": depth.get("features") or {},
    }
