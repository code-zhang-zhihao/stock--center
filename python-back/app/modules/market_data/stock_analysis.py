from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select

from app.modules.market_data.models import (
    Announcement,
    DailyBar,
    LimitEventDaily,
    LhbEvent,
    LhbSeatDetail,
    MinuteBar,
    SectorBasic,
    SectorComponent,
    Stock,
    StockChipPerfDaily,
    StockDailyBasic,
    StockFactorMinute,
    StockFundFlowDaily,
    StockTechnicalFactorDaily,
)
from app.modules.market_data.providers import AkShareProvider, MootdxProvider, json_safe, normalize_symbol
from app.modules.market_data.repository import MarketDataRepository


class StockAnalysisError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class StockAnalysisService:
    """Read-only page aggregation for the stock market workbench."""

    def __init__(
        self,
        repository: MarketDataRepository,
        *,
        mootdx_provider: MootdxProvider | None = None,
        akshare_provider: AkShareProvider | None = None,
    ) -> None:
        self.repository = repository
        self.session = repository.session
        self.mootdx = mootdx_provider or MootdxProvider()
        self.akshare = akshare_provider or AkShareProvider()

    async def search(self, *, keyword: str | None, limit: int = 20) -> dict:
        text = (keyword or "").strip()
        if not text:
            return {"items": [], "total": 0}
        pattern = f"%{text}%"
        result = await self.session.execute(
            select(Stock)
            .where(
                or_(
                    Stock.stock_code.ilike(pattern),
                    Stock.stock_name.ilike(pattern),
                )
            )
            .order_by(
                (Stock.status == "active").desc(),
                Stock.stock_code.asc(),
            )
            .limit(limit)
        )
        items = [self._stock(row) for row in result.scalars().all()]
        return {"items": items, "total": len(items)}

    async def overview(self, stock_code: str) -> dict:
        code = normalize_symbol(stock_code)
        stock = await self.repository.get_stock(code)
        if stock is None:
            raise StockAnalysisError("stock_not_found", f"stock not found: {code}")

        latest_daily_basic = await self._latest_row(StockDailyBasic, [StockDailyBasic.stock_code == code], StockDailyBasic.trade_date.desc())
        latest_daily_bar = await self._latest_row(DailyBar, [DailyBar.stock_code == code], DailyBar.trade_date.desc())
        computed_snapshots = await self.repository.computed_technical_snapshots(stock_code=code, limit=1)
        latest_snapshot = computed_snapshots[0] if computed_snapshots else None
        sectors = await self._stock_sectors(code)

        return {
            "stock": self._stock(stock),
            "daily_basic": self._row(latest_daily_basic),
            "latest_daily_bar": self._row(latest_daily_bar),
            "technical_snapshot": self._mapping(latest_snapshot),
            "sectors": sectors,
        }

    async def realtime(self, stock_code: str) -> dict:
        code = normalize_symbol(stock_code)
        quote = None
        minute_bars: list[dict] = []
        attempted: list[str] = []
        errors: list[str] = []
        resolved_source = None

        for provider_name, quote_call, minute_call in (
            ("mootdx", self.mootdx.quote, self.mootdx.minute_bars),
            ("akshare", self.akshare.quote, lambda value: self.akshare.minute_bars(value, start_time=None, end_time=None)),
        ):
            attempted.append(provider_name)
            try:
                quote_data, _ = await quote_call(code)
                minute_data, _ = await minute_call(code)
                if quote_data or minute_data:
                    quote = json_safe(quote_data)
                    minute_bars = [json_safe(item) for item in minute_data]
                    resolved_source = provider_name
                    break
            except Exception as exc:
                errors.append(f"{provider_name}: {exc}")

        minute_bars.sort(key=lambda item: str(item.get("bar_time") or ""))
        return {
            "stock_code": code,
            "quote": quote,
            "minute_bars": minute_bars,
            "meta": {
                "query_mode": "provider_only",
                "resolved_source": resolved_source,
                "attempted_engines": attempted,
                "fallback_used": bool(resolved_source and attempted.index(resolved_source) > 0),
                "persisted": False,
                "errors": errors,
            },
        }

    async def daily_bars(self, stock_code: str, *, limit: int = 250) -> dict:
        code = normalize_symbol(stock_code)
        rows = await self.repository.list_daily_bars(stock_code=code, limit=limit)
        factor_mas = await self.repository.list_stock_daily_factor_mas(
            stock_code=code,
            trade_dates=[row.trade_date for row in rows],
        )
        items = []
        for row in reversed(rows):
            item = self._row(row)
            item.update(
                factor_mas.get(
                    row.trade_date,
                    {"ma5": None, "ma10": None, "ma20": None, "ma30": None, "ma60": None},
                )
            )
            items.append(item)
        return {"stock_code": code, "items": items, "total": len(items), "source": "database"}

    async def minute_bars(self, stock_code: str, *, trade_date: date | None, limit: int = 2000) -> dict:
        code = normalize_symbol(stock_code)
        if trade_date is None:
            # A minute chart must represent one trading session. Returning the latest
            # N rows across several days makes same-clock timestamps collide in the UI.
            trade_date = await self.session.scalar(
                select(func.max(MinuteBar.trade_date)).where(MinuteBar.stock_code == code)
            )
        start_time = end_time = None
        if trade_date is not None:
            shanghai = ZoneInfo("Asia/Shanghai")
            start_time = datetime.combine(trade_date, time.min, tzinfo=shanghai)
            end_time = start_time + timedelta(days=1)
        rows = await self.repository.list_minute_bars(stock_code=code, start_time=start_time, end_time=end_time, limit=limit)
        items = [self._row(row) for row in reversed(rows)]
        resolved_trade_date = trade_date.isoformat() if trade_date else (items[-1].get("trade_date") if items else None)
        reference_price = None
        if trade_date is not None:
            daily_bar = await self._latest_row(
                DailyBar,
                [DailyBar.stock_code == code, DailyBar.trade_date == trade_date],
                DailyBar.id.desc(),
            )
            if daily_bar is not None:
                reference_price = daily_bar.pre_close_price
        return {
            "stock_code": code,
            "trade_date": resolved_trade_date,
            "reference_price": reference_price,
            "items": items,
            "total": len(items),
            "source": "database",
        }

    async def factors(self, stock_code: str, *, trade_date: date | None, lookback: int = 60) -> dict:
        code = normalize_symbol(stock_code)
        technical_filters = [StockTechnicalFactorDaily.stock_code == code]
        chip_filters = [StockChipPerfDaily.stock_code == code]
        if trade_date is not None:
            technical_filters.append(StockTechnicalFactorDaily.trade_date <= trade_date)
            chip_filters.append(StockChipPerfDaily.trade_date <= trade_date)

        # Minute factors describe an intraday session. They must not share the
        # daily-factor lookback limit, otherwise a 120-row request returns only
        # the afternoon half of a normal 240-minute A-share session.
        minute_trade_date = trade_date or await self.session.scalar(
            select(func.max(StockFactorMinute.trade_date)).where(StockFactorMinute.stock_code == code)
        )
        minute_filters = [StockFactorMinute.stock_code == code]
        if minute_trade_date is not None:
            minute_filters.append(StockFactorMinute.trade_date == minute_trade_date)

        daily = await self.repository.list_active_daily_factors(
            stock_code=code,
            end_date=trade_date,
            limit=lookback,
        )
        minute = await self.repository.list_rows(
            StockFactorMinute,
            filters=minute_filters,
            order_by=[StockFactorMinute.bar_time.desc()],
            limit=400,
        )
        # The workbench only consumes the latest snapshot and enhanced-factor
        # documents. Keeping their full JSON history in this response made a
        # single-stock page request unnecessarily large and slow.
        snapshots = await self.repository.computed_technical_snapshots(
            stock_code=code,
            end_date=trade_date,
            limit=1,
        )
        technical = await self.repository.list_rows(StockTechnicalFactorDaily, filters=technical_filters, order_by=[StockTechnicalFactorDaily.trade_date.desc()], limit=1)
        chip = await self.repository.list_rows(StockChipPerfDaily, filters=chip_filters, order_by=[StockChipPerfDaily.trade_date.desc()], limit=1)

        latest_daily = self._mapping(daily[0]) if daily else None
        latest_technical = self._row(technical[0]) if technical else None
        latest_chip = self._row(chip[0]) if chip else None
        latest_snapshot = self._mapping(snapshots[0]) if snapshots else None
        return {
            "stock_code": code,
            "daily_factors": [self._mapping(row) for row in reversed(daily)],
            "minute_factors": [self._row(row) for row in reversed(minute)],
            "minute_factor_trade_date": minute_trade_date.isoformat() if minute_trade_date else None,
            "technical_snapshots": [self._mapping(row) for row in reversed(snapshots)],
            "technical_factors": [self._row(row) for row in reversed(technical)],
            "chip_perf": [self._row(row) for row in reversed(chip)],
            "latest": {
                "daily_factor": latest_daily,
                "technical_factor": latest_technical,
                "chip_perf": latest_chip,
                "technical_snapshot": latest_snapshot,
            },
            "missing": {
                "technical_factor": latest_technical is None,
                "chip_perf": latest_chip is None,
            },
        }

    async def fund_flow(self, stock_code: str, *, lookback: int = 60) -> dict:
        code = normalize_symbol(stock_code)
        rows = await self.repository.list_rows(
            StockFundFlowDaily,
            filters=[StockFundFlowDaily.stock_code == code],
            order_by=[StockFundFlowDaily.trade_date.desc()],
            limit=lookback,
        )
        items = [self._row(row) for row in reversed(rows)]
        return {"stock_code": code, "items": items, "latest": self._row(rows[0]) if rows else None, "total": len(items), "source": "database"}

    async def events(self, stock_code: str, *, lookback: int = 60) -> dict:
        code = normalize_symbol(stock_code)
        since = date.today() - timedelta(days=lookback * 2)
        limit_events = await self.repository.list_rows(
            LimitEventDaily,
            filters=[LimitEventDaily.stock_code == code, LimitEventDaily.trade_date >= since],
            order_by=[LimitEventDaily.trade_date.desc(), LimitEventDaily.id.desc()],
            limit=lookback,
        )
        lhb_events = await self.repository.list_rows(
            LhbEvent,
            filters=[LhbEvent.stock_code == code, LhbEvent.trade_date >= since],
            order_by=[LhbEvent.trade_date.desc(), LhbEvent.id.desc()],
            limit=lookback,
        )
        seats = await self.repository.list_rows(
            LhbSeatDetail,
            filters=[LhbSeatDetail.stock_code == code, LhbSeatDetail.trade_date >= since],
            order_by=[LhbSeatDetail.trade_date.desc(), LhbSeatDetail.rank.asc()],
            limit=lookback * 5,
        )
        announcements = await self.repository.list_rows(
            Announcement,
            filters=[Announcement.stock_code == code],
            order_by=[Announcement.published_at.desc()],
            limit=20,
        )
        return {
            "stock_code": code,
            "limit_events": [self._row(row) for row in limit_events],
            "lhb_events": [self._row(row) for row in lhb_events],
            "lhb_seats": [self._row(row) for row in seats],
            "announcements": [self._row(row) for row in announcements],
        }

    async def _stock_sectors(self, stock_code: str) -> dict:
        result = await self.session.execute(
            select(SectorBasic, SectorComponent)
            .join(SectorComponent, SectorComponent.sector_code == SectorBasic.sector_code)
            .where(SectorComponent.stock_code == stock_code)
            .order_by(SectorBasic.sector_type.asc(), SectorBasic.sector_name.asc())
        )
        items = []
        for sector, component in result.all():
            items.append(
                {
                    "sector_code": sector.sector_code,
                    "sector_name": sector.sector_name,
                    "sector_type": sector.sector_type,
                    "source": sector.source,
                    "component_source": component.source,
                }
            )
        return {
            "concepts": [item for item in items if item["sector_type"] == "concept"],
            "industries": [item for item in items if item["sector_type"] == "industry"],
            "items": items,
        }

    async def _latest_row(self, model, filters: list, order_by):
        result = await self.session.execute(select(model).where(*filters).order_by(order_by).limit(1))
        return result.scalar_one_or_none()

    def _stock(self, row: Stock) -> dict:
        return {
            "stock_code": row.stock_code,
            "stock_name": row.stock_name,
            "market": row.market,
            "exchange": row.exchange,
            "list_date": row.list_date.isoformat() if row.list_date else None,
            "delist_date": row.delist_date.isoformat() if row.delist_date else None,
            "status": row.status,
            "industry": row.industry,
            "area": row.area,
        }

    def _row(self, row) -> dict | None:
        if row is None:
            return None
        result = {}
        for attr in row.__mapper__.column_attrs:
            result[attr.key] = json_safe(getattr(row, attr.key))
        return result

    @staticmethod
    def _mapping(row: dict | None) -> dict | None:
        if row is None:
            return None
        return {key: json_safe(value) for key, value in dict(row).items()}
