from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.modules.config_center.repository import ConfigCenterRepository
from app.modules.market_data.providers import AkShareProvider, first, parse_date, safe_float, safe_int
from app.modules.market_data.repository import MarketDataRepository
from app.modules.market_data.tushare.contracts import TushareApiRequest
from app.modules.market_data.tushare_runtime import TushareProviderFactory, TushareRuntimeError


class SectorAnalysisError(RuntimeError):
    def __init__(self, message: str, *, code: str = "sector_analysis_failed") -> None:
        super().__init__(message)
        self.code = code


class SectorAnalysisService:
    """Read-only page aggregation for sector detail and dashboard views."""

    def __init__(self, repository: MarketDataRepository) -> None:
        self.repository = repository
        self.akshare = AkShareProvider()
        self.tushare = TushareProviderFactory(ConfigCenterRepository(repository.session))

    async def search(self, *, keyword: str | None, limit: int = 20) -> dict:
        items = await self.repository.search_tushare_ths_sectors(keyword=keyword, sector_type="concept", limit=limit)
        return {"items": items, "total": len(items)}

    async def overview(self, sector_code: str) -> dict:
        sector = await self._sector_or_raise(sector_code)
        stocks = await self.repository.browse_sector_stocks(
            sector_code=sector.sector_code,
            keyword=None,
            status=None,
            page=1,
            page_size=1,
        )
        return {
            "sector": self._sector_payload(sector, component_count=(stocks or {}).get("total", 0)),
            "raw_code": self._raw_ths_code(sector),
            "taxonomy": (sector.metadata_json or {}).get("taxonomy") or "THS",
        }

    async def bars(
        self,
        sector_code: str,
        *,
        start_date: date | None,
        end_date: date | None,
        limit: int,
    ) -> dict:
        sector = await self._sector_or_raise(sector_code)
        raw_code = self._raw_ths_code(sector)
        params = self._range_params(raw_code, start_date=start_date, end_date=end_date)
        response = await self.tushare.call(
            "sector_analysis_bars",
            lambda provider: provider.request(TushareApiRequest(api_name="ths_daily", params=params)),
            request_summary={"api_name": "ths_daily", "sector_code": sector_code, **params},
        )
        items = []
        for record in response.records:
            trade_date = parse_date(record.get("trade_date"))
            if trade_date is None:
                continue
            items.append(
                {
                    "trade_date": trade_date,
                    "open": safe_float(record.get("open")),
                    "high": safe_float(record.get("high")),
                    "low": safe_float(record.get("low")),
                    "close": safe_float(record.get("close")),
                    "pre_close": safe_float(record.get("pre_close")),
                    "change": safe_float(record.get("change")),
                    "pct_change": safe_float(record.get("pct_change") or record.get("pct_chg")),
                    "volume": safe_float(record.get("vol") or record.get("volume")),
                    "amount": safe_float(record.get("amount")),
                    "raw": record,
                }
            )
        items.sort(key=lambda item: item["trade_date"])
        if limit:
            items = items[-limit:]
        return {
            "sector": self._sector_payload(sector),
            "source": "tushare:ths_daily",
            "items": items,
            "total": len(items),
            "provider": self._provider_meta(response),
        }

    async def money_flow(
        self,
        sector_code: str,
        *,
        start_date: date | None,
        end_date: date | None,
        limit: int,
    ) -> dict:
        sector = await self._sector_or_raise(sector_code)
        raw_code = self._raw_ths_code(sector)
        api_name = "moneyflow_cnt_ths" if sector.sector_type == "concept" else "moneyflow_ind_ths"
        params = self._range_params(raw_code, start_date=start_date, end_date=end_date)
        response = await self.tushare.call(
            "sector_analysis_money_flow",
            lambda provider: provider.request(TushareApiRequest(api_name=api_name, params=params)),
            request_summary={"api_name": api_name, "sector_code": sector_code, **params},
        )
        items = [self._money_flow_record(record) for record in response.records]
        items = [item for item in items if item["trade_date"] is not None]
        items.sort(key=lambda item: item["trade_date"])
        if limit:
            items = items[-limit:]
        return {
            "sector": self._sector_payload(sector),
            "source": f"tushare:{api_name}",
            "items": items,
            "total": len(items),
            "provider": self._provider_meta(response),
        }

    async def leaders(self, sector_code: str, *, limit: int = 30) -> dict:
        money_flow = await self.money_flow(
            sector_code,
            start_date=None,
            end_date=None,
            limit=limit,
        )
        stocks = await self.repository.browse_sector_stocks(
            sector_code=sector_code,
            keyword=None,
            status=None,
            page=1,
            page_size=5000,
        )
        by_name = {
            item.get("stock_name"): item
            for item in (stocks or {}).get("items", [])
            if item.get("stock_name")
        }
        leaders = []
        seen: set[tuple[str | None, str | None]] = set()
        for item in reversed(money_flow["items"]):
            leader_name = item.get("lead_stock")
            key = (str(item.get("trade_date")), leader_name)
            if not leader_name or key in seen:
                continue
            seen.add(key)
            stock = by_name.get(leader_name)
            leaders.append(
                {
                    "trade_date": item.get("trade_date"),
                    "stock_code": stock.get("stock_code") if stock else None,
                    "stock_name": leader_name,
                    "close_price": item.get("lead_close_price"),
                    "pct_change": item.get("lead_pct_change"),
                    "sector_pct_change": item.get("pct_change"),
                }
            )
            if len(leaders) >= limit:
                break
        return {"sector": money_flow["sector"], "items": leaders, "total": len(leaders)}

    async def stocks(self, sector_code: str, *, keyword: str | None, status: str | None, page: int, page_size: int) -> dict:
        result = await self.repository.browse_sector_stocks(
            sector_code=sector_code,
            keyword=keyword,
            status=status,
            page=page,
            page_size=page_size,
        )
        if result is None:
            raise SectorAnalysisError(f"sector not found: {sector_code}", code="sector_not_found")
        return result

    async def dashboard(self, *, sector_type: str = "concept", limit: int = 50) -> dict:
        warnings: list[str] = []
        try:
            rows, _raw = await self.akshare.sector_fund_flow(sector_type)
        except Exception as exc:
            warnings.append(f"akshare realtime fund flow failed: {type(exc).__name__}: {exc}")
            fallback = await self.repository.search_tushare_ths_sectors(keyword=None, sector_type=sector_type, limit=limit)
            return {
                "source": "db:t_sector_basic",
                "updated_at": date.today(),
                "warnings": warnings,
                "items": [
                    {
                        **item,
                        "rank": index + 1,
                        "main_net_inflow": None,
                        "main_net_ratio": None,
                        "change_pct": None,
                        "lead_stock": None,
                        "lead_stock_pct_change": None,
                        "hot": None,
                        "hot_rank": None,
                    }
                    for index, item in enumerate(fallback)
                ],
            }
        names = [row["sector_name"] for row in rows if row.get("sector_name")]
        summaries = await self.repository.sector_summaries_by_names(names=names, sector_type=sector_type)
        hot_map, hot_warning = await self._ths_hot_map(sector_type)
        if hot_warning:
            warnings.append(hot_warning)
        items = []
        for row in rows[:limit]:
            name = row.get("sector_name")
            summary = summaries.get(name or "") or {}
            hot = hot_map.get(name or "") or {}
            raw = (row.get("metadata_json") or {}).get("raw") or {}
            items.append(
                {
                    "sector_code": summary.get("sector_code") or row.get("sector_code"),
                    "sector_name": name,
                    "sector_type": sector_type,
                    "source": summary.get("source") or row.get("source"),
                    "last_synced_at": summary.get("last_synced_at"),
                    "component_count": summary.get("component_count"),
                    "rank": row.get("rank"),
                    "main_net_inflow": row.get("main_net_inflow"),
                    "main_net_ratio": row.get("main_net_ratio"),
                    "change_pct": row.get("change_pct"),
                    "lead_stock": first(raw, ["领涨股", "领涨股票", "lead_stock"]),
                    "lead_stock_pct_change": safe_float(first(raw, ["领涨股-涨跌幅", "领涨股涨跌幅", "pct_change_stock"])),
                    "hot": hot.get("hot"),
                    "hot_rank": hot.get("rank"),
                }
            )
        return {
            "source": "akshare:stock_fund_flow_concept" if sector_type == "concept" else "akshare:stock_fund_flow_industry",
            "updated_at": date.today(),
            "warnings": warnings,
            "items": items,
        }

    async def _sector_or_raise(self, sector_code: str):
        sector = await self.repository.get_sector(sector_code)
        if sector is None:
            raise SectorAnalysisError(f"sector not found: {sector_code}", code="sector_not_found")
        if not sector.sector_code.startswith(("ths_concept_", "ths_industry_")):
            raise SectorAnalysisError("sector analysis currently supports Tushare THS sectors only", code="unsupported_sector_source")
        return sector

    @staticmethod
    def _sector_payload(sector, *, component_count: int | None = None) -> dict:
        return {
            "sector_code": sector.sector_code,
            "sector_name": sector.sector_name,
            "sector_type": sector.sector_type,
            "source": sector.source,
            "last_synced_at": sector.updated_at,
            "component_count": component_count,
        }

    @staticmethod
    def _raw_ths_code(sector) -> str:
        metadata = sector.metadata_json or {}
        raw = metadata.get("raw") or {}
        raw_code = metadata.get("raw_code") or raw.get("ts_code") or raw.get("code")
        if raw_code:
            return str(raw_code)
        return sector.sector_code.removeprefix("ths_concept_").removeprefix("ths_industry_")

    @staticmethod
    def _range_params(raw_code: str, *, start_date: date | None, end_date: date | None) -> dict[str, Any]:
        resolved_end = end_date or date.today()
        resolved_start = start_date or (resolved_end - timedelta(days=180))
        return {
            "ts_code": raw_code,
            "start_date": resolved_start,
            "end_date": resolved_end,
        }

    @staticmethod
    def _money_flow_record(record: dict) -> dict:
        return {
            "trade_date": parse_date(record.get("trade_date")),
            "ts_code": record.get("ts_code"),
            "sector_name": record.get("name") or record.get("industry"),
            "lead_stock": record.get("lead_stock"),
            "close_price": safe_float(record.get("industry_index") or record.get("close")),
            "pct_change": safe_float(record.get("pct_change")),
            "company_num": safe_int(record.get("company_num")),
            "lead_close_price": safe_float(record.get("close_price")),
            "lead_pct_change": safe_float(record.get("pct_change_stock")),
            "net_buy_amount": safe_float(record.get("net_buy_amount")),
            "net_sell_amount": safe_float(record.get("net_sell_amount")),
            "net_amount": safe_float(record.get("net_amount")),
            "raw": record,
        }

    async def _ths_hot_map(self, sector_type: str) -> tuple[dict[str, dict], str | None]:
        market = "概念板块" if sector_type == "concept" else "行业板块"
        try:
            response = await self.tushare.call(
                "sector_analysis_hot",
                lambda provider: provider.request(TushareApiRequest(api_name="ths_hot", params={"market": market, "is_new": "Y"})),
                request_summary={"api_name": "ths_hot", "market": market, "is_new": "Y"},
            )
        except (TushareRuntimeError, Exception) as exc:
            return {}, f"tushare ths_hot failed: {type(exc).__name__}: {exc}"
        result = {}
        for record in response.records:
            name = str(record.get("ts_name") or "")
            if not name:
                continue
            result[name] = {
                "rank": safe_int(record.get("rank")),
                "hot": safe_float(record.get("hot")),
            }
        return result, None

    @staticmethod
    def _provider_meta(response) -> dict:
        return {
            "token_fingerprint": response.token_fingerprint,
            "endpoint_url": response.endpoint_url,
            "row_count": response.row_count,
        }
