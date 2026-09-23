"""Deterministic A-share price-limit calculations for live quotes.

The calculation follows the exchange formula ``previous close * (1 +/- ratio)``.
Prices are rounded to the A-share tick with ``ROUND_HALF_UP`` and low-priced
securities must move by at least one tick. This module only derives a limit
from known security reference data; it never substitutes a percentage
threshold for an unknown board or a no-limit listing period.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


PRICE_TICK = Decimal("0.01")
RULE_VERSION = "cn_equity_limit_v1_2025_06"


@dataclass(frozen=True)
class AShareLimitPriceService:
    """Derive A-share limit prices and quote change metrics from known inputs.

    The caller owns security master data and determines whether the quote is
    in the IPO's first five open trading days. Keeping the calendar decision
    outside this pure service makes the calculation deterministic and easy to
    use for both live and historical quote flows.
    """

    price_tick: Decimal = PRICE_TICK

    def calculate(
        self,
        *,
        stock_code: str | None,
        exchange: str | None,
        pre_close_price: object,
        last_price: object,
        is_new_listing_first_five_open_days: bool | None,
    ) -> dict[str, Any]:
        board, limit_ratio = self._board_rule(stock_code=stock_code, exchange=exchange)
        change_amount, change_pct = self._change_metrics(last_price=last_price, pre_close_price=pre_close_price)
        result: dict[str, Any] = {
            "source": "derived_a_share_rule",
            "rule_version": RULE_VERSION,
            "available": False,
            "reason": None,
            "board": board,
            "limit_ratio_pct": float(limit_ratio * 100) if limit_ratio is not None else None,
            "price_tick": float(self.price_tick),
            "limit_up": None,
            "limit_down": None,
            "is_limit_up": None,
            "is_limit_down": None,
            "change_amount": change_amount,
            "change_pct": change_pct,
        }
        if board is None or limit_ratio is None:
            result["reason"] = "security_board_unavailable"
            return result
        if is_new_listing_first_five_open_days is None:
            result["reason"] = "listing_limit_status_unavailable"
            return result
        if is_new_listing_first_five_open_days:
            result["reason"] = "new_listing_first_five_open_days"
            return result
        previous_close = self._decimal(pre_close_price)
        if previous_close is None or previous_close <= 0:
            result["reason"] = "pre_close_price_unavailable"
            return result

        limit_up = self._limit_price(previous_close, limit_ratio, direction="up")
        limit_down = self._limit_price(previous_close, limit_ratio, direction="down")
        current_price = self._decimal(last_price)
        result.update(
            {
                "available": True,
                "limit_up": float(limit_up),
                "limit_down": float(limit_down),
                "is_limit_up": self._at_tick_price(current_price, limit_up) if current_price is not None else None,
                "is_limit_down": self._at_tick_price(current_price, limit_down) if current_price is not None else None,
            }
        )
        return result

    def _limit_price(self, previous_close: Decimal, limit_ratio: Decimal, *, direction: str) -> Decimal:
        multiplier = Decimal("1") + limit_ratio if direction == "up" else Decimal("1") - limit_ratio
        candidate = (previous_close * multiplier).quantize(self.price_tick, rounding=ROUND_HALF_UP)
        if abs(candidate - previous_close) < self.price_tick:
            candidate = previous_close + self.price_tick if direction == "up" else previous_close - self.price_tick
        return max(self.price_tick, candidate)

    def _change_metrics(self, *, last_price: object, pre_close_price: object) -> tuple[float | None, float | None]:
        current_price = self._decimal(last_price)
        previous_close = self._decimal(pre_close_price)
        if current_price is None or previous_close is None or previous_close <= 0:
            return None, None
        change_amount = current_price - previous_close
        return float(change_amount), float((change_amount / previous_close * 100).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))

    def _at_tick_price(self, price: Decimal, target: Decimal) -> bool:
        return price.quantize(self.price_tick, rounding=ROUND_HALF_UP) == target

    @staticmethod
    def _board_rule(*, stock_code: str | None, exchange: str | None) -> tuple[str | None, Decimal | None]:
        code = str(stock_code or "").strip()
        normalized_exchange = str(exchange or "").upper()
        if normalized_exchange in {"BJ", "BSE"}:
            return "bse", Decimal("0.30")
        if normalized_exchange in {"SH", "SSE"}:
            return ("star", Decimal("0.20")) if code.startswith("688") else ("main", Decimal("0.10"))
        if normalized_exchange in {"SZ", "SZSE"}:
            return ("gem", Decimal("0.20")) if code.startswith(("300", "301")) else ("main", Decimal("0.10"))
        return None, None

    @staticmethod
    def _decimal(value: object) -> Decimal | None:
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return None
