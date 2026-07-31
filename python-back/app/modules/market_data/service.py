from datetime import date, datetime, timedelta
import hashlib
import json
from uuid import uuid4

from app.modules.market_data.capabilities import capability_definition
from app.modules.market_data.models import (
    Announcement,
    DailyBar,
    FactorDefinition,
    IndexBar,
    IndexBasic,
    IndexComponent,
    LhbEvent,
    LhbSeatDetail,
    MinuteBar,
    QuoteSnapshot,
    SectorBar,
    SectorBasic,
    SectorComponent,
    SectorFundFlowDaily,
    Stock,
    StockFactorMinute,
    StockFundFlowDaily,
    TickTrade,
)
from app.modules.market_data.providers import AkShareProvider, MootdxProvider, json_safe, normalize_symbol
from app.modules.market_data.repository import MarketDataRepository
from app.modules.market_data.schemas import DailyBarRead, MinuteBarRead, QueryMeta, QueryMode, QueryResult, QuoteRead, StockRead
from app.modules.market_data.tushare_runtime import TushareProviderFactory
from app.modules.market_data.tushare_mappers import TushareCanonicalMapper
from app.modules.config_center.repository import ConfigCenterRepository


class MarketDataQueryService:
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

    async def browse_sectors(
        self,
        *,
        sector_type: str,
        provider: str,
        keyword: str | None,
        page: int,
        page_size: int,
    ) -> dict:
        return await self.repository.browse_sectors(
            sector_type=self._sector_type(sector_type),
            provider=provider,
            keyword=(keyword or "").strip() or None,
            page=page,
            page_size=page_size,
        )

    async def browse_sector_stocks(
        self,
        *,
        sector_code: str,
        keyword: str | None,
        status: str | None,
        page: int,
        page_size: int,
    ) -> dict | None:
        return await self.repository.browse_sector_stocks(
            sector_code=sector_code,
            keyword=(keyword or "").strip() or None,
            status=(status or "").strip() or None,
            page=page,
            page_size=page_size,
        )

    async def query_stock_basic(
        self,
        stock_code: str,
        *,
        query_mode: QueryMode = "db_first",
        engine_priority: list[str] | None = None,
    ) -> QueryResult:
        code = normalize_symbol(stock_code)
        engines = self._engines(engine_priority, ["tushare", "akshare", "mootdx"])
        if query_mode in {"db_first", "db_only"}:
            row = await self.repository.get_stock(code)
            if row is not None or query_mode == "db_only":
                return self._result(
                    "stock_basic",
                    code,
                    self._stock(row) if row else None,
                    query_mode=query_mode,
                    engines=engines,
                    resolved_source="database" if row else None,
                    missing_ranges=[] if row else [{"scope": "stock_basic", "reason": "db_empty"}],
                )

        provider = await self._provider_stock(code, engines)
        data = provider["data"]
        if data and query_mode != "provider_only":
            row = await self.repository.upsert_stock(data)
            await self.repository.commit()
            data = self._stock(row)
            provider["persisted"] = True
        return self._provider_result("stock_basic", code, query_mode, engines, data, provider)

    async def query_daily_bars(
        self,
        stock_code: str,
        *,
        query_mode: QueryMode = "db_first",
        engine_priority: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 120,
    ) -> QueryResult:
        code = normalize_symbol(stock_code)
        engines = self._engines(engine_priority, ["tushare", "akshare", "mootdx"])
        db_rows: list[DailyBar] = []
        db_staleness: dict = {}
        if query_mode in {"db_first", "db_only"}:
            rows = await self.repository.list_daily_bars(stock_code=code, start_date=start_date, end_date=end_date, limit=limit)
            staleness = self._daily_staleness(rows, end_date=end_date)
            if query_mode == "db_only" or (rows and not staleness.get("is_stale", False)):
                return self._result(
                    "daily_bars",
                    code,
                    [self._daily_bar(row) for row in rows],
                    query_mode=query_mode,
                    engines=engines,
                    resolved_source="database" if rows else None,
                    missing_ranges=[] if rows else [{"scope": "daily_bars", "reason": "db_empty"}],
                    staleness=staleness,
                )
            db_rows = rows
            db_staleness = staleness

        provider = await self._provider_daily(code, engines, start_date=start_date, end_date=end_date, limit=limit)
        data = provider["data"][:limit]
        if data and query_mode != "provider_only":
            await self.repository.upsert_daily_bars(data)
            await self.repository.commit()
            provider["persisted"] = True
        if not data and query_mode == "db_first" and db_rows:
            return self._result(
                "daily_bars",
                code,
                [self._daily_bar(row) for row in db_rows],
                query_mode=query_mode,
                engines=engines,
                resolved_source="database",
                attempted_engines=provider.get("attempted_engines", []),
                missing_ranges=[{"scope": "daily_bars", "reason": "db_stale_provider_failed"}],
                staleness=db_staleness,
                errors=provider.get("errors", []),
            )
        return self._provider_result("daily_bars", code, query_mode, engines, [json_safe(row) for row in data], provider)

    async def query_minute_bars(
        self,
        stock_code: str,
        *,
        query_mode: QueryMode = "db_first",
        engine_priority: list[str] | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 240,
    ) -> QueryResult:
        code = normalize_symbol(stock_code)
        engines = self._engines(engine_priority, ["mootdx", "akshare"])
        if query_mode in {"db_first", "db_only"}:
            rows = await self.repository.list_minute_bars(stock_code=code, start_time=start_time, end_time=end_time, limit=limit)
            if rows or query_mode == "db_only":
                return self._result(
                    "minute_bars",
                    code,
                    [self._minute_bar(row) for row in rows],
                    query_mode=query_mode,
                    engines=engines,
                    resolved_source="database" if rows else None,
                    missing_ranges=[] if rows else [{"scope": "minute_bars", "reason": "db_empty"}],
                )

        provider = await self._provider_minute(code, engines, start_time=start_time, end_time=end_time)
        data = provider["data"][:limit]
        if data and query_mode != "provider_only":
            await self.repository.upsert_minute_bars(data)
            await self.repository.commit()
            provider["persisted"] = True
        return self._provider_result("minute_bars", code, query_mode, engines, [json_safe(row) for row in data], provider)

    async def query_quote(
        self,
        stock_code: str,
        *,
        query_mode: QueryMode = "provider_first",
        engine_priority: list[str] | None = None,
    ) -> QueryResult:
        code = normalize_symbol(stock_code)
        engines = self._engines(engine_priority, ["mootdx", "akshare"])
        db_row: QuoteSnapshot | None = None
        db_staleness: dict = {}
        if query_mode in {"db_first", "db_only"}:
            row = await self.repository.latest_quote(code)
            staleness = self._quote_staleness(row)
            if query_mode == "db_only" or (row is not None and not staleness.get("is_stale", False)):
                return self._result(
                    "quote",
                    code,
                    self._quote(row) if row else None,
                    query_mode=query_mode,
                    engines=engines,
                    resolved_source="database" if row else None,
                    missing_ranges=[] if row else [{"scope": "quote", "reason": "db_empty"}],
                    staleness=staleness,
                )
            db_row = row
            db_staleness = staleness

        provider = await self._provider_quote(code, engines)
        data = provider["data"]
        if data and query_mode != "provider_only":
            row = await self.repository.insert_quote(data)
            await self.repository.commit()
            data = self._quote(row)
            provider["persisted"] = True
        if not data and query_mode == "db_first" and db_row is not None:
            return self._result(
                "quote",
                code,
                self._quote(db_row),
                query_mode=query_mode,
                engines=engines,
                resolved_source="database",
                attempted_engines=provider.get("attempted_engines", []),
                missing_ranges=[{"scope": "quote", "reason": "db_stale_provider_failed"}],
                staleness=db_staleness,
                errors=provider.get("errors", []),
            )
        return self._provider_result("quote", code, query_mode, engines, data, provider)

    async def query_ticks(
        self,
        stock_code: str,
        *,
        query_mode: QueryMode = "db_first",
        engine_priority: list[str] | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        trade_date: date | None = None,
        limit: int = 800,
    ) -> QueryResult:
        code = normalize_symbol(stock_code)
        filters = [TickTrade.stock_code == code]
        if start_time:
            filters.append(TickTrade.trade_time >= start_time)
        if end_time:
            filters.append(TickTrade.trade_time <= end_time)
        return await self._query_rows(
            "ticks",
            code,
            query_mode=query_mode,
            engine_priority=engine_priority,
            default_engines=["mootdx", "akshare"],
            model=TickTrade,
            filters=filters,
            order_by=[TickTrade.trade_time.desc(), TickTrade.id.desc()],
            limit=limit,
            calls={
                "mootdx": lambda: self.mootdx.ticks(code, date_value=trade_date),
                "akshare": lambda: self.akshare.ticks(code),
            },
            request_extra={"start_time": start_time, "end_time": end_time, "trade_date": trade_date, "limit": limit},
            conflict_attrs=["stock_code", "trade_time", "source", "price", "volume_hand"],
        )

    async def query_sectors(
        self,
        *,
        sector_type: str = "industry",
        query_mode: QueryMode = "db_first",
        engine_priority: list[str] | None = None,
        limit: int = 500,
    ) -> QueryResult:
        sector_type = self._sector_type(sector_type)
        filters = [SectorBasic.sector_type == sector_type]
        return await self._query_rows(
            "sectors",
            sector_type,
            query_mode=query_mode,
            engine_priority=engine_priority,
            default_engines=["tushare", "akshare", "mootdx"],
            model=SectorBasic,
            filters=filters,
            order_by=[SectorBasic.sector_name.asc()],
            limit=limit,
            calls={
                "tushare": lambda: self.tushare.call("sectors", lambda provider: self.tushare_mapper.ths_sectors(provider, sector_type), request_summary={"sector_type": sector_type}),
                "akshare": lambda: self.akshare.sectors(sector_type),
                "mootdx": lambda: self.mootdx.sectors(sector_type),
            },
            request_extra={"sector_type": sector_type, "limit": limit},
            conflict_attrs=["sector_code"],
        )

    async def query_sector_components(
        self,
        sector_code: str,
        *,
        sector_type: str = "industry",
        query_mode: QueryMode = "db_first",
        engine_priority: list[str] | None = None,
        limit: int = 500,
    ) -> QueryResult:
        sector_type = self._sector_type(sector_type)
        provider_symbol = await self._sector_provider_symbol(sector_code)

        async def akshare_components():
            rows, raw = await self.akshare.sector_components(sector_type, provider_symbol)
            for row in rows:
                row["sector_code"] = sector_code
            return rows, raw

        async def tushare_components():
            if sector_code.startswith(("ths_concept_", "ths_industry_")):
                return await self.tushare.call(
                    "sector_components",
                    lambda provider: self.tushare_mapper.ths_sector_components(provider, sector_code),
                    request_summary={"sector_code": sector_code, "sector_type": sector_type},
                )
            if sector_code.startswith("sw2021_"):
                return await self.tushare.call(
                    "sector_components",
                    lambda provider: self.tushare_mapper.sector_components(provider, sector_code),
                    request_summary={"sector_code": sector_code, "sector_type": sector_type},
                )
            raise ValueError("Tushare sector components require a Tushare sector code")

        return await self._query_rows(
            "sector_components",
            sector_code,
            query_mode=query_mode,
            engine_priority=engine_priority,
            default_engines=["tushare", "akshare", "mootdx"],
            model=SectorComponent,
            filters=[SectorComponent.sector_code == sector_code],
            order_by=[SectorComponent.stock_code.asc()],
            limit=limit,
            calls={
                "tushare": tushare_components,
                "akshare": akshare_components,
                "mootdx": lambda: self.mootdx.sector_components(sector_type, sector_code),
            },
            request_extra={"sector_type": sector_type, "sector_code": sector_code, "limit": limit},
            conflict_attrs=["sector_code", "stock_code", "source"],
        )

    async def query_stock_sectors(
        self,
        stock_code: str,
        *,
        sector_type: str | None = None,
        query_mode: QueryMode = "db_only",
        limit: int = 500,
    ) -> QueryResult:
        code = normalize_symbol(stock_code)
        filters = [SectorComponent.stock_code == code]
        components = await self.repository.list_rows(
            SectorComponent,
            filters=filters,
            order_by=[SectorComponent.sector_code.asc()],
            limit=limit,
        )
        sector_codes = [row.sector_code for row in components]
        sectors = []
        if sector_codes:
            sector_filters = [SectorBasic.sector_code.in_(sector_codes)]
            if sector_type:
                sector_filters.append(SectorBasic.sector_type == self._sector_type(sector_type))
            sectors = await self.repository.list_rows(SectorBasic, filters=sector_filters, order_by=[SectorBasic.sector_name.asc()], limit=limit)
        sector_by_code = {row.sector_code: self._row(row) for row in sectors}
        data = []
        for component in components:
            sector = sector_by_code.get(component.sector_code)
            if sector_type and sector is None:
                continue
            item = self._row(component)
            item["sector"] = sector
            data.append(item)
        return self._result(
            "stock_sectors",
            code,
            data,
            query_mode=query_mode,
            engines=["database"],
            resolved_source="database" if data else None,
            missing_ranges=[] if data else [{"scope": "stock_sectors", "reason": "db_empty_or_sector_components_not_collected"}],
        )

    async def query_sector_bars(
        self,
        sector_code: str,
        *,
        sector_type: str = "industry",
        query_mode: QueryMode = "db_first",
        engine_priority: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 240,
    ) -> QueryResult:
        sector_type = self._sector_type(sector_type)
        provider_symbol = await self._sector_provider_symbol(sector_code)

        async def akshare_sector_bars():
            rows, raw = await self.akshare.sector_bars(sector_type, provider_symbol, start_date=start_date, end_date=end_date)
            for row in rows:
                row["sector_code"] = sector_code
            return rows, raw

        filters = [SectorBar.sector_code == sector_code]
        if start_date:
            filters.append(SectorBar.trade_date >= start_date)
        if end_date:
            filters.append(SectorBar.trade_date <= end_date)
        return await self._query_rows(
            "sector_bars",
            sector_code,
            query_mode=query_mode,
            engine_priority=engine_priority,
            default_engines=["akshare"],
            model=SectorBar,
            filters=filters,
            order_by=[SectorBar.trade_date.desc()],
            limit=limit,
            calls={"akshare": akshare_sector_bars},
            request_extra={"sector_type": sector_type, "sector_code": sector_code, "start_date": start_date, "end_date": end_date, "limit": limit},
            conflict_attrs=["sector_code", "trade_date"],
        )

    async def query_indexes(
        self,
        *,
        index_code: str | None = None,
        query_mode: QueryMode = "db_first",
        engine_priority: list[str] | None = None,
        limit: int = 500,
    ) -> QueryResult:
        filters = []
        target = normalize_symbol(index_code) if index_code else "all"
        if index_code:
            filters.append(IndexBasic.index_code == index_code)
        return await self._query_rows(
            "indexes",
            target,
            query_mode=query_mode,
            engine_priority=engine_priority,
            default_engines=["tushare", "akshare"],
            model=IndexBasic,
            filters=filters,
            order_by=[IndexBasic.index_code.asc()],
            limit=limit,
            calls={
                "tushare": lambda: self.tushare.call("indexes", lambda provider: self.tushare_mapper.indexes(provider, index_code), request_summary={"index_code": index_code}),
                "akshare": lambda: self.akshare.indexes(index_code),
            },
            request_extra={"index_code": index_code, "limit": limit},
            conflict_attrs=["index_code"],
        )

    async def query_index_components(
        self,
        index_code: str,
        *,
        query_mode: QueryMode = "db_first",
        engine_priority: list[str] | None = None,
        limit: int = 1000,
    ) -> QueryResult:
        code = normalize_symbol(index_code)
        return await self._query_rows(
            "index_components",
            code,
            query_mode=query_mode,
            engine_priority=engine_priority,
            default_engines=["tushare", "akshare"],
            model=IndexComponent,
            filters=[IndexComponent.index_code == code],
            order_by=[IndexComponent.stock_code.asc()],
            limit=limit,
            calls={
                "tushare": lambda: self.tushare.call("index_components", lambda provider: self.tushare_mapper.index_components(provider, index_code), request_summary={"index_code": index_code}),
                "akshare": lambda: self.akshare.index_components(code),
            },
            request_extra={"index_code": code, "limit": limit},
            conflict_attrs=["index_code", "stock_code"],
        )

    async def query_index_bars(
        self,
        index_code: str,
        *,
        query_mode: QueryMode = "db_first",
        engine_priority: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 240,
    ) -> QueryResult:
        code = normalize_symbol(index_code)
        filters = [IndexBar.index_code.in_([code, f"sh{code}", f"sz{code}", f"csi{code}"])]
        if start_date:
            filters.append(IndexBar.trade_date >= start_date)
        if end_date:
            filters.append(IndexBar.trade_date <= end_date)
        return await self._query_rows(
            "index_bars",
            code,
            query_mode=query_mode,
            engine_priority=engine_priority,
            default_engines=["tushare", "akshare", "mootdx"],
            model=IndexBar,
            filters=filters,
            order_by=[IndexBar.trade_date.desc()],
            limit=limit,
            calls={
                "tushare": lambda: self.tushare.call("index_bars", lambda provider: self.tushare_mapper.index_bars(provider, index_code, start_date=start_date, end_date=end_date), request_summary={"index_code": index_code}),
                "akshare": lambda: self.akshare.index_bars(code, start_date=start_date, end_date=end_date),
                "mootdx": lambda: self.mootdx.index_bars(code, limit=limit),
            },
            request_extra={"index_code": code, "start_date": start_date, "end_date": end_date, "limit": limit},
            conflict_attrs=["index_code", "trade_date"],
        )

    async def query_fund_flow(
        self,
        *,
        stock_code: str | None = None,
        sector_type: str | None = None,
        query_mode: QueryMode = "db_first",
        engine_priority: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 240,
    ) -> QueryResult:
        if stock_code:
            code = normalize_symbol(stock_code)
            filters = [StockFundFlowDaily.stock_code == code]
            if start_date:
                filters.append(StockFundFlowDaily.trade_date >= start_date)
            if end_date:
                filters.append(StockFundFlowDaily.trade_date <= end_date)
            return await self._query_rows(
                "fund_flow",
                code,
                query_mode=query_mode,
                engine_priority=engine_priority,
                default_engines=["tushare", "akshare"],
                model=StockFundFlowDaily,
                filters=filters,
                order_by=[StockFundFlowDaily.trade_date.desc()],
                limit=limit,
                calls={
                    "tushare": lambda: self.tushare.call("fund_flow", lambda provider: self.tushare_mapper.stock_fund_flow(provider, code, start_date=start_date, end_date=end_date), request_summary={"stock_code": code}),
                    "akshare": lambda: self.akshare.stock_fund_flow(code, start_date=start_date, end_date=end_date),
                },
                request_extra={"stock_code": code, "start_date": start_date, "end_date": end_date, "limit": limit},
                conflict_attrs=["stock_code", "trade_date"],
                normalized_table="t_stock_fund_flow_daily",
            )
        selected_sector_type = self._sector_type(sector_type or "industry")
        return await self._query_rows(
            "fund_flow",
            selected_sector_type,
            query_mode=query_mode,
            engine_priority=engine_priority,
            default_engines=["akshare"],
            model=SectorFundFlowDaily,
            filters=[SectorFundFlowDaily.sector_type == selected_sector_type],
            order_by=[SectorFundFlowDaily.trade_date.desc(), SectorFundFlowDaily.rank.asc()],
            limit=limit,
            calls={"akshare": lambda: self.akshare.sector_fund_flow(selected_sector_type)},
            request_extra={"sector_type": selected_sector_type, "limit": limit},
            conflict_attrs=["sector_code", "trade_date"],
            normalized_table="t_sector_fund_flow_daily",
        )

    async def query_lhb(
        self,
        *,
        stock_code: str | None = None,
        query_mode: QueryMode = "db_first",
        engine_priority: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 200,
    ) -> QueryResult:
        code = normalize_symbol(stock_code) if stock_code else "all"
        engines = self._engines(engine_priority, ["tushare", "akshare"])
        event_filters = []
        seat_filters = []
        if stock_code:
            event_filters.append(LhbEvent.stock_code == code)
            seat_filters.append(LhbSeatDetail.stock_code == code)
        if start_date:
            event_filters.append(LhbEvent.trade_date >= start_date)
            seat_filters.append(LhbSeatDetail.trade_date >= start_date)
        if end_date:
            event_filters.append(LhbEvent.trade_date <= end_date)
            seat_filters.append(LhbSeatDetail.trade_date <= end_date)
        if query_mode in {"db_first", "db_only"}:
            events = await self.repository.list_rows(LhbEvent, filters=event_filters, order_by=[LhbEvent.trade_date.desc(), LhbEvent.id.desc()], limit=limit)
            seats = await self.repository.list_rows(LhbSeatDetail, filters=seat_filters, order_by=[LhbSeatDetail.trade_date.desc(), LhbSeatDetail.rank.asc()], limit=limit)
            if events or query_mode == "db_only":
                return self._result("lhb", code, {"events": self._rows(events), "seats": self._rows(seats)}, query_mode=query_mode, engines=engines, resolved_source="database" if events else None)

        provider = await self._try_engines(
            code,
            engines,
            "lhb",
            {
                "tushare": lambda: self.tushare.call("lhb", lambda provider: self.tushare_mapper.lhb(provider, stock_code=stock_code, start_date=start_date, end_date=end_date), request_summary={"stock_code": stock_code}),
                "akshare": lambda: self.akshare.lhb(stock_code=stock_code, start_date=start_date, end_date=end_date),
            },
            request_extra={"stock_code": stock_code, "start_date": start_date, "end_date": end_date, "limit": limit},
            normalized_table="t_lhb_event",
            empty_data={"events": [], "seats": []},
            allow_empty_success=True,
        )
        data = provider["data"] or {"events": [], "seats": []}
        if query_mode != "provider_only":
            await self.repository.upsert_rows(
                LhbEvent,
                data.get("events", []),
                conflict_attrs=["stock_code", "trade_date", "reason"],
            )
            await self.repository.upsert_rows(
                LhbSeatDetail,
                data.get("seats", []),
                conflict_attrs=["stock_code", "trade_date", "seat_name", "side", "source"],
            )
            await self.repository.commit()
            provider["persisted"] = bool(data.get("events") or data.get("seats"))
        return self._provider_result("lhb", code, query_mode, engines, json_safe(data), provider)

    async def query_announcements(
        self,
        stock_code: str,
        *,
        query_mode: QueryMode = "db_first",
        engine_priority: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        keyword: str | None = None,
        limit: int = 200,
    ) -> QueryResult:
        code = normalize_symbol(stock_code)
        filters = [Announcement.stock_code == code]
        if start_date:
            filters.append(Announcement.published_at >= datetime.combine(start_date, datetime.min.time()))
        if end_date:
            filters.append(Announcement.published_at <= datetime.combine(end_date, datetime.max.time()))
        return await self._query_rows(
            "announcements",
            code,
            query_mode=query_mode,
            engine_priority=engine_priority,
            default_engines=["tushare", "akshare"],
            model=Announcement,
            filters=filters,
            order_by=[Announcement.published_at.desc()],
            limit=limit,
            calls={
                "tushare": lambda: self.tushare.call("announcements", lambda provider: self.tushare_mapper.announcements(provider, code, start_date=start_date, end_date=end_date), request_summary={"stock_code": code}),
                "akshare": lambda: self.akshare.announcements(stock_code=code, start_date=start_date, end_date=end_date, keyword=keyword),
            },
            request_extra={"stock_code": code, "start_date": start_date, "end_date": end_date, "keyword": keyword, "limit": limit},
            conflict_attrs=["stock_code", "title", "published_at", "source"],
        )

    async def query_indicators(
        self,
        stock_code: str,
        *,
        query_mode: QueryMode = "db_only",
        limit: int = 60,
    ) -> QueryResult:
        code = normalize_symbol(stock_code)
        definitions = await self.repository.list_rows(FactorDefinition, order_by=[FactorDefinition.factor_code.asc()], limit=1000)
        daily = await self.repository.list_active_daily_factors(stock_code=code, limit=limit)
        minute = await self.repository.list_rows(StockFactorMinute, filters=[StockFactorMinute.stock_code == code], order_by=[StockFactorMinute.bar_time.desc()], limit=limit)
        snapshots = await self.repository.computed_technical_snapshots(stock_code=code, limit=limit)
        return self._result(
            "indicators",
            code,
            {
                "factor_definitions": self._rows(definitions),
                "daily_factors": [{key: json_safe(value) for key, value in row.items()} for row in daily],
                "minute_factors": self._rows(minute),
                "technical_snapshots": [
                    {key: json_safe(value) for key, value in row.items()} for row in snapshots
                ],
            },
            query_mode=query_mode,
            engines=["database"],
            resolved_source="database",
        )

    async def _query_rows(
        self,
        capability: str,
        target_code: str,
        *,
        query_mode: QueryMode,
        engine_priority: list[str] | None,
        default_engines: list[str],
        model,
        filters: list,
        order_by: list,
        limit: int,
        calls: dict,
        request_extra: dict,
        conflict_attrs: list[str],
        normalized_table: str | None = None,
    ) -> QueryResult:
        engines = self._engines(engine_priority, default_engines)
        if query_mode in {"db_first", "db_only"}:
            rows = await self.repository.list_rows(model, filters=filters, order_by=order_by, limit=limit)
            if rows or query_mode == "db_only":
                return self._result(
                    capability,
                    target_code,
                    self._rows(rows),
                    query_mode=query_mode,
                    engines=engines,
                    resolved_source="database" if rows else None,
                    missing_ranges=[] if rows else [{"scope": capability, "reason": "db_empty"}],
                )

        provider = await self._try_engines(
            target_code,
            engines,
            capability,
            calls,
            request_extra=request_extra,
            normalized_table=normalized_table or capability_definition(capability).normalized_table,
            empty_data=[],
        )
        data = provider["data"] or []
        if data and query_mode != "provider_only":
            await self.repository.upsert_rows(model, data, conflict_attrs=conflict_attrs)
            await self.repository.commit()
            provider["persisted"] = True
        return self._provider_result(capability, target_code, query_mode, engines, [json_safe(row) for row in data], provider)

    async def _provider_stock(self, stock_code: str, engines: list[str]) -> dict:
        return await self._try_engines(
            stock_code,
            engines,
            "stock_basic",
            {
                "tushare": lambda: self.tushare.call("stock_basic", lambda provider: self.tushare_mapper.stock_basic(provider, stock_code), request_summary={"stock_code": stock_code}),
                "akshare": lambda: self.akshare.stock_basic(stock_code),
                "mootdx": lambda: self.mootdx.stock_basic(stock_code),
            },
            normalized_table="t_stock",
        )

    async def _provider_daily(
        self,
        stock_code: str,
        engines: list[str],
        *,
        start_date: date | None,
        end_date: date | None,
        limit: int,
    ) -> dict:
        # Tushare returns the full history when no range is provided. Keep the
        # query contract bounded by deriving a calendar window from ``limit``.
        resolved_end_date = end_date or date.today()
        resolved_start_date = start_date or (resolved_end_date - timedelta(days=max(limit * 2, 10)))
        return await self._try_engines(
            stock_code,
            engines,
            "daily_bars",
            {
                "tushare": lambda: self.tushare.call("daily_bars", lambda provider: self.tushare_mapper.daily_bars(provider, stock_code, start_date=resolved_start_date, end_date=resolved_end_date), request_summary={"stock_code": stock_code, "start_date": resolved_start_date, "end_date": resolved_end_date}),
                "akshare": lambda: self.akshare.daily_bars(stock_code, start_date=resolved_start_date, end_date=resolved_end_date),
                "mootdx": lambda: self.mootdx.daily_bars(stock_code, limit=limit),
            },
            request_extra={"start_date": resolved_start_date, "end_date": resolved_end_date, "limit": limit},
            normalized_table="t_daily_bar",
            empty_data=[],
        )

    async def _provider_minute(self, stock_code: str, engines: list[str], *, start_time: datetime | None, end_time: datetime | None) -> dict:
        return await self._try_engines(
            stock_code,
            engines,
            "minute_bars",
            {
                "mootdx": lambda: self.mootdx.minute_bars(stock_code),
                "akshare": lambda: self.akshare.minute_bars(stock_code, start_time=start_time, end_time=end_time),
            },
            request_extra={"start_time": start_time, "end_time": end_time},
            normalized_table="t_minute_bar",
            empty_data=[],
        )

    async def _provider_quote(self, stock_code: str, engines: list[str]) -> dict:
        return await self._try_engines(
            stock_code,
            engines,
            "quote",
            {"mootdx": lambda: self.mootdx.quote(stock_code), "akshare": lambda: self.akshare.quote(stock_code)},
            normalized_table="t_quote_snapshot",
        )

    async def _try_engines(
        self,
        stock_code: str,
        engines: list[str],
        capability: str,
        calls: dict,
        *,
        request_extra: dict | None = None,
        normalized_table: str | None = None,
        empty_data=None,
        allow_empty_success: bool = False,
    ) -> dict:
        errors = []
        attempted = []
        for engine in engines:
            attempted.append(engine)
            call = calls.get(engine)
            if call is None:
                errors.append(f"{engine}: unsupported capability {capability}")
                continue
            try:
                data, raw = await call()
                raw_ref = await self._capture_raw(
                    provider_code=engine,
                    capability=capability,
                    stock_code=stock_code,
                    request_extra=request_extra or {},
                    payload=raw,
                    normalized_table=normalized_table,
                )
                if self._has_data(data) or allow_empty_success:
                    return {
                        "data": data,
                        "resolved_source": engine,
                        "fallback_used": engines.index(engine) > 0,
                        "attempted_engines": attempted,
                        "raw_ref": raw_ref,
                        "errors": errors,
                        "persisted": False,
                    }
            except Exception as exc:
                errors.append(f"{engine}: {exc}")
                await self.repository.rollback()
        return {
            "data": empty_data,
            "resolved_source": None,
            "fallback_used": len(attempted) > 1,
            "attempted_engines": attempted,
            "raw_ref": None,
            "errors": errors,
            "missing_ranges": [{"scope": capability, "reason": "all_engines_failed"}],
            "persisted": False,
        }

    async def _capture_raw(self, *, provider_code: str, capability: str, stock_code: str, request_extra: dict, payload, normalized_table: str | None) -> dict:
        trace_id = f"trace_{uuid4().hex}"
        safe_payload = json_safe(payload)
        row_count = len(safe_payload) if isinstance(safe_payload, list) else (1 if safe_payload else 0)
        encoded = json.dumps(safe_payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        safe_request = {
            key: value
            for key, value in {"stock_code": stock_code, **request_extra}.items()
            if key.lower() not in {"token", "api_key", "secret", "password", "authorization"}
        }
        row = await self.repository.insert_ingest_audit({
            "trace_id": trace_id,
            "provider_code": provider_code,
            "capability": capability,
            "request_params": json_safe(safe_request),
            "requested_fields": [],
            "response_row_count": row_count,
            "normalized_row_count": 0,
            "payload_sha256": hashlib.sha256(encoded).hexdigest(),
            "normalized_table": normalized_table,
            "schema_version": "query_audit_v2",
            "status": "complete_zero" if row_count == 0 else "captured",
        })
        await self.repository.commit()
        return {"table": "t_provider_ingest_audit", "id": row.id, "trace_id": trace_id}

    def _provider_result(self, capability, stock_code: str, query_mode: QueryMode, engines: list[str], data, provider: dict) -> QueryResult:
        return self._result(
            capability,
            stock_code,
            data,
            query_mode=query_mode,
            engines=engines,
            resolved_source=provider.get("resolved_source"),
            fallback_used=provider.get("fallback_used", False),
            attempted_engines=provider.get("attempted_engines", []),
            missing_ranges=provider.get("missing_ranges", []),
            raw_ref=provider.get("raw_ref"),
            persisted=provider.get("persisted", False),
            errors=provider.get("errors", []),
        )

    def _result(
        self,
        capability,
        stock_code: str,
        data,
        *,
        query_mode: QueryMode,
        engines: list[str],
        resolved_source: str | None,
        fallback_used: bool = False,
        attempted_engines: list[str] | None = None,
        missing_ranges: list[dict] | None = None,
        staleness: dict | None = None,
        raw_ref: dict | None = None,
        persisted: bool = False,
        errors: list[str] | None = None,
    ) -> QueryResult:
        return QueryResult(
            capability=capability,
            stock_code=stock_code,
            data=data,
            meta=QueryMeta(
                query_mode=query_mode,
                engine_priority=engines,
                resolved_source=resolved_source,
                fallback_used=fallback_used,
                attempted_engines=attempted_engines or [],
                missing_ranges=missing_ranges or [],
                staleness=staleness or {},
                raw_ref=raw_ref,
                persisted=persisted,
                errors=errors or [],
            ),
        )

    def _engines(self, values: list[str] | None, default: list[str]) -> list[str]:
        engines = [item.strip().lower() for item in (values or default) if item and item.strip()]
        engines = [item for item in engines if item in {"tushare", "akshare", "mootdx"}]
        return engines or default

    def _has_data(self, data) -> bool:
        if data is None:
            return False
        if isinstance(data, dict):
            return any(self._has_data(value) for value in data.values())
        if isinstance(data, list):
            return len(data) > 0
        return True

    def _sector_type(self, value: str) -> str:
        text = (value or "industry").strip().lower()
        if text in {"concept", "概念"}:
            return "concept"
        if text in {"region", "area", "地区"}:
            return "region"
        return "industry"

    async def _sector_provider_symbol(self, sector_code: str) -> str:
        rows = await self.repository.list_rows(SectorBasic, filters=[SectorBasic.sector_code == sector_code], limit=1)
        if rows:
            return rows[0].sector_name
        return sector_code

    def _rows(self, rows: list) -> list[dict]:
        return [self._row(row) for row in rows]

    def _row(self, row) -> dict:
        result = {}
        for attr in row.__mapper__.column_attrs:
            value = getattr(row, attr.key)
            result[attr.key] = json_safe(value)
        return result

    def _stock(self, row: Stock) -> dict:
        return StockRead.model_validate(row, from_attributes=True).model_dump(mode="json")

    def _daily_bar(self, row: DailyBar) -> dict:
        return DailyBarRead.model_validate(row, from_attributes=True).model_dump(mode="json")

    def _minute_bar(self, row: MinuteBar) -> dict:
        return MinuteBarRead.model_validate(row, from_attributes=True).model_dump(mode="json")

    def _quote(self, row: QuoteSnapshot) -> dict:
        return QuoteRead.model_validate(row, from_attributes=True).model_dump(mode="json")

    def _daily_staleness(self, rows: list[DailyBar], *, end_date: date | None) -> dict:
        if not rows:
            return {"status": "missing"}
        latest = max(row.trade_date for row in rows)
        target = end_date or date.today()
        return {"latest_trade_date": latest.isoformat(), "target_date": target.isoformat(), "is_stale": latest < target}

    def _quote_staleness(self, row: QuoteSnapshot | None) -> dict:
        if row is None:
            return {"status": "missing"}
        age_seconds = max(int((datetime.now(tz=row.quote_time.tzinfo) - row.quote_time).total_seconds()), 0)
        return {"quote_time": row.quote_time.isoformat(), "age_seconds": age_seconds, "is_stale": age_seconds > 60}
