from datetime import date, datetime, timezone

from sqlalchemy import case, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.market_data.models import DailyBar, MinuteBar, ProviderRawRecord, QuoteSnapshot, SectorComponent, Stock


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

    async def list_daily_bars(
        self,
        *,
        stock_code: str,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 120,
    ) -> list[DailyBar]:
        source_priority = case((DailyBar.source == "akshare_qfq", 0), (DailyBar.source == "mootdx", 1), else_=9)
        stmt = select(DailyBar).where(DailyBar.stock_code == stock_code)
        if start_date:
            stmt = stmt.where(DailyBar.trade_date >= start_date)
        if end_date:
            stmt = stmt.where(DailyBar.trade_date <= end_date)
        stmt = stmt.order_by(DailyBar.trade_date.desc(), source_priority, DailyBar.id.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def upsert_daily_bars(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        insert_stmt = insert(DailyBar).values(rows)
        await self.session.execute(
            insert_stmt.on_conflict_do_update(
                index_elements=[DailyBar.stock_code, DailyBar.trade_date, DailyBar.source],
                set_={
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
        insert_stmt = insert(MinuteBar).values(rows)
        await self.session.execute(
            insert_stmt.on_conflict_do_update(
                index_elements=[MinuteBar.stock_code, MinuteBar.bar_time, MinuteBar.interval, MinuteBar.source],
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

    async def upsert_rows(self, model, rows: list[dict], *, conflict_attrs: list[str], update_attrs: list[str] | None = None) -> int:
        if not rows:
            return 0
        deduped: dict[tuple, dict] = {}
        for row in rows:
            key = tuple(row.get(attr) for attr in conflict_attrs)
            deduped[key] = row
        rows = list(deduped.values())
        insert_stmt = insert(model).values(rows)
        update_attrs = update_attrs or [key for key in rows[0].keys() if key not in conflict_attrs and key != "id"]
        set_values = {}
        for attr in update_attrs:
            column = getattr(model, attr)
            excluded_name = column.property.columns[0].name
            set_values[column] = getattr(insert_stmt.excluded, excluded_name)
        await self.session.execute(
            insert_stmt.on_conflict_do_update(
                index_elements=[getattr(model, attr) for attr in conflict_attrs],
                set_=set_values,
            )
        )
        return len(rows)

    async def expire_sector_components(
        self,
        *,
        sector_code: str,
        source: str,
        active_stock_codes: set[str],
        end_date: date,
    ) -> int:
        stmt = (
            update(SectorComponent)
            .where(
                SectorComponent.sector_code == sector_code,
                SectorComponent.source == source,
                SectorComponent.end_date.is_(None),
            )
            .values(end_date=end_date)
        )
        if active_stock_codes:
            stmt = stmt.where(SectorComponent.stock_code.not_in(active_stock_codes))
        result = await self.session.execute(stmt)
        return int(result.rowcount or 0)

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
