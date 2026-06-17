-- stock-center database schema.
-- First phase: protect existing stock-analysis assets and implement market data query contract.

CREATE TABLE IF NOT EXISTS t_provider_raw_record (
    id BIGSERIAL PRIMARY KEY,
    trace_id VARCHAR(80) NOT NULL,
    provider_code VARCHAR(80) NOT NULL,
    capability VARCHAR(80) NOT NULL,
    request_params JSONB NOT NULL DEFAULT '{}'::jsonb,
    record_key VARCHAR(200),
    payload JSONB NOT NULL,
    payload_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    normalized_table VARCHAR(80),
    normalized_pk VARCHAR(120),
    status VARCHAR(40) NOT NULL DEFAULT 'captured',
    error_code VARCHAR(120),
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_t_provider_raw_record_status CHECK (status IN ('captured', 'normalized', 'failed', 'skipped'))
);

CREATE INDEX IF NOT EXISTS idx_t_provider_raw_record_trace ON t_provider_raw_record(trace_id);
CREATE INDEX IF NOT EXISTS idx_t_provider_raw_record_provider_time ON t_provider_raw_record(provider_code, capability, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_t_provider_raw_record_key ON t_provider_raw_record(record_key, capability, created_at DESC);

CREATE TABLE IF NOT EXISTS t_stock (
    id BIGSERIAL PRIMARY KEY,
    stock_code VARCHAR(20) NOT NULL UNIQUE,
    stock_name VARCHAR(120) NOT NULL,
    market VARCHAR(20) NOT NULL DEFAULT 'CN',
    exchange VARCHAR(20),
    list_date DATE,
    delist_date DATE,
    status VARCHAR(40) NOT NULL DEFAULT 'active',
    industry VARCHAR(120),
    area VARCHAR(120),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS t_trade_calendar (
    id BIGSERIAL PRIMARY KEY,
    trade_date DATE NOT NULL,
    market VARCHAR(20) NOT NULL DEFAULT 'CN',
    is_open BOOLEAN NOT NULL,
    previous_trade_date DATE,
    next_trade_date DATE,
    source VARCHAR(80) NOT NULL DEFAULT 'migration',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_trade_calendar_date_market UNIQUE (trade_date, market)
);

CREATE TABLE IF NOT EXISTS t_daily_bar (
    id BIGSERIAL PRIMARY KEY,
    stock_code VARCHAR(20) NOT NULL,
    trade_date DATE NOT NULL,
    source VARCHAR(80) NOT NULL,
    adjust_mode VARCHAR(20) NOT NULL DEFAULT 'none',
    open_price NUMERIC(18, 4),
    high_price NUMERIC(18, 4),
    low_price NUMERIC(18, 4),
    close_price NUMERIC(18, 4),
    pre_close_price NUMERIC(18, 4),
    change_amount NUMERIC(18, 4),
    change_pct NUMERIC(18, 6),
    volume_hand BIGINT,
    volume_share BIGINT,
    amount_yuan NUMERIC(24, 2),
    turnover_rate NUMERIC(18, 6),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_daily_bar_stock_date_source UNIQUE (stock_code, trade_date, source)
);

CREATE INDEX IF NOT EXISTS idx_t_daily_bar_stock_date ON t_daily_bar(stock_code, trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_t_daily_bar_source ON t_daily_bar(source, trade_date DESC);

CREATE TABLE IF NOT EXISTS t_minute_bar (
    id BIGSERIAL PRIMARY KEY,
    stock_code VARCHAR(20) NOT NULL,
    bar_time TIMESTAMPTZ NOT NULL,
    interval VARCHAR(20) NOT NULL DEFAULT '1m',
    source VARCHAR(80) NOT NULL,
    price NUMERIC(18, 4),
    avg_price NUMERIC(18, 4),
    volume_hand BIGINT,
    volume_share BIGINT,
    amount_yuan NUMERIC(24, 2),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_minute_bar_stock_time_interval_source UNIQUE (stock_code, bar_time, interval, source)
);

CREATE INDEX IF NOT EXISTS idx_t_minute_bar_stock_time ON t_minute_bar(stock_code, bar_time DESC);

CREATE TABLE IF NOT EXISTS t_quote_snapshot (
    id BIGSERIAL PRIMARY KEY,
    stock_code VARCHAR(20) NOT NULL,
    quote_time TIMESTAMPTZ NOT NULL,
    source VARCHAR(80) NOT NULL,
    last_price NUMERIC(18, 4),
    pre_close_price NUMERIC(18, 4),
    change_amount NUMERIC(18, 4),
    change_pct NUMERIC(18, 6),
    open_price NUMERIC(18, 4),
    high_price NUMERIC(18, 4),
    low_price NUMERIC(18, 4),
    volume_hand BIGINT,
    amount_yuan NUMERIC(24, 2),
    order_book JSONB NOT NULL DEFAULT '{}'::jsonb,
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_quote_snapshot_stock_time_source UNIQUE (stock_code, quote_time, source)
);

CREATE INDEX IF NOT EXISTS idx_t_quote_snapshot_stock_time ON t_quote_snapshot(stock_code, quote_time DESC);

-- Reserved canonical tables for later phases. Raw data can enter t_provider_raw_record before these are populated.
CREATE TABLE IF NOT EXISTS t_tick_trade (
    id BIGSERIAL PRIMARY KEY,
    stock_code VARCHAR(20) NOT NULL,
    trade_time TIMESTAMPTZ NOT NULL,
    source VARCHAR(80) NOT NULL,
    price NUMERIC(18, 4),
    volume_hand BIGINT,
    amount_yuan NUMERIC(24, 2),
    side VARCHAR(20),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS t_financial_statement (
    id BIGSERIAL PRIMARY KEY,
    stock_code VARCHAR(20) NOT NULL,
    report_date DATE NOT NULL,
    statement_type VARCHAR(40) NOT NULL,
    period_type VARCHAR(40) NOT NULL,
    source VARCHAR(80) NOT NULL,
    values_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (stock_code, report_date, statement_type, period_type, source)
);

CREATE TABLE IF NOT EXISTS t_corporate_action (
    id BIGSERIAL PRIMARY KEY,
    stock_code VARCHAR(20) NOT NULL,
    action_date DATE NOT NULL,
    action_type VARCHAR(80) NOT NULL,
    source VARCHAR(80) NOT NULL,
    values_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS t_sector_basic (
    id BIGSERIAL PRIMARY KEY,
    sector_code VARCHAR(80) NOT NULL UNIQUE,
    sector_name VARCHAR(160) NOT NULL,
    sector_type VARCHAR(40) NOT NULL,
    source VARCHAR(80),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS t_sector_component (
    id BIGSERIAL PRIMARY KEY,
    sector_code VARCHAR(80) NOT NULL,
    stock_code VARCHAR(20) NOT NULL,
    weight NUMERIC(18, 6),
    start_date DATE,
    end_date DATE,
    source VARCHAR(80),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (sector_code, stock_code, source)
);

CREATE TABLE IF NOT EXISTS t_sector_bar (
    id BIGSERIAL PRIMARY KEY,
    sector_code VARCHAR(80) NOT NULL,
    trade_date DATE NOT NULL,
    source VARCHAR(80) NOT NULL,
    open_price NUMERIC(18, 4),
    high_price NUMERIC(18, 4),
    low_price NUMERIC(18, 4),
    close_price NUMERIC(18, 4),
    change_pct NUMERIC(18, 6),
    amount_yuan NUMERIC(24, 2),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (sector_code, trade_date, source)
);

CREATE TABLE IF NOT EXISTS t_index_basic (
    id BIGSERIAL PRIMARY KEY,
    index_code VARCHAR(20) NOT NULL UNIQUE,
    index_name VARCHAR(120) NOT NULL,
    market VARCHAR(20) NOT NULL DEFAULT 'CN',
    publisher VARCHAR(120),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS t_index_component (
    id BIGSERIAL PRIMARY KEY,
    index_code VARCHAR(20) NOT NULL,
    stock_code VARCHAR(20) NOT NULL,
    weight NUMERIC(18, 6),
    effective_date DATE,
    source VARCHAR(80),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (index_code, stock_code, effective_date, source)
);

CREATE TABLE IF NOT EXISTS t_index_bar (
    id BIGSERIAL PRIMARY KEY,
    index_code VARCHAR(20) NOT NULL,
    trade_date DATE NOT NULL,
    source VARCHAR(80) NOT NULL,
    open_price NUMERIC(18, 4),
    high_price NUMERIC(18, 4),
    low_price NUMERIC(18, 4),
    close_price NUMERIC(18, 4),
    change_pct NUMERIC(18, 6),
    amount_yuan NUMERIC(24, 2),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (index_code, trade_date, source)
);

-- Derived layer. These tables preserve migrated factor assets and can later be rebuilt from canonical data.
CREATE TABLE IF NOT EXISTS t_stock_factor_daily (
    id BIGSERIAL PRIMARY KEY,
    stock_code VARCHAR(20) NOT NULL,
    trade_date DATE NOT NULL,
    source VARCHAR(80) NOT NULL DEFAULT 'system',
    ma5 NUMERIC(18, 6),
    ma10 NUMERIC(18, 6),
    ma20 NUMERIC(18, 6),
    return_1d NUMERIC(18, 6),
    amplitude NUMERIC(18, 6),
    volume_ratio NUMERIC(18, 6),
    amount_ratio NUMERIC(18, 6),
    volatility_20d NUMERIC(18, 6),
    close_position NUMERIC(18, 6),
    features JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_stock_factor_daily UNIQUE (stock_code, trade_date, source)
);

CREATE INDEX IF NOT EXISTS idx_t_stock_factor_daily_stock_date ON t_stock_factor_daily(stock_code, trade_date DESC);

CREATE TABLE IF NOT EXISTS t_stock_factor_minute (
    id BIGSERIAL PRIMARY KEY,
    stock_code VARCHAR(20) NOT NULL,
    bar_time TIMESTAMPTZ NOT NULL,
    source VARCHAR(80) NOT NULL DEFAULT 'system',
    vwap NUMERIC(18, 6),
    minute_return NUMERIC(18, 6),
    volume_spike_ratio NUMERIC(18, 6),
    intraday_strength NUMERIC(18, 6),
    features JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_stock_factor_minute UNIQUE (stock_code, bar_time, source)
);

CREATE INDEX IF NOT EXISTS idx_t_stock_factor_minute_stock_time ON t_stock_factor_minute(stock_code, bar_time DESC);

CREATE TABLE IF NOT EXISTS t_technical_indicator_snapshot (
    id BIGSERIAL PRIMARY KEY,
    stock_code VARCHAR(20) NOT NULL,
    snapshot_time TIMESTAMPTZ NOT NULL,
    source VARCHAR(80) NOT NULL DEFAULT 'system',
    last_price NUMERIC(18, 4),
    change_pct NUMERIC(18, 6),
    intraday_strength NUMERIC(18, 6),
    volume_score NUMERIC(18, 6),
    trend_score NUMERIC(18, 6),
    factor_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_technical_indicator_snapshot UNIQUE (stock_code, snapshot_time, source)
);

COMMENT ON TABLE t_provider_raw_record IS 'Raw 层：保存外部 provider 原始响应，防止规范化字段不完整导致数据丢失。';
COMMENT ON COLUMN t_provider_raw_record.id IS '主键 ID。';
COMMENT ON COLUMN t_provider_raw_record.trace_id IS '一次外部查询或采集的追踪 ID。';
COMMENT ON COLUMN t_provider_raw_record.provider_code IS 'provider 编码，例如 akshare、mootdx。';
COMMENT ON COLUMN t_provider_raw_record.capability IS '数据能力类型，例如 quote、daily_bars、minute_bars、stock_basic。';
COMMENT ON COLUMN t_provider_raw_record.request_params IS '调用外部 provider 时使用的请求参数。';
COMMENT ON COLUMN t_provider_raw_record.record_key IS '业务定位键，例如股票代码或板块代码。';
COMMENT ON COLUMN t_provider_raw_record.payload IS '外部 provider 返回的原始 payload。';
COMMENT ON COLUMN t_provider_raw_record.payload_summary IS '原始 payload 摘要，例如行数、类型、哈希。';
COMMENT ON COLUMN t_provider_raw_record.normalized_table IS '已规范化写入的目标表名。';
COMMENT ON COLUMN t_provider_raw_record.normalized_pk IS '规范化记录的主键或业务键。';
COMMENT ON COLUMN t_provider_raw_record.status IS '处理状态：captured、normalized、failed、skipped。';
COMMENT ON COLUMN t_provider_raw_record.error_code IS '采集或规范化失败时的错误码。';
COMMENT ON COLUMN t_provider_raw_record.error_message IS '采集或规范化失败时的错误详情。';
COMMENT ON COLUMN t_provider_raw_record.created_at IS '创建时间。';

COMMENT ON TABLE t_stock IS 'Canonical 层：股票基础资料。';
COMMENT ON COLUMN t_stock.id IS '主键 ID。';
COMMENT ON COLUMN t_stock.stock_code IS '股票代码，例如 600519。';
COMMENT ON COLUMN t_stock.stock_name IS '股票名称。';
COMMENT ON COLUMN t_stock.market IS '市场标识，例如 CN。';
COMMENT ON COLUMN t_stock.exchange IS '交易所标识，例如 SSE、SZSE、BSE。';
COMMENT ON COLUMN t_stock.list_date IS '上市日期。';
COMMENT ON COLUMN t_stock.delist_date IS '退市日期。';
COMMENT ON COLUMN t_stock.status IS '证券状态，例如 active、suspended、delisted。';
COMMENT ON COLUMN t_stock.industry IS '所属行业。';
COMMENT ON COLUMN t_stock.area IS '所属地区。';
COMMENT ON COLUMN t_stock.metadata IS '扩展信息和迁移来源信息。';
COMMENT ON COLUMN t_stock.created_at IS '创建时间。';
COMMENT ON COLUMN t_stock.updated_at IS '更新时间。';

COMMENT ON TABLE t_trade_calendar IS 'Canonical 层：交易日历。';
COMMENT ON COLUMN t_trade_calendar.id IS '主键 ID。';
COMMENT ON COLUMN t_trade_calendar.trade_date IS '交易日期。';
COMMENT ON COLUMN t_trade_calendar.market IS '市场标识，例如 CN。';
COMMENT ON COLUMN t_trade_calendar.is_open IS '是否开市。';
COMMENT ON COLUMN t_trade_calendar.previous_trade_date IS '前一个交易日。';
COMMENT ON COLUMN t_trade_calendar.next_trade_date IS '后一个交易日。';
COMMENT ON COLUMN t_trade_calendar.source IS '数据来源或迁移来源。';
COMMENT ON COLUMN t_trade_calendar.metadata IS '扩展信息。';
COMMENT ON COLUMN t_trade_calendar.created_at IS '创建时间。';

COMMENT ON TABLE t_daily_bar IS 'Canonical 层：股票日线行情，按 source 保留不同数据源和复权口径。';
COMMENT ON COLUMN t_daily_bar.id IS '主键 ID。';
COMMENT ON COLUMN t_daily_bar.stock_code IS '股票代码。';
COMMENT ON COLUMN t_daily_bar.trade_date IS '交易日期。';
COMMENT ON COLUMN t_daily_bar.source IS '数据来源，例如 akshare_qfq、mootdx。';
COMMENT ON COLUMN t_daily_bar.adjust_mode IS '复权模式：none、qfq、hfq。';
COMMENT ON COLUMN t_daily_bar.open_price IS '开盘价。';
COMMENT ON COLUMN t_daily_bar.high_price IS '最高价。';
COMMENT ON COLUMN t_daily_bar.low_price IS '最低价。';
COMMENT ON COLUMN t_daily_bar.close_price IS '收盘价。';
COMMENT ON COLUMN t_daily_bar.pre_close_price IS '昨收价。';
COMMENT ON COLUMN t_daily_bar.change_amount IS '涨跌额。';
COMMENT ON COLUMN t_daily_bar.change_pct IS '涨跌幅百分比。';
COMMENT ON COLUMN t_daily_bar.volume_hand IS '成交量，单位手。';
COMMENT ON COLUMN t_daily_bar.volume_share IS '成交量，单位股。';
COMMENT ON COLUMN t_daily_bar.amount_yuan IS '成交额，单位元。';
COMMENT ON COLUMN t_daily_bar.turnover_rate IS '换手率百分比。';
COMMENT ON COLUMN t_daily_bar.metadata IS '扩展信息和原始字段摘要。';
COMMENT ON COLUMN t_daily_bar.created_at IS '创建时间。';
COMMENT ON COLUMN t_daily_bar.updated_at IS '更新时间。';

COMMENT ON TABLE t_minute_bar IS 'Canonical 层：股票分钟线行情。';
COMMENT ON COLUMN t_minute_bar.id IS '主键 ID。';
COMMENT ON COLUMN t_minute_bar.stock_code IS '股票代码。';
COMMENT ON COLUMN t_minute_bar.bar_time IS '分钟 K 线时间。';
COMMENT ON COLUMN t_minute_bar.interval IS '分钟周期，例如 1m、5m。';
COMMENT ON COLUMN t_minute_bar.source IS '数据来源，例如 mootdx、akshare。';
COMMENT ON COLUMN t_minute_bar.price IS '分钟成交价或收盘价。';
COMMENT ON COLUMN t_minute_bar.avg_price IS '分钟均价。';
COMMENT ON COLUMN t_minute_bar.volume_hand IS '成交量，单位手。';
COMMENT ON COLUMN t_minute_bar.volume_share IS '成交量，单位股。';
COMMENT ON COLUMN t_minute_bar.amount_yuan IS '成交额，单位元。';
COMMENT ON COLUMN t_minute_bar.metadata IS '扩展信息和原始字段摘要。';
COMMENT ON COLUMN t_minute_bar.created_at IS '创建时间。';

COMMENT ON TABLE t_quote_snapshot IS 'Canonical 层：实时行情快照。';
COMMENT ON COLUMN t_quote_snapshot.id IS '主键 ID。';
COMMENT ON COLUMN t_quote_snapshot.stock_code IS '股票代码。';
COMMENT ON COLUMN t_quote_snapshot.quote_time IS '行情快照时间。';
COMMENT ON COLUMN t_quote_snapshot.source IS '数据来源，例如 mootdx、akshare。';
COMMENT ON COLUMN t_quote_snapshot.last_price IS '最新价。';
COMMENT ON COLUMN t_quote_snapshot.pre_close_price IS '昨收价。';
COMMENT ON COLUMN t_quote_snapshot.change_amount IS '涨跌额。';
COMMENT ON COLUMN t_quote_snapshot.change_pct IS '涨跌幅百分比。';
COMMENT ON COLUMN t_quote_snapshot.open_price IS '开盘价。';
COMMENT ON COLUMN t_quote_snapshot.high_price IS '最高价。';
COMMENT ON COLUMN t_quote_snapshot.low_price IS '最低价。';
COMMENT ON COLUMN t_quote_snapshot.volume_hand IS '成交量，单位手。';
COMMENT ON COLUMN t_quote_snapshot.amount_yuan IS '成交额，单位元。';
COMMENT ON COLUMN t_quote_snapshot.order_book IS '五档盘口或盘口扩展数据。';
COMMENT ON COLUMN t_quote_snapshot.raw_payload IS '实时行情原始 payload。';
COMMENT ON COLUMN t_quote_snapshot.created_at IS '创建时间。';

COMMENT ON TABLE t_tick_trade IS 'Canonical 预留：逐笔成交。';
COMMENT ON COLUMN t_tick_trade.id IS '主键 ID。';
COMMENT ON COLUMN t_tick_trade.stock_code IS '股票代码。';
COMMENT ON COLUMN t_tick_trade.trade_time IS '成交时间。';
COMMENT ON COLUMN t_tick_trade.source IS '数据来源。';
COMMENT ON COLUMN t_tick_trade.price IS '成交价。';
COMMENT ON COLUMN t_tick_trade.volume_hand IS '成交量，单位手。';
COMMENT ON COLUMN t_tick_trade.amount_yuan IS '成交额，单位元。';
COMMENT ON COLUMN t_tick_trade.side IS '成交方向，例如 buy、sell、neutral。';
COMMENT ON COLUMN t_tick_trade.metadata IS '扩展信息。';
COMMENT ON COLUMN t_tick_trade.created_at IS '创建时间。';

COMMENT ON TABLE t_financial_statement IS 'Canonical 预留：财务报表或财务指标统一表。';
COMMENT ON COLUMN t_financial_statement.id IS '主键 ID。';
COMMENT ON COLUMN t_financial_statement.stock_code IS '股票代码。';
COMMENT ON COLUMN t_financial_statement.report_date IS '报告期日期。';
COMMENT ON COLUMN t_financial_statement.statement_type IS '报表类型，例如 income、balance、cashflow、indicator。';
COMMENT ON COLUMN t_financial_statement.period_type IS '报告期类型，例如 annual、quarter、ttm。';
COMMENT ON COLUMN t_financial_statement.source IS '数据来源。';
COMMENT ON COLUMN t_financial_statement.values_json IS '财务字段键值集合。';
COMMENT ON COLUMN t_financial_statement.metadata IS '扩展信息。';
COMMENT ON COLUMN t_financial_statement.created_at IS '创建时间。';
COMMENT ON COLUMN t_financial_statement.updated_at IS '更新时间。';

COMMENT ON TABLE t_corporate_action IS 'Canonical 预留：除权除息、分红、送转、配股等公司行动。';
COMMENT ON COLUMN t_corporate_action.id IS '主键 ID。';
COMMENT ON COLUMN t_corporate_action.stock_code IS '股票代码。';
COMMENT ON COLUMN t_corporate_action.action_date IS '公司行动日期。';
COMMENT ON COLUMN t_corporate_action.action_type IS '公司行动类型。';
COMMENT ON COLUMN t_corporate_action.source IS '数据来源。';
COMMENT ON COLUMN t_corporate_action.values_json IS '公司行动字段键值集合。';
COMMENT ON COLUMN t_corporate_action.metadata IS '扩展信息。';
COMMENT ON COLUMN t_corporate_action.created_at IS '创建时间。';

COMMENT ON TABLE t_sector_basic IS 'Canonical 预留：板块、行业、概念基础信息。';
COMMENT ON COLUMN t_sector_basic.id IS '主键 ID。';
COMMENT ON COLUMN t_sector_basic.sector_code IS '板块代码。';
COMMENT ON COLUMN t_sector_basic.sector_name IS '板块名称。';
COMMENT ON COLUMN t_sector_basic.sector_type IS '板块类型，例如 industry、concept、region。';
COMMENT ON COLUMN t_sector_basic.source IS '数据来源。';
COMMENT ON COLUMN t_sector_basic.metadata IS '扩展信息。';
COMMENT ON COLUMN t_sector_basic.created_at IS '创建时间。';
COMMENT ON COLUMN t_sector_basic.updated_at IS '更新时间。';

COMMENT ON TABLE t_sector_component IS 'Canonical 预留：板块成分股。';
COMMENT ON COLUMN t_sector_component.id IS '主键 ID。';
COMMENT ON COLUMN t_sector_component.sector_code IS '板块代码。';
COMMENT ON COLUMN t_sector_component.stock_code IS '股票代码。';
COMMENT ON COLUMN t_sector_component.weight IS '成分权重。';
COMMENT ON COLUMN t_sector_component.start_date IS '纳入日期。';
COMMENT ON COLUMN t_sector_component.end_date IS '移出日期。';
COMMENT ON COLUMN t_sector_component.source IS '数据来源。';
COMMENT ON COLUMN t_sector_component.metadata IS '扩展信息。';
COMMENT ON COLUMN t_sector_component.created_at IS '创建时间。';

COMMENT ON TABLE t_sector_bar IS 'Canonical 预留：板块日线行情。';
COMMENT ON COLUMN t_sector_bar.id IS '主键 ID。';
COMMENT ON COLUMN t_sector_bar.sector_code IS '板块代码。';
COMMENT ON COLUMN t_sector_bar.trade_date IS '交易日期。';
COMMENT ON COLUMN t_sector_bar.source IS '数据来源。';
COMMENT ON COLUMN t_sector_bar.open_price IS '开盘价。';
COMMENT ON COLUMN t_sector_bar.high_price IS '最高价。';
COMMENT ON COLUMN t_sector_bar.low_price IS '最低价。';
COMMENT ON COLUMN t_sector_bar.close_price IS '收盘价。';
COMMENT ON COLUMN t_sector_bar.change_pct IS '涨跌幅百分比。';
COMMENT ON COLUMN t_sector_bar.amount_yuan IS '成交额，单位元。';
COMMENT ON COLUMN t_sector_bar.metadata IS '扩展信息。';
COMMENT ON COLUMN t_sector_bar.created_at IS '创建时间。';

COMMENT ON TABLE t_index_basic IS 'Canonical 预留：指数基础信息。';
COMMENT ON COLUMN t_index_basic.id IS '主键 ID。';
COMMENT ON COLUMN t_index_basic.index_code IS '指数代码。';
COMMENT ON COLUMN t_index_basic.index_name IS '指数名称。';
COMMENT ON COLUMN t_index_basic.market IS '市场标识，例如 CN。';
COMMENT ON COLUMN t_index_basic.publisher IS '指数发布机构。';
COMMENT ON COLUMN t_index_basic.metadata IS '扩展信息。';
COMMENT ON COLUMN t_index_basic.created_at IS '创建时间。';
COMMENT ON COLUMN t_index_basic.updated_at IS '更新时间。';

COMMENT ON TABLE t_index_component IS 'Canonical 预留：指数成分股。';
COMMENT ON COLUMN t_index_component.id IS '主键 ID。';
COMMENT ON COLUMN t_index_component.index_code IS '指数代码。';
COMMENT ON COLUMN t_index_component.stock_code IS '股票代码。';
COMMENT ON COLUMN t_index_component.weight IS '成分权重。';
COMMENT ON COLUMN t_index_component.effective_date IS '成分生效日期。';
COMMENT ON COLUMN t_index_component.source IS '数据来源。';
COMMENT ON COLUMN t_index_component.metadata IS '扩展信息。';
COMMENT ON COLUMN t_index_component.created_at IS '创建时间。';

COMMENT ON TABLE t_index_bar IS 'Canonical 预留：指数日线行情。';
COMMENT ON COLUMN t_index_bar.id IS '主键 ID。';
COMMENT ON COLUMN t_index_bar.index_code IS '指数代码。';
COMMENT ON COLUMN t_index_bar.trade_date IS '交易日期。';
COMMENT ON COLUMN t_index_bar.source IS '数据来源。';
COMMENT ON COLUMN t_index_bar.open_price IS '开盘价。';
COMMENT ON COLUMN t_index_bar.high_price IS '最高价。';
COMMENT ON COLUMN t_index_bar.low_price IS '最低价。';
COMMENT ON COLUMN t_index_bar.close_price IS '收盘价。';
COMMENT ON COLUMN t_index_bar.change_pct IS '涨跌幅百分比。';
COMMENT ON COLUMN t_index_bar.amount_yuan IS '成交额，单位元。';
COMMENT ON COLUMN t_index_bar.metadata IS '扩展信息。';
COMMENT ON COLUMN t_index_bar.created_at IS '创建时间。';

COMMENT ON TABLE t_stock_factor_daily IS 'Derived 层：股票日频量化因子，迁移阶段保留旧结果，后续可重算。';
COMMENT ON COLUMN t_stock_factor_daily.id IS '主键 ID。';
COMMENT ON COLUMN t_stock_factor_daily.stock_code IS '股票代码。';
COMMENT ON COLUMN t_stock_factor_daily.trade_date IS '交易日期。';
COMMENT ON COLUMN t_stock_factor_daily.source IS '因子来源。';
COMMENT ON COLUMN t_stock_factor_daily.ma5 IS '5 日均线。';
COMMENT ON COLUMN t_stock_factor_daily.ma10 IS '10 日均线。';
COMMENT ON COLUMN t_stock_factor_daily.ma20 IS '20 日均线。';
COMMENT ON COLUMN t_stock_factor_daily.return_1d IS '单日收益率百分比。';
COMMENT ON COLUMN t_stock_factor_daily.amplitude IS '振幅百分比。';
COMMENT ON COLUMN t_stock_factor_daily.volume_ratio IS '成交量相对 5 日均量比值。';
COMMENT ON COLUMN t_stock_factor_daily.amount_ratio IS '成交额相对 5 日均额比值。';
COMMENT ON COLUMN t_stock_factor_daily.volatility_20d IS '20 日收益波动率。';
COMMENT ON COLUMN t_stock_factor_daily.close_position IS '收盘价在当日高低区间的位置。';
COMMENT ON COLUMN t_stock_factor_daily.features IS '扩展因子字段。';
COMMENT ON COLUMN t_stock_factor_daily.created_at IS '创建时间。';

COMMENT ON TABLE t_stock_factor_minute IS 'Derived 层：股票分钟量化因子，迁移阶段保留旧结果，后续可重算。';
COMMENT ON COLUMN t_stock_factor_minute.id IS '主键 ID。';
COMMENT ON COLUMN t_stock_factor_minute.stock_code IS '股票代码。';
COMMENT ON COLUMN t_stock_factor_minute.bar_time IS '分钟时间。';
COMMENT ON COLUMN t_stock_factor_minute.source IS '因子来源。';
COMMENT ON COLUMN t_stock_factor_minute.vwap IS '成交额和成交量推导的 VWAP。';
COMMENT ON COLUMN t_stock_factor_minute.minute_return IS '分钟收益率百分比。';
COMMENT ON COLUMN t_stock_factor_minute.volume_spike_ratio IS '分钟放量倍数。';
COMMENT ON COLUMN t_stock_factor_minute.intraday_strength IS '盘中强度。';
COMMENT ON COLUMN t_stock_factor_minute.features IS '扩展因子字段。';
COMMENT ON COLUMN t_stock_factor_minute.created_at IS '创建时间。';

COMMENT ON TABLE t_technical_indicator_snapshot IS 'Derived 层：技术指标快照。';
COMMENT ON COLUMN t_technical_indicator_snapshot.id IS '主键 ID。';
COMMENT ON COLUMN t_technical_indicator_snapshot.stock_code IS '股票代码。';
COMMENT ON COLUMN t_technical_indicator_snapshot.snapshot_time IS '快照时间。';
COMMENT ON COLUMN t_technical_indicator_snapshot.source IS '指标来源。';
COMMENT ON COLUMN t_technical_indicator_snapshot.last_price IS '快照最新价。';
COMMENT ON COLUMN t_technical_indicator_snapshot.change_pct IS '快照涨跌幅百分比。';
COMMENT ON COLUMN t_technical_indicator_snapshot.intraday_strength IS '盘中强度。';
COMMENT ON COLUMN t_technical_indicator_snapshot.volume_score IS '成交量评分。';
COMMENT ON COLUMN t_technical_indicator_snapshot.trend_score IS '趋势评分。';
COMMENT ON COLUMN t_technical_indicator_snapshot.factor_payload IS '指标快照扩展 payload。';
COMMENT ON COLUMN t_technical_indicator_snapshot.created_at IS '创建时间。';
