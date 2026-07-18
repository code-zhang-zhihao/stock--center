from __future__ import annotations

from datetime import date
from typing import Any

from app.modules.market_data.contracts import CanonicalMappingResult, ProviderAdapter
from app.modules.market_data.providers import normalize_symbol, parse_date, safe_float, safe_int


class TushareMarketAdapter(ProviderAdapter):
    provider_code = "tushare"

    index_daily_unit_conversions = {
        "index_daily.amount": "thousand_yuan -> yuan",
    }
    ths_daily_unit_conversions = {
        "ths_daily.amount": "thousand_yuan -> yuan",
    }
    sector_moneyflow_unit_conversions = {
        "moneyflow_*_ths.net_buy_amount": "ten_thousand_yuan -> yuan",
        "moneyflow_*_ths.net_sell_amount": "ten_thousand_yuan -> yuan",
        "moneyflow_*_ths.net_amount": "ten_thousand_yuan -> yuan",
    }
    top_list_unit_conversions = {
        "top_list.amount": "ten_thousand_yuan -> yuan",
        "top_list.l_buy": "ten_thousand_yuan -> yuan",
        "top_list.l_sell": "ten_thousand_yuan -> yuan",
        "top_list.net_amount": "ten_thousand_yuan -> yuan",
    }
    raw_unit_conversions = {
        "daily_info.amount": "provider_raw -> provider_raw",
        "daily_info.vol": "provider_raw -> provider_raw",
        "index_dailybasic.*": "provider_raw -> provider_raw",
    }

    def map_index_daily(
        self,
        records: list[dict[str, Any]],
        *,
        trade_date: date | str,
        index_codes: set[str] | None = None,
    ) -> CanonicalMappingResult:
        target_date = self._as_date(trade_date)
        rows: list[dict[str, Any]] = []
        warnings: list[str] = []
        for record in records:
            row_date = parse_date(record.get("trade_date"))
            index_code = normalize_symbol(str(record.get("ts_code") or ""))
            if not index_code or row_date != target_date or (index_codes is not None and index_code not in index_codes):
                continue
            source = str(record.get("source") or "tushare:index_daily")
            amount = safe_float(record.get("amount"))
            rows.append(
                {
                    "index_code": index_code,
                    "trade_date": row_date,
                    "source": source,
                    "open_price": safe_float(record.get("open")),
                    "high_price": safe_float(record.get("high")),
                    "low_price": safe_float(record.get("low")),
                    "close_price": safe_float(record.get("close")),
                    "change_pct": safe_float(record.get("pct_chg")),
                    "volume": safe_float(record.get("vol")),
                    "amount_yuan": amount * 1000 if amount is not None else None,
                    "metadata_json": self._metadata(
                        "index_daily",
                        record.get("raw", record),
                        self.index_daily_unit_conversions,
                        provider=source.split(":", 1)[0],
                        source=source,
                        unit_normalized="yuan",
                    ),
                }
            )
        if len(records) != len(rows):
            warnings.append(f"index_daily skipped records: {len(records) - len(rows)}")
        return self._result("index_daily", "index_daily", target_date, target_date, records, rows, warnings, self.index_daily_unit_conversions)

    def map_index_daily_range(
        self,
        records: list[dict[str, Any]],
        *,
        start_date: date | str,
        end_date: date | str,
        index_codes: set[str] | None = None,
    ) -> CanonicalMappingResult:
        start = self._as_date(start_date)
        end = self._as_date(end_date)
        rows: list[dict[str, Any]] = []
        warnings: list[str] = []
        for record in records:
            row_date = parse_date(record.get("trade_date"))
            index_code = normalize_symbol(str(record.get("ts_code") or ""))
            if not index_code or row_date is None or not (start <= row_date <= end):
                continue
            if index_codes is not None and index_code not in index_codes:
                continue
            source = str(record.get("source") or "tushare:index_daily")
            amount = safe_float(record.get("amount"))
            rows.append(
                {
                    "index_code": index_code,
                    "trade_date": row_date,
                    "source": source,
                    "open_price": safe_float(record.get("open")),
                    "high_price": safe_float(record.get("high")),
                    "low_price": safe_float(record.get("low")),
                    "close_price": safe_float(record.get("close")),
                    "change_pct": safe_float(record.get("pct_chg")),
                    "volume": safe_float(record.get("vol")),
                    "amount_yuan": amount * 1000 if amount is not None else None,
                    "metadata_json": self._metadata(
                        "index_daily",
                        record.get("raw", record),
                        self.index_daily_unit_conversions,
                        provider=source.split(":", 1)[0],
                        source=source,
                        unit_normalized="yuan",
                    ),
                }
            )
        if len(records) != len(rows):
            warnings.append(f"index_daily skipped records: {len(records) - len(rows)}")
        return self._result("index_daily", "index_daily", start, end, records, rows, warnings, self.index_daily_unit_conversions)

    def map_index_daily_basic(
        self,
        records: list[dict[str, Any]],
        *,
        start_date: date | str,
        end_date: date | str,
        index_codes: set[str] | None = None,
    ) -> CanonicalMappingResult:
        start = self._as_date(start_date)
        end = self._as_date(end_date)
        rows: list[dict[str, Any]] = []
        warnings: list[str] = []
        for record in records:
            row_date = parse_date(record.get("trade_date"))
            index_code = normalize_symbol(str(record.get("ts_code") or ""))
            if not index_code or row_date is None or not (start <= row_date <= end) or (index_codes is not None and index_code not in index_codes):
                continue
            rows.append(
                {
                    "index_code": index_code,
                    "trade_date": row_date,
                    "source": "tushare:index_dailybasic",
                    "total_mv": safe_float(record.get("total_mv")),
                    "float_mv": safe_float(record.get("float_mv")),
                    "total_share": safe_float(record.get("total_share")),
                    "float_share": safe_float(record.get("float_share")),
                    "free_share": safe_float(record.get("free_share")),
                    "turnover_rate": safe_float(record.get("turnover_rate")),
                    "turnover_rate_f": safe_float(record.get("turnover_rate_f")),
                    "pe": safe_float(record.get("pe")),
                    "pe_ttm": safe_float(record.get("pe_ttm")),
                    "pb": safe_float(record.get("pb")),
                    "metadata_json": self._metadata("index_dailybasic", record, self.raw_unit_conversions),
                }
            )
        if len(records) != len(rows):
            warnings.append(f"index_dailybasic skipped records: {len(records) - len(rows)}")
        return self._result("index_dailybasic", "index_daily_basic", start, end, records, rows, warnings, self.raw_unit_conversions)

    def map_market_daily_stat(
        self,
        records: list[dict[str, Any]],
        *,
        start_date: date | str,
        end_date: date | str,
        default_exchange: str,
    ) -> CanonicalMappingResult:
        start = self._as_date(start_date)
        end = self._as_date(end_date)
        rows: list[dict[str, Any]] = []
        warnings: list[str] = []
        for record in records:
            row_date = parse_date(record.get("trade_date"))
            ts_code = str(record.get("ts_code") or "")
            if row_date is None or not (start <= row_date <= end) or not ts_code:
                continue
            rows.append(
                {
                    "trade_date": row_date,
                    "ts_code": ts_code,
                    "ts_name": record.get("ts_name"),
                    "exchange": str(record.get("exchange") or default_exchange),
                    "source": "tushare:daily_info",
                    "company_count": safe_int(record.get("com_count")),
                    "total_share": safe_float(record.get("total_share")),
                    "float_share": safe_float(record.get("float_share")),
                    "total_mv": safe_float(record.get("total_mv")),
                    "float_mv": safe_float(record.get("float_mv")),
                    "amount": safe_float(record.get("amount")),
                    "volume": safe_float(record.get("vol")),
                    "transaction_count": safe_float(record.get("trans_count")),
                    "pe": safe_float(record.get("pe")),
                    "turnover_rate": safe_float(record.get("tr")),
                    "metadata_json": self._metadata("daily_info", record, self.raw_unit_conversions),
                }
            )
        if len(records) != len(rows):
            warnings.append(f"daily_info skipped records: {len(records) - len(rows)}")
        return self._result("daily_info", "market_daily_stat", start, end, records, rows, warnings, self.raw_unit_conversions)

    def map_ths_daily(
        self,
        records: list[dict[str, Any]],
        *,
        trade_date: date | str,
        sector_map: dict[str, dict[str, Any]],
    ) -> CanonicalMappingResult:
        target_date = self._as_date(trade_date)
        return self.map_ths_daily_range(
            records,
            start_date=target_date,
            end_date=target_date,
            sector_map=sector_map,
        )

    def map_ths_daily_range(
        self,
        records: list[dict[str, Any]],
        *,
        start_date: date | str,
        end_date: date | str,
        sector_map: dict[str, dict[str, Any]],
    ) -> CanonicalMappingResult:
        start = self._as_date(start_date)
        end = self._as_date(end_date)
        rows: list[dict[str, Any]] = []
        warnings: list[str] = []
        for record in records:
            raw_code = str(record.get("ts_code") or "")
            sector = sector_map.get(raw_code)
            row_date = parse_date(record.get("trade_date"))
            if not sector or row_date is None or not (start <= row_date <= end):
                continue
            amount = safe_float(record.get("amount"))
            rows.append(
                {
                    "sector_code": sector["sector_code"],
                    "trade_date": row_date,
                    "source": "tushare:ths_daily",
                    "open_price": safe_float(record.get("open")),
                    "high_price": safe_float(record.get("high")),
                    "low_price": safe_float(record.get("low")),
                    "close_price": safe_float(record.get("close")),
                    "pre_close_price": safe_float(record.get("pre_close")),
                    "change_amount": safe_float(record.get("change")),
                    "change_pct": safe_float(record.get("pct_change") or record.get("pct_chg")),
                    "volume": safe_float(record.get("vol")),
                    "amount_yuan": amount * 1000 if amount is not None else None,
                    "turnover_rate": safe_float(record.get("turnover_rate")),
                    "metadata_json": self._metadata(
                        "ths_daily",
                        record,
                        self.ths_daily_unit_conversions,
                        unit_normalized="yuan",
                    ),
                }
            )
        if len(records) != len(rows):
            warnings.append(f"ths_daily skipped records: {len(records) - len(rows)}")
        return self._result(
            "ths_daily",
            "sector_daily_bar",
            start,
            end,
            records,
            rows,
            warnings,
            self.ths_daily_unit_conversions,
        )

    def map_sector_moneyflow(
        self,
        records: list[dict[str, Any]],
        *,
        api_name: str,
        sector_type: str,
        start_date: date | str,
        end_date: date | str,
        sector_map: dict[str, dict[str, Any]],
    ) -> CanonicalMappingResult:
        start = self._as_date(start_date)
        end = self._as_date(end_date)
        rows: list[dict[str, Any]] = []
        warnings: list[str] = []
        for record in records:
            raw_code = str(record.get("ts_code") or "")
            sector = sector_map.get(raw_code)
            row_date = parse_date(record.get("trade_date"))
            if row_date is None or not (start <= row_date <= end):
                continue
            sector_code = (sector or {}).get("sector_code") or f"ths_{sector_type}_{raw_code or record.get('name') or record.get('industry')}"
            sector_name = (sector or {}).get("sector_name") or str(record.get("name") or record.get("industry") or sector_code)
            rows.append(
                {
                    "sector_code": sector_code,
                    "sector_name": sector_name,
                    "sector_type": (sector or {}).get("sector_type") or sector_type,
                    "trade_date": row_date,
                    "source": f"tushare:{api_name}",
                    "main_net_inflow": self._ten_thousand(record.get("net_amount")),
                    "net_buy_amount": self._ten_thousand(record.get("net_buy_amount")),
                    "net_sell_amount": self._ten_thousand(record.get("net_sell_amount")),
                    "main_net_ratio": None,
                    "change_pct": safe_float(record.get("pct_change")),
                    "close_price": safe_float(record.get("close_price") or record.get("close")),
                    "company_num": safe_int(record.get("company_num")),
                    "lead_stock": record.get("lead_stock"),
                    "lead_stock_change_pct": safe_float(record.get("pct_change_stock")),
                    "rank": None,
                    "metadata_json": self._metadata(
                        api_name,
                        record,
                        self.sector_moneyflow_unit_conversions,
                        unit_normalized="yuan",
                        source_unit="ten_thousand_yuan",
                    ),
                }
            )
        if len(records) != len(rows):
            warnings.append(f"{api_name} skipped records: {len(records) - len(rows)}")
        return self._result(api_name, "sector_moneyflow", start, end, records, rows, warnings, self.sector_moneyflow_unit_conversions)

    def map_top_list(
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
            stock_code = normalize_symbol(str(record.get("ts_code") or ""))
            row_date = parse_date(record.get("trade_date"))
            reason = str(record.get("reason") or "Tushare top_list")
            if not stock_code or row_date is None or not (start <= row_date <= end) or (universe is not None and stock_code not in universe):
                continue
            rows.append(
                {
                    "stock_code": stock_code,
                    "stock_name": record.get("name"),
                    "trade_date": row_date,
                    "source": "tushare:top_list",
                    "reason": reason,
                    "close_price": safe_float(record.get("close")),
                    "change_pct": safe_float(record.get("pct_change") or record.get("pct_chg")),
                    "turnover_amount": self._ten_thousand(record.get("amount")),
                    "net_buy_amount": self._ten_thousand(record.get("net_amount")),
                    "buy_amount": self._ten_thousand(record.get("l_buy")),
                    "sell_amount": self._ten_thousand(record.get("l_sell")),
                    "metadata_json": self._metadata(
                        "top_list",
                        record,
                        self.top_list_unit_conversions,
                        unit_normalized="yuan",
                        source_unit="ten_thousand_yuan",
                    ),
                }
            )
        if len(records) != len(rows):
            warnings.append(f"top_list skipped records: {len(records) - len(rows)}")
        return self._result("top_list", "lhb_event", start, end, records, rows, warnings, self.top_list_unit_conversions)

    def _result(
        self,
        api_name: str,
        capability_code: str,
        start_date: date,
        end_date: date,
        records: list[dict[str, Any]],
        rows: list[dict[str, Any]],
        warnings: list[str],
        unit_conversions: dict[str, str],
    ) -> CanonicalMappingResult:
        request_range = {"trade_date": start_date.isoformat()} if start_date == end_date else {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()}
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
            request_range=request_range,
        )

    @staticmethod
    def _metadata(
        api_name: str,
        record: dict[str, Any],
        unit_conversions: dict[str, str],
        *,
        provider: str = "tushare",
        source: str | None = None,
        unit_normalized: str | None = None,
        source_unit: str | None = None,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "provider": provider,
            "api_name": api_name,
            "source": source or f"{provider}:{api_name}",
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
            raise ValueError(f"invalid date: {value}")
        return parsed

    @staticmethod
    def _ten_thousand(value: Any) -> float | None:
        parsed = safe_float(value)
        return parsed * 10000 if parsed is not None else None
