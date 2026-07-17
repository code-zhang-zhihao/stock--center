import asyncio
import hashlib
import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from app.modules.market_data.models import (
    CorporateAction,
    FinancialIndicator,
    FinancialStatement,
    IndexBasic,
    IndexComponent,
    LimitEventDaily,
    MarginDetailDaily,
    MarginSummaryDaily,
    SectorBasic,
    StockAdjustFactor,
    StockDailyBasic,
    StockHolderCount,
    StockTopHolder,
)
from app.modules.market_data.providers import AkShareProvider, MootdxProvider, SectorComponentSnapshot, frame_records, json_safe, normalize_symbol, parse_date, safe_float
from app.modules.market_data.repository import MarketDataRepository
from app.modules.market_data.tushare_runtime import TushareProviderFactory
from app.modules.market_data.tushare_mappers import TushareCanonicalMapper
from app.modules.market_data.tushare.contracts import TushareApiRequest
from app.modules.config_center.repository import ConfigCenterRepository


logger = logging.getLogger(__name__)


class TradeCalendarSyncRequest(BaseModel):
    year: int = Field(ge=1990, le=2100)
    market: str = Field(default="CN", min_length=1, max_length=20)
    mode: Literal["upsert", "rebuild"] = "upsert"
    source: str = Field(default="chinese_calendar", min_length=1, max_length=80)


class TradeCalendarSyncResult(BaseModel):
    year: int
    market: str
    mode: str
    source: str
    total_days: int
    open_days: int
    closed_days: int
    upserted_count: int
    deleted_count: int = 0


class SectorCatalogSyncRequest(BaseModel):
    sector_types: list[Literal["concept", "industry"]] = Field(default_factory=lambda: ["concept", "industry"])
    sync_components: bool = True
    limit_sectors: int | None = Field(default=None, ge=1, le=5000)
    max_concurrency: int = Field(default=1, ge=1, le=10)
    source: Literal["tushare", "akshare"] = "tushare"
    delete_missing_components: bool = True
    ths_request_interval_seconds: float = Field(default=0.8, ge=0.1, le=10)
    provider_timeout_seconds: int = Field(default=45, ge=5, le=600)


class SectorCatalogSyncResult(BaseModel):
    sector_count: int
    component_count: int
    inserted_component_count: int
    updated_component_count: int
    unchanged_component_count: int
    deleted_component_count: int
    incomplete_sector_count: int
    sector_types: list[str]
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class StockBasicSyncRequest(BaseModel):
    source: Literal["tushare", "akshare", "mootdx"] = "tushare"
    include_detail: bool = True
    detail_mode: Literal["missing_or_stale", "missing", "stale", "all", "none"] = "missing_or_stale"
    max_detail_per_run: int = Field(default=300, ge=0, le=2000)
    detail_refresh_days: int = Field(default=90, ge=1, le=3650)
    fallback_to_mootdx: bool = True
    mark_delisted: bool = True
    min_expected_count: int = Field(default=3000, ge=1, le=10000)
    provider_timeout_seconds: int = Field(default=120, ge=5, le=600)


class StockBasicSyncResult(BaseModel):
    source: str
    fetched_count: int
    upserted_count: int
    detail_enriched_count: int
    delisted_marked_count: int
    fallback_used: bool
    errors: list[str] = Field(default_factory=list)


CORE_INDEX_DEFINITIONS: dict[str, dict] = {
    "000001.SH": {"index_name": "上证综指", "publisher": "SSE", "component_required": False},
    "399001.SZ": {"index_name": "深证成指", "publisher": "SZSE", "component_required": True, "expected_component_count": 500},
    "399006.SZ": {"index_name": "创业板指", "publisher": "SZSE", "component_required": True, "expected_component_count": 100},
    "000300.SH": {"index_name": "沪深300", "publisher": "CSI", "component_required": True, "expected_component_count": 300},
    "000905.SH": {"index_name": "中证500", "publisher": "CSI", "component_required": True, "expected_component_count": 500},
    "000852.SH": {"index_name": "中证1000", "publisher": "CSI", "component_required": True, "expected_component_count": 1000},
    "000016.SH": {"index_name": "上证50", "publisher": "SSE", "component_required": True, "expected_component_count": 50},
}


class IndexCatalogSyncRequest(BaseModel):
    index_codes: list[str] = Field(default_factory=lambda: list(CORE_INDEX_DEFINITIONS.keys()))
    sync_components: bool = True
    component_index_codes: list[str] | None = None
    weight_lookback_months: int = Field(default=3, ge=1, le=24)
    source: Literal["tushare", "akshare"] = "tushare"
    fallback_to_akshare: bool = True
    provider_timeout_seconds: int = Field(default=120, ge=5, le=600)


class IndexCatalogSyncResult(BaseModel):
    source: str
    index_count: int
    component_count: int
    component_index_count: int
    component_required_count: int
    fallback_used: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TushareTopicSyncRequest(BaseModel):
    topic: Literal[
        "daily_basic", "adj_factor", "income", "balancesheet", "cashflow", "fina_indicator",
        "dividend", "margin", "margin_detail", "limit_list_d", "stk_holdernumber", "top10_holders",
    ]
    params: dict = Field(default_factory=dict)
    fields: str = ""
    limit: int = Field(default=5000, ge=1, le=10000)


class TushareTopicSyncResult(BaseModel):
    topic: str
    api_name: str
    fetched_count: int
    upserted_count: int
    normalized_table: str
    errors: list[str] = Field(default_factory=list)


def _code(record: dict) -> str:
    return normalize_symbol(str(record.get("ts_code") or record.get("con_code") or ""))


def _date(record: dict, *keys: str):
    for key in keys:
        value = parse_date(record.get(key))
        if value is not None:
            return value
    return None


def _metadata(api_name: str, record: dict) -> dict:
    return {"source": f"tushare:{api_name}", "raw": record}


def _canonical_index_code(index_code: str) -> str:
    code = normalize_symbol(str(index_code or ""))
    for prefix in ("sh", "sz", "csi"):
        if code.lower().startswith(prefix):
            return code[len(prefix) :]
    return code


def _daily_basic_rows(records: list[dict]) -> list[dict]:
    rows = []
    for record in records:
        code, trade_date = _code(record), _date(record, "trade_date")
        if code and trade_date:
            rows.append({"stock_code": code, "trade_date": trade_date, "source": "tushare:daily_basic", "turnover_rate": safe_float(record.get("turnover_rate")), "volume_ratio": safe_float(record.get("volume_ratio")), "pe": safe_float(record.get("pe")), "pb": safe_float(record.get("pb")), "total_share": safe_float(record.get("total_share")), "float_share": safe_float(record.get("float_share")), "total_mv": safe_float(record.get("total_mv")), "circ_mv": safe_float(record.get("circ_mv")), "metadata_json": _metadata("daily_basic", record)})
    return rows


def _adjust_factor_rows(records: list[dict]) -> list[dict]:
    rows = []
    for record in records:
        code, trade_date, factor = _code(record), _date(record, "trade_date"), safe_float(record.get("adj_factor"))
        if code and trade_date and factor is not None:
            rows.append({"stock_code": code, "trade_date": trade_date, "source": "tushare:adj_factor", "adj_factor": factor, "metadata_json": _metadata("adj_factor", record)})
    return rows


def _statement_rows(report_type: str, api_name: str):
    def normalize(records: list[dict]) -> list[dict]:
        rows = []
        for record in records:
            code, period = _code(record), _date(record, "end_date")
            if code and period:
                rows.append({"stock_code": code, "report_type": report_type, "report_period": period, "announcement_date": _date(record, "ann_date", "f_ann_date"), "source": f"tushare:{api_name}", "fields": record, "metadata_json": _metadata(api_name, record)})
        return rows
    return normalize


def _indicator_rows(records: list[dict]) -> list[dict]:
    rows = []
    for record in records:
        code, period = _code(record), _date(record, "end_date")
        if code and period:
            rows.append({"stock_code": code, "report_period": period, "announcement_date": _date(record, "ann_date"), "source": "tushare:fina_indicator", "indicators": record, "metadata_json": _metadata("fina_indicator", record)})
    return rows


def _dividend_rows(records: list[dict]) -> list[dict]:
    rows = []
    for record in records:
        code = _code(record)
        if code:
            rows.append({"stock_code": code, "action_type": "dividend", "ex_date": _date(record, "ex_date"), "announcement_date": _date(record, "ann_date"), "record_date": _date(record, "record_date"), "source": "tushare:dividend", "fields": record, "metadata_json": _metadata("dividend", record)})
    return rows


def _margin_summary_rows(records: list[dict]) -> list[dict]:
    rows = []
    for record in records:
        trade_date = _date(record, "trade_date")
        exchange = str(record.get("exchange_id") or record.get("exchange") or "ALL")
        if trade_date:
            rows.append({"trade_date": trade_date, "exchange": exchange, "source": "tushare:margin", "rzye": safe_float(record.get("rzye")), "rz_mre": safe_float(record.get("rzmre")), "rzche": safe_float(record.get("rzche")), "rqye": safe_float(record.get("rqye")), "rq_mcl": safe_float(record.get("rqmcl")), "rzrqye": safe_float(record.get("rzrqye")), "metadata_json": _metadata("margin", record)})
    return rows


def _margin_detail_rows(records: list[dict]) -> list[dict]:
    rows = []
    for record in records:
        code, trade_date = _code(record), _date(record, "trade_date")
        if code and trade_date:
            rows.append({"stock_code": code, "trade_date": trade_date, "exchange": record.get("exchange"), "source": "tushare:margin_detail", "rzye": safe_float(record.get("rzye")), "rz_mre": safe_float(record.get("rzmre")), "rzche": safe_float(record.get("rzche")), "rqye": safe_float(record.get("rqye")), "rq_mcl": safe_float(record.get("rqmcl")), "rzrqye": safe_float(record.get("rzrqye")), "metadata_json": _metadata("margin_detail", record)})
    return rows


def _limit_rows(records: list[dict]) -> list[dict]:
    rows = []
    for record in records:
        code, trade_date = _code(record), _date(record, "trade_date")
        if code and trade_date:
            limit_type = str(record.get("limit") or record.get("limit_type") or "unknown").lower()
            rows.append({"stock_code": code, "trade_date": trade_date, "event_type": limit_type, "source": "tushare:limit_list_d", "close_price": safe_float(record.get("close")), "limit_price": safe_float(record.get("limit_price")), "first_time": None, "last_time": None, "open_count": None, "turnover_amount": safe_float(record.get("amount")), "metadata_json": _metadata("limit_list_d", record)})
    return rows


def _holder_count_rows(records: list[dict]) -> list[dict]:
    rows = []
    for record in records:
        code, period = _code(record), _date(record, "end_date")
        if code and period:
            rows.append({"stock_code": code, "report_period": period, "announcement_date": _date(record, "ann_date"), "holder_count": safe_float(record.get("holder_num")), "source": "tushare:stk_holdernumber", "metadata_json": _metadata("stk_holdernumber", record)})
    return rows


def _top_holder_rows(records: list[dict]) -> list[dict]:
    rows = []
    for record in records:
        code, period, name = _code(record), _date(record, "end_date"), str(record.get("holder_name") or "")
        if code and period and name:
            rows.append({"stock_code": code, "report_period": period, "holder_name": name, "holder_type": record.get("holder_type"), "hold_amount": safe_float(record.get("hold_amount")), "hold_ratio": safe_float(record.get("hold_ratio")), "source": "tushare:top10_holders", "metadata_json": _metadata("top10_holders", record)})
    return rows


_TUSHARE_TOPIC_DEFINITIONS = {
    "daily_basic": {"api_name": "daily_basic", "model": StockDailyBasic, "table": "t_stock_daily_basic", "conflict": ["stock_code", "trade_date", "source"], "normalize": _daily_basic_rows},
    "adj_factor": {"api_name": "adj_factor", "model": StockAdjustFactor, "table": "t_stock_adjust_factor", "conflict": ["stock_code", "trade_date", "source"], "normalize": _adjust_factor_rows},
    "income": {"api_name": "income", "model": FinancialStatement, "table": "t_financial_statement", "conflict": ["stock_code", "report_type", "report_period", "source"], "normalize": _statement_rows("income", "income")},
    "balancesheet": {"api_name": "balancesheet", "model": FinancialStatement, "table": "t_financial_statement", "conflict": ["stock_code", "report_type", "report_period", "source"], "normalize": _statement_rows("balancesheet", "balancesheet")},
    "cashflow": {"api_name": "cashflow", "model": FinancialStatement, "table": "t_financial_statement", "conflict": ["stock_code", "report_type", "report_period", "source"], "normalize": _statement_rows("cashflow", "cashflow")},
    "fina_indicator": {"api_name": "fina_indicator", "model": FinancialIndicator, "table": "t_financial_indicator", "conflict": ["stock_code", "report_period", "source"], "normalize": _indicator_rows},
    "dividend": {"api_name": "dividend", "model": CorporateAction, "table": "t_corporate_action", "conflict": ["stock_code", "action_type", "ex_date", "announcement_date", "source"], "normalize": _dividend_rows},
    "margin": {"api_name": "margin", "model": MarginSummaryDaily, "table": "t_margin_summary_daily", "conflict": ["trade_date", "exchange", "source"], "normalize": _margin_summary_rows},
    "margin_detail": {"api_name": "margin_detail", "model": MarginDetailDaily, "table": "t_margin_detail_daily", "conflict": ["stock_code", "trade_date", "source"], "normalize": _margin_detail_rows},
    "limit_list_d": {"api_name": "limit_list_d", "model": LimitEventDaily, "table": "t_limit_event_daily", "conflict": ["stock_code", "trade_date", "event_type", "source"], "normalize": _limit_rows},
    "stk_holdernumber": {"api_name": "stk_holdernumber", "model": StockHolderCount, "table": "t_stock_holder_count", "conflict": ["stock_code", "report_period", "source"], "normalize": _holder_count_rows},
    "top10_holders": {"api_name": "top10_holders", "model": StockTopHolder, "table": "t_stock_top_holder", "conflict": ["stock_code", "report_period", "holder_name", "source"], "normalize": _top_holder_rows},
}


class MarketDataSyncError(Exception):
    def __init__(self, code: str, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class MarketDataSyncService:
    def __init__(
        self,
        repository: MarketDataRepository,
        *,
        akshare_provider: AkShareProvider | None = None,
        mootdx_provider: MootdxProvider | None = None,
        tushare_factory: TushareProviderFactory | None = None,
    ) -> None:
        self.repository = repository
        self.akshare = akshare_provider or AkShareProvider()
        self.mootdx = mootdx_provider or MootdxProvider()
        self.tushare = tushare_factory or TushareProviderFactory(ConfigCenterRepository(repository.session))
        self.tushare_mapper = TushareCanonicalMapper()

    async def sync_trade_calendar(self, payload: TradeCalendarSyncRequest) -> TradeCalendarSyncResult:
        logger.info(
            "market data sync_trade_calendar started: year=%s market=%s mode=%s source=%s",
            payload.year,
            payload.market,
            payload.mode,
            payload.source,
        )
        deleted_count = 0
        if payload.mode == "rebuild":
            deleted_count = await self.repository.delete_trade_calendar_year(
                year=payload.year,
                market=payload.market,
            )
        rows = self._build_trade_calendar_rows(
            year=payload.year,
            market=payload.market,
            source=payload.source,
        )
        upserted_count = await self.repository.upsert_trade_calendar(rows)
        open_days = sum(1 for row in rows if row["is_open"])
        logger.info(
            "market data sync_trade_calendar finished: year=%s market=%s total=%s open=%s closed=%s upserted=%s deleted=%s",
            payload.year,
            payload.market,
            len(rows),
            open_days,
            len(rows) - open_days,
            upserted_count,
            deleted_count,
        )
        return TradeCalendarSyncResult(
            year=payload.year,
            market=payload.market,
            mode=payload.mode,
            source=payload.source,
            total_days=len(rows),
            open_days=open_days,
            closed_days=len(rows) - open_days,
            upserted_count=upserted_count,
            deleted_count=deleted_count,
        )

    @staticmethod
    def _build_trade_calendar_rows(*, year: int, market: str, source: str) -> list[dict]:
        try:
            import chinese_calendar
        except ImportError as exc:
            raise MarketDataSyncError(
                "trade_calendar_dependency_missing",
                "缺少交易日历依赖，请在 python-back 目录安装 chinesecalendar",
                details={
                    "package": "chinesecalendar",
                    "import_name": "chinese_calendar",
                    "recommended_install": ".venv/bin/python -m pip install chinesecalendar",
                },
            ) from exc

        rows: list[dict] = []
        open_dates: list[date] = []
        current = date(year, 1, 1)
        end = date(year, 12, 31)
        while current <= end:
            is_open = current.weekday() < 5 and bool(chinese_calendar.is_workday(current))
            if is_open:
                open_dates.append(current)
            rows.append(
                {
                    "trade_date": current,
                    "market": market,
                    "is_open": is_open,
                    "previous_trade_date": None,
                    "next_trade_date": None,
                    "source": source,
                    "metadata_json": {
                        "calendar_rule": "weekday_and_chinese_calendar_workday",
                        "generated_year": year,
                    },
                }
            )
            current += timedelta(days=1)

        previous_by_date: dict[date, date | None] = {}
        next_by_date: dict[date, date | None] = {}
        for index, open_date in enumerate(open_dates):
            previous_by_date[open_date] = open_dates[index - 1] if index > 0 else None
            next_by_date[open_date] = open_dates[index + 1] if index + 1 < len(open_dates) else None

        for row in rows:
            if row["is_open"]:
                row["previous_trade_date"] = previous_by_date[row["trade_date"]]
                row["next_trade_date"] = next_by_date[row["trade_date"]]
        return rows

    async def sync_sector_catalog(self, payload: SectorCatalogSyncRequest) -> SectorCatalogSyncResult:
        errors: list[str] = []
        warnings: list[str] = []
        total_sectors = 0
        total_components = 0
        inserted_components = 0
        updated_components = 0
        unchanged_components = 0
        deleted_components = 0
        incomplete_sectors = 0
        self.akshare.set_ths_request_interval(payload.ths_request_interval_seconds)
        logger.info(
            "market data sync_sector_catalog started: sector_types=%s sync_components=%s limit_sectors=%s max_concurrency=%s ths_interval=%s timeout=%s",
            payload.sector_types,
            payload.sync_components,
            payload.limit_sectors,
            payload.max_concurrency,
            payload.ths_request_interval_seconds,
            payload.provider_timeout_seconds,
        )
        for sector_type in payload.sector_types:
            component_source = payload.source
            try:
                logger.info("market data sync_sector_catalog fetching sector list: sector_type=%s", sector_type)
                if payload.source == "tushare":
                    sectors, raw = await asyncio.wait_for(
                        self.tushare.call(
                            "sector_catalog_sync",
                            lambda provider: self.tushare_mapper.ths_sectors(provider, sector_type),
                            request_summary={"sector_type": sector_type},
                            execution_mode="scheduler",
                        ),
                        timeout=payload.provider_timeout_seconds,
                    )
                else:
                    sectors, raw = await asyncio.wait_for(self.akshare.sectors(sector_type), timeout=payload.provider_timeout_seconds)
            except Exception as exc:
                error = self._error_text(f"{sector_type}: sectors failed", exc)
                if payload.source != "tushare":
                    logger.warning("market data sync_sector_catalog sector list failed: %s", error)
                    errors.append(error)
                    continue
                logger.warning("market data sync_sector_catalog Tushare failed, fallback to AkShare: %s", error)
                errors.append(error)
                try:
                    sectors, raw = await asyncio.wait_for(self.akshare.sectors(sector_type), timeout=payload.provider_timeout_seconds)
                    component_source = "akshare"
                except Exception as fallback_exc:
                    fallback_error = self._error_text(f"{sector_type}: akshare fallback failed", fallback_exc)
                    logger.warning("market data sync_sector_catalog sector fallback failed: %s", fallback_error)
                    errors.append(fallback_error)
                    continue
            await self._capture_sync_raw(
                provider_code=component_source,
                capability="sector_catalog_sync",
                record_key=sector_type,
                request_params={"sector_type": sector_type, "limit_sectors": payload.limit_sectors},
                payload=raw,
                normalized_table="t_sector_basic",
            )
            if payload.limit_sectors:
                sectors = sectors[: payload.limit_sectors]
            logger.info(
                "market data sync_sector_catalog fetched sector list: sector_type=%s sector_count=%s raw_count=%s",
                sector_type,
                len(sectors),
                len(raw),
            )
            if sectors:
                upserted_sectors = await self.repository.upsert_rows(
                    SectorBasic,
                    sectors,
                    conflict_attrs=["sector_code"],
                    update_attrs=["sector_name", "sector_type", "source", "metadata_json"],
                )
                total_sectors += upserted_sectors
                await self.repository.commit()
                logger.info(
                    "market data sync_sector_catalog persisted sectors: sector_type=%s upserted=%s total=%s",
                    sector_type,
                    upserted_sectors,
                    total_sectors,
                )
            else:
                await self.repository.commit()
            if not payload.sync_components:
                continue
            semaphore = asyncio.Semaphore(payload.max_concurrency)

            async def fetch_components(sector: dict) -> tuple[dict, SectorComponentSnapshot | None, str | None]:
                async with semaphore:
                    try:
                        logger.info(
                            "market data sync_sector_catalog fetching components: sector_type=%s sector_code=%s sector_name=%s",
                            sector_type,
                            sector.get("sector_code"),
                            sector.get("sector_name"),
                        )
                        if component_source == "tushare":
                            rows, raw = await asyncio.wait_for(
                                self.tushare.call(
                                    "sector_components_sync",
                                    lambda provider: self.tushare_mapper.ths_sector_components(provider, str(sector["sector_code"])),
                                    request_summary={"sector_code": str(sector["sector_code"]), "sector_type": sector_type},
                                    execution_mode="scheduler",
                                ),
                                timeout=payload.provider_timeout_seconds,
                            )
                            snapshot = SectorComponentSnapshot(
                                rows=rows,
                                raw=raw,
                                source="tushare:ths_member",
                                is_complete=True,
                                fetched_page_count=1,
                                expected_page_count=1,
                            )
                        else:
                            snapshot = await asyncio.wait_for(
                                self.akshare.sector_component_snapshot(sector_type, str(sector["sector_code"])),
                                timeout=payload.provider_timeout_seconds,
                            )
                        for row in snapshot.rows:
                            row["sector_code"] = str(sector["sector_code"])
                            row["end_date"] = None
                            row["metadata_json"] = self._component_metadata(
                                row,
                                is_complete=snapshot.is_complete,
                                fetched_page_count=snapshot.fetched_page_count,
                                expected_page_count=snapshot.expected_page_count,
                            )
                        return sector, snapshot, None
                    except Exception as exc:
                        return sector, None, self._error_text(
                            f"{sector_type}/{sector.get('sector_code')}: components failed",
                            exc,
                        )

            results = await asyncio.gather(*(fetch_components(sector) for sector in sectors))
            for sector, snapshot, error in results:
                if error:
                    logger.warning("market data sync_sector_catalog components failed: %s", error)
                    errors.append(error)
                    continue
                assert snapshot is not None
                await self._capture_sync_raw(
                provider_code=component_source,
                    capability="sector_components_sync",
                    record_key=str(sector["sector_code"]),
                    request_params={"sector_type": sector_type, "sector_code": str(sector["sector_code"])},
                    payload=snapshot.raw,
                    normalized_table="t_sector_component",
                )
                components = snapshot.rows
                if not components:
                    await self.repository.commit()
                    logger.info(
                        "market data sync_sector_catalog components empty: sector_type=%s sector_code=%s",
                        sector_type,
                        sector.get("sector_code"),
                    )
                    continue
                try:
                    stats = await self.repository.sync_sector_component_rows(components)
                    total_components += len(components)
                    inserted_components += stats["inserted"]
                    updated_components += stats["updated"]
                    unchanged_components += stats["unchanged"]
                    if snapshot.is_complete and payload.delete_missing_components:
                        active = {str(row["stock_code"]) for row in components}
                        deleted = await self.repository.delete_missing_sector_components(
                            sector_code=str(sector["sector_code"]),
                            source=snapshot.source,
                            active_stock_codes=active,
                        )
                        deleted_components += deleted
                    elif not snapshot.is_complete:
                        incomplete_sectors += 1
                        warning = (
                            f"{sector_type}/{sector.get('sector_code')}: component snapshot incomplete "
                            f"source={snapshot.source} pages={snapshot.fetched_page_count}/{snapshot.expected_page_count or '?'}; "
                            "physical deletion skipped"
                        )
                        warnings.append(warning)
                        logger.warning("market data sync_sector_catalog %s", warning)
                    await self.repository.commit()
                    logger.info(
                        "market data sync_sector_catalog persisted component snapshot: sector_type=%s sector_code=%s "
                        "fetched=%s inserted=%s updated=%s unchanged=%s deleted=%s complete=%s pages=%s/%s",
                        sector_type,
                        sector.get("sector_code"),
                        len(components),
                        stats["inserted"],
                        stats["updated"],
                        stats["unchanged"],
                        deleted if snapshot.is_complete and payload.delete_missing_components else 0,
                        snapshot.is_complete,
                        snapshot.fetched_page_count,
                        snapshot.expected_page_count,
                    )
                except Exception as exc:
                    await self.repository.rollback()
                    error = self._error_text(f"{sector_type}/{sector.get('sector_code')}: persist failed", exc)
                    logger.warning("market data sync_sector_catalog persist failed: %s", error)
                    errors.append(error)
        if total_sectors == 0 and errors:
            raise MarketDataSyncError(
                "sector_catalog_sync_failed",
                "板块目录同步失败，未获取到任何板块",
                details={
                    "sector_types": list(payload.sector_types),
                    "errors": errors,
                    "sector_count": total_sectors,
                    "component_count": total_components,
                    "inserted_component_count": inserted_components,
                    "updated_component_count": updated_components,
                    "unchanged_component_count": unchanged_components,
                    "deleted_component_count": deleted_components,
                    "incomplete_sector_count": incomplete_sectors,
                },
            )
        logger.info(
            "market data sync_sector_catalog finished: sector_count=%s component_count=%s inserted=%s updated=%s unchanged=%s deleted=%s incomplete=%s errors=%s warnings=%s",
            total_sectors,
            total_components,
            inserted_components,
            updated_components,
            unchanged_components,
            deleted_components,
            incomplete_sectors,
            len(errors),
            len(warnings),
        )
        return SectorCatalogSyncResult(
            sector_count=total_sectors,
            component_count=total_components,
            inserted_component_count=inserted_components,
            updated_component_count=updated_components,
            unchanged_component_count=unchanged_components,
            deleted_component_count=deleted_components,
            incomplete_sector_count=incomplete_sectors,
            sector_types=list(payload.sector_types),
            errors=errors,
            warnings=warnings,
        )

    @staticmethod
    def _component_metadata(
        row: dict,
        *,
        is_complete: bool,
        fetched_page_count: int,
        expected_page_count: int | None,
    ) -> dict:
        metadata = dict(row.get("metadata_json") or {})
        component_identity = {
            "sector_code": str(row.get("sector_code") or ""),
            "stock_code": str(row.get("stock_code") or ""),
            "source": str(row.get("source") or ""),
            "weight": row.get("weight"),
        }
        metadata["component_sync_hash"] = hashlib.sha256(
            json.dumps(component_identity, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        metadata["snapshot_complete"] = is_complete
        metadata["fetched_page_count"] = fetched_page_count
        metadata["expected_page_count"] = expected_page_count
        return metadata

    async def sync_stock_basic(self, payload: StockBasicSyncRequest) -> StockBasicSyncResult:
        errors: list[str] = []
        fallback_used = False
        source = payload.source
        logger.info(
            "market data sync_stock_basic started: source=%s include_detail=%s fallback_to_mootdx=%s timeout=%s",
            payload.source,
            payload.include_detail,
            payload.fallback_to_mootdx,
            payload.provider_timeout_seconds,
        )
        fallback_order = [source]
        if payload.fallback_to_mootdx:
            fallback_order.extend(candidate for candidate in ["tushare", "akshare", "mootdx"] if candidate not in fallback_order)
        rows: list[dict] = []
        delisted_codes: set[str] = set()
        raw: list[dict] = []
        selected_source: str | None = None
        for candidate in fallback_order:
            try:
                candidate_rows, candidate_delisted, candidate_raw = await self._fetch_stock_basic_rows(
                    candidate,
                    timeout_seconds=payload.provider_timeout_seconds,
                )
            except Exception as exc:
                error = self._error_text(candidate, exc)
                logger.warning("market data sync_stock_basic source failed: %s", error)
                errors.append(error)
                continue
            candidate_rows, candidate_delisted = self._normalize_stock_basic_rows(
                candidate,
                candidate_rows,
                candidate_delisted,
            )
            candidate_universe_count = sum(1 for row in candidate_rows if row.get("status") in {"active", "suspended", "delisted"})
            if candidate != "mootdx" and candidate_universe_count < payload.min_expected_count:
                error = f"{candidate} fetched_count too small: {candidate_universe_count}"
                logger.warning("market data sync_stock_basic %s", error)
                errors.append(error)
                continue
            source = candidate
            selected_source = candidate
            rows, delisted_codes, raw = candidate_rows, candidate_delisted, candidate_raw
            fallback_used = candidate != payload.source
            break
        if selected_source is None:
            raise MarketDataSyncError(
                "stock_basic_sync_failed",
                "股票基础资料同步失败，所有 provider 都不可用或返回数量异常",
                details={"errors": errors, "min_expected_count": payload.min_expected_count},
            )

        await self._capture_sync_raw(
            provider_code=source,
            capability="stock_basic_sync",
            request_params=payload.model_dump(),
            payload=raw,
            normalized_table="t_stock",
        )
        stock_codes = [row["stock_code"] for row in rows]
        existing = await self.repository.get_stock_map(stock_codes)
        prepared = [self._merge_stock_row(row, existing.get(row["stock_code"])) for row in rows]
        upserted_count = await self.repository.upsert_stock_rows(prepared)
        await self.repository.commit()
        logger.info(
            "market data sync_stock_basic persisted stocks: source=%s fetched=%s upserted=%s fallback_used=%s",
            source,
            len(rows),
            upserted_count,
            fallback_used,
        )

        detail_enriched_count = 0
        if source == "akshare" and payload.include_detail and payload.detail_mode != "none" and payload.max_detail_per_run > 0:
            targets = await self.repository.list_stocks_for_detail(
                limit=payload.max_detail_per_run,
                detail_refresh_days=payload.detail_refresh_days,
                mode=payload.detail_mode,
            )
            detail_rows, detail_errors = await self._fetch_akshare_detail_rows(targets)
            errors.extend(detail_errors)
            if detail_rows:
                refreshed = await self.repository.get_stock_map([row["stock_code"] for row in detail_rows])
                prepared_detail = [self._merge_stock_row(row, refreshed.get(row["stock_code"])) for row in detail_rows]
                detail_enriched_count = await self.repository.upsert_stock_rows(prepared_detail)
                await self.repository.commit()

        delisted_marked_count = 0
        if source == "akshare" and payload.mark_delisted and delisted_codes:
            delisted_marked_count = await self.repository.update_stock_statuses(stock_codes=sorted(delisted_codes), status="delisted")
            await self.repository.commit()

        return StockBasicSyncResult(
            source=source,
            fetched_count=len(rows),
            upserted_count=upserted_count,
            detail_enriched_count=detail_enriched_count,
            delisted_marked_count=delisted_marked_count,
            fallback_used=fallback_used,
            errors=errors,
        )

    async def sync_index_catalog(self, payload: IndexCatalogSyncRequest) -> IndexCatalogSyncResult:
        errors: list[str] = []
        warnings: list[str] = []
        fallback_used = False
        index_rows: list[dict] = []
        component_count = 0
        component_index_count = 0

        index_codes = self._dedupe_index_codes(payload.index_codes or list(CORE_INDEX_DEFINITIONS.keys()))
        component_index_codes = self._dedupe_index_codes(
            payload.component_index_codes
            if payload.component_index_codes is not None
            else [
                code
                for code in index_codes
                if CORE_INDEX_DEFINITIONS.get(self._official_index_code(code), {}).get("component_required")
            ]
        )
        weight_start_date, weight_end_date = self._month_window(payload.weight_lookback_months)
        component_required_count = len(component_index_codes)
        logger.info(
            "market data sync_index_catalog started: source=%s index_count=%s sync_components=%s component_index_count=%s weight_start_date=%s weight_end_date=%s timeout=%s",
            payload.source,
            len(index_codes),
            payload.sync_components,
            component_required_count,
            weight_start_date,
            weight_end_date,
            payload.provider_timeout_seconds,
        )

        for official_code in index_codes:
            source_used = payload.source
            rows: list[dict] = []
            raw: list[dict] = []
            try:
                rows, raw = await asyncio.wait_for(
                    self._fetch_index_basic_rows(payload.source, official_code),
                    timeout=payload.provider_timeout_seconds,
                )
            except Exception as exc:
                error = self._error_text(f"{official_code}: index basic failed", exc)
                logger.warning("market data sync_index_catalog index basic failed: %s", error)
                errors.append(error)
            if not rows and payload.source == "tushare" and payload.fallback_to_akshare:
                try:
                    rows, raw = await asyncio.wait_for(
                        self._fetch_index_basic_rows("akshare", official_code),
                        timeout=payload.provider_timeout_seconds,
                    )
                    source_used = "akshare"
                    fallback_used = True
                except Exception as exc:
                    error = self._error_text(f"{official_code}: akshare index basic fallback failed", exc)
                    logger.warning("market data sync_index_catalog index basic fallback failed: %s", error)
                    errors.append(error)

            normalized_rows = self._normalize_index_basic_rows(rows, official_code, source_used)
            if not normalized_rows:
                normalized_rows = [self._bootstrap_index_basic_row(official_code)]
                warning = f"{official_code}: provider returned no index basic row; bootstrapped core index metadata"
                warnings.append(warning)
                logger.warning("market data sync_index_catalog %s", warning)

            index_rows.extend(normalized_rows)
            await self._capture_sync_raw(
                provider_code=source_used,
                capability="index_catalog_sync",
                record_key=_canonical_index_code(official_code),
                request_params={"index_code": official_code},
                payload=raw,
                normalized_table="t_index_basic",
            )

        upserted_indexes = await self.repository.upsert_rows(
            IndexBasic,
            index_rows,
            conflict_attrs=["index_code"],
            update_attrs=["index_name", "market", "publisher", "metadata_json"],
        )
        await self.repository.commit()
        logger.info(
            "market data sync_index_catalog persisted index basics: requested=%s mapped=%s upserted=%s warnings=%s",
            len(index_codes),
            len(index_rows),
            upserted_indexes,
            len(warnings),
        )

        if payload.sync_components:
            for official_code in component_index_codes:
                source_used = payload.source
                rows = []
                raw = []
                try:
                    rows, raw = await asyncio.wait_for(
                        self._fetch_index_component_rows(
                            payload.source,
                            official_code,
                            start_date=weight_start_date,
                            end_date=weight_end_date,
                        ),
                        timeout=payload.provider_timeout_seconds,
                    )
                except Exception as exc:
                    error = self._error_text(f"{official_code}: index components failed", exc)
                    logger.warning("market data sync_index_catalog components failed: %s", error)
                    errors.append(error)
                if not rows and payload.source == "tushare" and payload.fallback_to_akshare:
                    try:
                        rows, raw = await asyncio.wait_for(
                            self._fetch_index_component_rows("akshare", official_code),
                            timeout=payload.provider_timeout_seconds,
                        )
                        source_used = "akshare"
                        fallback_used = True
                    except Exception as exc:
                        error = self._error_text(f"{official_code}: akshare components fallback failed", exc)
                        logger.warning("market data sync_index_catalog components fallback failed: %s", error)
                        errors.append(error)
                rows, component_warnings = self._normalize_index_component_snapshot(rows, official_code)
                warnings.extend(component_warnings)
                await self._capture_sync_raw(
                    provider_code=source_used,
                    capability="index_components_sync",
                    record_key=_canonical_index_code(official_code),
                    request_params={
                        "index_code": official_code,
                        "start_date": weight_start_date,
                        "end_date": weight_end_date,
                        "weight_lookback_months": payload.weight_lookback_months,
                    },
                    payload=raw,
                    normalized_table="t_index_component",
                )
                if not rows:
                    warning = f"{official_code}: provider returned no index components"
                    warnings.append(warning)
                    logger.warning("market data sync_index_catalog %s", warning)
                    await self.repository.commit()
                    continue
                expected_count = int(CORE_INDEX_DEFINITIONS.get(official_code, {}).get("expected_component_count") or 0)
                if expected_count and len(rows) < expected_count:
                    warning = (
                        f"{official_code}: incomplete index components after normalization "
                        f"source={source_used} rows={len(rows)} expected={expected_count}; persist/delete skipped"
                    )
                    warnings.append(warning)
                    logger.warning("market data sync_index_catalog %s", warning)
                    await self.repository.commit()
                    continue
                upserted_components = await self.repository.upsert_rows(
                    IndexComponent,
                    rows,
                    conflict_attrs=["index_code", "stock_code"],
                    update_attrs=["weight", "effective_date", "source", "metadata_json"],
                )
                active_stock_codes = {str(row["stock_code"]) for row in rows}
                deleted_missing = await self.repository.delete_missing_index_components(
                    index_code=_canonical_index_code(official_code),
                    active_stock_codes=active_stock_codes,
                )
                await self.repository.commit()
                component_count += upserted_components
                component_index_count += 1
                logger.info(
                    "market data sync_index_catalog persisted current index components: index_code=%s source=%s rows=%s upserted=%s deleted_missing=%s",
                    _canonical_index_code(official_code),
                    source_used,
                    len(rows),
                    upserted_components,
                    deleted_missing,
                )

        logger.info(
            "market data sync_index_catalog finished: index_count=%s component_count=%s component_index_count=%s fallback_used=%s errors=%s warnings=%s",
            upserted_indexes,
            component_count,
            component_index_count,
            fallback_used,
            len(errors),
            len(warnings),
        )
        return IndexCatalogSyncResult(
            source=payload.source,
            index_count=upserted_indexes,
            component_count=component_count,
            component_index_count=component_index_count,
            component_required_count=component_required_count,
            fallback_used=fallback_used,
            errors=errors,
            warnings=warnings,
        )

    @staticmethod
    def _dedupe_index_codes(index_codes: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in index_codes:
            official_code = MarketDataSyncService._official_index_code(item)
            canonical = _canonical_index_code(official_code)
            if not canonical or canonical in seen:
                continue
            seen.add(canonical)
            result.append(official_code)
        return result

    @staticmethod
    def _official_index_code(index_code: str) -> str:
        text = str(index_code or "").strip()
        if "." in text:
            return text.upper()
        canonical = _canonical_index_code(text)
        for official_code in CORE_INDEX_DEFINITIONS:
            if _canonical_index_code(official_code) == canonical:
                return official_code
        if canonical.startswith("399"):
            return f"{canonical}.SZ"
        return f"{canonical}.SH"

    @staticmethod
    def _month_window(lookback_months: int, *, today: date | None = None) -> tuple[date, date]:
        current = today or datetime.now(tz=ZoneInfo("Asia/Shanghai")).date()
        month_index = current.year * 12 + current.month - 1
        start_month_index = month_index - max(lookback_months - 1, 0)
        start_year, start_month_zero = divmod(start_month_index, 12)
        start = date(start_year, start_month_zero + 1, 1)
        if current.month == 12:
            end = date(current.year, 12, 31)
        else:
            end = date(current.year, current.month + 1, 1) - timedelta(days=1)
        return start, end

    async def _fetch_index_basic_rows(self, source: str, official_code: str) -> tuple[list[dict], list[dict]]:
        if source == "tushare":
            return await self.tushare.call(
                "index_catalog_sync",
                lambda provider: self.tushare_mapper.indexes(provider, official_code),
                request_summary={"index_code": official_code},
                execution_mode="scheduler",
            )
        if source == "akshare":
            return await self.akshare.indexes(official_code)
        raise ValueError(f"unsupported index catalog source: {source}")

    async def _fetch_index_component_rows(
        self,
        source: str,
        official_code: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> tuple[list[dict], list[dict]]:
        if source == "tushare":
            return await self.tushare.call(
                "index_components_sync",
                lambda provider: self.tushare_mapper.index_components(
                    provider,
                    official_code,
                    start_date=start_date,
                    end_date=end_date,
                ),
                request_summary={"index_code": official_code, "start_date": start_date, "end_date": end_date},
                execution_mode="scheduler",
            )
        if source == "akshare":
            return await self.akshare.index_components(official_code)
        raise ValueError(f"unsupported index component source: {source}")

    @staticmethod
    def _normalize_index_basic_rows(rows: list[dict], official_code: str, source_used: str) -> list[dict]:
        canonical = _canonical_index_code(official_code)
        normalized: list[dict] = []
        for row in rows:
            row_code = _canonical_index_code(str(row.get("index_code") or official_code))
            if row_code != canonical:
                continue
            metadata = dict(row.get("metadata_json") or {})
            metadata["source_used"] = source_used
            metadata["official_index_code"] = official_code
            fallback = CORE_INDEX_DEFINITIONS.get(official_code, {})
            normalized.append(
                {
                    "index_code": canonical,
                    "index_name": str(row.get("index_name") or fallback.get("index_name") or canonical),
                    "market": str(row.get("market") or "CN"),
                    "publisher": row.get("publisher") or fallback.get("publisher"),
                    "metadata_json": metadata,
                }
            )
        return normalized

    @staticmethod
    def _bootstrap_index_basic_row(official_code: str) -> dict:
        definition = CORE_INDEX_DEFINITIONS.get(official_code, {})
        canonical = _canonical_index_code(official_code)
        return {
            "index_code": canonical,
            "index_name": str(definition.get("index_name") or canonical),
            "market": "CN",
            "publisher": definition.get("publisher"),
            "metadata_json": {
                "source": "system:core_index_seed",
                "official_index_code": official_code,
                "bootstrap_core_index": True,
                "component_required": bool(definition.get("component_required")),
            },
        }

    @staticmethod
    def _normalize_index_component_snapshot(rows: list[dict], official_code: str) -> tuple[list[dict], list[str]]:
        warnings: list[str] = []
        canonical = _canonical_index_code(official_code)
        normalized: list[dict] = []
        is_akshare_snapshot = any(str(row.get("source") or "").startswith("akshare:") for row in rows)
        for row in rows:
            stock_code = normalize_symbol(str(row.get("stock_code") or ""))
            if not stock_code:
                continue
            metadata = dict(row.get("metadata_json") or {})
            metadata["official_index_code"] = official_code
            original_effective_date = row.get("effective_date")
            if is_akshare_snapshot:
                metadata["component_semantics"] = "current_master"
            normalized.append(
                {
                    "index_code": canonical,
                    "stock_code": stock_code,
                    "weight": row.get("weight"),
                    "effective_date": original_effective_date,
                    "source": row.get("source") or "unknown",
                    "metadata_json": metadata,
                }
            )
        if not normalized:
            return [], warnings
        if is_akshare_snapshot:
            return normalized, warnings
        sync_date = datetime.now(tz=timezone.utc).date()
        dated = [row["effective_date"] for row in normalized if row.get("effective_date")]
        before = len(normalized)
        if dated:
            expected_count = int(CORE_INDEX_DEFINITIONS.get(official_code, {}).get("expected_component_count") or 0)
            grouped: dict[date, list[dict]] = {}
            for row in normalized:
                row_date = row.get("effective_date")
                if row_date:
                    grouped.setdefault(row_date, []).append(row)
            latest_date = max(grouped)
            selected_date = latest_date
            if expected_count:
                for candidate_date in sorted(grouped, reverse=True):
                    unique_count = len({row["stock_code"] for row in grouped[candidate_date]})
                    if unique_count >= expected_count:
                        selected_date = candidate_date
                        break
                if selected_date != latest_date:
                    warnings.append(
                        f"{official_code}: latest index_weight date {latest_date.isoformat()} incomplete; "
                        f"kept latest complete date {selected_date.isoformat()}"
                    )
            normalized = grouped[selected_date]
            effective_date = selected_date
        else:
            effective_date = sync_date
            for row in normalized:
                row["effective_date"] = effective_date
        deduped: dict[str, dict] = {}
        for row in normalized:
            deduped[row["stock_code"]] = row
        normalized = list(deduped.values())
        duplicate_count = before - len(deduped) if not dated else len(grouped.get(effective_date, [])) - len(deduped)
        if duplicate_count > 0:
            warnings.append(f"{official_code}: removed duplicate index component rows duplicate_count={duplicate_count}")
        pruned = before - len(normalized)
        if pruned:
            warnings.append(
                f"{official_code}: kept latest component snapshot effective_date={effective_date.isoformat()}, pruned={pruned}"
            )
        return normalized, warnings

    async def sync_tushare_topic(self, payload: TushareTopicSyncRequest) -> TushareTopicSyncResult:
        definition = _TUSHARE_TOPIC_DEFINITIONS[payload.topic]
        records, raw = await self.tushare.call(
            f"tushare_{payload.topic}_sync",
            lambda provider: self._tushare_topic_records(provider, definition["api_name"], payload.params, payload.fields),
            request_summary={"topic": payload.topic, "params": payload.params},
            execution_mode="scheduler",
        )
        rows = definition["normalize"](records)
        if payload.limit:
            rows = rows[: payload.limit]
        await self._capture_sync_raw(
            provider_code="tushare",
            capability=f"{payload.topic}_sync",
            record_key=str(payload.params.get("ts_code") or payload.params.get("trade_date") or payload.topic),
            request_params={"topic": payload.topic, "params": payload.params},
            payload=raw,
            normalized_table=definition["table"],
        )
        upserted = await self.repository.upsert_rows(
            definition["model"],
            rows,
            conflict_attrs=definition["conflict"],
        )
        await self.repository.commit()
        logger.info(
            "market data sync_tushare_topic finished: topic=%s api=%s fetched=%s upserted=%s",
            payload.topic,
            definition["api_name"],
            len(records),
            upserted,
        )
        return TushareTopicSyncResult(
            topic=payload.topic,
            api_name=definition["api_name"],
            fetched_count=len(records),
            upserted_count=upserted,
            normalized_table=definition["table"],
        )

    @staticmethod
    def _error_text(prefix: str, exc: Exception) -> str:
        message = str(exc).strip() or repr(exc)
        return f"{prefix}: {type(exc).__name__}: {message}"

    async def _fetch_stock_basic_rows(self, source: str, *, timeout_seconds: int) -> tuple[list[dict], set[str], list[dict]]:
        if source == "tushare":
            return await asyncio.wait_for(
                self.tushare.call("stock_basic_sync", lambda provider: self.tushare_mapper.stock_basic_list(provider), request_summary={"full_list": True}, execution_mode="scheduler"),
                timeout=timeout_seconds,
            )
        if source == "akshare":
            return await asyncio.wait_for(self.akshare.stock_basic_list(), timeout=timeout_seconds)
        if source == "mootdx":
            return await asyncio.wait_for(self.mootdx.stock_basic_list(), timeout=timeout_seconds)
        raise ValueError(f"unsupported stock basic source: {source}")

    async def _tushare_topic_records(self, provider, api_name: str, params: dict, fields: str) -> tuple[list[dict], list[dict]]:
        response = await provider.request(
            TushareApiRequest(
                api_name=api_name,
                params=params,
                fields=tuple(item.strip() for item in fields.split(",") if item.strip()),
            )
        )
        return response.records, [response.raw_payload]

    async def _fetch_akshare_detail_rows(self, stocks) -> tuple[list[dict], list[str]]:
        return await asyncio.to_thread(self._fetch_akshare_detail_rows_sync, stocks)

    def _fetch_akshare_detail_rows_sync(self, stocks) -> tuple[list[dict], list[str]]:
        import akshare as ak

        rows: list[dict] = []
        errors: list[str] = []
        sync_at = datetime.now(tz=timezone.utc).isoformat()
        for stock in stocks:
            code = stock.stock_code
            metadata = {"sync_source": "akshare", "detail_last_synced_at": sync_at}
            industry = None
            list_date = None
            try:
                raw = frame_records(ak.stock_individual_info_em(symbol=code, timeout=10))
                detail_map = self._item_value_map(raw)
                industry = detail_map.get("行业")
                list_date = parse_date(detail_map.get("上市时间") or detail_map.get("上市日期"))
                metadata["raw_detail"] = json_safe(detail_map)
            except Exception as exc:
                errors.append(f"{code} stock_individual_info_em: {exc}")
            try:
                previous_names = frame_records(ak.stock_info_change_name(symbol=code))
                if previous_names:
                    metadata["previous_names"] = json_safe(previous_names)
            except Exception:
                pass
            if industry is None and list_date is None and len(metadata) <= 2:
                continue
            rows.append({
                "stock_code": code,
                "stock_name": stock.stock_name,
                "market": stock.market,
                "exchange": stock.exchange,
                "list_date": list_date,
                "delist_date": stock.delist_date,
                "status": stock.status,
                "industry": industry,
                "area": stock.area,
                "metadata_json": metadata,
            })
        return rows, errors

    @staticmethod
    def _item_value_map(raw: list[dict]) -> dict:
        result = {}
        for record in raw:
            item = record.get("item") or record.get("项目")
            if item in (None, ""):
                continue
            result[str(item)] = record.get("value") or record.get("值")
        return result

    @staticmethod
    def _merge_stock_row(row: dict, existing) -> dict:
        incoming_metadata = dict(row.get("metadata_json") or {})
        metadata = {**(getattr(existing, "metadata_json", None) or {}), **incoming_metadata}
        incoming_source = str(incoming_metadata.get("source") or incoming_metadata.get("sync_source") or "")
        incoming_status = row.get("status") or getattr(existing, "status", None) or "active"
        existing_status = getattr(existing, "status", None)
        if existing_status in {"excluded", "delisted", "suspended"} and not incoming_source.startswith("tushare:"):
            incoming_status = existing_status
        return {
            "stock_code": normalize_symbol(str(row["stock_code"])),
            "stock_name": row.get("stock_name") or getattr(existing, "stock_name", None) or str(row["stock_code"]),
            "market": row.get("market") or getattr(existing, "market", None) or "CN",
            "exchange": row.get("exchange") or getattr(existing, "exchange", None),
            "list_date": row.get("list_date") or getattr(existing, "list_date", None),
            "delist_date": row.get("delist_date") or getattr(existing, "delist_date", None),
            "status": incoming_status,
            "industry": row.get("industry") or getattr(existing, "industry", None),
            "area": row.get("area") or getattr(existing, "area", None),
            "metadata_json": metadata,
        }

    def _normalize_stock_basic_rows(
        self,
        source: str,
        rows: list[dict],
        delisted_codes: set[str],
    ) -> tuple[list[dict], set[str]]:
        normalized: list[dict] = []
        normalized_delisted: set[str] = set()
        for row in rows:
            stock_code = normalize_symbol(str(row.get("stock_code") or ""))
            if not stock_code:
                continue
            row = {**row, "stock_code": stock_code}
            if self._is_excluded_stock_row(row):
                if source == "tushare":
                    normalized.append(self._excluded_stock_row(row))
                continue
            if not self._is_mainland_stock_row(row):
                continue
            if source != "tushare":
                row["status"] = "active"
            else:
                row["status"] = self._normalize_tushare_status(row.get("status"))
            if self._is_delisted_stock_row(row):
                metadata = dict(row.get("metadata_json") or {})
                metadata.setdefault("status_normalized_reason", "name_prefix_delisted")
                metadata.setdefault("provider_status_before_name_check", row.get("status"))
                row["metadata_json"] = metadata
                row["status"] = "delisted"
            if row["status"] == "delisted":
                normalized_delisted.add(stock_code)
            normalized.append(row)
        for code in delisted_codes:
            code = normalize_symbol(str(code))
            if self._is_mainland_stock_code(code):
                normalized_delisted.add(code)
        return normalized, normalized_delisted

    @staticmethod
    def _normalize_tushare_status(value: object) -> str:
        text = str(value or "active").lower()
        if text in {"d", "delisted"}:
            return "delisted"
        if text in {"p", "paused", "suspended"}:
            return "suspended"
        return "active"

    @staticmethod
    def _excluded_stock_row(row: dict) -> dict:
        metadata = dict(row.get("metadata_json") or {})
        metadata.update(
            {
                "excluded_from_daily_universe": True,
                "excluded_reason": "BSE/BJ excluded from stock-center universe",
                "provider_exchange": row.get("exchange"),
                "provider_status": metadata.get("provider_list_status") or row.get("status"),
            }
        )
        return {**row, "status": "excluded", "metadata_json": metadata}

    @staticmethod
    def _is_excluded_stock_row(row: dict) -> bool:
        exchange = str(row.get("exchange") or "").upper()
        code = normalize_symbol(str(row.get("stock_code") or ""))
        return exchange in {"BJ", "BSE"} or code.startswith(("4", "8", "920"))

    @staticmethod
    def _is_mainland_stock_row(row: dict) -> bool:
        exchange = str(row.get("exchange") or "").upper()
        code = normalize_symbol(str(row.get("stock_code") or ""))
        if exchange in {"SH", "SZ", "SSE", "SZSE"}:
            return True
        return MarketDataSyncService._is_mainland_stock_code(code)

    @staticmethod
    def _is_mainland_stock_code(stock_code: str) -> bool:
        code = normalize_symbol(str(stock_code or ""))
        return bool(code) and code[0] in {"0", "3", "6"}

    @staticmethod
    def _is_delisted_stock_row(row: dict) -> bool:
        metadata = dict(row.get("metadata_json") or {})
        raw = metadata.get("raw") if isinstance(metadata.get("raw"), dict) else {}
        raw_source_fields = metadata.get("raw_source_fields") if isinstance(metadata.get("raw_source_fields"), dict) else {}
        candidates = [
            row.get("stock_name"),
            row.get("name"),
            raw.get("name"),
            raw_source_fields.get("证券简称"),
            raw_source_fields.get("证券全称"),
            raw_source_fields.get("公司简称"),
        ]
        return any(str(value or "").strip().startswith("退市") for value in candidates)

    async def _capture_sync_raw(
        self,
        *,
        provider_code: str,
        capability: str,
        record_key: str | None = None,
        request_params: dict,
        payload,
        normalized_table: str,
    ) -> None:
        safe_payload = json_safe(payload)
        await self.repository.insert_raw({
            "trace_id": f"sync_{datetime.now(tz=timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
            "provider_code": provider_code,
            "capability": capability,
            "request_params": json_safe(request_params),
            "record_key": record_key or capability,
            "payload": safe_payload,
            "payload_summary": {"payload_type": type(safe_payload).__name__, "row_count": len(safe_payload) if isinstance(safe_payload, list) else 1},
            "normalized_table": normalized_table,
            "status": "captured",
        })
