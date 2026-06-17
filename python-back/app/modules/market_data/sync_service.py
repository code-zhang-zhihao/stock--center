import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field

from app.modules.market_data.models import SectorBasic, SectorComponent
from app.modules.market_data.providers import AkShareProvider, MootdxProvider, frame_records, json_safe, normalize_symbol, parse_date
from app.modules.market_data.repository import MarketDataRepository


logger = logging.getLogger(__name__)


class SectorCatalogSyncRequest(BaseModel):
    sector_types: list[Literal["concept", "industry"]] = Field(default_factory=lambda: ["concept", "industry"])
    sync_components: bool = True
    limit_sectors: int | None = Field(default=None, ge=1, le=5000)
    max_concurrency: int = Field(default=3, ge=1, le=10)
    source: Literal["akshare"] = "akshare"
    expire_missing_components: bool = True
    provider_timeout_seconds: int = Field(default=45, ge=5, le=600)


class SectorCatalogSyncResult(BaseModel):
    sector_count: int
    component_count: int
    expired_component_count: int
    sector_types: list[str]
    errors: list[str] = Field(default_factory=list)


class StockBasicSyncRequest(BaseModel):
    source: Literal["akshare", "mootdx"] = "akshare"
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
    ) -> None:
        self.repository = repository
        self.akshare = akshare_provider or AkShareProvider()
        self.mootdx = mootdx_provider or MootdxProvider()

    async def sync_sector_catalog(self, payload: SectorCatalogSyncRequest) -> SectorCatalogSyncResult:
        errors: list[str] = []
        total_sectors = 0
        total_components = 0
        expired_components = 0
        sync_date = date.today()
        logger.info(
            "market data sync_sector_catalog started: sector_types=%s sync_components=%s limit_sectors=%s max_concurrency=%s timeout=%s",
            payload.sector_types,
            payload.sync_components,
            payload.limit_sectors,
            payload.max_concurrency,
            payload.provider_timeout_seconds,
        )
        for sector_type in payload.sector_types:
            try:
                logger.info("market data sync_sector_catalog fetching sector list: sector_type=%s", sector_type)
                sectors, raw = await asyncio.wait_for(self.akshare.sectors(sector_type), timeout=payload.provider_timeout_seconds)
            except Exception as exc:
                error = self._error_text(f"{sector_type}: sectors failed", exc)
                logger.warning("market data sync_sector_catalog sector list failed: %s", error)
                errors.append(error)
                continue
            await self._capture_sync_raw(
                provider_code=payload.source,
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

            async def fetch_components(sector: dict) -> tuple[dict, list[dict], list[dict] | None, str | None]:
                async with semaphore:
                    try:
                        logger.info(
                            "market data sync_sector_catalog fetching components: sector_type=%s sector_code=%s sector_name=%s",
                            sector_type,
                            sector.get("sector_code"),
                            sector.get("sector_name"),
                        )
                        components, raw = await asyncio.wait_for(
                            self.akshare.sector_components(sector_type, str(sector["sector_code"])),
                            timeout=payload.provider_timeout_seconds,
                        )
                        for row in components:
                            row["sector_code"] = str(sector["sector_code"])
                            row["end_date"] = None
                        return sector, components, raw, None
                    except Exception as exc:
                        return sector, [], None, self._error_text(
                            f"{sector_type}/{sector.get('sector_code')}: components failed",
                            exc,
                        )

            results = await asyncio.gather(*(fetch_components(sector) for sector in sectors))
            for sector, components, raw, error in results:
                if error:
                    logger.warning("market data sync_sector_catalog components failed: %s", error)
                    errors.append(error)
                    continue
                await self._capture_sync_raw(
                    provider_code=payload.source,
                    capability="sector_components_sync",
                    record_key=str(sector["sector_code"]),
                    request_params={"sector_type": sector_type, "sector_code": str(sector["sector_code"])},
                    payload=raw or [],
                    normalized_table="t_sector_component",
                )
                if not components:
                    await self.repository.commit()
                    logger.info(
                        "market data sync_sector_catalog components empty: sector_type=%s sector_code=%s",
                        sector_type,
                        sector.get("sector_code"),
                    )
                    continue
                try:
                    upserted_components = await self.repository.upsert_rows(
                        SectorComponent,
                        components,
                        conflict_attrs=["sector_code", "stock_code", "source"],
                        update_attrs=["weight", "start_date", "end_date", "metadata_json"],
                    )
                    total_components += upserted_components
                    if payload.expire_missing_components:
                        active = {str(row["stock_code"]) for row in components}
                        source = str(components[0].get("source") or "")
                        expired_components += await self.repository.expire_sector_components(
                            sector_code=str(sector["sector_code"]),
                            source=source,
                            active_stock_codes=active,
                            end_date=sync_date,
                        )
                    await self.repository.commit()
                    logger.info(
                        "market data sync_sector_catalog persisted components: sector_type=%s sector_code=%s upserted=%s total=%s expired_total=%s",
                        sector_type,
                        sector.get("sector_code"),
                        upserted_components,
                        total_components,
                        expired_components,
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
                    "expired_component_count": expired_components,
                },
            )
        logger.info(
            "market data sync_sector_catalog finished: sector_count=%s component_count=%s expired_component_count=%s errors=%s",
            total_sectors,
            total_components,
            expired_components,
            len(errors),
        )
        return SectorCatalogSyncResult(
            sector_count=total_sectors,
            component_count=total_components,
            expired_component_count=expired_components,
            sector_types=list(payload.sector_types),
            errors=errors,
        )

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
        try:
            rows, delisted_codes, raw = await self._fetch_stock_basic_rows(source, timeout_seconds=payload.provider_timeout_seconds)
        except Exception as exc:
            error = self._error_text(source, exc)
            logger.warning("market data sync_stock_basic source failed: %s", error)
            errors.append(error)
            if not payload.fallback_to_mootdx or source == "mootdx":
                raise MarketDataSyncError("stock_basic_sync_failed", f"股票基础资料同步失败: {exc}") from exc
            source = "mootdx"
            fallback_used = True
            logger.info("market data sync_stock_basic fallback to mootdx")
            rows, delisted_codes, raw = await self._fetch_stock_basic_rows(source, timeout_seconds=payload.provider_timeout_seconds)

        if source == "akshare" and len(rows) < payload.min_expected_count:
            if payload.fallback_to_mootdx:
                errors.append(f"akshare fetched_count too small: {len(rows)}")
                source = "mootdx"
                fallback_used = True
                logger.warning(
                    "market data sync_stock_basic akshare fetched_count too small, fallback to mootdx: fetched=%s min_expected=%s",
                    len(rows),
                    payload.min_expected_count,
                )
                rows, delisted_codes, raw = await self._fetch_stock_basic_rows(source, timeout_seconds=payload.provider_timeout_seconds)
            else:
                raise MarketDataSyncError(
                    "stock_basic_sync_abnormal",
                    f"AkShare 返回股票数量异常: {len(rows)}",
                    details={"fetched_count": len(rows), "min_expected": payload.min_expected_count},
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

    @staticmethod
    def _error_text(prefix: str, exc: Exception) -> str:
        message = str(exc).strip() or repr(exc)
        return f"{prefix}: {type(exc).__name__}: {message}"

    async def _fetch_stock_basic_rows(self, source: str, *, timeout_seconds: int) -> tuple[list[dict], set[str], list[dict]]:
        if source == "akshare":
            return await asyncio.wait_for(self.akshare.stock_basic_list(), timeout=timeout_seconds)
        if source == "mootdx":
            return await asyncio.wait_for(self.mootdx.stock_basic_list(), timeout=timeout_seconds)
        raise ValueError(f"unsupported stock basic source: {source}")

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
        metadata = {**(getattr(existing, "metadata_json", None) or {}), **(row.get("metadata_json") or {})}
        return {
            "stock_code": normalize_symbol(str(row["stock_code"])),
            "stock_name": row.get("stock_name") or getattr(existing, "stock_name", None) or str(row["stock_code"]),
            "market": row.get("market") or getattr(existing, "market", None) or "CN",
            "exchange": row.get("exchange") or getattr(existing, "exchange", None),
            "list_date": row.get("list_date") or getattr(existing, "list_date", None),
            "delist_date": row.get("delist_date") or getattr(existing, "delist_date", None),
            "status": row.get("status") or getattr(existing, "status", None) or "active",
            "industry": row.get("industry") or getattr(existing, "industry", None),
            "area": row.get("area") or getattr(existing, "area", None),
            "metadata_json": metadata,
        }

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
