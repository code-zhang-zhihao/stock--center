"""Caller-side mappings from raw Tushare responses to stock-center facts.

This module intentionally owns all code conversion, unit conversion and
Canonical shaping. ``tushare.transport`` remains a raw protocol adapter.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from app.modules.market_data.providers import normalize_symbol, parse_date, safe_float
from app.modules.market_data.tushare.contracts import TushareApiRequest


def _ts_code(stock_code: str) -> str:
    text = stock_code.strip().upper()
    if "." in text:
        return text
    code = normalize_symbol(text)
    if code.startswith("6"):
        return f"{code}.SH"
    if code.startswith(("4", "8")):
        return f"{code}.BJ"
    return f"{code}.SZ"


def _stock_code(record: dict, fallback: str = "") -> str:
    """Use the provider-neutral stock symbol for Canonical associations."""
    return normalize_symbol(str(record.get("symbol") or record.get("ts_code") or fallback))


def _raw(response):
    return response.records, [response.raw_payload]


def _metadata(api_name: str, record: dict) -> dict:
    return {"source": f"tushare:{api_name}", "raw": record}


def _stock_status(list_status: object) -> str:
    value = str(list_status or "L").upper()
    if value == "D":
        return "delisted"
    if value == "P":
        return "suspended"
    return "active"


class TushareCanonicalMapper:
    """Compatibility mapping set used only by QueryService and SyncService."""

    async def stock_basic_list(self, transport):
        rows: list[dict] = []
        delisted: set[str] = set()
        raw: list[dict] = []
        for list_status in ("L", "D", "P"):
            response = await transport.request(TushareApiRequest("stock_basic", {"exchange": "", "list_status": list_status}))
            raw.append(response.raw_payload)
            for record in response.records:
                code = _stock_code(record)
                if not code:
                    continue
                status = _stock_status(record.get("list_status") or list_status)
                if status == "delisted":
                    delisted.add(code)
                metadata = _metadata("stock_basic", record)
                metadata["provider_list_status"] = str(record.get("list_status") or list_status)
                rows.append({
                    "stock_code": code,
                    "stock_name": str(record.get("name") or code),
                    "market": "CN",
                    "exchange": str(record.get("exchange") or str(record.get("ts_code") or "").split(".")[-1] or ""),
                    "list_date": parse_date(record.get("list_date")),
                    "delist_date": parse_date(record.get("delist_date")),
                    "status": status,
                    "industry": record.get("industry"),
                    "area": record.get("area"),
                    "metadata_json": metadata,
                })
        return rows, delisted, raw

    async def stock_basic(self, transport, stock_code: str):
        response = await transport.request(TushareApiRequest("stock_basic", {"ts_code": _ts_code(stock_code), "list_status": "L"}))
        if not response.records:
            return None, [response.raw_payload]
        record = response.records[0]
        code = _stock_code(record, stock_code)
        status = _stock_status(record.get("list_status"))
        metadata = _metadata("stock_basic", record)
        metadata["provider_list_status"] = str(record.get("list_status") or "L")
        return {
            "stock_code": code,
            "stock_name": str(record.get("name") or code),
            "market": "CN",
            "exchange": str(record.get("exchange") or str(record.get("ts_code") or "").split(".")[-1] or ""),
            "list_date": parse_date(record.get("list_date")),
            "delist_date": parse_date(record.get("delist_date")),
            "status": status,
            "industry": record.get("industry"),
            "area": record.get("area"),
            "metadata_json": metadata,
        }, [response.raw_payload]

    async def daily_bars(self, transport, stock_code: str, *, start_date: date | None, end_date: date | None):
        response = await transport.request(TushareApiRequest("daily", {
            "ts_code": _ts_code(stock_code),
            **({"start_date": start_date} if start_date else {}),
            **({"end_date": end_date} if end_date else {}),
        }))
        rows = []
        for record in response.records:
            trade_date = parse_date(record.get("trade_date"))
            if trade_date is None:
                continue
            rows.append({
                "stock_code": normalize_symbol(str(record.get("ts_code") or stock_code)),
                "trade_date": trade_date,
                "source": "tushare:daily",
                "adjust_mode": "none",
                "open_price": safe_float(record.get("open")),
                "high_price": safe_float(record.get("high")),
                "low_price": safe_float(record.get("low")),
                "close_price": safe_float(record.get("close")),
                "pre_close_price": safe_float(record.get("pre_close")),
                "change_amount": safe_float(record.get("change")),
                "change_pct": safe_float(record.get("pct_chg")),
                "volume_hand": safe_float(record.get("vol")),
                "volume_share": None,
                "amount_yuan": safe_float(record.get("amount")) * 1000 if safe_float(record.get("amount")) is not None else None,
                "turnover_rate": None,
                "metadata_json": _metadata("daily", record),
            })
        return rows, [response.raw_payload]

    async def ths_sectors(self, transport, sector_type: str):
        api_type = "N" if sector_type == "concept" else "I"
        response = await transport.request(TushareApiRequest("ths_index", {"exchange": "A", "type": api_type}))
        rows = []
        for record in response.records:
            raw_code = str(record.get("ts_code") or "")
            if not raw_code:
                continue
            rows.append({
                "sector_code": f"ths_{sector_type}_{raw_code}",
                "sector_name": str(record.get("name") or raw_code),
                "sector_type": sector_type,
                "source": "tushare:ths_index",
                "metadata_json": {**_metadata("ths_index", record), "raw_code": raw_code, "taxonomy": "THS"},
            })
        return rows, [response.raw_payload]

    async def sectors(self, transport, sector_type: str):
        if sector_type != "industry":
            raise ValueError("Tushare SW catalog only supports industry sectors")
        response = await transport.request(TushareApiRequest("index_classify", {"src": "SW2021"}))
        rows = []
        for record in response.records:
            industry_code = str(record.get("industry_code") or "")
            if not industry_code:
                continue
            rows.append({
                "sector_code": f"sw2021_{industry_code}",
                "sector_name": str(record.get("industry_name") or industry_code),
                "sector_type": "industry",
                "source": "tushare:index_classify:SW2021",
                "metadata_json": {**_metadata("index_classify", record), "taxonomy": "SW2021"},
            })
        return rows, [response.raw_payload]

    async def ths_sector_components(self, transport, sector_code: str):
        raw_code = sector_code.removeprefix("ths_concept_").removeprefix("ths_industry_")
        response = await transport.request(TushareApiRequest("ths_member", {"ts_code": raw_code}))
        rows = []
        for record in response.records:
            code = normalize_symbol(str(record.get("con_code") or record.get("ts_code") or record.get("code") or ""))
            if code:
                rows.append({"sector_code": sector_code, "stock_code": code, "weight": safe_float(record.get("weight")), "start_date": parse_date(record.get("in_date")), "end_date": parse_date(record.get("out_date")), "source": "tushare:ths_member", "metadata_json": _metadata("ths_member", record)})
        return rows, [response.raw_payload]

    async def sector_components(self, transport, sector_code: str):
        industry_code = sector_code.removeprefix("sw2021_")
        key = "l1_code" if len(industry_code) == 6 and industry_code.endswith("0000") else "l2_code" if len(industry_code) == 6 and industry_code.endswith("00") else "l3_code"
        response = await transport.request(TushareApiRequest("index_member_all", {key: industry_code, "is_new": "Y"}))
        rows = []
        for record in response.records:
            code = normalize_symbol(str(record.get("ts_code") or ""))
            if code:
                rows.append({"sector_code": sector_code, "stock_code": code, "weight": None, "start_date": parse_date(record.get("in_date")), "end_date": parse_date(record.get("out_date")), "source": "tushare:index_member_all:SW2021", "metadata_json": _metadata("index_member_all", record)})
        return rows, [response.raw_payload]

    async def indexes(self, transport, index_code: str | None):
        response = await transport.request(TushareApiRequest("index_basic", {"ts_code": index_code} if index_code else {"market": "SSE"}))
        rows = []
        for record in response.records:
            code = normalize_symbol(str(record.get("ts_code") or ""))
            if code:
                rows.append({"index_code": code, "index_name": str(record.get("name") or code), "market": "CN", "publisher": record.get("publisher"), "metadata_json": _metadata("index_basic", record)})
        return rows, [response.raw_payload]

    async def index_bars(self, transport, index_code: str, *, start_date: date | None, end_date: date | None):
        response = await transport.request(TushareApiRequest("index_daily", {"ts_code": index_code, **({"start_date": start_date} if start_date else {}), **({"end_date": end_date} if end_date else {})}))
        rows = []
        for record in response.records:
            trade_date = parse_date(record.get("trade_date"))
            if trade_date:
                rows.append({"index_code": normalize_symbol(str(record.get("ts_code") or index_code)), "trade_date": trade_date, "source": "tushare:index_daily", "open_price": safe_float(record.get("open")), "high_price": safe_float(record.get("high")), "low_price": safe_float(record.get("low")), "close_price": safe_float(record.get("close")), "change_pct": safe_float(record.get("pct_chg")), "volume": safe_float(record.get("vol")), "amount_yuan": safe_float(record.get("amount")) * 1000 if safe_float(record.get("amount")) is not None else None, "metadata_json": _metadata("index_daily", record)})
        return rows, [response.raw_payload]

    async def index_components(self, transport, index_code: str, *, start_date: date | None = None, end_date: date | None = None):
        response = await transport.request(
            TushareApiRequest(
                "index_weight",
                {
                    "index_code": index_code,
                    **({"start_date": start_date} if start_date else {}),
                    **({"end_date": end_date} if end_date else {}),
                },
            )
        )
        rows = []
        for record in response.records:
            code = normalize_symbol(str(record.get("con_code") or record.get("ts_code") or ""))
            if code:
                rows.append({"index_code": normalize_symbol(index_code), "stock_code": code, "effective_date": parse_date(record.get("trade_date")), "weight": safe_float(record.get("weight")), "source": "tushare:index_weight", "metadata_json": _metadata("index_weight", record)})
        return rows, [response.raw_payload]

    async def stock_fund_flow(self, transport, stock_code: str, *, start_date: date | None, end_date: date | None):
        response = await transport.request(TushareApiRequest("moneyflow", {"ts_code": _ts_code(stock_code), **({"start_date": start_date} if start_date else {}), **({"end_date": end_date} if end_date else {})}))
        rows = []
        for record in response.records:
            trade_date = parse_date(record.get("trade_date"))
            if trade_date:
                small_buy, small_sell = safe_float(record.get("buy_sm_amount")), safe_float(record.get("sell_sm_amount"))
                medium_buy, medium_sell = safe_float(record.get("buy_md_amount")), safe_float(record.get("sell_md_amount"))
                large_buy, large_sell = safe_float(record.get("buy_lg_amount")), safe_float(record.get("sell_lg_amount"))
                super_buy, super_sell = safe_float(record.get("buy_elg_amount")), safe_float(record.get("sell_elg_amount"))
                rows.append({
                    "stock_code": normalize_symbol(str(record.get("ts_code") or stock_code)),
                    "trade_date": trade_date,
                    "source": "tushare:moneyflow",
                    "main_net_inflow": safe_float(record.get("net_mf_amount")),
                    "main_net_ratio": None,
                    "small_net_inflow": small_buy - small_sell if small_buy is not None and small_sell is not None else None,
                    "medium_net_inflow": medium_buy - medium_sell if medium_buy is not None and medium_sell is not None else None,
                    "big_order_net_inflow": large_buy - large_sell if large_buy is not None and large_sell is not None else None,
                    "big_order_net_ratio": None,
                    "super_large_net_inflow": super_buy - super_sell if super_buy is not None and super_sell is not None else None,
                    "small_buy_amount": small_buy,
                    "small_sell_amount": small_sell,
                    "medium_buy_amount": medium_buy,
                    "medium_sell_amount": medium_sell,
                    "large_buy_amount": large_buy,
                    "large_sell_amount": large_sell,
                    "super_large_buy_amount": super_buy,
                    "super_large_sell_amount": super_sell,
                    "metadata_json": _metadata("moneyflow", record),
                })
        return rows, [response.raw_payload]

    async def lhb(self, transport, *, stock_code: str | None, start_date: date | None, end_date: date | None):
        params = {"ts_code": _ts_code(stock_code)} if stock_code else {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        response = await transport.request(TushareApiRequest("top_list", params))
        events = []
        for record in response.records:
            code, trade_date = normalize_symbol(str(record.get("ts_code") or "")), parse_date(record.get("trade_date"))
            if code and trade_date:
                events.append({"stock_code": code, "trade_date": trade_date, "reason": str(record.get("reason") or "Tushare top list"), "source": "tushare:top_list", "close_price": safe_float(record.get("close")), "change_pct": safe_float(record.get("pct_change") or record.get("pct_chg")), "turnover_rate": safe_float(record.get("turnover_rate")), "buy_amount": safe_float(record.get("l_buy")), "sell_amount": safe_float(record.get("l_sell")), "net_amount": safe_float(record.get("net_amount")), "metadata_json": _metadata("top_list", record)})
        return {"events": events, "seats": []}, [response.raw_payload]

    async def announcements(self, transport, stock_code: str, *, start_date: date | None, end_date: date | None):
        response = await transport.request(TushareApiRequest("anns_d", {"ts_code": _ts_code(stock_code), **({"start_date": start_date} if start_date else {}), **({"end_date": end_date} if end_date else {})}))
        rows = []
        for record in response.records:
            published = parse_date(record.get("ann_date"))
            title = str(record.get("title") or record.get("rec_title") or "")
            if published and title:
                rows.append({"stock_code": normalize_symbol(str(record.get("ts_code") or stock_code)), "title": title, "category": record.get("category"), "published_at": datetime.combine(published, datetime.min.time(), tzinfo=timezone.utc), "url": record.get("url"), "source": "tushare:anns_d", "metadata_json": _metadata("anns_d", record)})
        return rows, [response.raw_payload]
