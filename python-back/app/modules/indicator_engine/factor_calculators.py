from __future__ import annotations

from datetime import date
from statistics import mean, pstdev

from app.modules.market_data.models import DailyBar, StockFundFlowDaily


class StockFundFactorCalculator:
    """Calculates stock-level fund-flow factors from canonical daily facts."""

    def cross_section_percentiles(self, flows: dict[str, StockFundFlowDaily]) -> dict[str, float]:
        values = [
            self._float(row.main_net_inflow)
            for row in flows.values()
            if row.main_net_inflow is not None
        ]
        if not values:
            return {}
        ordered = sorted(values)
        denominator = max(len(ordered), 1)
        return {
            stock_code: (sum(1 for value in ordered if value <= self._float(row.main_net_inflow)) / denominator) * 100
            for stock_code, row in flows.items()
            if row.main_net_inflow is not None
        }

    def features(
        self,
        *,
        trade_date: date,
        bars: list[DailyBar],
        flows: list[StockFundFlowDaily],
        cross_section_percentile: float | None,
    ) -> dict:
        current_flow = next((row for row in reversed(flows) if row.trade_date == trade_date), None)
        current_bar = next((row for row in reversed(bars) if row.trade_date == trade_date), None)
        if current_flow is None:
            return {"fund_flow_available": False}

        sorted_flows = sorted(flows, key=lambda item: item.trade_date)
        net_values = [self._float(row.main_net_inflow) for row in sorted_flows]
        amount_yuan = self._float(current_bar.amount_yuan) if current_bar is not None else None
        main_net = self._float(current_flow.main_net_inflow)
        big_net = self._float(current_flow.big_order_net_inflow)
        super_net = self._float(current_flow.super_large_net_inflow)
        continuous = 0
        for row in reversed(sorted_flows):
            if self._float(row.main_net_inflow) > 0:
                continuous += 1
            else:
                break
        missing_windows = []
        for window in (3, 5, 10):
            if len(net_values) < window:
                missing_windows.append(f"main_net_inflow_{window}d")
        if not amount_yuan:
            missing_windows.extend(["main_net_ratio", "big_order_net_ratio", "super_large_net_ratio"])
        return {
            "fund_flow_available": True,
            "main_net_inflow": main_net,
            "main_net_ratio": self._ratio(main_net, amount_yuan),
            "big_order_net_inflow": big_net,
            "big_order_net_ratio": self._ratio(big_net, amount_yuan),
            "super_large_net_inflow": super_net,
            "super_large_net_ratio": self._ratio(super_net, amount_yuan),
            "continuous_main_inflow_days": continuous,
            "main_net_inflow_3d": self._window_sum(net_values, 3),
            "main_net_inflow_5d": self._window_sum(net_values, 5),
            "main_net_inflow_10d": self._window_sum(net_values, 10),
            "fund_strength_percentile": cross_section_percentile,
            "fund_factor_missing_windows": missing_windows,
        }

    @staticmethod
    def _window_sum(values: list[float], window: int) -> float | None:
        return sum(values[-window:]) if values else None

    @staticmethod
    def _ratio(
        numerator: float | None,
        denominator: float | None,
    ) -> float | None:
        if numerator is None or denominator in (None, 0):
            return None
        return numerator / denominator

    @staticmethod
    def _float(value: object) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0


class SectorFactorCalculator:
    """Calculates sector factors by aggregating canonical sector and component facts."""

    def rows(self, *, trade_date: date, inputs: dict) -> list[dict]:
        sectors = inputs["sectors"]
        bars = inputs["bars"]
        flows = inputs["flows"]
        components = inputs["components"]
        daily_bars = inputs["daily_bars"]
        stock_flows = inputs["stock_flows"]
        limit_up_codes = inputs["limit_up_codes"]
        current_flow_values = [
            self._float(history[-1].main_net_inflow)
            for history in flows.values()
            if history and history[-1].trade_date == trade_date and history[-1].main_net_inflow is not None
        ]
        sector_percentiles = self._percentile_map(current_flow_values)

        rows = []
        for sector_code, sector in sectors.items():
            bar_history = bars.get(sector_code, [])
            flow_history = flows.get(sector_code, [])
            current_bar = next((row for row in reversed(bar_history) if row.trade_date == trade_date), None)
            current_flow = next((row for row in reversed(flow_history) if row.trade_date == trade_date), None)
            if current_bar is None and current_flow is None:
                continue
            component_codes = components.get(sector_code, [])
            priced_bars = [daily_bars[code] for code in component_codes if code in daily_bars]
            component_flows = [stock_flows[code] for code in component_codes if code in stock_flows]
            changes = [self._float(row.change_pct) for row in priced_bars if row.change_pct is not None]
            current_net = self._float(current_flow.main_net_inflow) if current_flow else None
            flow_values = [self._float(row.main_net_inflow) for row in flow_history]
            continuous = self._continuous_positive(flow_values)
            amount_ratio = self._volume_anomaly_ratio(bar_history, trade_date)
            net_inflow_stock_ratio = self._ratio(
                sum(1 for row in component_flows if self._float(row.main_net_inflow) > 0),
                len(component_flows),
                percent=True,
            )
            tags = self._tags(
                current_net=current_net,
                change_pct=self._float(current_bar.change_pct) if current_bar else None,
                average_change_pct=mean(changes) if changes else None,
                fund_strength=self._percentile_for(current_net, sector_percentiles),
                continuous_inflow_days=continuous,
                volume_anomaly_ratio=amount_ratio,
            )
            missing_windows = self._missing_windows(flow_history, bar_history, component_codes, priced_bars, component_flows)
            rows.append(
                {
                    "sector_code": sector_code,
                    "sector_name": sector.sector_name,
                    "sector_type": sector.sector_type,
                    "trade_date": trade_date,
                    "source": "system:daily_close",
                    "fund_strength": self._percentile_for(current_net, sector_percentiles),
                    "net_inflow_3d": self._window_sum(flow_values, 3),
                    "net_inflow_5d": self._window_sum(flow_values, 5),
                    "net_inflow_10d": self._window_sum(flow_values, 10),
                    "continuous_inflow_days": continuous,
                    "rising_stock_count": sum(1 for value in changes if value > 0),
                    "limit_up_stock_count": sum(1 for code in component_codes if code in limit_up_codes),
                    "average_change_pct": mean(changes) if changes else (self._float(current_bar.change_pct) if current_bar else None),
                    "volatility_20d": self._volatility_20d(bar_history),
                    "tags": tags,
                    "features": {
                        "main_net_inflow": current_net,
                        "net_inflow_stock_ratio": net_inflow_stock_ratio,
                        "volume_anomaly_ratio": amount_ratio,
                        "component_count": len(component_codes),
                        "priced_component_count": len(priced_bars),
                        "fund_flow_component_count": len(component_flows),
                        "missing_windows": missing_windows,
                        "source_tables": [
                            "t_sector_component",
                            "t_sector_bar",
                            "t_sector_fund_flow_daily",
                            "t_daily_bar",
                            "t_stock_fund_flow_daily",
                            "t_limit_event_daily",
                        ],
                    },
                }
            )
        return rows

    def _tags(
        self,
        *,
        current_net: float | None,
        change_pct: float | None,
        average_change_pct: float | None,
        fund_strength: float | None,
        continuous_inflow_days: int,
        volume_anomaly_ratio: float | None,
    ) -> list[str]:
        tags = []
        if volume_anomaly_ratio is not None and volume_anomaly_ratio >= 1.5 and (change_pct or 0) > 0:
            tags.append("放量异动")
        if (change_pct is not None and change_pct >= 2) or (average_change_pct is not None and average_change_pct >= 2) or (fund_strength is not None and fund_strength >= 80):
            tags.append("强度异动")
        if continuous_inflow_days >= 3:
            tags.append("持续流入")
        if current_net is not None and current_net > 0 and change_pct is not None and change_pct < 0:
            tags.append("逆势异动")
        return tags

    def _volume_anomaly_ratio(self, bars: list, trade_date: date) -> float | None:
        current = next((row for row in reversed(bars) if row.trade_date == trade_date), None)
        if current is None:
            return None
        previous_amounts = [self._float(row.amount_yuan) for row in bars if row.trade_date < trade_date and row.amount_yuan is not None]
        previous = previous_amounts[-5:]
        return self._ratio(self._float(current.amount_yuan), mean(previous)) if previous else None

    def _volatility_20d(self, bars: list) -> float | None:
        changes = [self._float(row.change_pct) for row in bars if row.change_pct is not None][-20:]
        return pstdev(changes) if len(changes) >= 2 else None

    def _missing_windows(self, flows: list, bars: list, component_codes: list[str], priced_bars: list, component_flows: list) -> list[str]:
        missing = []
        for window in (3, 5, 10):
            if len(flows) < window:
                missing.append(f"net_inflow_{window}d")
        if len(bars) < 20:
            missing.append("volatility_20d")
        if not component_codes:
            missing.append("components")
        if component_codes and not priced_bars:
            missing.append("component_daily_bars")
        if component_codes and not component_flows:
            missing.append("component_fund_flows")
        return missing

    @staticmethod
    def _continuous_positive(values: list[float]) -> int:
        count = 0
        for value in reversed(values):
            if value > 0:
                count += 1
            else:
                break
        return count

    @staticmethod
    def _window_sum(values: list[float], window: int) -> float | None:
        return sum(values[-window:]) if values else None

    def _percentile_map(self, values: list[float]) -> dict[float, float]:
        if not values:
            return {}
        ordered = sorted(values)
        return {value: (sum(1 for item in ordered if item <= value) / len(ordered)) * 100 for value in ordered}

    @staticmethod
    def _percentile_for(value: float | None, mapping: dict[float, float]) -> float | None:
        if value is None:
            return None
        return mapping.get(value)

    @staticmethod
    def _ratio(numerator: float | None, denominator: float | None, *, percent: bool = False) -> float | None:
        if numerator is None or denominator in (None, 0):
            return None
        value = numerator / denominator
        return value * 100 if percent else value

    @staticmethod
    def _float(value: object) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0
