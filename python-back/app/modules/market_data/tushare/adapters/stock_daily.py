from __future__ import annotations

from datetime import date
from typing import Any

from app.modules.market_data.contracts import CanonicalMappingResult, ProviderAdapter
from app.modules.market_data.providers import normalize_symbol, parse_date, safe_float, safe_int


class TushareStockDailyAdapter(ProviderAdapter):
    provider_code = "tushare"

    daily_unit_conversions = {
        "daily.amount": "thousand_yuan -> yuan",
        "daily.vol": "hand -> shares",
        "daily.pct_chg": "percent_point -> percent_point",
    }
    daily_basic_unit_conversions = {
        "daily_basic.turnover_rate": "percent_point -> percent_point",
        "daily_basic.total_mv": "ten_thousand_yuan -> ten_thousand_yuan",
    }
    moneyflow_unit_conversions = {
        "moneyflow.*_amount": "ten_thousand_yuan -> yuan",
        "moneyflow.net_mf_amount": "ten_thousand_yuan -> yuan",
    }

    def map_daily(
        self,
        records: list[dict[str, Any]],
        *,
        trade_date: date | str,
        universe: set[str] | None = None,
    ) -> CanonicalMappingResult:
        target_date = self._as_date(trade_date)
        return self.map_daily_range(records, start_date=target_date, end_date=target_date, universe=universe)

    def map_daily_range(
        self,
        records: list[dict[str, Any]],
        *,
        start_date: date | str,
        end_date: date | str,
        universe: set[str] | None = None,
    ) -> CanonicalMappingResult:
        start = self._as_date(start_date)
        end = self._as_date(end_date)
        rows: list[dict[str, Any]] = []
        warnings: list[str] = []
        for record in records:
            row_date = parse_date(record.get("trade_date"))
            stock_code = normalize_symbol(str(record.get("ts_code") or ""))
            if not stock_code or row_date is None or row_date < start or row_date > end or (universe is not None and stock_code not in universe):
                continue
            volume_hand = safe_int(record.get("vol"))
            rows.append(
                {
                    "stock_code": stock_code,
                    "trade_date": row_date,
                    "source": "tushare:daily",
                    "adjust_mode": "none",
                    "open_price": safe_float(record.get("open")),
                    "high_price": safe_float(record.get("high")),
                    "low_price": safe_float(record.get("low")),
                    "close_price": safe_float(record.get("close")),
                    "pre_close_price": safe_float(record.get("pre_close")),
                    "change_amount": safe_float(record.get("change")),
                    "change_pct": safe_float(record.get("pct_chg")),
                    "volume_hand": volume_hand,
                    "volume_share": volume_hand * 100 if volume_hand is not None else None,
                    "amount_yuan": self._ten_thousand(record.get("amount"), multiplier=1000),
                    "turnover_rate": None,
                    "metadata_json": self._metadata("daily", record, self.daily_unit_conversions),
                }
            )
        missing = len(records) - len(rows)
        if missing:
            warnings.append(f"daily skipped records: {missing}")
        return self._result(
            api_name="daily",
            capability_code="stock_daily",
            start_date=start,
            end_date=end,
            records=records,
            rows=rows,
            warnings=warnings,
            unit_conversions=self.daily_unit_conversions,
        )

    def map_daily_basic(
        self,
        records: list[dict[str, Any]],
        *,
        trade_date: date | str,
        universe: set[str] | None = None,
    ) -> CanonicalMappingResult:
        target_date = self._as_date(trade_date)
        return self.map_daily_basic_range(records, start_date=target_date, end_date=target_date, universe=universe)

    def map_daily_basic_range(
        self,
        records: list[dict[str, Any]],
        *,
        start_date: date | str,
        end_date: date | str,
        universe: set[str] | None = None,
    ) -> CanonicalMappingResult:
        start = self._as_date(start_date)
        end = self._as_date(end_date)
        rows: list[dict[str, Any]] = []
        warnings: list[str] = []
        for record in records:
            row_date = parse_date(record.get("trade_date"))
            stock_code = normalize_symbol(str(record.get("ts_code") or ""))
            if not stock_code or row_date is None or row_date < start or row_date > end or (universe is not None and stock_code not in universe):
                continue
            rows.append(
                {
                    "stock_code": stock_code,
                    "trade_date": row_date,
                    "source": "tushare:daily_basic",
                    "close_price": safe_float(record.get("close")),
                    "turnover_rate": safe_float(record.get("turnover_rate")),
                    "turnover_rate_f": safe_float(record.get("turnover_rate_f")),
                    "volume_ratio": safe_float(record.get("volume_ratio")),
                    "pe": safe_float(record.get("pe")),
                    "pe_ttm": safe_float(record.get("pe_ttm")),
                    "pb": safe_float(record.get("pb")),
                    "ps": safe_float(record.get("ps")),
                    "ps_ttm": safe_float(record.get("ps_ttm")),
                    "dv_ratio": safe_float(record.get("dv_ratio")),
                    "dv_ttm": safe_float(record.get("dv_ttm")),
                    "total_share": safe_float(record.get("total_share")),
                    "float_share": safe_float(record.get("float_share")),
                    "free_share": safe_float(record.get("free_share")),
                    "total_mv": safe_float(record.get("total_mv")),
                    "circ_mv": safe_float(record.get("circ_mv")),
                    "limit_status": safe_int(record.get("limit_status")),
                    "metadata_json": self._metadata("daily_basic", record, self.daily_basic_unit_conversions),
                }
            )
        missing = len(records) - len(rows)
        if missing:
            warnings.append(f"daily_basic skipped records: {missing}")
        return self._result(
            api_name="daily_basic",
            capability_code="stock_daily_basic",
            start_date=start,
            end_date=end,
            records=records,
            rows=rows,
            warnings=warnings,
            unit_conversions=self.daily_basic_unit_conversions,
        )

    def map_moneyflow(
        self,
        records: list[dict[str, Any]],
        *,
        trade_date: date | str,
        universe: set[str] | None = None,
    ) -> CanonicalMappingResult:
        target_date = self._as_date(trade_date)
        return self.map_moneyflow_range(records, start_date=target_date, end_date=target_date, universe=universe)

    def map_moneyflow_range(
        self,
        records: list[dict[str, Any]],
        *,
        start_date: date | str,
        end_date: date | str,
        universe: set[str] | None = None,
    ) -> CanonicalMappingResult:
        start = self._as_date(start_date)
        end = self._as_date(end_date)
        rows: list[dict[str, Any]] = []
        warnings: list[str] = []
        for record in records:
            row_date = parse_date(record.get("trade_date"))
            stock_code = normalize_symbol(str(record.get("ts_code") or ""))
            if not stock_code or row_date is None or row_date < start or row_date > end or (universe is not None and stock_code not in universe):
                continue
            small_buy = self._ten_thousand(record.get("buy_sm_amount"))
            small_sell = self._ten_thousand(record.get("sell_sm_amount"))
            medium_buy = self._ten_thousand(record.get("buy_md_amount"))
            medium_sell = self._ten_thousand(record.get("sell_md_amount"))
            large_buy = self._ten_thousand(record.get("buy_lg_amount"))
            large_sell = self._ten_thousand(record.get("sell_lg_amount"))
            super_buy = self._ten_thousand(record.get("buy_elg_amount"))
            super_sell = self._ten_thousand(record.get("sell_elg_amount"))
            rows.append(
                {
                    "stock_code": stock_code,
                    "trade_date": row_date,
                    "source": "tushare:moneyflow",
                    "main_net_inflow": self._ten_thousand(record.get("net_mf_amount")),
                    "main_net_ratio": None,
                    "big_order_net_inflow": self._net(large_buy, large_sell),
                    "big_order_net_ratio": None,
                    "super_large_net_inflow": self._net(super_buy, super_sell),
                    "medium_net_inflow": self._net(medium_buy, medium_sell),
                    "small_net_inflow": self._net(small_buy, small_sell),
                    "small_buy_amount": small_buy,
                    "small_sell_amount": small_sell,
                    "medium_buy_amount": medium_buy,
                    "medium_sell_amount": medium_sell,
                    "large_buy_amount": large_buy,
                    "large_sell_amount": large_sell,
                    "super_large_buy_amount": super_buy,
                    "super_large_sell_amount": super_sell,
                    "close_price": None,
                    "change_pct": None,
                    "rank": None,
                    "metadata_json": self._metadata(
                        "moneyflow",
                        record,
                        self.moneyflow_unit_conversions,
                        unit_normalized="yuan",
                        source_unit="ten_thousand_yuan",
                    ),
                }
            )
        missing = len(records) - len(rows)
        if missing:
            warnings.append(f"moneyflow skipped records: {missing}")
        return self._result(
            api_name="moneyflow",
            capability_code="stock_moneyflow",
            start_date=start,
            end_date=end,
            records=records,
            rows=rows,
            warnings=warnings,
            unit_conversions=self.moneyflow_unit_conversions,
        )

    def _result(
        self,
        *,
        api_name: str,
        capability_code: str,
        start_date: date,
        end_date: date,
        records: list[dict[str, Any]],
        rows: list[dict[str, Any]],
        warnings: list[str],
        unit_conversions: dict[str, str],
    ) -> CanonicalMappingResult:
        return CanonicalMappingResult(
            rows=rows,
            raw_count=len(records),
            mapped_count=len(rows),
            missing_count=max(len(records) - len(rows), 0),
            warnings=warnings,
            unit_conversions=unit_conversions,
            provider_code=self.provider_code,
            api_name=api_name,
            capability_code=capability_code,
            request_range={"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
        )

    @staticmethod
    def _metadata(
        api_name: str,
        record: dict[str, Any],
        unit_conversions: dict[str, str],
        *,
        unit_normalized: str | None = None,
        source_unit: str | None = None,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "provider": "tushare",
            "api_name": api_name,
            "source": f"tushare:{api_name}",
            "unit_conversions": unit_conversions,
            "raw": record,
        }
        if unit_normalized:
            metadata["unit_normalized"] = unit_normalized
        if source_unit:
            metadata["source_unit"] = source_unit
        return metadata

    @staticmethod
    def _as_date(value: date | str) -> date:
        if isinstance(value, date):
            return value
        parsed = parse_date(value)
        if parsed is None:
            raise ValueError(f"invalid trade_date: {value}")
        return parsed

    @staticmethod
    def _net(buy: float | None, sell: float | None) -> float | None:
        if buy is None or sell is None:
            return None
        return buy - sell

    @staticmethod
    def _ten_thousand(value: Any, *, multiplier: float = 10000) -> float | None:
        parsed = safe_float(value)
        return parsed * multiplier if parsed is not None else None
