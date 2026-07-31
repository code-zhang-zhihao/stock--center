from datetime import date, datetime, time

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Index, String, Text, Time, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def created_at_column():
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def updated_at_column():
    return mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class ProviderRawRecord(Base):
    __tablename__ = "t_provider_raw_record"

    id: Mapped[int] = mapped_column(primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(80), nullable=False)
    provider_code: Mapped[str] = mapped_column(String(80), nullable=False)
    capability: Mapped[str] = mapped_column(String(80), nullable=False)
    request_params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    record_key: Mapped[str | None] = mapped_column(String(200))
    payload: Mapped[dict | list] = mapped_column(JSONB, nullable=False)
    payload_summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    normalized_table: Mapped[str | None] = mapped_column(String(80))
    normalized_pk: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="captured")
    error_code: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at = created_at_column()


class ProviderIngestAudit(Base):
    """Compact, permanent provider completion audit without raw payloads."""

    __tablename__ = "t_provider_ingest_audit"
    __table_args__ = (UniqueConstraint("trace_id", name="uq_t_provider_ingest_audit_trace"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(80), nullable=False)
    provider_code: Mapped[str] = mapped_column(String(80), nullable=False)
    capability: Mapped[str] = mapped_column(String(120), nullable=False)
    trade_date: Mapped[date | None] = mapped_column(Date)
    request_params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    requested_fields: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    response_row_count: Mapped[int] = mapped_column(nullable=False, default=0)
    normalized_row_count: Mapped[int] = mapped_column(nullable=False, default=0)
    payload_sha256: Mapped[str | None] = mapped_column(String(64))
    normalized_table: Mapped[str | None] = mapped_column(String(120))
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False, default="v1")
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at = created_at_column()


class Stock(Base):
    __tablename__ = "t_stock"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    stock_name: Mapped[str] = mapped_column(String(120), nullable=False)
    market: Mapped[str] = mapped_column(String(20), nullable=False, default="CN")
    exchange: Mapped[str | None] = mapped_column(String(20))
    list_date: Mapped[date | None] = mapped_column(Date)
    delist_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="active")
    is_st: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    industry: Mapped[str | None] = mapped_column(String(120))
    area: Mapped[str | None] = mapped_column(String(120))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at = created_at_column()
    updated_at = updated_at_column()


class MarketUniverse(Base):
    """Provider-owned symbol universe catalogue.

    The raw provider universe is retained independently from canonical Tushare
    sectors.  TickFlow's SW1/SW2/SW3 rows are later grouped by the runtime for
    display and realtime industry aggregation.
    """

    __tablename__ = "t_market_universe"
    __table_args__ = (UniqueConstraint("provider_code", "universe_id", name="uq_t_market_universe_provider_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider_code: Mapped[str] = mapped_column(String(40), nullable=False)
    universe_id: Mapped[str] = mapped_column(String(160), nullable=False)
    universe_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(String(20))
    category: Mapped[str | None] = mapped_column(String(40))
    taxonomy_level: Mapped[str | None] = mapped_column(String(20))
    logical_group_key: Mapped[str | None] = mapped_column(String(260))
    source_symbol_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    catalog_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    first_seen_at = created_at_column()
    last_synced_at = updated_at_column()


class MarketUniverseMember(Base):
    __tablename__ = "t_market_universe_member"
    __table_args__ = (
        UniqueConstraint("universe_row_id", "stock_code", "valid_from", name="uq_t_market_universe_member_effective_from"),
        Index("uq_t_market_universe_member_active", "universe_row_id", "stock_code", unique=True, postgresql_where=text("valid_to IS NULL")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    universe_row_id: Mapped[int] = mapped_column(ForeignKey("t_market_universe.id", ondelete="CASCADE"), nullable=False)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    first_seen_at = created_at_column()
    last_seen_at = updated_at_column()


class TradeCalendar(Base):
    __tablename__ = "t_trade_calendar"
    __table_args__ = (UniqueConstraint("trade_date", "market", name="uq_t_trade_calendar_date_market"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    market: Mapped[str] = mapped_column(String(20), nullable=False, default="CN")
    is_open: Mapped[bool] = mapped_column(nullable=False)
    previous_trade_date: Mapped[date | None] = mapped_column(Date)
    next_trade_date: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(80), nullable=False, default="migration")
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at = created_at_column()


class DailyBar(Base):
    __tablename__ = "t_daily_bar"
    __table_args__ = (UniqueConstraint("stock_code", "trade_date", name="uq_t_daily_bar_stock_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    adjust_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="none")
    open_price: Mapped[float | None]
    high_price: Mapped[float | None]
    low_price: Mapped[float | None]
    close_price: Mapped[float | None]
    pre_close_price: Mapped[float | None]
    change_amount: Mapped[float | None]
    change_pct: Mapped[float | None]
    volume_hand: Mapped[int | None] = mapped_column(BigInteger)
    volume_share: Mapped[int | None] = mapped_column(BigInteger)
    amount_yuan: Mapped[float | None]
    turnover_rate: Mapped[float | None]
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at = created_at_column()
    updated_at = updated_at_column()


class MinuteBar(Base):
    __tablename__ = "t_minute_bar"
    __table_args__ = (UniqueConstraint("stock_code", "trade_date", "bar_time", "interval", "source", name="uq_t_minute_bar_stock_date_time_interval_source_v2"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True, nullable=False)
    bar_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    interval: Mapped[str] = mapped_column(String(20), nullable=False, default="1m")
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    price: Mapped[float | None]
    avg_price: Mapped[float | None]
    volume_hand: Mapped[int | None] = mapped_column(BigInteger)
    volume_share: Mapped[int | None] = mapped_column(BigInteger)
    amount_yuan: Mapped[float | None]
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at = created_at_column()


class QuoteSnapshot(Base):
    __tablename__ = "t_quote_snapshot"
    __table_args__ = (UniqueConstraint("stock_code", "quote_time", "source", name="uq_t_quote_snapshot_stock_time_source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    quote_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    snapshot_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="realtime")
    last_price: Mapped[float | None]
    pre_close_price: Mapped[float | None]
    change_amount: Mapped[float | None]
    change_pct: Mapped[float | None]
    open_price: Mapped[float | None]
    high_price: Mapped[float | None]
    low_price: Mapped[float | None]
    volume_hand: Mapped[int | None] = mapped_column(BigInteger)
    amount_yuan: Mapped[float | None]
    order_book: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at = created_at_column()


class TickTrade(Base):
    __tablename__ = "t_tick_trade"
    __table_args__ = (UniqueConstraint("stock_code", "trade_time", "source", "price", "volume_hand", name="uq_t_tick_trade_business"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    trade_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    price: Mapped[float | None]
    volume_hand: Mapped[int | None] = mapped_column(BigInteger)
    amount_yuan: Mapped[float | None]
    side: Mapped[str | None] = mapped_column(String(20))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at = created_at_column()


class SectorBasic(Base):
    __tablename__ = "t_sector_basic"

    id: Mapped[int] = mapped_column(primary_key=True)
    sector_code: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    sector_name: Mapped[str] = mapped_column(String(160), nullable=False)
    sector_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source: Mapped[str | None] = mapped_column(String(80))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at = created_at_column()
    updated_at = updated_at_column()


class SectorComponent(Base):
    __tablename__ = "t_sector_component"
    __table_args__ = (UniqueConstraint("sector_code", "stock_code", "source", name="uq_t_sector_component_sector_stock_source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sector_code: Mapped[str] = mapped_column(String(80), nullable=False)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    weight: Mapped[float | None]
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str | None] = mapped_column(String(80))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at = created_at_column()


class SectorBar(Base):
    __tablename__ = "t_sector_bar"
    __table_args__ = (UniqueConstraint("sector_code", "trade_date", name="uq_t_sector_bar_sector_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sector_code: Mapped[str] = mapped_column(String(80), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    open_price: Mapped[float | None]
    high_price: Mapped[float | None]
    low_price: Mapped[float | None]
    close_price: Mapped[float | None]
    pre_close_price: Mapped[float | None]
    change_amount: Mapped[float | None]
    change_pct: Mapped[float | None]
    volume: Mapped[float | None]
    amount_yuan: Mapped[float | None]
    turnover_rate: Mapped[float | None]
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at = created_at_column()


class IndexBasic(Base):
    __tablename__ = "t_index_basic"

    id: Mapped[int] = mapped_column(primary_key=True)
    index_code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    index_name: Mapped[str] = mapped_column(String(120), nullable=False)
    market: Mapped[str] = mapped_column(String(20), nullable=False, default="CN")
    publisher: Mapped[str | None] = mapped_column(String(120))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at = created_at_column()
    updated_at = updated_at_column()


class IndexComponent(Base):
    __tablename__ = "t_index_component"
    __table_args__ = (UniqueConstraint("index_code", "stock_code", name="uq_t_index_component_index_stock"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    index_code: Mapped[str] = mapped_column(String(20), nullable=False)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    weight: Mapped[float | None]
    effective_date: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str | None] = mapped_column(String(80))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at = created_at_column()


class IndexBar(Base):
    __tablename__ = "t_index_bar"
    __table_args__ = (UniqueConstraint("index_code", "trade_date", name="uq_t_index_bar_index_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    index_code: Mapped[str] = mapped_column(String(20), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    open_price: Mapped[float | None]
    high_price: Mapped[float | None]
    low_price: Mapped[float | None]
    close_price: Mapped[float | None]
    change_pct: Mapped[float | None]
    volume: Mapped[float | None]
    amount_yuan: Mapped[float | None]
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at = created_at_column()


class StockFundFlowDaily(Base):
    __tablename__ = "t_stock_fund_flow_daily"
    __table_args__ = (UniqueConstraint("stock_code", "trade_date", name="uq_t_stock_fund_flow_daily_stock_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    main_net_inflow: Mapped[float | None]
    main_net_ratio: Mapped[float | None]
    big_order_net_inflow: Mapped[float | None]
    big_order_net_ratio: Mapped[float | None]
    super_large_net_inflow: Mapped[float | None]
    medium_net_inflow: Mapped[float | None]
    small_net_inflow: Mapped[float | None]
    small_buy_amount: Mapped[float | None]
    small_sell_amount: Mapped[float | None]
    medium_buy_amount: Mapped[float | None]
    medium_sell_amount: Mapped[float | None]
    large_buy_amount: Mapped[float | None]
    large_sell_amount: Mapped[float | None]
    super_large_buy_amount: Mapped[float | None]
    super_large_sell_amount: Mapped[float | None]
    close_price: Mapped[float | None]
    change_pct: Mapped[float | None]
    rank: Mapped[int | None]
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at = created_at_column()
    updated_at = updated_at_column()


class SectorFundFlowDaily(Base):
    __tablename__ = "t_sector_fund_flow_daily"
    __table_args__ = (UniqueConstraint("sector_code", "trade_date", name="uq_t_sector_fund_flow_daily_sector_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sector_code: Mapped[str] = mapped_column(String(80), nullable=False)
    sector_name: Mapped[str] = mapped_column(String(160), nullable=False)
    sector_type: Mapped[str] = mapped_column(String(40), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    main_net_inflow: Mapped[float | None]
    net_buy_amount: Mapped[float | None]
    net_sell_amount: Mapped[float | None]
    main_net_ratio: Mapped[float | None]
    change_pct: Mapped[float | None]
    close_price: Mapped[float | None]
    company_num: Mapped[int | None]
    lead_stock: Mapped[str | None] = mapped_column(String(120))
    lead_stock_change_pct: Mapped[float | None]
    rank: Mapped[int | None]
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at = created_at_column()
    updated_at = updated_at_column()


class LhbEvent(Base):
    __tablename__ = "t_lhb_event"
    __table_args__ = (UniqueConstraint("stock_code", "trade_date", "reason", name="uq_t_lhb_event_stock_date_reason"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    stock_name: Mapped[str | None] = mapped_column(String(120))
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    reason: Mapped[str] = mapped_column(String(300), nullable=False)
    close_price: Mapped[float | None]
    change_pct: Mapped[float | None]
    turnover_amount: Mapped[float | None]
    net_buy_amount: Mapped[float | None]
    buy_amount: Mapped[float | None]
    sell_amount: Mapped[float | None]
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at = created_at_column()
    updated_at = updated_at_column()


class LhbSeatDetail(Base):
    __tablename__ = "t_lhb_seat_detail"
    __table_args__ = (UniqueConstraint("stock_code", "trade_date", "seat_name", "side", "source", name="uq_t_lhb_seat_detail_business"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    side: Mapped[str] = mapped_column(String(20), nullable=False)
    seat_name: Mapped[str] = mapped_column(String(240), nullable=False)
    buy_amount: Mapped[float | None]
    sell_amount: Mapped[float | None]
    net_amount: Mapped[float | None]
    rank: Mapped[int | None]
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at = created_at_column()


class Announcement(Base):
    __tablename__ = "t_announcement"
    __table_args__ = (UniqueConstraint("stock_code", "title", "published_at", "source", name="uq_t_announcement_stock_title_time_source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    stock_name: Mapped[str | None] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    category: Mapped[str | None] = mapped_column(String(120))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at = created_at_column()
    updated_at = updated_at_column()


class FactorDefinition(Base):
    __tablename__ = "t_factor_definition"

    id: Mapped[int] = mapped_column(primary_key=True)
    factor_code: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    factor_name: Mapped[str] = mapped_column(String(200), nullable=False)
    factor_group: Mapped[str] = mapped_column(String(80), nullable=False)
    frequency: Mapped[str] = mapped_column(String(40), nullable=False)
    source_table: Mapped[str | None] = mapped_column(String(120))
    compute_method: Mapped[str | None] = mapped_column(Text)
    is_rebuildable: Mapped[bool] = mapped_column(nullable=False, default=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at = created_at_column()
    updated_at = updated_at_column()


class FactorSetVersion(Base):
    __tablename__ = "t_factor_set_version"

    factor_set_code: Mapped[str] = mapped_column(String(80), primary_key=True)
    factor_set_name: Mapped[str] = mapped_column(String(160), nullable=False)
    version_no: Mapped[int] = mapped_column(nullable=False)
    price_basis: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at = created_at_column()
    updated_at = updated_at_column()


class StockFactorDaily(Base):
    __tablename__ = "t_stock_factor_daily"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False, default="system")
    ma5: Mapped[float | None]
    ma10: Mapped[float | None]
    ma20: Mapped[float | None]
    ma30: Mapped[float | None]
    ma60: Mapped[float | None]
    return_1d: Mapped[float | None]
    amplitude: Mapped[float | None]
    volume_ratio: Mapped[float | None]
    amount_ratio: Mapped[float | None]
    volatility_20d: Mapped[float | None]
    close_position: Mapped[float | None]
    features: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at = created_at_column()


class StockFactorDailyV2(Base):
    __tablename__ = "t_stock_factor_daily_v2"
    __table_args__ = (
        UniqueConstraint(
            "stock_code",
            "trade_date",
            "factor_set_version",
            name="uq_t_stock_factor_daily_v2_business",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    factor_set_version: Mapped[str] = mapped_column(String(80), nullable=False, default="stock_daily_v2")
    price_basis: Mapped[str] = mapped_column(String(20), nullable=False, default="qfq")
    factor_status: Mapped[str] = mapped_column(String(24), nullable=False, default="partial")
    technical_source: Mapped[str | None] = mapped_column(String(80))
    local_source: Mapped[str] = mapped_column(String(80), nullable=False, default="system:daily_factor_v2")
    fund_source: Mapped[str | None] = mapped_column(String(80))
    source_map: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    missing_factors: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    open_qfq: Mapped[float | None]
    high_qfq: Mapped[float | None]
    low_qfq: Mapped[float | None]
    close_qfq: Mapped[float | None]
    pre_close_qfq: Mapped[float | None]
    ma5: Mapped[float | None]
    ma10: Mapped[float | None]
    ma20: Mapped[float | None]
    ma30: Mapped[float | None]
    ma60: Mapped[float | None]
    ma90: Mapped[float | None]
    ma250: Mapped[float | None]
    ema5: Mapped[float | None]
    ema10: Mapped[float | None]
    ema20: Mapped[float | None]
    ema30: Mapped[float | None]
    ema60: Mapped[float | None]
    macd: Mapped[float | None]
    macd_dif: Mapped[float | None]
    macd_dea: Mapped[float | None]
    kdj_j: Mapped[float | None]
    kdj_k: Mapped[float | None]
    kdj_d: Mapped[float | None]
    rsi6: Mapped[float | None]
    rsi12: Mapped[float | None]
    rsi14: Mapped[float | None]
    rsi24: Mapped[float | None]
    boll_upper: Mapped[float | None]
    boll_mid: Mapped[float | None]
    boll_lower: Mapped[float | None]
    atr: Mapped[float | None]
    cci: Mapped[float | None]
    vr: Mapped[float | None]
    wr: Mapped[float | None]
    wr1: Mapped[float | None]
    bias1: Mapped[float | None]
    bias2: Mapped[float | None]
    bias3: Mapped[float | None]
    obv: Mapped[float | None]
    mfi: Mapped[float | None]
    roc: Mapped[float | None]
    mtm: Mapped[float | None]
    return_1d: Mapped[float | None]
    return_3d: Mapped[float | None]
    return_5d: Mapped[float | None]
    return_10d: Mapped[float | None]
    return_20d: Mapped[float | None]
    amplitude_1d: Mapped[float | None]
    volume_ratio_5d: Mapped[float | None]
    amount_ratio_5d: Mapped[float | None]
    volatility_20d: Mapped[float | None]
    close_position_1d: Mapped[float | None]
    high_20d: Mapped[float | None]
    low_20d: Mapped[float | None]
    high_60d: Mapped[float | None]
    low_60d: Mapped[float | None]
    drawdown_20d: Mapped[float | None]
    drawdown_60d: Mapped[float | None]
    turnover_rate: Mapped[float | None]
    circ_mv: Mapped[float | None]
    total_mv: Mapped[float | None]
    main_net_inflow: Mapped[float | None]
    provider_main_net_ratio: Mapped[float | None]
    main_net_amount_ratio: Mapped[float | None]
    big_order_net_inflow: Mapped[float | None]
    big_order_net_amount_ratio: Mapped[float | None]
    super_large_net_inflow: Mapped[float | None]
    super_large_net_amount_ratio: Mapped[float | None]
    main_net_inflow_3d: Mapped[float | None]
    main_net_inflow_5d: Mapped[float | None]
    main_net_inflow_10d: Mapped[float | None]
    continuous_main_inflow_days: Mapped[int | None]
    fund_strength_percentile: Mapped[float | None]
    history_days: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at = created_at_column()
    updated_at = updated_at_column()


class StockFactorDailyActive(Base):
    """Read-only ORM projection for the currently activated factor set."""

    __tablename__ = "v_stock_factor_daily_active"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    ma5: Mapped[float | None]
    ma10: Mapped[float | None]
    ma20: Mapped[float | None]
    ma30: Mapped[float | None]
    ma60: Mapped[float | None]
    return_1d: Mapped[float | None]
    amplitude: Mapped[float | None]
    volume_ratio: Mapped[float | None]
    amount_ratio: Mapped[float | None]
    volatility_20d: Mapped[float | None]
    close_position: Mapped[float | None]
    features: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    factor_set_version: Mapped[str] = mapped_column(String(80), nullable=False)
    price_basis: Mapped[str] = mapped_column(String(20), nullable=False)
    factor_status: Mapped[str] = mapped_column(String(24), nullable=False)
    source_map: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    missing_factors: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StockFactorMinute(Base):
    __tablename__ = "t_stock_factor_minute"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True, nullable=False)
    bar_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False, default="system")
    vwap: Mapped[float | None]
    minute_return: Mapped[float | None]
    volume_spike_ratio: Mapped[float | None]
    intraday_strength: Mapped[float | None]
    features: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at = created_at_column()


class TechnicalIndicatorSnapshot(Base):
    __tablename__ = "t_technical_indicator_snapshot"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    snapshot_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False, default="system")
    last_price: Mapped[float | None]
    change_pct: Mapped[float | None]
    intraday_strength: Mapped[float | None]
    volume_score: Mapped[float | None]
    trend_score: Mapped[float | None]
    factor_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at = created_at_column()


class StockDailyBasic(Base):
    __tablename__ = "t_stock_daily_basic"
    __table_args__ = (UniqueConstraint("stock_code", "trade_date", name="uq_t_stock_daily_basic_business"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    close_price: Mapped[float | None]
    turnover_rate: Mapped[float | None]
    turnover_rate_f: Mapped[float | None]
    volume_ratio: Mapped[float | None]
    pe: Mapped[float | None]
    pe_ttm: Mapped[float | None]
    pb: Mapped[float | None]
    ps: Mapped[float | None]
    ps_ttm: Mapped[float | None]
    dv_ratio: Mapped[float | None]
    dv_ttm: Mapped[float | None]
    total_share: Mapped[float | None]
    float_share: Mapped[float | None]
    free_share: Mapped[float | None]
    total_mv: Mapped[float | None]
    circ_mv: Mapped[float | None]
    limit_status: Mapped[int | None]
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at = created_at_column()
    updated_at = updated_at_column()


class StockTechnicalFactorDaily(Base):
    __tablename__ = "t_stock_technical_factor_daily"
    __table_args__ = (UniqueConstraint("stock_code", "trade_date", name="uq_t_stock_technical_factor_daily_business"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    factors: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at = created_at_column()
    updated_at = updated_at_column()


class StockChipPerfDaily(Base):
    __tablename__ = "t_stock_chip_perf_daily"
    __table_args__ = (UniqueConstraint("stock_code", "trade_date", name="uq_t_stock_chip_perf_daily_business"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    his_low: Mapped[float | None]
    his_high: Mapped[float | None]
    cost_5pct: Mapped[float | None]
    cost_15pct: Mapped[float | None]
    cost_50pct: Mapped[float | None]
    cost_85pct: Mapped[float | None]
    cost_95pct: Mapped[float | None]
    weight_avg: Mapped[float | None]
    winner_rate: Mapped[float | None]
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at = created_at_column()
    updated_at = updated_at_column()


class MarketDailyStat(Base):
    __tablename__ = "t_market_daily_stat"
    __table_args__ = (UniqueConstraint("trade_date", "ts_code", "exchange", name="uq_t_market_daily_stat_business"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    ts_code: Mapped[str] = mapped_column(String(40), nullable=False)
    ts_name: Mapped[str | None] = mapped_column(String(120))
    exchange: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    company_count: Mapped[int | None]
    total_share: Mapped[float | None]
    float_share: Mapped[float | None]
    total_mv: Mapped[float | None]
    float_mv: Mapped[float | None]
    amount: Mapped[float | None]
    volume: Mapped[float | None]
    transaction_count: Mapped[float | None]
    pe: Mapped[float | None]
    turnover_rate: Mapped[float | None]
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at = created_at_column()
    updated_at = updated_at_column()


class IndexDailyBasic(Base):
    __tablename__ = "t_index_daily_basic"
    __table_args__ = (UniqueConstraint("index_code", "trade_date", name="uq_t_index_daily_basic_business"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    index_code: Mapped[str] = mapped_column(String(20), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    total_mv: Mapped[float | None]
    float_mv: Mapped[float | None]
    total_share: Mapped[float | None]
    float_share: Mapped[float | None]
    free_share: Mapped[float | None]
    turnover_rate: Mapped[float | None]
    turnover_rate_f: Mapped[float | None]
    pe: Mapped[float | None]
    pe_ttm: Mapped[float | None]
    pb: Mapped[float | None]
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at = created_at_column()
    updated_at = updated_at_column()


class StockAdjustFactor(Base):
    __tablename__ = "t_stock_adjust_factor"
    __table_args__ = (UniqueConstraint("stock_code", "trade_date", "source", name="uq_t_stock_adjust_factor_business"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    adj_factor: Mapped[float] = mapped_column(nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at = created_at_column()


class FinancialStatement(Base):
    __tablename__ = "t_financial_statement"
    __table_args__ = (UniqueConstraint("stock_code", "report_type", "report_period", "source", name="uq_t_financial_statement_business"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    report_type: Mapped[str] = mapped_column(String(40), nullable=False)
    report_period: Mapped[date] = mapped_column(Date, nullable=False)
    announcement_date: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    fields: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at = created_at_column()
    updated_at = updated_at_column()


class FinancialIndicator(Base):
    __tablename__ = "t_financial_indicator"
    __table_args__ = (UniqueConstraint("stock_code", "report_period", "source", name="uq_t_financial_indicator_business"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    report_period: Mapped[date] = mapped_column(Date, nullable=False)
    announcement_date: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    indicators: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at = created_at_column()
    updated_at = updated_at_column()


class CorporateAction(Base):
    __tablename__ = "t_corporate_action"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    action_type: Mapped[str] = mapped_column(String(60), nullable=False)
    ex_date: Mapped[date | None] = mapped_column(Date)
    announcement_date: Mapped[date | None] = mapped_column(Date)
    record_date: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    fields: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at = created_at_column()
    updated_at = updated_at_column()


class MarginSummaryDaily(Base):
    __tablename__ = "t_margin_summary_daily"
    __table_args__ = (UniqueConstraint("trade_date", "exchange", "source", name="uq_t_margin_summary_daily_business"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    exchange: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    rzye: Mapped[float | None]
    rz_mre: Mapped[float | None]
    rzche: Mapped[float | None]
    rqye: Mapped[float | None]
    rq_mcl: Mapped[float | None]
    rzrqye: Mapped[float | None]
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at = created_at_column()


class MarginDetailDaily(Base):
    __tablename__ = "t_margin_detail_daily"
    __table_args__ = (UniqueConstraint("stock_code", "trade_date", "source", name="uq_t_margin_detail_daily_business"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    exchange: Mapped[str | None] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    rzye: Mapped[float | None]
    rz_mre: Mapped[float | None]
    rzche: Mapped[float | None]
    rqye: Mapped[float | None]
    rq_mcl: Mapped[float | None]
    rzrqye: Mapped[float | None]
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at = created_at_column()


class LimitEventDaily(Base):
    __tablename__ = "t_limit_event_daily"
    __table_args__ = (UniqueConstraint("stock_code", "trade_date", "event_type", name="uq_t_limit_event_daily_business"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    close_price: Mapped[float | None]
    limit_price: Mapped[float | None]
    first_time: Mapped[time | None] = mapped_column(Time)
    last_time: Mapped[time | None] = mapped_column(Time)
    open_count: Mapped[int | None]
    turnover_amount: Mapped[float | None]
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at = created_at_column()


class StockNorthHoldDaily(Base):
    __tablename__ = "t_stock_north_hold_daily"
    __table_args__ = (UniqueConstraint("stock_code", "trade_date", "exchange", name="uq_t_stock_north_hold_daily_business"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    stock_name: Mapped[str | None] = mapped_column(String(120))
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    exchange: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    hold_volume: Mapped[float | None]
    hold_ratio: Mapped[float | None]
    hold_market_value: Mapped[float | None]
    hold_volume_change: Mapped[float | None]
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at = created_at_column()
    updated_at = updated_at_column()


class MarketNorthFlowDaily(Base):
    """Canonical daily Stock Connect aggregate flow from Tushare moneyflow_hsgt."""

    __tablename__ = "t_market_north_flow_daily"
    __table_args__ = (UniqueConstraint("trade_date", "source", name="uq_t_market_north_flow_daily_business"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    hgt: Mapped[float | None]
    sgt: Mapped[float | None]
    north_money: Mapped[float | None]
    ggt_ss: Mapped[float | None]
    ggt_sz: Mapped[float | None]
    south_money: Mapped[float | None]
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at = created_at_column()
    updated_at = updated_at_column()


class SectorFactorDaily(Base):
    __tablename__ = "t_sector_factor_daily"
    __table_args__ = (UniqueConstraint("sector_code", "trade_date", name="uq_t_sector_factor_daily_business"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sector_code: Mapped[str] = mapped_column(String(80), nullable=False)
    sector_name: Mapped[str | None] = mapped_column(String(160))
    sector_type: Mapped[str] = mapped_column(String(40), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False, default="system:daily_close")
    fund_strength: Mapped[float | None]
    net_inflow_3d: Mapped[float | None]
    net_inflow_5d: Mapped[float | None]
    net_inflow_10d: Mapped[float | None]
    continuous_inflow_days: Mapped[int | None]
    rising_stock_count: Mapped[int | None]
    limit_up_stock_count: Mapped[int | None]
    average_change_pct: Mapped[float | None]
    volatility_20d: Mapped[float | None]
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    features: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at = created_at_column()
    updated_at = updated_at_column()


class IndexFactorDaily(Base):
    __tablename__ = "t_index_factor_daily"
    __table_args__ = (UniqueConstraint("index_code", "trade_date", name="uq_t_index_factor_daily_business"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    index_code: Mapped[str] = mapped_column(String(20), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False, default="system:history_backfill")
    ma5: Mapped[float | None]
    ma10: Mapped[float | None]
    ma20: Mapped[float | None]
    ma30: Mapped[float | None]
    ma60: Mapped[float | None]
    return_1d: Mapped[float | None]
    amplitude: Mapped[float | None]
    volume_ratio: Mapped[float | None]
    amount_ratio: Mapped[float | None]
    volatility_20d: Mapped[float | None]
    turnover_rate: Mapped[float | None]
    pe_ttm: Mapped[float | None]
    pb: Mapped[float | None]
    features: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at = created_at_column()
    updated_at = updated_at_column()


class StockHolderCount(Base):
    __tablename__ = "t_stock_holder_count"
    __table_args__ = (UniqueConstraint("stock_code", "report_period", "source", name="uq_t_stock_holder_count_business"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    report_period: Mapped[date] = mapped_column(Date, nullable=False)
    announcement_date: Mapped[date | None] = mapped_column(Date)
    holder_count: Mapped[float | None]
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at = created_at_column()
    updated_at = updated_at_column()


class StockTopHolder(Base):
    __tablename__ = "t_stock_top_holder"
    __table_args__ = (UniqueConstraint("stock_code", "report_period", "holder_name", "source", name="uq_t_stock_top_holder_business"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    report_period: Mapped[date] = mapped_column(Date, nullable=False)
    holder_name: Mapped[str] = mapped_column(String(300), nullable=False)
    holder_type: Mapped[str | None] = mapped_column(String(80))
    hold_amount: Mapped[float | None]
    hold_ratio: Mapped[float | None]
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at = created_at_column()
    updated_at = updated_at_column()
