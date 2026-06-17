-- stock-center quantitative data capabilities migration.
-- Adds canonical event/factor tables for fund flow, LHB, announcements, and factor definitions.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_t_tick_trade_business'
    ) THEN
        ALTER TABLE t_tick_trade
            ADD CONSTRAINT uq_t_tick_trade_business UNIQUE (stock_code, trade_time, source, price, volume_hand);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_t_sector_component_stock ON t_sector_component(stock_code, sector_code);
CREATE INDEX IF NOT EXISTS idx_t_sector_component_sector ON t_sector_component(sector_code, stock_code);

CREATE TABLE IF NOT EXISTS t_stock_fund_flow_daily (
    id BIGSERIAL PRIMARY KEY,
    stock_code VARCHAR(20) NOT NULL,
    trade_date DATE NOT NULL,
    source VARCHAR(80) NOT NULL,
    main_net_inflow NUMERIC(24, 2),
    main_net_ratio NUMERIC(18, 6),
    big_order_net_inflow NUMERIC(24, 2),
    big_order_net_ratio NUMERIC(18, 6),
    super_large_net_inflow NUMERIC(24, 2),
    medium_net_inflow NUMERIC(24, 2),
    small_net_inflow NUMERIC(24, 2),
    close_price NUMERIC(18, 4),
    change_pct NUMERIC(18, 6),
    rank INTEGER,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_stock_fund_flow_daily_stock_date_source UNIQUE (stock_code, trade_date, source)
);

CREATE INDEX IF NOT EXISTS idx_t_stock_fund_flow_daily_stock_date ON t_stock_fund_flow_daily(stock_code, trade_date DESC);

CREATE TABLE IF NOT EXISTS t_sector_fund_flow_daily (
    id BIGSERIAL PRIMARY KEY,
    sector_code VARCHAR(80) NOT NULL,
    sector_name VARCHAR(160) NOT NULL,
    sector_type VARCHAR(40) NOT NULL,
    trade_date DATE NOT NULL,
    source VARCHAR(80) NOT NULL,
    main_net_inflow NUMERIC(24, 2),
    main_net_ratio NUMERIC(18, 6),
    change_pct NUMERIC(18, 6),
    rank INTEGER,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_sector_fund_flow_daily_sector_date_source UNIQUE (sector_code, trade_date, source)
);

CREATE INDEX IF NOT EXISTS idx_t_sector_fund_flow_daily_type_date ON t_sector_fund_flow_daily(sector_type, trade_date DESC);

CREATE TABLE IF NOT EXISTS t_lhb_event (
    id BIGSERIAL PRIMARY KEY,
    stock_code VARCHAR(20) NOT NULL,
    stock_name VARCHAR(120),
    trade_date DATE NOT NULL,
    source VARCHAR(80) NOT NULL,
    reason VARCHAR(300) NOT NULL,
    close_price NUMERIC(18, 4),
    change_pct NUMERIC(18, 6),
    turnover_amount NUMERIC(24, 2),
    net_buy_amount NUMERIC(24, 2),
    buy_amount NUMERIC(24, 2),
    sell_amount NUMERIC(24, 2),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_lhb_event_stock_date_reason_source UNIQUE (stock_code, trade_date, reason, source)
);

CREATE INDEX IF NOT EXISTS idx_t_lhb_event_stock_date ON t_lhb_event(stock_code, trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_t_lhb_event_date ON t_lhb_event(trade_date DESC);

CREATE TABLE IF NOT EXISTS t_lhb_seat_detail (
    id BIGSERIAL PRIMARY KEY,
    stock_code VARCHAR(20) NOT NULL,
    trade_date DATE NOT NULL,
    source VARCHAR(80) NOT NULL,
    side VARCHAR(20) NOT NULL,
    seat_name VARCHAR(240) NOT NULL,
    buy_amount NUMERIC(24, 2),
    sell_amount NUMERIC(24, 2),
    net_amount NUMERIC(24, 2),
    rank INTEGER,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_lhb_seat_detail_business UNIQUE (stock_code, trade_date, seat_name, side, source)
);

CREATE INDEX IF NOT EXISTS idx_t_lhb_seat_detail_stock_date ON t_lhb_seat_detail(stock_code, trade_date DESC);

CREATE TABLE IF NOT EXISTS t_announcement (
    id BIGSERIAL PRIMARY KEY,
    stock_code VARCHAR(20) NOT NULL,
    stock_name VARCHAR(120),
    title VARCHAR(500) NOT NULL,
    category VARCHAR(120),
    published_at TIMESTAMPTZ NOT NULL,
    url TEXT,
    source VARCHAR(80) NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_announcement_stock_title_time_source UNIQUE (stock_code, title, published_at, source)
);

CREATE INDEX IF NOT EXISTS idx_t_announcement_stock_time ON t_announcement(stock_code, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_t_announcement_category_time ON t_announcement(category, published_at DESC);

CREATE TABLE IF NOT EXISTS t_factor_definition (
    id BIGSERIAL PRIMARY KEY,
    factor_code VARCHAR(120) NOT NULL UNIQUE,
    factor_name VARCHAR(200) NOT NULL,
    factor_group VARCHAR(80) NOT NULL,
    frequency VARCHAR(40) NOT NULL,
    source_table VARCHAR(120),
    compute_method TEXT,
    is_rebuildable BOOLEAN NOT NULL DEFAULT true,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE t_stock_fund_flow_daily IS 'Canonical 层：个股每日资金流事实。';
COMMENT ON COLUMN t_stock_fund_flow_daily.id IS '主键 ID。';
COMMENT ON COLUMN t_stock_fund_flow_daily.stock_code IS '股票代码。';
COMMENT ON COLUMN t_stock_fund_flow_daily.trade_date IS '交易日期。';
COMMENT ON COLUMN t_stock_fund_flow_daily.source IS '数据来源。';
COMMENT ON COLUMN t_stock_fund_flow_daily.main_net_inflow IS '主力净流入金额，单位元。';
COMMENT ON COLUMN t_stock_fund_flow_daily.main_net_ratio IS '主力净流入占比，单位百分比。';
COMMENT ON COLUMN t_stock_fund_flow_daily.big_order_net_inflow IS '大单净流入金额，单位元。';
COMMENT ON COLUMN t_stock_fund_flow_daily.big_order_net_ratio IS '大单净流入占比，单位百分比。';
COMMENT ON COLUMN t_stock_fund_flow_daily.super_large_net_inflow IS '超大单净流入金额，单位元。';
COMMENT ON COLUMN t_stock_fund_flow_daily.medium_net_inflow IS '中单净流入金额，单位元。';
COMMENT ON COLUMN t_stock_fund_flow_daily.small_net_inflow IS '小单净流入金额，单位元。';
COMMENT ON COLUMN t_stock_fund_flow_daily.close_price IS '当日收盘价或最新价。';
COMMENT ON COLUMN t_stock_fund_flow_daily.change_pct IS '涨跌幅百分比。';
COMMENT ON COLUMN t_stock_fund_flow_daily.rank IS '来源侧排名。';
COMMENT ON COLUMN t_stock_fund_flow_daily.metadata IS '扩展信息和原始字段摘要。';
COMMENT ON COLUMN t_stock_fund_flow_daily.created_at IS '创建时间。';
COMMENT ON COLUMN t_stock_fund_flow_daily.updated_at IS '更新时间。';

COMMENT ON TABLE t_sector_fund_flow_daily IS 'Canonical 层：板块、概念、行业每日资金流事实。';
COMMENT ON COLUMN t_sector_fund_flow_daily.id IS '主键 ID。';
COMMENT ON COLUMN t_sector_fund_flow_daily.sector_code IS '板块代码或板块名称 fallback。';
COMMENT ON COLUMN t_sector_fund_flow_daily.sector_name IS '板块名称。';
COMMENT ON COLUMN t_sector_fund_flow_daily.sector_type IS '板块类型：industry、concept、region 等。';
COMMENT ON COLUMN t_sector_fund_flow_daily.trade_date IS '交易日期。';
COMMENT ON COLUMN t_sector_fund_flow_daily.source IS '数据来源。';
COMMENT ON COLUMN t_sector_fund_flow_daily.main_net_inflow IS '主力净流入金额，单位元。';
COMMENT ON COLUMN t_sector_fund_flow_daily.main_net_ratio IS '主力净流入占比，单位百分比。';
COMMENT ON COLUMN t_sector_fund_flow_daily.change_pct IS '板块涨跌幅百分比。';
COMMENT ON COLUMN t_sector_fund_flow_daily.rank IS '来源侧排名。';
COMMENT ON COLUMN t_sector_fund_flow_daily.metadata IS '扩展信息和原始字段摘要。';
COMMENT ON COLUMN t_sector_fund_flow_daily.created_at IS '创建时间。';
COMMENT ON COLUMN t_sector_fund_flow_daily.updated_at IS '更新时间。';

COMMENT ON TABLE t_lhb_event IS 'Canonical 层：龙虎榜上榜事件。';
COMMENT ON COLUMN t_lhb_event.id IS '主键 ID。';
COMMENT ON COLUMN t_lhb_event.stock_code IS '股票代码。';
COMMENT ON COLUMN t_lhb_event.stock_name IS '股票名称。';
COMMENT ON COLUMN t_lhb_event.trade_date IS '上榜交易日。';
COMMENT ON COLUMN t_lhb_event.source IS '数据来源。';
COMMENT ON COLUMN t_lhb_event.reason IS '上榜原因或解读。';
COMMENT ON COLUMN t_lhb_event.close_price IS '上榜日收盘价。';
COMMENT ON COLUMN t_lhb_event.change_pct IS '上榜日涨跌幅百分比。';
COMMENT ON COLUMN t_lhb_event.turnover_amount IS '上榜日成交额，单位元。';
COMMENT ON COLUMN t_lhb_event.net_buy_amount IS '龙虎榜净买额，单位元。';
COMMENT ON COLUMN t_lhb_event.buy_amount IS '龙虎榜买入金额，单位元。';
COMMENT ON COLUMN t_lhb_event.sell_amount IS '龙虎榜卖出金额，单位元。';
COMMENT ON COLUMN t_lhb_event.metadata IS '扩展信息和原始字段摘要。';
COMMENT ON COLUMN t_lhb_event.created_at IS '创建时间。';
COMMENT ON COLUMN t_lhb_event.updated_at IS '更新时间。';

COMMENT ON TABLE t_lhb_seat_detail IS 'Canonical 层：龙虎榜营业部席位买卖明细。';
COMMENT ON COLUMN t_lhb_seat_detail.id IS '主键 ID。';
COMMENT ON COLUMN t_lhb_seat_detail.stock_code IS '股票代码。';
COMMENT ON COLUMN t_lhb_seat_detail.trade_date IS '交易日期。';
COMMENT ON COLUMN t_lhb_seat_detail.source IS '数据来源。';
COMMENT ON COLUMN t_lhb_seat_detail.side IS '席位方向：buy、sell。';
COMMENT ON COLUMN t_lhb_seat_detail.seat_name IS '营业部或机构席位名称。';
COMMENT ON COLUMN t_lhb_seat_detail.buy_amount IS '买入金额，单位元。';
COMMENT ON COLUMN t_lhb_seat_detail.sell_amount IS '卖出金额，单位元。';
COMMENT ON COLUMN t_lhb_seat_detail.net_amount IS '净买入金额，单位元。';
COMMENT ON COLUMN t_lhb_seat_detail.rank IS '来源侧排名。';
COMMENT ON COLUMN t_lhb_seat_detail.metadata IS '扩展信息和原始字段摘要。';
COMMENT ON COLUMN t_lhb_seat_detail.created_at IS '创建时间。';

COMMENT ON TABLE t_announcement IS 'Canonical 层：上市公司公告事件。';
COMMENT ON COLUMN t_announcement.id IS '主键 ID。';
COMMENT ON COLUMN t_announcement.stock_code IS '股票代码。';
COMMENT ON COLUMN t_announcement.stock_name IS '股票名称。';
COMMENT ON COLUMN t_announcement.title IS '公告标题。';
COMMENT ON COLUMN t_announcement.category IS '公告类别。';
COMMENT ON COLUMN t_announcement.published_at IS '公告发布时间。';
COMMENT ON COLUMN t_announcement.url IS '公告链接。';
COMMENT ON COLUMN t_announcement.source IS '数据来源。';
COMMENT ON COLUMN t_announcement.metadata IS '扩展信息和原始字段摘要。';
COMMENT ON COLUMN t_announcement.created_at IS '创建时间。';
COMMENT ON COLUMN t_announcement.updated_at IS '更新时间。';

COMMENT ON TABLE t_factor_definition IS 'Derived 层：量化指标字段定义与计算口径。';
COMMENT ON COLUMN t_factor_definition.id IS '主键 ID。';
COMMENT ON COLUMN t_factor_definition.factor_code IS '指标字段编码，例如 main_net_inflow。';
COMMENT ON COLUMN t_factor_definition.factor_name IS '指标中文名称。';
COMMENT ON COLUMN t_factor_definition.factor_group IS '指标分组，例如 fund_flow、lhb、sector、tick、announcement。';
COMMENT ON COLUMN t_factor_definition.frequency IS '指标频率，例如 daily、minute、snapshot。';
COMMENT ON COLUMN t_factor_definition.source_table IS '指标来源 canonical 表。';
COMMENT ON COLUMN t_factor_definition.compute_method IS '计算口径说明。';
COMMENT ON COLUMN t_factor_definition.is_rebuildable IS '是否可从 canonical 层重建。';
COMMENT ON COLUMN t_factor_definition.metadata IS '扩展信息。';
COMMENT ON COLUMN t_factor_definition.created_at IS '创建时间。';
COMMENT ON COLUMN t_factor_definition.updated_at IS '更新时间。';

INSERT INTO t_factor_definition (
    factor_code, factor_name, factor_group, frequency, source_table, compute_method, is_rebuildable, metadata
) VALUES
('main_net_inflow', '主力净流入', 'fund_flow', 'daily', 't_stock_fund_flow_daily', '来源侧主力净流入金额。', true, '{}'::jsonb),
('main_net_ratio', '主力净流入占比', 'fund_flow', 'daily', 't_stock_fund_flow_daily', '来源侧主力净流入占成交额比例。', true, '{}'::jsonb),
('big_order_net_ratio', '大单净流入占比', 'fund_flow', 'daily', 't_stock_fund_flow_daily', '来源侧大单净流入占比。', true, '{}'::jsonb),
('lhb_flag', '龙虎榜上榜标记', 'lhb', 'daily', 't_lhb_event', '交易日存在龙虎榜事件则为 1。', true, '{}'::jsonb),
('lhb_net_buy_amount', '龙虎榜净买额', 'lhb', 'daily', 't_lhb_event', '同日龙虎榜事件净买额汇总。', true, '{}'::jsonb),
('institution_net_buy', '机构净买额', 'lhb', 'daily', 't_lhb_seat_detail', '机构或席位明细净买额聚合，后续按席位类型增强。', true, '{}'::jsonb),
('sector_strength', '板块强度', 'sector', 'daily', 't_sector_bar', '板块涨跌幅、成交额和排名综合。', true, '{}'::jsonb),
('sector_rank', '板块排名', 'sector', 'daily', 't_sector_fund_flow_daily', '来源侧板块资金流或行情排名。', true, '{}'::jsonb),
('relative_strength_vs_index', '相对指数强弱', 'index', 'daily', 't_daily_bar,t_index_bar', '个股收益相对目标指数收益。', true, '{}'::jsonb),
('concept_exposure_count', '概念暴露数量', 'sector', 'daily', 't_sector_component', '股票关联概念数量。', true, '{}'::jsonb),
('active_buy_ratio', '主动买入占比', 'tick', 'minute', 't_tick_trade', '分笔成交中主动买入成交额占比。', true, '{}'::jsonb),
('tick_vwap', '分笔 VWAP', 'tick', 'minute', 't_tick_trade', '分笔成交额除以成交量。', true, '{}'::jsonb),
('order_imbalance', '盘口不平衡', 'quote', 'snapshot', 't_quote_snapshot', '买卖盘口量差相对总盘口量。', true, '{}'::jsonb),
('large_trade_count', '大额成交次数', 'tick', 'minute', 't_tick_trade', '超过阈值的分笔成交次数。', true, '{}'::jsonb),
('announcement_count', '公告数量', 'announcement', 'daily', 't_announcement', '交易日公告数量。', true, '{}'::jsonb),
('announcement_category_flags', '公告类别标记', 'announcement', 'daily', 't_announcement', '按公告类别生成事件标记。', true, '{}'::jsonb)
ON CONFLICT (factor_code) DO UPDATE SET
    factor_name = EXCLUDED.factor_name,
    factor_group = EXCLUDED.factor_group,
    frequency = EXCLUDED.frequency,
    source_table = EXCLUDED.source_table,
    compute_method = EXCLUDED.compute_method,
    is_rebuildable = EXCLUDED.is_rebuildable,
    updated_at = now();
