from collections.abc import Iterable
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.market_data.models import (
    DailyBar,
    IndexBasic,
    IndexComponent,
    IndexDailyBasic,
    IndexBar,
    LhbEvent,
    LhbSeatDetail,
    LimitEventDaily,
    MarketDailyStat,
    MinuteBar,
    ProviderRawRecord,
    QuoteSnapshot,
    SectorBasic,
    SectorBar,
    SectorComponent,
    SectorFactorDaily,
    SectorFundFlowDaily,
    Stock,
    StockChipPerfDaily,
    StockDailyBasic,
    StockFactorDaily,
    StockFundFlowDaily,
    StockNorthHoldDaily,
    StockTechnicalFactorDaily,
    TradeCalendar,
)
from app.modules.market_data.partitioning import ensure_market_partition, partition_date_from_child_name


MAX_POSTGRES_QUERY_PARAMS = 30000
DEFAULT_BULK_UPSERT_BATCH_SIZE = 1000
MAINLAND_EXCHANGES = ("SH", "SZ", "SSE", "SZSE")
STOCK_LIMIT_EVENT_HISTORY_CAPABILITY = "stock_limit_event_history_backfill"


def _chunked(rows: list[dict], batch_size: int) -> Iterable[list[dict]]:
    for offset in range(0, len(rows), batch_size):
        yield rows[offset : offset + batch_size]


def _safe_batch_size(rows: list[dict], *, default: int = DEFAULT_BULK_UPSERT_BATCH_SIZE) -> int:
    if not rows:
        return default
    # asyncpg rejects queries with more than 32767 bound parameters. SQLAlchemy
    # expands multi-row INSERT values into one bind per row field, so keep a
    # little headroom for JSON and dialect-specific binds.
    column_count = max(1, len(rows[0]))
    return max(1, min(default, MAX_POSTGRES_QUERY_PARAMS // column_count))


class MarketDataRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_stock(self, stock_code: str) -> Stock | None:
        result = await self.session.execute(select(Stock).where(Stock.stock_code == stock_code))
        return result.scalar_one_or_none()

    async def upsert_stock(self, row: dict) -> Stock:
        insert_stmt = insert(Stock).values(**row)
        stmt = insert_stmt.on_conflict_do_update(
            index_elements=[Stock.stock_code],
            set_={
                "stock_name": insert_stmt.excluded.stock_name,
                "market": insert_stmt.excluded.market,
                "exchange": insert_stmt.excluded.exchange,
                "list_date": insert_stmt.excluded.list_date,
                "delist_date": insert_stmt.excluded.delist_date,
                "status": insert_stmt.excluded.status,
                "industry": insert_stmt.excluded.industry,
                "area": insert_stmt.excluded.area,
                Stock.metadata_json: insert_stmt.excluded["metadata"],
            },
        ).returning(Stock)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def get_stock_map(self, stock_codes: list[str]) -> dict[str, Stock]:
        if not stock_codes:
            return {}
        result = await self.session.execute(select(Stock).where(Stock.stock_code.in_(stock_codes)))
        return {row.stock_code: row for row in result.scalars().all()}

    async def list_active_stock_codes(self) -> list[str]:
        result = await self.session.execute(
            select(Stock.stock_code)
            .where(
                Stock.status == "active",
                or_(
                    Stock.exchange.in_(MAINLAND_EXCHANGES),
                    and_(
                        or_(Stock.exchange.is_(None), Stock.exchange == ""),
                        or_(
                            Stock.stock_code.like("0%"),
                            Stock.stock_code.like("3%"),
                            Stock.stock_code.like("6%"),
                        ),
                    ),
                ),
            )
            .order_by(Stock.stock_code)
        )
        return list(result.scalars().all())

    async def stock_pool_member_codes(self, pool_code: str) -> list[str]:
        """Return enabled stock-pool members without coupling market_data to stock_pool services."""
        result = await self.session.execute(
            text(
                "SELECT m.stock_code "
                "FROM t_stock_pool p "
                "JOIN t_stock_pool_member m ON m.pool_id = p.id "
                "WHERE p.pool_code = :pool_code AND p.is_enabled = TRUE "
                "ORDER BY m.stock_code"
            ),
            {"pool_code": pool_code},
        )
        return [str(row[0]) for row in result.all()]

    async def stock_pool_exists(self, pool_code: str) -> bool:
        result = await self.session.execute(
            text("SELECT 1 FROM t_stock_pool WHERE pool_code = :pool_code AND is_enabled = TRUE LIMIT 1"),
            {"pool_code": pool_code},
        )
        return result.first() is not None

    async def existing_daily_bar_dates(self, *, stock_code: str, start_date: date, end_date: date) -> set[date]:
        result = await self.session.execute(
            select(DailyBar.trade_date).where(
                DailyBar.stock_code == stock_code,
                DailyBar.trade_date >= start_date,
                DailyBar.trade_date <= end_date,
            )
        )
        return set(result.scalars().all())

    async def existing_daily_basic_dates(self, *, stock_code: str, start_date: date, end_date: date) -> set[date]:
        result = await self.session.execute(
            select(StockDailyBasic.trade_date).where(
                StockDailyBasic.stock_code == stock_code,
                StockDailyBasic.trade_date >= start_date,
                StockDailyBasic.trade_date <= end_date,
            )
        )
        return set(result.scalars().all())

    async def existing_stock_fund_flow_dates(self, *, stock_code: str, start_date: date, end_date: date) -> set[date]:
        result = await self.session.execute(
            select(StockFundFlowDaily.trade_date).where(
                StockFundFlowDaily.stock_code == stock_code,
                StockFundFlowDaily.trade_date >= start_date,
                StockFundFlowDaily.trade_date <= end_date,
            )
        )
        return set(result.scalars().all())

    async def existing_stock_technical_factor_dates(self, *, stock_code: str, start_date: date, end_date: date) -> set[date]:
        result = await self.session.execute(
            select(StockTechnicalFactorDaily.trade_date).where(
                StockTechnicalFactorDaily.stock_code == stock_code,
                StockTechnicalFactorDaily.trade_date >= start_date,
                StockTechnicalFactorDaily.trade_date <= end_date,
            )
        )
        return set(result.scalars().all())

    async def completed_stock_limit_event_backfill_dates(
        self,
        *,
        completion_scope: str,
        start_date: date,
        end_date: date,
    ) -> set[date]:
        result = await self.session.execute(
            select(ProviderRawRecord.record_key).where(
                ProviderRawRecord.capability == STOCK_LIMIT_EVENT_HISTORY_CAPABILITY,
                ProviderRawRecord.status == "captured",
                ProviderRawRecord.request_params["completion_scope"].astext == completion_scope,
            )
        )
        completed: set[date] = set()
        for record_key in result.scalars().all():
            try:
                trade_date = date.fromisoformat(str(record_key or "")[-10:])
            except ValueError:
                continue
            if start_date <= trade_date <= end_date:
                completed.add(trade_date)
        return completed

    async def existing_index_bar_dates(self, *, index_code: str, start_date: date, end_date: date) -> set[date]:
        result = await self.session.execute(
            select(IndexBar.trade_date).where(
                IndexBar.index_code == index_code,
                IndexBar.trade_date >= start_date,
                IndexBar.trade_date <= end_date,
            )
        )
        return set(result.scalars().all())

    async def existing_sector_bar_dates(self, *, sector_code: str, start_date: date, end_date: date) -> set[date]:
        result = await self.session.execute(
            select(SectorBar.trade_date).where(
                SectorBar.sector_code == sector_code,
                SectorBar.trade_date >= start_date,
                SectorBar.trade_date <= end_date,
            )
        )
        return set(result.scalars().all())

    async def existing_index_daily_basic_dates(self, *, index_code: str, start_date: date, end_date: date) -> set[date]:
        result = await self.session.execute(
            select(IndexDailyBasic.trade_date).where(
                IndexDailyBasic.index_code == index_code,
                IndexDailyBasic.trade_date >= start_date,
                IndexDailyBasic.trade_date <= end_date,
            )
        )
        return set(result.scalars().all())

    async def list_index_history_targets(self) -> list[dict[str, str]]:
        rows = (await self.session.execute(select(IndexBasic).order_by(IndexBasic.index_code))).scalars().all()
        targets: list[dict[str, str]] = []
        for row in rows:
            metadata = dict(row.metadata_json or {})
            official_code = str(metadata.get("official_index_code") or "").strip()
            if not official_code:
                official_code = f"{row.index_code}.SZ" if row.index_code.startswith("399") else f"{row.index_code}.SH"
            targets.append({"index_code": row.index_code, "official_index_code": official_code})
        return targets

    async def clear_stock_fact_range(
        self,
        *,
        fact_kind: str,
        stock_codes: list[str],
        start_date: date,
        end_date: date,
    ) -> int:
        if not stock_codes:
            return 0
        model = {
            "daily": DailyBar,
            "daily_basic": StockDailyBasic,
            "moneyflow": StockFundFlowDaily,
            "stock_technical_factor_pro": StockTechnicalFactorDaily,
        }.get(fact_kind)
        if model is None:
            raise ValueError(f"unsupported stock fact kind: {fact_kind}")
        deleted = 0
        for codes in _chunked(stock_codes, 1000):
            result = await self.session.execute(
                delete(model).where(
                    model.stock_code.in_(codes),
                    model.trade_date >= start_date,
                    model.trade_date <= end_date,
                )
            )
            deleted += int(result.rowcount or 0)
        return deleted

    async def clear_stock_limit_event_range(
        self,
        *,
        stock_codes: list[str],
        start_date: date,
        end_date: date,
    ) -> int:
        deleted = 0
        for codes in _chunked(stock_codes, 1000):
            result = await self.session.execute(
                delete(LimitEventDaily).where(
                    LimitEventDaily.stock_code.in_(codes),
                    LimitEventDaily.trade_date >= start_date,
                    LimitEventDaily.trade_date <= end_date,
                )
            )
            deleted += int(result.rowcount or 0)
        return deleted

    async def clear_sector_daily_fact_range(self, *, start_date: date, end_date: date) -> int:
        deleted = 0
        for model in (SectorBar, SectorFundFlowDaily):
            result = await self.session.execute(
                delete(model).where(model.trade_date >= start_date, model.trade_date <= end_date)
            )
            deleted += int(result.rowcount or 0)
        return deleted

    async def clear_index_daily_fact_range(
        self,
        *,
        index_codes: list[str],
        start_date: date,
        end_date: date,
    ) -> int:
        if not index_codes:
            return 0
        deleted = 0
        for codes in _chunked(index_codes, 1000):
            for model in (IndexBar, IndexDailyBasic):
                result = await self.session.execute(
                    delete(model).where(
                        model.index_code.in_(codes),
                        model.trade_date >= start_date,
                        model.trade_date <= end_date,
                    )
                )
                deleted += int(result.rowcount or 0)
        return deleted

    async def open_trade_dates_between(self, *, start_date: date, end_date: date, market: str = "CN") -> list[date]:
        result = await self.session.execute(
            select(TradeCalendar.trade_date)
            .where(
                TradeCalendar.market == market,
                TradeCalendar.is_open.is_(True),
                TradeCalendar.trade_date >= start_date,
                TradeCalendar.trade_date <= end_date,
            )
            .order_by(TradeCalendar.trade_date.asc())
        )
        return list(result.scalars().all())

    async def get_trade_day(self, trade_date: date, *, market: str = "CN") -> TradeCalendar | None:
        result = await self.session.execute(
            select(TradeCalendar).where(TradeCalendar.trade_date == trade_date, TradeCalendar.market == market)
        )
        return result.scalar_one_or_none()

    async def recent_open_trade_dates(self, *, up_to: date, limit: int, market: str = "CN") -> list[date]:
        result = await self.session.execute(
            select(TradeCalendar.trade_date)
            .where(
                TradeCalendar.market == market,
                TradeCalendar.is_open.is_(True),
                TradeCalendar.trade_date <= up_to,
            )
            .order_by(TradeCalendar.trade_date.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def recent_daily_trade_dates(self, *, up_to: date, limit: int) -> list[date]:
        """Return recent trading dates that already have canonical stock daily bars."""
        result = await self.session.execute(
            select(DailyBar.trade_date)
            .where(DailyBar.trade_date <= up_to)
            .distinct()
            .order_by(DailyBar.trade_date.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def daily_close_asset_counts(self, trade_date: date) -> dict[str, int | set[str]]:
        """Read the small count/marker set used by repair and report readiness."""
        start = datetime.combine(trade_date, datetime.min.time(), tzinfo=ZoneInfo("Asia/Shanghai"))
        end = datetime.combine(
            trade_date.fromordinal(trade_date.toordinal() + 1),
            datetime.min.time(),
            tzinfo=ZoneInfo("Asia/Shanghai"),
        )
        row = (
            await self.session.execute(
                text(
                    """
                    SELECT
                        (SELECT count(*) FROM t_stock WHERE status = 'active') AS active_stock,
                        (SELECT count(DISTINCT stock_code) FROM t_daily_bar WHERE trade_date = :trade_date) AS daily_bar,
                        (SELECT count(DISTINCT stock_code) FROM t_stock_daily_basic WHERE trade_date = :trade_date) AS daily_basic,
                        (SELECT count(DISTINCT stock_code) FROM t_stock_fund_flow_daily WHERE trade_date = :trade_date) AS stock_moneyflow,
                        (SELECT count(*) FROM t_limit_event_daily WHERE trade_date = :trade_date) AS limit_event,
                        (SELECT count(*) FROM t_lhb_event WHERE trade_date = :trade_date) AS lhb_event,
                        (SELECT count(DISTINCT stock_code) FROM t_stock_technical_factor_daily WHERE trade_date = :trade_date) AS stock_technical,
                        (SELECT count(DISTINCT stock_code) FROM t_stock_factor_daily
                            WHERE trade_date = :trade_date AND source = 'system:daily_close') AS daily_factor,
                        (SELECT count(DISTINCT stock_code) FROM t_technical_indicator_snapshot
                            WHERE snapshot_time >= :snapshot_start AND snapshot_time < :snapshot_end
                              AND source = 'system:daily_close') AS technical_snapshot,
                        (SELECT count(DISTINCT index_code) FROM t_index_bar WHERE trade_date = :trade_date) AS index_bar,
                        (SELECT count(DISTINCT index_code) FROM t_index_daily_basic WHERE trade_date = :trade_date) AS index_daily_basic,
                        (SELECT count(DISTINCT sector_code) FROM t_sector_bar WHERE trade_date = :trade_date) AS sector_bar,
                        (SELECT count(DISTINCT sector_code) FROM t_sector_fund_flow_daily WHERE trade_date = :trade_date) AS sector_moneyflow,
                        (SELECT count(DISTINCT sector_code) FROM t_sector_factor_daily WHERE trade_date = :trade_date) AS sector_factor,
                        (SELECT count(*) FROM t_market_daily_stat WHERE trade_date = :trade_date) AS market_stat,
                        (SELECT count(*) FROM t_sector_basic
                            WHERE source LIKE 'tushare:%'
                              AND sector_code LIKE 'ths_%'
                              AND metadata ->> 'raw_code' IS NOT NULL) AS tushare_sector
                    """
                ),
                {
                    "trade_date": trade_date,
                    "snapshot_start": start,
                    "snapshot_end": end,
                },
            )
        ).mappings().one()
        capabilities = set(
            (
                await self.session.execute(
                    select(ProviderRawRecord.capability).where(
                        ProviderRawRecord.record_key == trade_date.isoformat(),
                        ProviderRawRecord.status == "captured",
                        ProviderRawRecord.capability.in_(
                            (
                                "daily_market_close_stock_limit",
                                "daily_market_close_stock_suspend",
                                "daily_market_close_lhb",
                                "daily_market_close_lhb_seats",
                                "daily_market_close_index_daily_basic",
                                "daily_market_close_market_stats",
                                "daily_market_close_sector_bars",
                                "daily_market_close_moneyflow_cnt_ths",
                                "daily_market_close_moneyflow_ind_ths",
                            )
                        ),
                    )
                )
            ).scalars().all()
        )
        return {
            **{key: int(value or 0) for key, value in row.items()},
            "raw_capabilities": capabilities,
        }

    async def delete_trade_calendar_year(self, *, year: int, market: str = "CN") -> int:
        result = await self.session.execute(
            delete(TradeCalendar).where(
                TradeCalendar.market == market,
                TradeCalendar.trade_date >= date(year, 1, 1),
                TradeCalendar.trade_date <= date(year, 12, 31),
            )
        )
        return int(result.rowcount or 0)

    async def upsert_trade_calendar(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        stmt = insert(TradeCalendar).values(rows)
        await self.session.execute(
            stmt.on_conflict_do_update(
                index_elements=[TradeCalendar.trade_date, TradeCalendar.market],
                set_={
                    "is_open": stmt.excluded.is_open,
                    "previous_trade_date": stmt.excluded.previous_trade_date,
                    "next_trade_date": stmt.excluded.next_trade_date,
                    "source": stmt.excluded.source,
                    "metadata": stmt.excluded.metadata,
                },
            )
        )
        return len(rows)

    async def list_stocks_for_detail(self, *, limit: int, detail_refresh_days: int, mode: str) -> list[Stock]:
        rows = await self.list_rows(Stock, order_by=[Stock.stock_code.asc()], limit=20000)
        cutoff = datetime.now(timezone.utc).timestamp() - detail_refresh_days * 86400

        def detail_time(row: Stock) -> float | None:
            value = (row.metadata_json or {}).get("detail_last_synced_at")
            if not value:
                return None
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.timestamp()
            except ValueError:
                return None

        candidates = []
        for row in rows:
            if row.status not in {"active", "suspended"}:
                continue
            exchange = str(row.exchange or "").upper()
            if exchange not in MAINLAND_EXCHANGES and not row.stock_code.startswith(("0", "3", "6")):
                continue
            missing = not row.industry or not row.list_date
            synced_at = detail_time(row)
            stale = synced_at is None or synced_at < cutoff
            if mode == "none":
                continue
            if mode == "missing" and not missing:
                continue
            if mode == "stale" and not stale:
                continue
            if mode == "missing_or_stale" and not (missing or stale):
                continue
            candidates.append((0 if missing else 1, row.stock_code, row))
        candidates.sort(key=lambda item: (item[0], item[1]))
        return [row for _, _, row in candidates[:limit]]

    async def upsert_stock_rows(self, rows: list[dict], *, batch_size: int = 1000) -> int:
        total = 0
        for offset in range(0, len(rows), batch_size):
            batch = rows[offset : offset + batch_size]
            if not batch:
                continue
            insert_stmt = insert(Stock).values(batch)
            await self.session.execute(
                insert_stmt.on_conflict_do_update(
                    index_elements=[Stock.stock_code],
                    set_={
                        "stock_name": insert_stmt.excluded.stock_name,
                        "market": insert_stmt.excluded.market,
                        "exchange": insert_stmt.excluded.exchange,
                        "list_date": case(
                            (insert_stmt.excluded.list_date.is_not(None), insert_stmt.excluded.list_date),
                            else_=Stock.list_date,
                        ),
                        "delist_date": case(
                            (insert_stmt.excluded.delist_date.is_not(None), insert_stmt.excluded.delist_date),
                            else_=Stock.delist_date,
                        ),
                        "status": insert_stmt.excluded.status,
                        "industry": case(
                            (insert_stmt.excluded.industry.is_not(None), insert_stmt.excluded.industry),
                            else_=Stock.industry,
                        ),
                        "area": case((insert_stmt.excluded.area.is_not(None), insert_stmt.excluded.area), else_=Stock.area),
                        Stock.metadata_json: Stock.metadata_json.op("||")(insert_stmt.excluded["metadata"]),
                    },
                )
            )
            total += len(batch)
        return total

    async def update_stock_statuses(self, *, stock_codes: list[str], status: str) -> int:
        if not stock_codes:
            return 0
        result = await self.session.execute(update(Stock).where(Stock.stock_code.in_(stock_codes)).values(status=status))
        return int(result.rowcount or 0)

    async def browse_sectors(
        self,
        *,
        sector_type: str,
        provider: str,
        keyword: str | None,
        page: int,
        page_size: int,
    ) -> dict:
        sector_filters = [SectorBasic.sector_type == sector_type]
        if provider != "all":
            sector_filters.append(SectorBasic.source.like(f"{provider}:%"))
        if keyword:
            sector_filters.append(
                or_(
                    SectorBasic.sector_name.ilike(f"%{keyword}%"),
                    SectorBasic.sector_code.ilike(f"%{keyword}%"),
                )
            )
        component_source = True if provider == "all" else SectorComponent.source.like(f"{provider}:%")
        join_condition = and_(
            SectorComponent.sector_code == SectorBasic.sector_code,
            component_source,
        )
        total = await self.session.scalar(select(func.count()).select_from(SectorBasic).where(*sector_filters)) or 0
        rows = (
            await self.session.execute(
                select(
                    SectorBasic.sector_code,
                    SectorBasic.sector_name,
                    SectorBasic.sector_type,
                    SectorBasic.source,
                    SectorBasic.updated_at,
                    func.count(SectorComponent.id).label("component_count"),
                )
                .outerjoin(SectorComponent, join_condition)
                .where(*sector_filters)
                .group_by(
                    SectorBasic.sector_code,
                    SectorBasic.sector_name,
                    SectorBasic.sector_type,
                    SectorBasic.source,
                    SectorBasic.updated_at,
                )
                .order_by(SectorBasic.sector_name.asc(), SectorBasic.sector_code.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).mappings().all()
        return {
            "items": [
                {
                    "sector_code": row["sector_code"],
                    "sector_name": row["sector_name"],
                    "sector_type": row["sector_type"],
                    "source": row["source"],
                    "last_synced_at": row["updated_at"],
                    "component_count": int(row["component_count"] or 0),
                }
                for row in rows
            ],
            "total": int(total),
            "page": page,
            "page_size": page_size,
        }

    async def browse_sector_stocks(
        self,
        *,
        sector_code: str,
        keyword: str | None,
        status: str | None,
        page: int,
        page_size: int,
    ) -> dict | None:
        sector = (
            await self.session.execute(select(SectorBasic).where(SectorBasic.sector_code == sector_code).limit(1))
        ).scalar_one_or_none()
        if sector is None:
            return None
        provider_family = (sector.source or "").split(":", 1)[0]
        component_filters = [SectorComponent.sector_code == sector_code]
        if provider_family in {"tushare", "akshare", "mootdx"}:
            component_filters.append(SectorComponent.source.like(f"{provider_family}:%"))
        raw_name = SectorComponent.metadata_json["raw"]["con_name"].astext
        if keyword:
            component_filters.append(
                or_(
                    SectorComponent.stock_code.ilike(f"%{keyword}%"),
                    Stock.stock_name.ilike(f"%{keyword}%"),
                    raw_name.ilike(f"%{keyword}%"),
                )
            )
        if status:
            component_filters.append(Stock.status == status)
        base = (
            select(SectorComponent)
            .outerjoin(Stock, Stock.stock_code == SectorComponent.stock_code)
            .where(*component_filters)
        )
        total = await self.session.scalar(select(func.count()).select_from(base.subquery())) or 0
        rows = (
            await self.session.execute(
                select(
                    SectorComponent.stock_code,
                    SectorComponent.source.label("component_source"),
                    SectorComponent.weight,
                    SectorComponent.created_at.label("linked_at"),
                    raw_name.label("raw_stock_name"),
                    Stock.stock_name,
                    Stock.exchange,
                    Stock.industry,
                    Stock.area,
                    Stock.status,
                )
                .outerjoin(Stock, Stock.stock_code == SectorComponent.stock_code)
                .where(*component_filters)
                .order_by(SectorComponent.stock_code.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).mappings().all()
        return {
            "sector": {
                "sector_code": sector.sector_code,
                "sector_name": sector.sector_name,
                "sector_type": sector.sector_type,
                "source": sector.source,
                "last_synced_at": sector.updated_at,
            },
            "items": [
                {
                    "stock_code": row["stock_code"],
                    "stock_name": row["stock_name"] or row["raw_stock_name"],
                    "raw_stock_name": row["raw_stock_name"],
                    "stock_exists": row["stock_name"] is not None,
                    "exchange": row["exchange"],
                    "industry": row["industry"],
                    "area": row["area"],
                    "status": row["status"],
                    "weight": row["weight"],
                    "component_source": row["component_source"],
                    "linked_at": row["linked_at"],
                }
                for row in rows
            ],
            "total": int(total),
            "page": page,
            "page_size": page_size,
        }

    async def get_sector(self, sector_code: str) -> SectorBasic | None:
        result = await self.session.execute(select(SectorBasic).where(SectorBasic.sector_code == sector_code).limit(1))
        return result.scalar_one_or_none()

    async def search_tushare_ths_sectors(self, *, keyword: str | None, sector_type: str = "concept", limit: int = 20) -> list[dict]:
        filters = [
            SectorBasic.sector_type == sector_type,
            SectorBasic.source.like("tushare:%"),
            SectorBasic.sector_code.like(f"ths_{sector_type}_%"),
        ]
        if keyword:
            filters.append(
                or_(
                    SectorBasic.sector_name.ilike(f"%{keyword}%"),
                    SectorBasic.sector_code.ilike(f"%{keyword}%"),
                )
            )
        rows = (
            await self.session.execute(
                select(
                    SectorBasic.sector_code,
                    SectorBasic.sector_name,
                    SectorBasic.sector_type,
                    SectorBasic.source,
                    SectorBasic.updated_at,
                    func.count(SectorComponent.id).label("component_count"),
                )
                .outerjoin(
                    SectorComponent,
                    and_(
                        SectorComponent.sector_code == SectorBasic.sector_code,
                        SectorComponent.source.like("tushare:%"),
                    ),
                )
                .where(*filters)
                .group_by(
                    SectorBasic.sector_code,
                    SectorBasic.sector_name,
                    SectorBasic.sector_type,
                    SectorBasic.source,
                    SectorBasic.updated_at,
                )
                .order_by(SectorBasic.sector_name.asc(), SectorBasic.sector_code.asc())
                .limit(limit)
            )
        ).mappings().all()
        return [
            {
                "sector_code": row["sector_code"],
                "sector_name": row["sector_name"],
                "sector_type": row["sector_type"],
                "source": row["source"],
                "last_synced_at": row["updated_at"],
                "component_count": int(row["component_count"] or 0),
            }
            for row in rows
        ]

    async def tushare_ths_sector_map(self) -> dict[str, dict]:
        rows = (
            await self.session.execute(
                select(SectorBasic).where(
                    SectorBasic.source.like("tushare:%"),
                    SectorBasic.sector_code.like("ths_%"),
                )
            )
        ).scalars().all()
        mapping: dict[str, dict] = {}
        for row in rows:
            raw_code = str((row.metadata_json or {}).get("raw_code") or row.sector_code.rsplit("_", 1)[-1])
            if raw_code:
                mapping[raw_code] = {
                    "sector_code": row.sector_code,
                    "sector_name": row.sector_name,
                    "sector_type": row.sector_type,
                }
        return mapping

    async def sector_summaries_by_names(self, *, names: list[str], sector_type: str = "concept") -> dict[str, dict]:
        if not names:
            return {}
        rows = (
            await self.session.execute(
                select(
                    SectorBasic.sector_code,
                    SectorBasic.sector_name,
                    SectorBasic.sector_type,
                    SectorBasic.source,
                    SectorBasic.updated_at,
                    func.count(SectorComponent.id).label("component_count"),
                )
                .outerjoin(
                    SectorComponent,
                    and_(
                        SectorComponent.sector_code == SectorBasic.sector_code,
                        SectorComponent.source.like("tushare:%"),
                    ),
                )
                .where(
                    SectorBasic.sector_type == sector_type,
                    SectorBasic.source.like("tushare:%"),
                    SectorBasic.sector_name.in_(names),
                )
                .group_by(
                    SectorBasic.sector_code,
                    SectorBasic.sector_name,
                    SectorBasic.sector_type,
                    SectorBasic.source,
                    SectorBasic.updated_at,
                )
            )
        ).mappings().all()
        return {
            row["sector_name"]: {
                "sector_code": row["sector_code"],
                "sector_name": row["sector_name"],
                "sector_type": row["sector_type"],
                "source": row["source"],
                "last_synced_at": row["updated_at"],
                "component_count": int(row["component_count"] or 0),
            }
            for row in rows
        }

    async def list_daily_bars(
        self,
        *,
        stock_code: str,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 120,
    ) -> list[DailyBar]:
        source_priority = case((DailyBar.source == "tushare:daily", 0), (DailyBar.source == "akshare_qfq", 1), (DailyBar.source == "mootdx", 2), else_=9)
        stmt = select(DailyBar).where(DailyBar.stock_code == stock_code)
        if start_date:
            stmt = stmt.where(DailyBar.trade_date >= start_date)
        if end_date:
            stmt = stmt.where(DailyBar.trade_date <= end_date)
        stmt = stmt.order_by(DailyBar.trade_date.desc(), source_priority, DailyBar.id.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_stock_daily_factor_mas(
        self,
        *,
        stock_code: str,
        trade_dates: list[date],
    ) -> dict[date, dict[str, float | None]]:
        """Return the lightweight MA projection used by the stock daily chart."""
        if not trade_dates:
            return {}
        result = await self.session.execute(
            select(
                StockFactorDaily.trade_date,
                StockFactorDaily.ma5,
                StockFactorDaily.ma10,
                StockFactorDaily.ma20,
                StockFactorDaily.ma30,
                StockFactorDaily.ma60,
            ).where(
                StockFactorDaily.stock_code == stock_code,
                StockFactorDaily.source == "system:daily_close",
                StockFactorDaily.trade_date.in_(trade_dates),
            )
        )
        return {
            row.trade_date: {
                "ma5": float(row.ma5) if row.ma5 is not None else None,
                "ma10": float(row.ma10) if row.ma10 is not None else None,
                "ma20": float(row.ma20) if row.ma20 is not None else None,
                "ma30": float(row.ma30) if row.ma30 is not None else None,
                "ma60": float(row.ma60) if row.ma60 is not None else None,
            }
            for row in result
        }

    async def upsert_daily_bars(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        for batch in _chunked(rows, _safe_batch_size(rows)):
            insert_stmt = insert(DailyBar).values(batch)
            await self.session.execute(
                insert_stmt.on_conflict_do_update(
                    index_elements=[DailyBar.stock_code, DailyBar.trade_date],
                    set_={
                        "source": insert_stmt.excluded.source,
                        "adjust_mode": insert_stmt.excluded.adjust_mode,
                        "open_price": insert_stmt.excluded.open_price,
                        "high_price": insert_stmt.excluded.high_price,
                        "low_price": insert_stmt.excluded.low_price,
                        "close_price": insert_stmt.excluded.close_price,
                        "pre_close_price": insert_stmt.excluded.pre_close_price,
                        "change_amount": insert_stmt.excluded.change_amount,
                        "change_pct": insert_stmt.excluded.change_pct,
                        "volume_hand": insert_stmt.excluded.volume_hand,
                        "volume_share": insert_stmt.excluded.volume_share,
                        "amount_yuan": insert_stmt.excluded.amount_yuan,
                        "turnover_rate": insert_stmt.excluded.turnover_rate,
                        DailyBar.metadata_json: insert_stmt.excluded.metadata,
                    },
                )
            )
        return len(rows)

    async def list_minute_bars(
        self,
        *,
        stock_code: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 240,
    ) -> list[MinuteBar]:
        stmt = select(MinuteBar).where(MinuteBar.stock_code == stock_code)
        if start_time:
            stmt = stmt.where(MinuteBar.bar_time >= start_time)
        if end_time:
            stmt = stmt.where(MinuteBar.bar_time <= end_time)
        result = await self.session.execute(stmt.order_by(MinuteBar.bar_time.desc()).limit(limit))
        return list(result.scalars().all())

    async def upsert_minute_bars(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        shanghai = ZoneInfo("Asia/Shanghai")
        for row in rows:
            if row.get("trade_date") is None:
                bar_time = row.get("bar_time")
                if isinstance(bar_time, datetime):
                    if bar_time.tzinfo is None:
                        bar_time = bar_time.replace(tzinfo=timezone.utc)
                    row["trade_date"] = bar_time.astimezone(shanghai).date()
                else:
                    raise ValueError("minute bar requires trade_date or timezone-aware bar_time")
        for batch in _chunked(rows, _safe_batch_size(rows)):
            insert_stmt = insert(MinuteBar).values(batch)
            await self.session.execute(
                insert_stmt.on_conflict_do_update(
                    index_elements=[
                        MinuteBar.stock_code,
                        MinuteBar.trade_date,
                        MinuteBar.bar_time,
                        MinuteBar.interval,
                        MinuteBar.source,
                    ],
                    set_={
                        "price": insert_stmt.excluded.price,
                        "avg_price": insert_stmt.excluded.avg_price,
                        "volume_hand": insert_stmt.excluded.volume_hand,
                        "volume_share": insert_stmt.excluded.volume_share,
                        "amount_yuan": insert_stmt.excluded.amount_yuan,
                        MinuteBar.metadata_json: insert_stmt.excluded.metadata,
                    },
                )
            )
        return len(rows)

    async def upsert_daily_basic_rows(self, rows: list[dict]) -> int:
        return await self.upsert_rows(
            StockDailyBasic,
            rows,
            conflict_attrs=["stock_code", "trade_date"],
            update_attrs=[
                "source",
                "close_price",
                "turnover_rate",
                "turnover_rate_f",
                "volume_ratio",
                "pe",
                "pe_ttm",
                "pb",
                "ps",
                "ps_ttm",
                "dv_ratio",
                "dv_ttm",
                "total_share",
                "float_share",
                "free_share",
                "total_mv",
                "circ_mv",
                "limit_status",
                "metadata_json",
            ],
        )

    async def upsert_stock_technical_factor_rows(self, rows: list[dict]) -> int:
        return await self.upsert_rows(
            StockTechnicalFactorDaily,
            rows,
            conflict_attrs=["stock_code", "trade_date"],
        )

    async def upsert_stock_chip_perf_rows(self, rows: list[dict]) -> int:
        return await self.upsert_rows(
            StockChipPerfDaily,
            rows,
            conflict_attrs=["stock_code", "trade_date"],
        )

    async def upsert_market_daily_stat_rows(self, rows: list[dict]) -> int:
        return await self.upsert_rows(
            MarketDailyStat,
            rows,
            conflict_attrs=["trade_date", "ts_code", "exchange"],
        )

    async def upsert_index_daily_basic_rows(self, rows: list[dict]) -> int:
        return await self.upsert_rows(
            IndexDailyBasic,
            rows,
            conflict_attrs=["index_code", "trade_date"],
        )

    async def upsert_stock_fund_flow_rows(self, rows: list[dict]) -> int:
        return await self.upsert_rows(
            StockFundFlowDaily,
            rows,
            conflict_attrs=["stock_code", "trade_date"],
        )

    async def upsert_limit_event_rows(self, rows: list[dict]) -> int:
        return await self.upsert_rows(
            LimitEventDaily,
            rows,
            conflict_attrs=["stock_code", "trade_date", "event_type"],
        )

    async def upsert_lhb_event_rows(self, rows: list[dict]) -> int:
        return await self.upsert_rows(
            LhbEvent,
            rows,
            conflict_attrs=["stock_code", "trade_date", "reason"],
        )

    async def upsert_lhb_seat_rows(self, rows: list[dict]) -> int:
        return await self.upsert_rows(
            LhbSeatDetail,
            rows,
            conflict_attrs=["stock_code", "trade_date", "seat_name", "side", "source"],
        )

    async def upsert_index_bar_rows(self, rows: list[dict]) -> int:
        return await self.upsert_rows(
            IndexBar,
            rows,
            conflict_attrs=["index_code", "trade_date"],
        )

    async def upsert_north_hold_rows(self, rows: list[dict]) -> int:
        return await self.upsert_rows(
            StockNorthHoldDaily,
            rows,
            conflict_attrs=["stock_code", "trade_date", "exchange"],
        )

    async def upsert_sector_bar_rows(self, rows: list[dict]) -> int:
        return await self.upsert_rows(
            SectorBar,
            rows,
            conflict_attrs=["sector_code", "trade_date"],
        )

    async def upsert_sector_fund_flow_rows(self, rows: list[dict]) -> int:
        return await self.upsert_rows(
            SectorFundFlowDaily,
            rows,
            conflict_attrs=["sector_code", "trade_date"],
        )

    async def upsert_sector_factor_rows(self, rows: list[dict]) -> int:
        return await self.upsert_rows(
            SectorFactorDaily,
            rows,
            conflict_attrs=["sector_code", "trade_date"],
        )

    async def latest_quote(self, stock_code: str) -> QuoteSnapshot | None:
        result = await self.session.execute(
            select(QuoteSnapshot)
            .where(QuoteSnapshot.stock_code == stock_code)
            .order_by(QuoteSnapshot.quote_time.desc(), QuoteSnapshot.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def insert_quote(self, row: dict) -> QuoteSnapshot:
        stmt = (
            insert(QuoteSnapshot)
            .values(**row)
            .on_conflict_do_nothing(index_elements=[QuoteSnapshot.stock_code, QuoteSnapshot.quote_time, QuoteSnapshot.source])
            .returning(QuoteSnapshot)
        )
        result = await self.session.execute(stmt)
        inserted = result.scalar_one_or_none()
        if inserted is not None:
            return inserted
        existing = await self.latest_quote(row["stock_code"])
        if existing is None:
            raise RuntimeError("quote insert conflict but existing row was not found")
        return existing

    async def minute_bar_counts(self, *, stock_codes: list[str], trade_date: date) -> dict[str, int]:
        if not stock_codes:
            return {}
        result = await self.session.execute(
            select(MinuteBar.stock_code, func.count(MinuteBar.id))
            .where(MinuteBar.stock_code.in_(stock_codes), MinuteBar.trade_date == trade_date)
            .group_by(MinuteBar.stock_code)
        )
        return {row[0]: int(row[1]) for row in result.all()}

    async def minute_factor_counts(self, *, stock_codes: list[str], trade_date: date) -> dict[str, int]:
        if not stock_codes:
            return {}
        from app.modules.market_data.models import StockFactorMinute

        result = await self.session.execute(
            select(StockFactorMinute.stock_code, func.count(StockFactorMinute.id))
            .where(
                StockFactorMinute.stock_code.in_(stock_codes),
                StockFactorMinute.trade_date == trade_date,
                StockFactorMinute.source == "system:daily_close",
            )
            .group_by(StockFactorMinute.stock_code)
        )
        return {row[0]: int(row[1]) for row in result.all()}

    async def ensure_minute_bar_partition(self, trade_date: date) -> None:
        await ensure_market_partition(self.session, parent_table="t_minute_bar", trade_date=trade_date)

    async def drop_minute_partitions_before(self, cutoff_date: date) -> list[str]:
        result = await self.session.execute(
            text(
                "SELECT c.relname FROM pg_inherits i "
                "JOIN pg_class p ON p.oid = i.inhparent "
                "JOIN pg_class c ON c.oid = i.inhrelid "
                "WHERE p.relname IN ('t_minute_bar', 't_stock_factor_minute') "
                "ORDER BY c.relname"
            )
        )
        dropped: list[str] = []
        for (child_name,) in result.all():
            partition_date = partition_date_from_child_name(str(child_name))
            if partition_date is None:
                continue
            if partition_date < cutoff_date:
                await self.session.execute(text(f"DROP TABLE IF EXISTS {child_name}"))
                dropped.append(str(child_name))
        return dropped

    async def clear_minute_ingest_data(self, trade_date: date) -> dict[str, int]:
        """Clear only current minute bars/factors for an explicit minute rebuild."""
        from app.modules.market_data.models import StockFactorMinute

        deleted: dict[str, int] = {}
        result = await self.session.execute(
            delete(MinuteBar).where(
                MinuteBar.trade_date == trade_date,
                MinuteBar.source == "mootdx",
            )
        )
        deleted["minute"] = int(result.rowcount or 0)
        result = await self.session.execute(
            delete(StockFactorMinute).where(
                StockFactorMinute.trade_date == trade_date,
                StockFactorMinute.source == "system:daily_close",
            )
        )
        deleted["minute_factor"] = int(result.rowcount or 0)
        return deleted

    async def clear_daily_close_ingest_data(self, trade_date: date) -> dict[str, int]:
        """Remove only data produced by this job for a targeted rebuild."""
        from app.modules.market_data.models import StockFactorDaily, StockFactorMinute, TechnicalIndicatorSnapshot

        start = datetime.combine(trade_date, datetime.min.time(), tzinfo=ZoneInfo("Asia/Shanghai"))
        end = datetime.combine(
            trade_date.fromordinal(trade_date.toordinal() + 1),
            datetime.min.time(),
            tzinfo=ZoneInfo("Asia/Shanghai"),
        )
        statements = {
            "daily": delete(DailyBar).where(DailyBar.trade_date == trade_date),
            "daily_basic": delete(StockDailyBasic).where(
                StockDailyBasic.trade_date == trade_date,
            ),
            "stock_technical_factor": delete(StockTechnicalFactorDaily).where(
                StockTechnicalFactorDaily.trade_date == trade_date,
            ),
            "stock_chip_perf": delete(StockChipPerfDaily).where(
                StockChipPerfDaily.trade_date == trade_date,
            ),
            "stock_fund_flow": delete(StockFundFlowDaily).where(StockFundFlowDaily.trade_date == trade_date),
            "limit_event": delete(LimitEventDaily).where(LimitEventDaily.trade_date == trade_date),
            "lhb_event": delete(LhbEvent).where(LhbEvent.trade_date == trade_date),
            "lhb_seat": delete(LhbSeatDetail).where(LhbSeatDetail.trade_date == trade_date),
            "index_bar": delete(IndexBar).where(IndexBar.trade_date == trade_date),
            "index_daily_basic": delete(IndexDailyBasic).where(IndexDailyBasic.trade_date == trade_date),
            "market_daily_stat": delete(MarketDailyStat).where(MarketDailyStat.trade_date == trade_date),
            "north_hold": delete(StockNorthHoldDaily).where(StockNorthHoldDaily.trade_date == trade_date),
            "sector_bar": delete(SectorBar).where(SectorBar.trade_date == trade_date),
            "sector_fund_flow": delete(SectorFundFlowDaily).where(SectorFundFlowDaily.trade_date == trade_date),
            "sector_factor": delete(SectorFactorDaily).where(SectorFactorDaily.trade_date == trade_date),
            "minute": delete(MinuteBar).where(MinuteBar.trade_date == trade_date, MinuteBar.source == "mootdx"),
            "daily_factor": delete(StockFactorDaily).where(
                StockFactorDaily.trade_date == trade_date,
                StockFactorDaily.source == "system:daily_close",
            ),
            "minute_factor": delete(StockFactorMinute).where(
                StockFactorMinute.trade_date == trade_date,
                StockFactorMinute.source == "system:daily_close",
            ),
            "technical_snapshot": delete(TechnicalIndicatorSnapshot).where(
                TechnicalIndicatorSnapshot.source == "system:daily_close",
                TechnicalIndicatorSnapshot.snapshot_time >= start,
                TechnicalIndicatorSnapshot.snapshot_time < end,
            ),
        }
        deleted: dict[str, int] = {}
        for name, statement in statements.items():
            result = await self.session.execute(statement)
            deleted[name] = int(result.rowcount or 0)
        return deleted

    async def insert_raw(self, row: dict) -> ProviderRawRecord:
        result = await self.session.execute(insert(ProviderRawRecord).values(**row).returning(ProviderRawRecord))
        return result.scalar_one()

    async def list_rows(self, model, *, filters: list | None = None, order_by: list | None = None, limit: int = 200) -> list:
        stmt = select(model)
        for condition in filters or []:
            stmt = stmt.where(condition)
        if order_by:
            stmt = stmt.order_by(*order_by)
        if limit:
            stmt = stmt.limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def upsert_rows(
        self,
        model,
        rows: list[dict],
        *,
        conflict_attrs: list[str],
        update_attrs: list[str] | None = None,
        batch_size: int | None = None,
    ) -> int:
        if not rows:
            return 0
        deduped: dict[tuple, dict] = {}
        for row in rows:
            key = tuple(row.get(attr) for attr in conflict_attrs)
            deduped[key] = row
        rows = list(deduped.values())
        resolved_batch_size = min(batch_size or DEFAULT_BULK_UPSERT_BATCH_SIZE, _safe_batch_size(rows))
        total = 0
        for batch in _chunked(rows, resolved_batch_size):
            insert_stmt = insert(model).values(batch)
            resolved_update_attrs = update_attrs or [key for key in batch[0].keys() if key not in conflict_attrs and key != "id"]
            set_values = {}
            for attr in resolved_update_attrs:
                column = getattr(model, attr)
                excluded_name = column.property.columns[0].name
                set_values[column] = getattr(insert_stmt.excluded, excluded_name)
            await self.session.execute(
                insert_stmt.on_conflict_do_update(
                    index_elements=[getattr(model, attr) for attr in conflict_attrs],
                    set_=set_values,
                )
            )
            total += len(batch)
        return total

    async def delete_missing_index_components(
        self,
        *,
        index_code: str,
        active_stock_codes: set[str],
    ) -> int:
        if not active_stock_codes:
            return 0
        result = await self.session.execute(
            delete(IndexComponent).where(
                IndexComponent.index_code == index_code,
                IndexComponent.stock_code.not_in(active_stock_codes),
            )
        )
        return int(result.rowcount or 0)

    async def sync_sector_component_rows(self, rows: list[dict]) -> dict[str, int]:
        if not rows:
            return {"inserted": 0, "updated": 0, "unchanged": 0}
        sector_code = str(rows[0]["sector_code"])
        source = str(rows[0].get("source") or "")
        existing_result = await self.session.execute(
            select(SectorComponent).where(
                SectorComponent.sector_code == sector_code,
                SectorComponent.source == source,
            )
        )
        existing_by_stock = {row.stock_code: row for row in existing_result.scalars().all()}
        changed_rows: list[dict] = []
        inserted = 0
        updated = 0
        unchanged = 0
        for row in rows:
            existing = existing_by_stock.get(str(row["stock_code"]))
            incoming_hash = str((row.get("metadata_json") or {}).get("component_sync_hash") or "")
            existing_hash = str((existing.metadata_json or {}).get("component_sync_hash") or "") if existing else ""
            if existing is None:
                inserted += 1
                changed_rows.append(row)
            elif existing_hash != incoming_hash or existing.end_date is not None:
                updated += 1
                changed_rows.append(row)
            else:
                unchanged += 1
        if changed_rows:
            await self.upsert_rows(
                SectorComponent,
                changed_rows,
                conflict_attrs=["sector_code", "stock_code", "source"],
                update_attrs=["weight", "start_date", "end_date", "metadata_json"],
            )
        return {"inserted": inserted, "updated": updated, "unchanged": unchanged}

    async def delete_missing_sector_components(
        self,
        *,
        sector_code: str,
        source: str,
        active_stock_codes: set[str],
    ) -> int:
        if not active_stock_codes:
            return 0
        stmt = delete(SectorComponent).where(
            SectorComponent.sector_code == sector_code,
            SectorComponent.source == source,
            SectorComponent.stock_code.not_in(active_stock_codes),
        )
        result = await self.session.execute(stmt)
        return int(result.rowcount or 0)

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
