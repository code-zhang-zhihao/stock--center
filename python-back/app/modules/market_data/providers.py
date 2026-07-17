from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import logging
import threading
import time as time_module
from typing import Any
from zoneinfo import ZoneInfo


logger = logging.getLogger(__name__)


class ThsAuthenticationRequiredError(RuntimeError):
    """Raised when a THS pagination response is replaced by its login page."""


def normalize_symbol(stock_code: str) -> str:
    return stock_code.split(".")[0].strip()


def safe_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def json_safe(value: Any):
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return json_safe(value.item())
        except Exception:
            pass
    try:
        import pandas as pd

        if pd.isna(value):
            return None
    except Exception:
        pass
    return value


def frame_records(value) -> list[dict]:
    if hasattr(value, "to_dict"):
        return [json_safe(row) for row in value.to_dict(orient="records")]
    if isinstance(value, list):
        return [json_safe(row) for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        return [json_safe(value)]
    return []


def first(row: dict, keys: list[str]):
    for key in keys:
        if key in row and row.get(key) not in (None, ""):
            return row.get(key)
    return None


def parse_date(value) -> date | None:
    if value is None:
        return None
    text = str(value).strip().replace("/", "-")
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        if len(text) >= 8 and text[:8].isdigit():
            return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
        return None


def parse_datetime(value, *, trade_date: date | None = None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip().replace("/", "-")
        if len(text) <= 12 and ":" in text and trade_date is not None:
            text = f"{trade_date.isoformat()} {text}"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=ZoneInfo("Asia/Shanghai")).astimezone(ZoneInfo("UTC"))
    return parsed


def market_prefix(code: str) -> str:
    code = normalize_symbol(code)
    if code.lower().startswith(("sh", "sz", "bj", "csi")):
        return code.lower()
    if code.startswith("6"):
        return f"sh{code}"
    if code.startswith(("0", "3")):
        return f"sz{code}"
    if code.startswith(("4", "8")):
        return f"bj{code}"
    return code


def parse_trade_side(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"买盘", "买入", "buy", "b"}:
        return "buy"
    if text in {"卖盘", "卖出", "sell", "s"}:
        return "sell"
    if text in {"中性盘", "中性", "neutral"}:
        return "neutral"
    return text or None


@dataclass(frozen=True)
class SectorComponentSnapshot:
    rows: list[dict]
    raw: list[dict]
    source: str
    is_complete: bool
    fetched_page_count: int
    expected_page_count: int | None


class AkShareProvider:
    code = "akshare"
    _THS_REQUEST_INTERVAL_SECONDS = 0.8
    _THS_PAGE_RETRY_COUNT = 3
    _THS_RETRY_BACKOFF_SECONDS = 2.0
    _THS_MAX_PAGE_COUNT = 100

    def __init__(self) -> None:
        self._ths_session = None
        self._ths_session_lock = threading.Lock()
        self._ths_last_request_at = 0.0

    def set_ths_request_interval(self, seconds: float) -> None:
        self._THS_REQUEST_INTERVAL_SECONDS = max(0.1, float(seconds))

    async def stock_basic_list(self) -> tuple[list[dict], set[str], list[dict]]:
        return await asyncio.to_thread(self._stock_basic_list_sync)

    async def stock_basic(self, stock_code: str) -> tuple[dict | None, list[dict]]:
        return await asyncio.to_thread(self._stock_basic_sync, stock_code)

    async def daily_bars(self, stock_code: str, *, start_date: date | None, end_date: date | None) -> tuple[list[dict], list[dict]]:
        return await asyncio.to_thread(self._daily_bars_sync, stock_code, start_date, end_date)

    async def minute_bars(
        self,
        stock_code: str,
        *,
        start_time: datetime | None,
        end_time: datetime | None,
    ) -> tuple[list[dict], list[dict]]:
        return await asyncio.to_thread(self._minute_bars_sync, stock_code, start_time, end_time)

    async def quote(self, stock_code: str) -> tuple[dict | None, list[dict]]:
        return await asyncio.to_thread(self._quote_sync, stock_code)

    async def ticks(self, stock_code: str) -> tuple[list[dict], list[dict]]:
        return await asyncio.to_thread(self._ticks_sync, stock_code)

    async def sectors(self, sector_type: str) -> tuple[list[dict], list[dict]]:
        return await asyncio.to_thread(self._sectors_sync, sector_type)

    async def sector_components(self, sector_type: str, sector_code: str) -> tuple[list[dict], list[dict]]:
        return await asyncio.to_thread(self._sector_components_sync, sector_type, sector_code)

    async def sector_component_snapshot(self, sector_type: str, sector_code: str) -> SectorComponentSnapshot:
        return await asyncio.to_thread(self._sector_component_snapshot_sync, sector_type, sector_code)

    async def sector_bars(
        self,
        sector_type: str,
        sector_code: str,
        *,
        start_date: date | None,
        end_date: date | None,
    ) -> tuple[list[dict], list[dict]]:
        return await asyncio.to_thread(self._sector_bars_sync, sector_type, sector_code, start_date, end_date)

    async def indexes(self, index_code: str | None) -> tuple[list[dict], list[dict]]:
        return await asyncio.to_thread(self._indexes_sync, index_code)

    async def index_components(self, index_code: str) -> tuple[list[dict], list[dict]]:
        return await asyncio.to_thread(self._index_components_sync, index_code)

    async def index_bars(self, index_code: str, *, start_date: date | None, end_date: date | None) -> tuple[list[dict], list[dict]]:
        return await asyncio.to_thread(self._index_bars_sync, index_code, start_date, end_date)

    async def stock_fund_flow(self, stock_code: str, *, start_date: date | None, end_date: date | None) -> tuple[list[dict], list[dict]]:
        return await asyncio.to_thread(self._stock_fund_flow_sync, stock_code, start_date, end_date)

    async def sector_fund_flow(self, sector_type: str) -> tuple[list[dict], list[dict]]:
        return await asyncio.to_thread(self._sector_fund_flow_sync, sector_type)

    async def lhb(
        self,
        *,
        stock_code: str | None,
        start_date: date | None,
        end_date: date | None,
    ) -> tuple[dict[str, list[dict]], list[dict]]:
        return await asyncio.to_thread(self._lhb_sync, stock_code, start_date, end_date)

    async def announcements(
        self,
        *,
        stock_code: str,
        start_date: date | None,
        end_date: date | None,
        keyword: str | None,
    ) -> tuple[list[dict], list[dict]]:
        return await asyncio.to_thread(self._announcements_sync, stock_code, start_date, end_date, keyword)

    def _stock_basic_list_sync(self) -> tuple[list[dict], set[str], list[dict]]:
        import akshare as ak

        sync_at = datetime.now(tz=ZoneInfo("UTC")).isoformat()
        rows_by_code: dict[str, dict] = {}
        raw_all: list[dict] = []
        primary = frame_records(ak.stock_info_a_code_name())
        raw_all.extend(primary)
        for record in primary:
            row = self._stock_row_from_record(record, source="akshare:stock_info_a_code_name", sync_at=sync_at)
            if row:
                rows_by_code[row["stock_code"]] = row

        supplement_calls = [
            ("akshare:stock_info_sh_name_code:main", lambda: ak.stock_info_sh_name_code(symbol="主板A股"), "SH"),
            ("akshare:stock_info_sh_name_code:star", lambda: ak.stock_info_sh_name_code(symbol="科创板"), "SH"),
            ("akshare:stock_info_sz_name_code", lambda: ak.stock_info_sz_name_code(symbol="A股列表"), "SZ"),
            ("akshare:stock_info_bj_name_code", ak.stock_info_bj_name_code, "BJ"),
        ]
        for source_name, loader, market in supplement_calls:
            try:
                records = frame_records(loader())
                raw_all.extend(records)
                for record in records:
                    row = self._stock_row_from_record(record, source=source_name, sync_at=sync_at, market=market)
                    if not row:
                        continue
                    rows_by_code[row["stock_code"]] = self._merge_stock_rows(rows_by_code.get(row["stock_code"]), row)
            except Exception:
                continue

        return list(rows_by_code.values()), self._delisted_codes_sync(ak), raw_all

    def _stock_row_from_record(
        self,
        record: dict,
        *,
        source: str,
        sync_at: str,
        market: str | None = None,
    ) -> dict | None:
        code = normalize_symbol(str(first(record, ["stock_code", "code", "代码", "证券代码", "A股代码", "公司代码"]) or ""))
        name = first(record, ["stock_name", "name", "名称", "证券简称", "A股简称", "股票简称", "公司简称"])
        if not code or not name:
            return None
        market = market or self._market(code)
        return {
            "stock_code": code,
            "stock_name": str(name).strip(),
            "market": "CN",
            "exchange": {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}.get(market),
            "list_date": parse_date(first(record, ["上市日期", "A股上市日期", "上市时间"])),
            "delist_date": None,
            "status": "active",
            "industry": first(record, ["所属行业", "行业"]),
            "area": first(record, ["地区", "区域"]),
            "metadata_json": {"sync_source": source, "sync_at": sync_at, "raw_source_fields": json_safe(record)},
        }

    def _merge_stock_rows(self, base: dict | None, incoming: dict) -> dict:
        if base is None:
            return incoming
        merged = {**base}
        for key in ["stock_name", "market", "exchange", "list_date", "industry", "area"]:
            if incoming.get(key) not in (None, ""):
                merged[key] = incoming[key]
        merged["metadata_json"] = {**(base.get("metadata_json") or {}), **(incoming.get("metadata_json") or {})}
        return merged

    def _delisted_codes_sync(self, ak) -> set[str]:
        codes: set[str] = set()
        calls = [
            lambda: ak.stock_info_sh_delist(symbol="全部"),
            lambda: ak.stock_info_sz_delist(symbol="终止上市公司"),
        ]
        for loader in calls:
            try:
                for record in frame_records(loader()):
                    code = normalize_symbol(str(first(record, ["证券代码", "A股代码", "公司代码", "code", "代码"]) or ""))
                    if code:
                        codes.add(code)
            except Exception:
                continue
        return codes

    def _stock_basic_sync(self, stock_code: str) -> tuple[dict | None, list[dict]]:
        import akshare as ak

        code = normalize_symbol(stock_code)
        raw = frame_records(ak.stock_individual_info_em(symbol=code, timeout=10))
        info = self._item_map(raw)
        market = self._market(code)
        return {
            "stock_code": code,
            "stock_name": str(info.get("股票简称") or info.get("简称") or info.get("名称") or code),
            "market": "CN",
            "exchange": {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}.get(market),
            "list_date": parse_date(info.get("上市时间") or info.get("上市日期")),
            "delist_date": None,
            "status": "active",
            "industry": info.get("行业"),
            "area": info.get("地区"),
            "metadata_json": {"source": "akshare:stock_individual_info_em", "raw": info},
        }, raw

    def _daily_bars_sync(self, stock_code: str, start_date: date | None, end_date: date | None) -> tuple[list[dict], list[dict]]:
        import akshare as ak

        code = normalize_symbol(stock_code)
        raw = frame_records(
            ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=(start_date or date(1990, 1, 1)).strftime("%Y%m%d"),
                end_date=(end_date or date.today()).strftime("%Y%m%d"),
                adjust="qfq",
            )
        )
        rows = []
        for item in raw:
            trade_date = parse_date(first(item, ["日期", "date"]))
            if trade_date is None:
                continue
            volume_hand = safe_int(first(item, ["成交量", "volume"]))
            rows.append({
                "stock_code": code,
                "trade_date": trade_date,
                "source": "akshare_qfq",
                "adjust_mode": "qfq",
                "open_price": safe_float(first(item, ["开盘", "open"])),
                "high_price": safe_float(first(item, ["最高", "high"])),
                "low_price": safe_float(first(item, ["最低", "low"])),
                "close_price": safe_float(first(item, ["收盘", "close"])),
                "pre_close_price": None,
                "change_amount": safe_float(first(item, ["涨跌额"])),
                "change_pct": safe_float(first(item, ["涨跌幅"])),
                "volume_hand": volume_hand,
                "volume_share": volume_hand * 100 if volume_hand is not None else None,
                "amount_yuan": safe_float(first(item, ["成交额"])),
                "turnover_rate": safe_float(first(item, ["换手率"])),
                "metadata_json": {"source": "akshare:stock_zh_a_hist", "raw": item},
            })
        return rows, raw

    def _minute_bars_sync(self, stock_code: str, start_time: datetime | None, end_time: datetime | None) -> tuple[list[dict], list[dict]]:
        import akshare as ak

        code = normalize_symbol(stock_code)
        raw = frame_records(
            ak.stock_zh_a_hist_min_em(
                symbol=code,
                start_date=(start_time or datetime(1979, 9, 1, 9, 32)).strftime("%Y-%m-%d %H:%M:%S"),
                end_date=(end_time or datetime(2222, 1, 1, 9, 32)).strftime("%Y-%m-%d %H:%M:%S"),
                period="1",
                adjust="",
            )
        )
        rows = []
        for item in raw:
            bar_time = parse_datetime(first(item, ["时间", "日期", "datetime"]))
            if bar_time is None:
                continue
            volume_hand = safe_int(first(item, ["成交量", "volume"]))
            rows.append({
                "stock_code": code,
                "bar_time": bar_time,
                "interval": "1m",
                "source": "akshare",
                "price": safe_float(first(item, ["收盘", "最新价", "price"])),
                "avg_price": safe_float(first(item, ["均价"])),
                "volume_hand": volume_hand,
                "volume_share": volume_hand * 100 if volume_hand is not None else None,
                "amount_yuan": safe_float(first(item, ["成交额"])),
                "metadata_json": {"source": "akshare:stock_zh_a_hist_min_em", "raw": item},
            })
        return rows, raw

    def _quote_sync(self, stock_code: str) -> tuple[dict | None, list[dict]]:
        import akshare as ak

        code = normalize_symbol(stock_code)
        raw = frame_records(ak.stock_bid_ask_em(symbol=code))
        info = self._item_map(raw)
        last_price = safe_float(first(info, ["最新", "最新价", "现价"]))
        pre_close = safe_float(first(info, ["昨收", "昨收价"]))
        change = last_price - pre_close if last_price is not None and pre_close not in (None, 0) else None
        change_pct = change / pre_close * 100 if change is not None and pre_close not in (None, 0) else None
        return {
            "stock_code": code,
            "quote_time": datetime.now(tz=ZoneInfo("UTC")),
            "source": "akshare",
            "last_price": last_price,
            "pre_close_price": pre_close,
            "change_amount": change,
            "change_pct": change_pct,
            "open_price": safe_float(first(info, ["今开", "开盘"])),
            "high_price": safe_float(first(info, ["最高"])),
            "low_price": safe_float(first(info, ["最低"])),
            "volume_hand": safe_int(first(info, ["成交量", "总手"])),
            "amount_yuan": safe_float(first(info, ["成交额"])),
            "order_book": {},
            "raw_payload": {"source": "akshare:stock_bid_ask_em", "raw": raw},
        }, raw

    def _ticks_sync(self, stock_code: str) -> tuple[list[dict], list[dict]]:
        import akshare as ak

        code = normalize_symbol(stock_code)
        raw = frame_records(ak.stock_zh_a_tick_tx_js(symbol=market_prefix(code)))
        today = datetime.now(tz=ZoneInfo("Asia/Shanghai")).date()
        rows = []
        for item in raw:
            trade_time = parse_datetime(first(item, ["成交时间", "时间", "time"]), trade_date=today)
            price = safe_float(first(item, ["成交价格", "价格", "price"]))
            volume_hand = safe_int(first(item, ["成交量", "volume", "成交量(手)"]))
            if trade_time is None:
                continue
            rows.append({
                "stock_code": code,
                "trade_time": trade_time,
                "source": "akshare:stock_zh_a_tick_tx_js",
                "price": price,
                "volume_hand": volume_hand,
                "amount_yuan": safe_float(first(item, ["成交金额", "amount"])),
                "side": parse_trade_side(first(item, ["性质", "方向", "type"])),
                "metadata_json": {"source": "akshare:stock_zh_a_tick_tx_js", "raw": item},
            })
        return rows, raw

    def _sectors_sync(self, sector_type: str) -> tuple[list[dict], list[dict]]:
        import akshare as ak

        normalized_type = self._sector_type(sector_type)
        try:
            if normalized_type == "concept":
                raw = frame_records(ak.stock_board_concept_name_em())
                source = "akshare:stock_board_concept_name_em"
            else:
                raw = frame_records(ak.stock_board_industry_name_em())
                source = "akshare:stock_board_industry_name_em"
                normalized_type = "industry"
            return self._sector_rows_from_raw(raw, normalized_type=normalized_type, source=source)
        except Exception as em_exc:
            try:
                if normalized_type == "concept":
                    raw = frame_records(ak.stock_board_concept_name_ths())
                    source = "akshare:stock_board_concept_name_ths"
                else:
                    raw = frame_records(ak.stock_board_industry_name_ths())
                    source = "akshare:stock_board_industry_name_ths"
                    normalized_type = "industry"
            except Exception as ths_exc:
                raise RuntimeError(
                    "sector catalog providers failed: "
                    f"eastmoney={type(em_exc).__name__}: {em_exc}; "
                    f"ths={type(ths_exc).__name__}: {ths_exc}"
                ) from ths_exc
            rows, raw_records = self._sector_rows_from_raw(raw, normalized_type=normalized_type, source=source)
            for row in rows:
                row["metadata_json"]["fallback_from"] = "eastmoney"
                row["metadata_json"]["fallback_error"] = f"{type(em_exc).__name__}: {em_exc}"
            return rows, raw_records

    def _sector_rows_from_raw(self, raw: list[dict], *, normalized_type: str, source: str) -> tuple[list[dict], list[dict]]:
        rows = []
        for item in raw:
            name = first(item, ["板块名称", "名称", "name"])
            if not name:
                continue
            raw_code = str(first(item, ["板块代码", "代码", "code"]) or name)
            code = self._canonical_sector_code(normalized_type, raw_code, source)
            rows.append({
                "sector_code": code,
                "sector_name": str(name),
                "sector_type": normalized_type,
                "source": source,
                "metadata_json": {"source": source, "raw_code": raw_code, "raw": item},
            })
        return rows, raw

    def _sector_components_sync(self, sector_type: str, sector_code: str) -> tuple[list[dict], list[dict]]:
        snapshot = self._sector_component_snapshot_sync(sector_type, sector_code)
        return snapshot.rows, snapshot.raw

    def _sector_component_snapshot_sync(self, sector_type: str, sector_code: str) -> SectorComponentSnapshot:
        import akshare as ak

        normalized_type = self._sector_type(sector_type)
        symbol = self._raw_sector_code(sector_code)
        is_complete = True
        fetched_page_count = 1
        expected_page_count: int | None = 1
        if self._is_ths_sector_code(sector_code):
            raw, source, is_complete, fetched_page_count, expected_page_count = self._sector_components_ths(normalized_type, sector_code)
        else:
            try:
                if normalized_type == "concept":
                    raw = frame_records(ak.stock_board_concept_cons_em(symbol=symbol))
                    source = "akshare:stock_board_concept_cons_em"
                else:
                    raw = frame_records(ak.stock_board_industry_cons_em(symbol=symbol))
                    source = "akshare:stock_board_industry_cons_em"
                    normalized_type = "industry"
            except Exception as em_exc:
                raw, source, is_complete, fetched_page_count, expected_page_count = self._sector_components_ths(normalized_type, sector_code)
                for item in raw:
                    item["fallback_from"] = "eastmoney"
                    item["fallback_error"] = f"{type(em_exc).__name__}: {em_exc}"
        rows = []
        for item in raw:
            code = first(item, ["代码", "股票代码", "stock_code"])
            if not code:
                continue
            rows.append({
                "sector_code": str(sector_code),
                "stock_code": normalize_symbol(str(code)),
                "weight": safe_float(first(item, ["权重", "weight"])),
                "start_date": None,
                "end_date": None,
                "source": source,
                "metadata_json": {"sector_type": normalized_type, "source": source, "raw": item},
            })
        return SectorComponentSnapshot(
            rows=rows,
            raw=raw,
            source=source,
            is_complete=is_complete,
            fetched_page_count=fetched_page_count,
            expected_page_count=expected_page_count,
        )

    @staticmethod
    def _canonical_sector_code(sector_type: str, raw_code: str, source: str) -> str:
        if source.endswith("_ths"):
            return f"ths_{sector_type}_{raw_code}"
        return raw_code

    @staticmethod
    def _is_ths_sector_code(sector_code: str) -> bool:
        return sector_code.startswith("ths_concept_") or sector_code.startswith("ths_industry_")

    @staticmethod
    def _raw_sector_code(sector_code: str) -> str:
        if sector_code.startswith("ths_concept_"):
            return sector_code.removeprefix("ths_concept_")
        if sector_code.startswith("ths_industry_"):
            return sector_code.removeprefix("ths_industry_")
        return sector_code

    def _sector_components_ths(self, sector_type: str, sector_code: str) -> tuple[list[dict], str, bool, int, int | None]:
        import requests

        raw_code = self._raw_sector_code(sector_code)
        if sector_type == "concept":
            base_path = "gn/detail"
            source = "akshare:stock_board_concept_detail_ths_html"
        else:
            base_path = "thshy/detail"
            source = "akshare:stock_board_industry_detail_ths_html"
        first_url = f"https://q.10jqka.com.cn/{base_path}/code/{raw_code}/"
        with self._ths_session_lock:
            session = self._get_ths_session(requests)
            first_rows, expected_page_count, field, order, actual_page = self._fetch_ths_component_page(
                session,
                first_url,
                source_url=first_url,
            )
            if actual_page not in {None, 1}:
                raise RuntimeError(f"THS first component page mismatch: expected=1 actual={actual_page}")
            expected_page_count = expected_page_count or 1
            if expected_page_count < 1 or expected_page_count > self._THS_MAX_PAGE_COUNT:
                raise RuntimeError(f"THS component page count out of range: {expected_page_count}")
            pages = [first_rows]
            for page in range(2, expected_page_count + 1):
                page_url = (
                    f"https://q.10jqka.com.cn/{base_path}/field/{field}/order/{order}/"
                    f"page/{page}/ajax/1/code/{raw_code}/"
                )
                rows, page_count, _, _, actual_page = self._fetch_ths_component_page(
                    session,
                    page_url,
                    source_url=page_url,
                    ajax=True,
                )
                if page_count not in {None, expected_page_count} or actual_page not in {None, page}:
                    raise RuntimeError(
                        "THS component pagination mismatch: "
                        f"expected={page}/{expected_page_count} actual={actual_page}/{page_count}"
                    )
                if not rows:
                    raise RuntimeError(f"THS component page returned no rows: page={page}/{expected_page_count}")
                pages.append(rows)
            deduped = {str(row["代码"]): row for rows in pages for row in rows}
        rows = list(deduped.values())
        if not rows:
            raise RuntimeError("THS component snapshot returned no valid stock rows")
        return rows, source, True, expected_page_count, expected_page_count

    def _get_ths_session(self, requests):
        if self._ths_session is None:
            session = requests.Session()
            session.headers.update({
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html, */*; q=0.01",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Referer": "https://q.10jqka.com.cn/",
            })
            self._ths_session = session
        return self._ths_session

    def _ths_get(self, session, url: str, *, ajax: bool = False):
        elapsed = time_module.monotonic() - self._ths_last_request_at
        if elapsed < self._THS_REQUEST_INTERVAL_SECONDS:
            time_module.sleep(self._THS_REQUEST_INTERVAL_SECONDS - elapsed)
        headers = {"X-Requested-With": "XMLHttpRequest"} if ajax else None
        response = session.get(url, headers=headers, timeout=20)
        self._ths_last_request_at = time_module.monotonic()
        response.raise_for_status()
        response.encoding = response.apparent_encoding or "gbk"
        return response

    def _fetch_ths_component_page(self, session, url: str, *, source_url: str, ajax: bool = False):
        last_error: Exception | None = None
        for attempt in range(1, self._THS_PAGE_RETRY_COUNT + 1):
            try:
                response = self._ths_get(session, url, ajax=ajax)
                if self._is_ths_login_page(response.text):
                    raise ThsAuthenticationRequiredError("THS component pagination requires an authenticated session")
                parsed = self._parse_ths_component_page(response.text, source_url=source_url)
                if not parsed[0]:
                    raise RuntimeError("THS response contained no component rows")
                return parsed
            except ThsAuthenticationRequiredError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt == self._THS_PAGE_RETRY_COUNT:
                    break
                delay = self._THS_RETRY_BACKOFF_SECONDS * attempt
                logger.warning(
                    "THS component page retry scheduled: attempt=%s/%s delay=%ss url=%s error=%s: %s",
                    attempt,
                    self._THS_PAGE_RETRY_COUNT,
                    delay,
                    url,
                    type(exc).__name__,
                    exc,
                )
                time_module.sleep(delay)
        raise RuntimeError(
            f"THS component page failed after {self._THS_PAGE_RETRY_COUNT} attempts: "
            f"{type(last_error).__name__}: {last_error}"
        ) from last_error

    @staticmethod
    def _is_ths_login_page(html: str) -> bool:
        return "同花顺-用户登录" in html or ("短信登录" in html and "密码登录" in html)

    @staticmethod
    def _parse_ths_component_page(html: str, *, source_url: str) -> tuple[list[dict], int | None, str, str, int | None]:
        import re

        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, features="lxml")
        page_info = soup.select_one(".page_info")
        current_page: int | None = None
        expected_page_count: int | None = None
        if page_info:
            matched = re.search(r"(\d+)\s*/\s*(\d+)", page_info.get_text(" ", strip=True))
            if matched:
                current_page = int(matched.group(1))
                expected_page_count = int(matched.group(2))
        current_sort = soup.select_one(".m-pager-table th.cur a[field]")
        field = current_sort.get("field") if current_sort else "199112"
        order = current_sort.get("order") if current_sort else "desc"
        rows: list[dict] = []
        for tr in soup.select("table tbody tr"):
            cells = [cell.get_text(strip=True) for cell in tr.find_all("td")]
            if len(cells) < 3:
                continue
            code = cells[1]
            name = cells[2]
            if not code or not name:
                continue
            rows.append({
                "序号": cells[0],
                "代码": code,
                "名称": name,
                "现价": cells[3] if len(cells) > 3 else None,
                "涨跌幅": cells[4] if len(cells) > 4 else None,
                "raw_cells": cells,
                "source_url": source_url,
            })
        return rows, expected_page_count, str(field), str(order), current_page

    def _sector_bars_sync(self, sector_type: str, sector_code: str, start_date: date | None, end_date: date | None) -> tuple[list[dict], list[dict]]:
        import akshare as ak

        normalized_type = self._sector_type(sector_type)
        start_text = (start_date or date(1990, 1, 1)).strftime("%Y%m%d")
        end_text = (end_date or date.today()).strftime("%Y%m%d")
        if normalized_type == "concept":
            raw = frame_records(ak.stock_board_concept_hist_em(symbol=sector_code, period="daily", start_date=start_text, end_date=end_text, adjust=""))
            source = "akshare:stock_board_concept_hist_em"
        else:
            raw = frame_records(ak.stock_board_industry_hist_em(symbol=sector_code, period="日k", start_date=start_text, end_date=end_text, adjust=""))
            source = "akshare:stock_board_industry_hist_em"
            normalized_type = "industry"
        rows = []
        for item in raw:
            trade_date = parse_date(first(item, ["日期", "date"]))
            if trade_date is None:
                continue
            rows.append({
                "sector_code": str(sector_code),
                "trade_date": trade_date,
                "source": source,
                "open_price": safe_float(first(item, ["开盘", "open"])),
                "high_price": safe_float(first(item, ["最高", "high"])),
                "low_price": safe_float(first(item, ["最低", "low"])),
                "close_price": safe_float(first(item, ["收盘", "close"])),
                "change_pct": safe_float(first(item, ["涨跌幅", "change_pct"])),
                "amount_yuan": safe_float(first(item, ["成交额", "amount"])),
                "metadata_json": {"sector_type": normalized_type, "source": source, "raw": item},
            })
        return rows, raw

    def _indexes_sync(self, index_code: str | None) -> tuple[list[dict], list[dict]]:
        import akshare as ak

        raw = []
        for symbol in ["沪深重要指数", "上证系列指数", "深证系列指数", "中证系列指数"]:
            try:
                raw.extend(frame_records(ak.stock_zh_index_spot_em(symbol=symbol)))
            except Exception:
                if index_code:
                    continue
                raise
        target = normalize_symbol(index_code) if index_code else None
        rows = []
        for item in raw:
            code = str(first(item, ["代码", "index_code", "code"]) or "")
            if not code:
                continue
            if target and normalize_symbol(code).replace("sh", "").replace("sz", "").replace("csi", "") != target:
                continue
            rows.append({
                "index_code": code,
                "index_name": str(first(item, ["名称", "name"]) or code),
                "market": "CN",
                "publisher": None,
                "metadata_json": {"source": "akshare:stock_zh_index_spot_em", "raw": item},
            })
        return rows, raw

    def _index_components_sync(self, index_code: str) -> tuple[list[dict], list[dict]]:
        import akshare as ak

        code = normalize_symbol(index_code).replace("sh", "").replace("sz", "").replace("csi", "")
        raw = frame_records(ak.index_stock_cons(symbol=code))
        rows = []
        for item in raw:
            stock_code = first(item, ["品种代码", "成分券代码", "股票代码", "代码", "stock_code"])
            if not stock_code:
                continue
            rows.append({
                "index_code": code,
                "stock_code": normalize_symbol(str(stock_code)),
                "weight": safe_float(first(item, ["权重", "weight"])),
                "effective_date": parse_date(first(item, ["纳入日期", "日期", "date"])),
                "source": "akshare:index_stock_cons",
                "metadata_json": {"source": "akshare:index_stock_cons", "raw": item},
            })
        return rows, raw

    def _index_bars_sync(self, index_code: str, start_date: date | None, end_date: date | None) -> tuple[list[dict], list[dict]]:
        import akshare as ak

        symbol = market_prefix(index_code)
        raw = frame_records(
            ak.stock_zh_index_daily_em(
                symbol=symbol,
                start_date=(start_date or date(1990, 1, 1)).strftime("%Y%m%d"),
                end_date=(end_date or date.today()).strftime("%Y%m%d"),
            )
        )
        rows = []
        for item in raw:
            trade_date = parse_date(first(item, ["date", "日期"]))
            if trade_date is None:
                continue
            rows.append({
                "index_code": symbol,
                "trade_date": trade_date,
                "source": "akshare:stock_zh_index_daily_em",
                "open_price": safe_float(first(item, ["open", "开盘"])),
                "high_price": safe_float(first(item, ["high", "最高"])),
                "low_price": safe_float(first(item, ["low", "最低"])),
                "close_price": safe_float(first(item, ["close", "收盘"])),
                "change_pct": safe_float(first(item, ["涨跌幅", "change_pct"])),
                "amount_yuan": safe_float(first(item, ["amount", "成交额"])),
                "metadata_json": {"source": "akshare:stock_zh_index_daily_em", "raw": item},
            })
        return rows, raw

    def _stock_fund_flow_sync(self, stock_code: str, start_date: date | None, end_date: date | None) -> tuple[list[dict], list[dict]]:
        import akshare as ak

        code = normalize_symbol(stock_code)
        raw = frame_records(ak.stock_individual_fund_flow(stock=code, market=self._market(code).lower().replace("sse", "sh").replace("szse", "sz")))
        rows = []
        for index, item in enumerate(raw):
            trade_date = parse_date(first(item, ["日期", "date"]))
            if trade_date is None:
                continue
            if start_date and trade_date < start_date:
                continue
            if end_date and trade_date > end_date:
                continue
            rows.append({
                "stock_code": code,
                "trade_date": trade_date,
                "source": "akshare:stock_individual_fund_flow",
                "main_net_inflow": safe_float(first(item, ["主力净流入-净额", "主力净流入净额", "主力净流入"])),
                "main_net_ratio": safe_float(first(item, ["主力净流入-净占比", "主力净占比"])),
                "big_order_net_inflow": safe_float(first(item, ["大单净流入-净额", "大单净流入净额"])),
                "big_order_net_ratio": safe_float(first(item, ["大单净流入-净占比", "大单净占比"])),
                "super_large_net_inflow": safe_float(first(item, ["超大单净流入-净额", "超大单净流入净额"])),
                "medium_net_inflow": safe_float(first(item, ["中单净流入-净额", "中单净流入净额"])),
                "small_net_inflow": safe_float(first(item, ["小单净流入-净额", "小单净流入净额"])),
                "close_price": safe_float(first(item, ["收盘价", "最新价", "close"])),
                "change_pct": safe_float(first(item, ["涨跌幅", "change_pct"])),
                "rank": index + 1,
                "metadata_json": {"source": "akshare:stock_individual_fund_flow", "raw": item},
            })
        return rows, raw

    def _sector_fund_flow_sync(self, sector_type: str) -> tuple[list[dict], list[dict]]:
        import akshare as ak

        normalized_type = self._sector_type(sector_type)
        if normalized_type == "concept":
            raw = frame_records(ak.stock_fund_flow_concept(symbol="即时"))
            source = "akshare:stock_fund_flow_concept"
        else:
            raw = frame_records(ak.stock_fund_flow_industry(symbol="即时"))
            source = "akshare:stock_fund_flow_industry"
            normalized_type = "industry"
        today = date.today()
        rows = []
        for index, item in enumerate(raw):
            name = first(item, ["行业", "名称", "板块名称", "concept", "sector_name"])
            if not name:
                continue
            code = str(first(item, ["代码", "板块代码", "sector_code"]) or name)
            rows.append({
                "sector_code": code,
                "sector_name": str(name),
                "sector_type": normalized_type,
                "trade_date": parse_date(first(item, ["日期", "date"])) or today,
                "source": source,
                "main_net_inflow": safe_float(first(item, ["净额", "主力净流入-净额", "今日主力净流入-净额"])),
                "main_net_ratio": safe_float(first(item, ["净占比", "主力净流入-净占比", "今日主力净流入-净占比"])),
                "change_pct": safe_float(first(item, ["涨跌幅", "change_pct"])),
                "rank": safe_int(first(item, ["序号", "排名"])) or index + 1,
                "metadata_json": {"source": source, "raw": item},
            })
        return rows, raw

    def _lhb_sync(self, stock_code: str | None, start_date: date | None, end_date: date | None) -> tuple[dict[str, list[dict]], list[dict]]:
        import akshare as ak

        start_text = (start_date or date.today()).strftime("%Y%m%d")
        end_text = (end_date or start_date or date.today()).strftime("%Y%m%d")
        try:
            raw_events = frame_records(ak.stock_lhb_detail_em(start_date=start_text, end_date=end_text))
        except Exception as exc:
            message = str(exc)
            if "NoneType" in message or "股票代码" in message:
                raw_events = []
            else:
                raise
        target = normalize_symbol(stock_code) if stock_code else None
        events = []
        for item in raw_events:
            code = first(item, ["代码", "股票代码", "stock_code"])
            trade_date = parse_date(first(item, ["上榜日", "日期", "trade_date"])) or parse_date(start_text)
            if not code or trade_date is None:
                continue
            code = normalize_symbol(str(code))
            if target and code != target:
                continue
            events.append({
                "stock_code": code,
                "stock_name": first(item, ["名称", "股票名称", "stock_name"]),
                "trade_date": trade_date,
                "source": "akshare:stock_lhb_detail_em",
                "reason": str(first(item, ["解读", "上榜原因", "原因", "reason"]) or "龙虎榜"),
                "close_price": safe_float(first(item, ["收盘价", "close"])),
                "change_pct": safe_float(first(item, ["涨跌幅", "change_pct"])),
                "turnover_amount": safe_float(first(item, ["成交额", "成交金额", "turnover_amount"])),
                "net_buy_amount": safe_float(first(item, ["净买额", "龙虎榜净买额", "net_buy_amount"])),
                "buy_amount": safe_float(first(item, ["买入额", "买入金额", "buy_amount"])),
                "sell_amount": safe_float(first(item, ["卖出额", "卖出金额", "sell_amount"])),
                "metadata_json": {"source": "akshare:stock_lhb_detail_em", "raw": item},
            })

        seats = []
        if target and start_date and end_date and start_date == end_date:
            for flag, side in [("买入", "buy"), ("卖出", "sell")]:
                try:
                    seat_rows = frame_records(ak.stock_lhb_stock_detail_em(symbol=target, date=start_text, flag=flag))
                except Exception as exc:
                    message = str(exc)
                    if "NoneType" in message or "股票代码" in message:
                        seat_rows = []
                    else:
                        raise
                for index, item in enumerate(seat_rows):
                    seat_name = first(item, ["营业部名称", "交易营业部名称", "名称", "seat_name"])
                    if not seat_name:
                        continue
                    seats.append({
                        "stock_code": target,
                        "trade_date": start_date,
                        "source": "akshare:stock_lhb_stock_detail_em",
                        "side": side,
                        "seat_name": str(seat_name),
                        "buy_amount": safe_float(first(item, ["买入金额", "买入额", "buy_amount"])),
                        "sell_amount": safe_float(first(item, ["卖出金额", "卖出额", "sell_amount"])),
                        "net_amount": safe_float(first(item, ["净额", "净买额", "net_amount"])),
                        "rank": safe_int(first(item, ["序号", "排名"])) or index + 1,
                        "metadata_json": {"source": "akshare:stock_lhb_stock_detail_em", "flag": flag, "raw": item},
                    })
        return {"events": events, "seats": seats}, raw_events

    def _announcements_sync(
        self,
        stock_code: str,
        start_date: date | None,
        end_date: date | None,
        keyword: str | None,
    ) -> tuple[list[dict], list[dict]]:
        import akshare as ak

        code = normalize_symbol(stock_code)
        raw = frame_records(
            ak.stock_zh_a_disclosure_report_cninfo(
                symbol=code,
                market="沪深京",
                keyword=keyword or "",
                category="",
                start_date=(start_date or date.today()).strftime("%Y%m%d"),
                end_date=(end_date or start_date or date.today()).strftime("%Y%m%d"),
            )
        )
        rows = []
        for item in raw:
            title = first(item, ["公告标题", "标题", "title"])
            published_at = parse_datetime(first(item, ["公告时间", "发布时间", "published_at"]))
            if not title or published_at is None:
                continue
            rows.append({
                "stock_code": normalize_symbol(str(first(item, ["代码", "股票代码"]) or code)),
                "stock_name": first(item, ["简称", "股票简称", "名称"]),
                "title": str(title),
                "category": first(item, ["公告类别", "类别", "category"]),
                "published_at": published_at,
                "url": first(item, ["公告链接", "链接", "url"]),
                "source": "akshare:stock_zh_a_disclosure_report_cninfo",
                "metadata_json": {"source": "akshare:stock_zh_a_disclosure_report_cninfo", "raw": item},
            })
        return rows, raw

    def _item_map(self, rows: list[dict]) -> dict:
        result = {}
        for row in rows:
            key = row.get("item") or row.get("项目") or row.get("名称")
            value = row.get("value") or row.get("值") or row.get("数据")
            if key is not None:
                result[str(key)] = value
        return result or (rows[0] if rows else {})

    def _market(self, code: str) -> str:
        if code.startswith("6"):
            return "SH"
        if code.startswith(("0", "3")):
            return "SZ"
        if code.startswith(("4", "8")):
            return "BJ"
        return "CN"

    def _sector_type(self, value: str | None) -> str:
        text = (value or "industry").strip().lower()
        if text in {"concept", "概念"}:
            return "concept"
        if text in {"region", "area", "地区"}:
            return "region"
        return "industry"


class MootdxProvider:
    code = "mootdx"
    market = "std"
    bestip = False
    timeout_seconds = 30
    auto_retry = 3
    fallback_server_limit = 12

    def __init__(self) -> None:
        self._client = None
        self._client_label = None
        self._client_lock = threading.RLock()
        self._stocks_cache: dict[int, list[dict]] = {}

    async def stock_basic(self, stock_code: str) -> tuple[dict | None, list[dict]]:
        return await asyncio.to_thread(self._stock_basic_sync, stock_code)

    async def stock_basic_list(self) -> tuple[list[dict], set[str], list[dict]]:
        return await asyncio.to_thread(self._stock_basic_list_sync)

    async def daily_bars(self, stock_code: str, *, limit: int) -> tuple[list[dict], list[dict]]:
        return await asyncio.to_thread(self._daily_bars_sync, stock_code, limit)

    async def minute_bars(self, stock_code: str) -> tuple[list[dict], list[dict]]:
        return await asyncio.to_thread(self._minute_bars_sync, stock_code)

    async def quote(self, stock_code: str) -> tuple[dict | None, list[dict]]:
        return await asyncio.to_thread(self._quote_sync, stock_code)

    async def quote_batch(self, stock_codes: list[str]) -> tuple[list[dict], list[dict]]:
        return await asyncio.to_thread(self._quote_batch_sync, stock_codes)

    async def ticks(self, stock_code: str, *, date_value: date | None = None) -> tuple[list[dict], list[dict]]:
        return await asyncio.to_thread(self._ticks_sync, stock_code, date_value)

    async def sectors(self, sector_type: str) -> tuple[list[dict], list[dict]]:
        return await asyncio.to_thread(self._sectors_sync, sector_type)

    async def sector_components(self, sector_type: str, sector_code: str) -> tuple[list[dict], list[dict]]:
        return await asyncio.to_thread(self._sector_components_sync, sector_type, sector_code)

    async def index_bars(self, index_code: str, *, limit: int) -> tuple[list[dict], list[dict]]:
        return await asyncio.to_thread(self._index_bars_sync, index_code, limit)

    def _quote_client(self, *, server: tuple[str, int] | None = None, bestip: bool | None = None):
        from mootdx.quotes import Quotes

        kwargs = {
            "market": self.market,
                "bestip": self.bestip if bestip is None else bestip,
                "timeout": self.timeout_seconds,
                "multithread": True,
                "heartbeat": False,
                "auto_retry": self.auto_retry,
                "raise_exception": True,
            }
        if server is not None:
            kwargs["server"] = server
            kwargs["bestip"] = False
        return Quotes.factory(**kwargs)

    def _server_candidates(self) -> list[tuple[str, tuple[str, int] | None]]:
        candidates: list[tuple[str, tuple[str, int] | None]] = []
        try:
            from mootdx.consts import HQ_HOSTS

            for name, host, port in HQ_HOSTS[: self.fallback_server_limit]:
                candidates.append((str(name), (str(host), int(port))))
        except Exception:
            pass
        if not candidates:
            candidates.append(("bestip", None))
        return candidates

    def _close_client(self) -> None:
        client = getattr(self._client, "client", None)
        disconnect = getattr(client, "disconnect", None)
        if callable(disconnect):
            with suppress(Exception):
                disconnect()
        if self._client is not None:
            with suppress(Exception):
                self._client.client = None
        self._client = None
        self._client_label = None

    def close(self) -> None:
        with self._client_lock:
            self._close_client()

    def _call_quotes(self, operation, *, require_records: bool = False):
        def invoke(client):
            result = operation(client)
            if require_records and not frame_records(result):
                raise RuntimeError("MooTDX returned an empty quote response")
            return result

        with self._client_lock:
            errors = []
            if self._client is not None:
                try:
                    return invoke(self._client)
                except Exception as exc:
                    errors.append(f"{self._client_label or 'cached'}: {exc}")
                    self._close_client()

            for label, server in self._server_candidates():
                try:
                    self._client = self._quote_client(server=server, bestip=(server is None))
                    self._client_label = label
                    return invoke(self._client)
                except Exception as exc:
                    errors.append(f"{label}: {exc}")
                    self._close_client()
            raise RuntimeError("; ".join(errors) or "MooTDX connection failed")

    def _tdx_markets(self, code: str) -> list[int]:
        if code.startswith("6"):
            return [1, 0]
        return [0, 1]

    def _stock_basic_sync(self, stock_code: str) -> tuple[dict | None, list[dict]]:
        code = normalize_symbol(stock_code)
        raw_rows: list[dict] = []
        for market_id in self._tdx_markets(code):
            if market_id not in self._stocks_cache:
                self._stocks_cache[market_id] = frame_records(self._call_quotes(lambda quotes: quotes.stocks(market=market_id)))
            rows = self._stocks_cache[market_id]
            raw_rows.extend(rows)
            match = next((row for row in rows if str(row.get("code")) == code), None)
            if match:
                market = self._market(code)
                safe_match = json_safe(match)
                return {
                    "stock_code": code,
                    "stock_name": str(safe_match.get("name") or code).strip(),
                    "market": "CN",
                    "exchange": {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}.get(market),
                    "list_date": None,
                    "delist_date": None,
                    "status": "active",
                    "industry": None,
                    "area": None,
                    "metadata_json": {"source": "mootdx:stocks", "market_id": market_id, "raw": safe_match},
                }, [safe_match]
        return None, json_safe(raw_rows[:100])

    def _stock_basic_list_sync(self) -> tuple[list[dict], set[str], list[dict]]:
        rows_by_code: dict[str, dict] = {}
        raw_all: list[dict] = []
        for market_id, market in [(0, "SZ"), (1, "SH")]:
            records = frame_records(self._call_quotes(lambda quotes: quotes.stocks(market=market_id)))
            raw_all.extend(records)
            for item in records:
                code = normalize_symbol(str(item.get("code") or ""))
                name = str(item.get("name") or "").strip()
                if not code or not name:
                    continue
                rows_by_code[code] = {
                    "stock_code": code,
                    "stock_name": name,
                    "market": "CN",
                    "exchange": {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}.get(market),
                    "list_date": None,
                    "delist_date": None,
                    "status": "active",
                    "industry": None,
                    "area": None,
                    "metadata_json": {"sync_source": "mootdx:stocks", "market_id": market_id, "raw": json_safe(item)},
                }
        return list(rows_by_code.values()), set(), json_safe(raw_all[:2000])

    def _daily_bars_sync(self, stock_code: str, limit: int) -> tuple[list[dict], list[dict]]:
        code = normalize_symbol(stock_code)
        raw = frame_records(self._call_quotes(lambda quotes: quotes.bars(symbol=code, frequency="day", offset=limit)))
        rows = []
        for item in raw:
            trade_date = parse_date(first(item, ["datetime", "date", "__index__"]))
            if trade_date is None:
                continue
            volume_hand = safe_int(first(item, ["vol", "volume"]))
            rows.append({
                "stock_code": code,
                "trade_date": trade_date,
                "source": "mootdx",
                "adjust_mode": "none",
                "open_price": safe_float(first(item, ["open"])),
                "high_price": safe_float(first(item, ["high"])),
                "low_price": safe_float(first(item, ["low"])),
                "close_price": safe_float(first(item, ["close"])),
                "pre_close_price": None,
                "change_amount": None,
                "change_pct": None,
                "volume_hand": volume_hand,
                "volume_share": volume_hand * 100 if volume_hand is not None else None,
                "amount_yuan": safe_float(first(item, ["amount"])),
                "turnover_rate": None,
                "metadata_json": {"source": "mootdx:bars", "raw": item},
            })
        return rows, raw

    def _minute_bars_sync(self, stock_code: str) -> tuple[list[dict], list[dict]]:
        code = normalize_symbol(stock_code)
        raw = frame_records(self._call_quotes(lambda quotes: quotes.minute(symbol=code)))
        today = datetime.now(tz=ZoneInfo("Asia/Shanghai")).date()
        rows = []
        for index, item in enumerate(raw):
            bar_time = parse_datetime(first(item, ["datetime", "date", "time"]), trade_date=today)
            if bar_time is None and "price" in item:
                bar_time = self._minute_bar_time(today, index)
            if bar_time is None:
                continue
            volume_hand = safe_int(first(item, ["vol", "volume"]))
            rows.append({
                "stock_code": code,
                "bar_time": bar_time,
                "interval": "1m",
                "source": "mootdx",
                "price": safe_float(first(item, ["price", "close"])),
                "avg_price": safe_float(first(item, ["avg_price", "average"])),
                "volume_hand": volume_hand,
                "volume_share": volume_hand * 100 if volume_hand is not None else None,
                "amount_yuan": safe_float(first(item, ["amount"])),
                "metadata_json": {"source": "mootdx:minute", "raw": item},
            })
        return rows, raw

    def _minute_bar_time(self, trade_date: date, index: int) -> datetime | None:
        if index < 0 or index >= 240:
            return None
        if index < 120:
            local_time = datetime.combine(trade_date, time(9, 31)) + timedelta(minutes=index)
        else:
            local_time = datetime.combine(trade_date, time(13, 1)) + timedelta(minutes=index - 120)
        return local_time.replace(tzinfo=ZoneInfo("Asia/Shanghai")).astimezone(ZoneInfo("UTC"))

    def _market(self, code: str) -> str:
        if code.startswith("6"):
            return "SH"
        if code.startswith(("0", "3")):
            return "SZ"
        if code.startswith(("4", "8")):
            return "BJ"
        return "CN"

    def _quote_sync(self, stock_code: str) -> tuple[dict | None, list[dict]]:
        code = normalize_symbol(stock_code)
        raw = frame_records(self._call_quotes(lambda quotes: quotes.quotes(symbol=[code]), require_records=True))
        if not raw:
            return None, raw
        return self._quote_row_from_item(code, raw[0]), raw

    def _quote_batch_sync(self, stock_codes: list[str]) -> tuple[list[dict], list[dict]]:
        codes = [normalize_symbol(stock_code) for stock_code in stock_codes if normalize_symbol(stock_code)]
        if not codes:
            return [], []
        raw = frame_records(self._call_quotes(lambda quotes: quotes.quotes(symbol=codes), require_records=True))
        rows: list[dict] = []
        for index, item in enumerate(raw):
            fallback_code = codes[index] if index < len(codes) else ""
            code = normalize_symbol(str(first(item, ["code", "symbol", "stock_code", "ts_code"]) or fallback_code))
            if not code:
                continue
            rows.append(self._quote_row_from_item(code, item))
        return rows, raw

    def _quote_row_from_item(self, code: str, item: dict) -> dict:
        last_price = safe_float(item.get("price"))
        pre_close = safe_float(item.get("last_close"))
        change = last_price - pre_close if last_price is not None and pre_close not in (None, 0) else None
        change_pct = change / pre_close * 100 if change is not None and pre_close not in (None, 0) else None
        return {
            "stock_code": code,
            "quote_time": datetime.now(tz=ZoneInfo("UTC")),
            "source": "mootdx",
            "last_price": last_price,
            "pre_close_price": pre_close,
            "change_amount": change,
            "change_pct": change_pct,
            "open_price": safe_float(item.get("open")),
            "high_price": safe_float(item.get("high")),
            "low_price": safe_float(item.get("low")),
            "volume_hand": safe_int(item.get("volume") or item.get("vol")),
            "amount_yuan": safe_float(item.get("amount")),
            "order_book": {"raw_levels": item},
            "raw_payload": {"source": "mootdx:quotes", "raw": item},
        }

    def _ticks_sync(self, stock_code: str, date_value: date | None) -> tuple[list[dict], list[dict]]:
        code = normalize_symbol(stock_code)
        if date_value:
            raw = frame_records(self._call_quotes(lambda quotes: quotes.transactions(symbol=code, date=date_value.strftime("%Y%m%d"))))
        else:
            raw = frame_records(self._call_quotes(lambda quotes: quotes.transaction(symbol=code)))
        today = date_value or datetime.now(tz=ZoneInfo("Asia/Shanghai")).date()
        rows = []
        for item in raw:
            trade_time = parse_datetime(first(item, ["datetime", "time", "date"]), trade_date=today)
            if trade_time is None:
                continue
            price = safe_float(first(item, ["price", "成交价格"]))
            volume_hand = safe_int(first(item, ["vol", "volume", "成交量"]))
            rows.append({
                "stock_code": code,
                "trade_time": trade_time,
                "source": "mootdx:transaction",
                "price": price,
                "volume_hand": volume_hand,
                "amount_yuan": safe_float(first(item, ["amount", "成交金额"])),
                "side": parse_trade_side(first(item, ["buyorsell", "side", "性质"])),
                "metadata_json": {"source": "mootdx:transaction", "raw": item},
            })
        return rows, raw

    def _sectors_sync(self, sector_type: str) -> tuple[list[dict], list[dict]]:
        raw = frame_records(self._call_quotes(lambda quotes: quotes.block(tofile="/tmp/mootdx-block.dat")))
        rows = []
        for item in raw:
            name = first(item, ["blockname", "name", "板块名称"])
            code = first(item, ["blockname", "code", "板块代码"]) or name
            if not name or not code:
                continue
            rows.append({
                "sector_code": str(code),
                "sector_name": str(name),
                "sector_type": "tdx_block",
                "source": "mootdx:block",
                "metadata_json": {"requested_sector_type": sector_type, "source": "mootdx:block", "raw": item},
            })
        return rows, raw

    def _sector_components_sync(self, sector_type: str, sector_code: str) -> tuple[list[dict], list[dict]]:
        raw = frame_records(self._call_quotes(lambda quotes: quotes.block(tofile="/tmp/mootdx-block.dat")))
        rows = []
        for item in raw:
            name = str(first(item, ["blockname", "name", "板块名称"]) or "")
            if name != sector_code:
                continue
            stocks = first(item, ["code", "stocks", "股票代码"]) or []
            if isinstance(stocks, str):
                stocks = [stocks]
            for stock in stocks if isinstance(stocks, list) else []:
                rows.append({
                    "sector_code": sector_code,
                    "stock_code": normalize_symbol(str(stock)),
                    "weight": None,
                    "start_date": None,
                    "end_date": None,
                    "source": "mootdx:block",
                    "metadata_json": {"sector_type": sector_type, "source": "mootdx:block", "raw": item},
                })
        return rows, raw

    def _index_bars_sync(self, index_code: str, limit: int) -> tuple[list[dict], list[dict]]:
        code = normalize_symbol(index_code).replace("sh", "").replace("sz", "")
        raw = frame_records(self._call_quotes(lambda quotes: quotes.index(symbol=code, frequency="day", offset=limit)))
        rows = []
        for item in raw:
            trade_date = parse_date(first(item, ["datetime", "date", "__index__"]))
            if trade_date is None:
                continue
            rows.append({
                "index_code": code,
                "trade_date": trade_date,
                "source": "mootdx:index",
                "open_price": safe_float(first(item, ["open"])),
                "high_price": safe_float(first(item, ["high"])),
                "low_price": safe_float(first(item, ["low"])),
                "close_price": safe_float(first(item, ["close"])),
                "change_pct": None,
                "amount_yuan": safe_float(first(item, ["amount"])),
                "metadata_json": {"source": "mootdx:index", "raw": item},
            })
        return rows, raw
