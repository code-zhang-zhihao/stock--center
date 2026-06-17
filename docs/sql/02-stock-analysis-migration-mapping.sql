-- stock-analysis legacy tables -> stock-center t_* tables.
-- Run this in the existing stock-analysis PostgreSQL database after docs/sql/01-schema.sql.
--
-- Source tables are the existing unprefixed tables:
-- stock_basic, trade_calendar, daily_bar, minute_bar, quote_snapshot,
-- stock_factor_daily, stock_factor_minute, technical_indicator_snapshot.
--
-- Target tables are the new prefixed tables:
-- t_stock, t_trade_calendar, t_daily_bar, t_minute_bar, t_quote_snapshot,
-- t_stock_factor_daily, t_stock_factor_minute, t_technical_indicator_snapshot.

INSERT INTO t_stock (
    stock_code, stock_name, market, exchange, list_date, delist_date, status,
    industry, area, metadata, created_at, updated_at
)
SELECT
    stock_code, stock_name, market, exchange, list_date, delist_date, status,
    industry, area, metadata, created_at, updated_at
FROM stock_basic
ON CONFLICT (stock_code) DO UPDATE SET
    stock_name = EXCLUDED.stock_name,
    market = EXCLUDED.market,
    exchange = EXCLUDED.exchange,
    list_date = EXCLUDED.list_date,
    delist_date = EXCLUDED.delist_date,
    status = EXCLUDED.status,
    industry = EXCLUDED.industry,
    area = EXCLUDED.area,
    metadata = t_stock.metadata || EXCLUDED.metadata,
    updated_at = now();

INSERT INTO t_trade_calendar (
    trade_date, market, is_open, previous_trade_date, next_trade_date, source, created_at
)
SELECT
    trade_date, market, is_open, previous_trade_date, next_trade_date,
    'stock-analysis', created_at
FROM trade_calendar
ON CONFLICT (trade_date, market) DO UPDATE SET
    is_open = EXCLUDED.is_open,
    previous_trade_date = EXCLUDED.previous_trade_date,
    next_trade_date = EXCLUDED.next_trade_date,
    source = EXCLUDED.source;

INSERT INTO t_daily_bar (
    stock_code, trade_date, source, adjust_mode, open_price, high_price, low_price,
    close_price, pre_close_price, change_amount, change_pct, volume_hand, volume_share,
    amount_yuan, turnover_rate, metadata, created_at, updated_at
)
SELECT
    stock_code,
    trade_date,
    source,
    CASE
        WHEN source IN ('akshare_qfq', 'qfq') THEN 'qfq'
        WHEN source IN ('akshare_hfq', 'hfq') THEN 'hfq'
        ELSE COALESCE(metadata->>'adjust_mode', 'none')
    END AS adjust_mode,
    open_price, high_price, low_price, close_price, pre_close_price, change_amount,
    change_pct, volume_hand, volume_share, amount_yuan, turnover_rate,
    metadata || jsonb_build_object('migrated_from', 'stock-analysis.daily_bar'),
    created_at, updated_at
FROM daily_bar
ON CONFLICT (stock_code, trade_date, source) DO UPDATE SET
    adjust_mode = EXCLUDED.adjust_mode,
    open_price = EXCLUDED.open_price,
    high_price = EXCLUDED.high_price,
    low_price = EXCLUDED.low_price,
    close_price = EXCLUDED.close_price,
    pre_close_price = EXCLUDED.pre_close_price,
    change_amount = EXCLUDED.change_amount,
    change_pct = EXCLUDED.change_pct,
    volume_hand = EXCLUDED.volume_hand,
    volume_share = EXCLUDED.volume_share,
    amount_yuan = EXCLUDED.amount_yuan,
    turnover_rate = EXCLUDED.turnover_rate,
    metadata = t_daily_bar.metadata || EXCLUDED.metadata,
    updated_at = now();

INSERT INTO t_minute_bar (
    stock_code, bar_time, interval, source, price, avg_price, volume_hand,
    volume_share, amount_yuan, metadata, created_at
)
SELECT
    stock_code, bar_time, '1m', source, price, avg_price, volume_hand,
    volume_share, amount_yuan,
    metadata || jsonb_build_object('migrated_from', 'stock-analysis.minute_bar'),
    created_at
FROM minute_bar
ON CONFLICT (stock_code, bar_time, interval, source) DO UPDATE SET
    price = EXCLUDED.price,
    avg_price = EXCLUDED.avg_price,
    volume_hand = EXCLUDED.volume_hand,
    volume_share = EXCLUDED.volume_share,
    amount_yuan = EXCLUDED.amount_yuan,
    metadata = t_minute_bar.metadata || EXCLUDED.metadata;

INSERT INTO t_quote_snapshot (
    stock_code, quote_time, source, last_price, pre_close_price, change_amount,
    change_pct, open_price, high_price, low_price, volume_hand, amount_yuan,
    order_book, raw_payload, created_at
)
SELECT
    stock_code, quote_time, source, last_price, pre_close_price, change_amount,
    change_pct, open_price, high_price, low_price, volume_hand, amount_yuan,
    order_book, raw_payload, created_at
FROM quote_snapshot
ON CONFLICT (stock_code, quote_time, source) DO NOTHING;

INSERT INTO t_stock_factor_daily (
    stock_code, trade_date, source, ma5, ma10, ma20, return_1d, amplitude,
    volume_ratio, amount_ratio, volatility_20d, close_position, features, created_at
)
SELECT
    stock_code, trade_date, source, ma5, ma10, ma20, return_1d, amplitude,
    volume_ratio, amount_ratio, volatility_20d, close_position,
    features || jsonb_build_object('migrated_from', 'stock-analysis.stock_factor_daily'),
    created_at
FROM stock_factor_daily
ON CONFLICT (stock_code, trade_date, source) DO UPDATE SET
    ma5 = EXCLUDED.ma5,
    ma10 = EXCLUDED.ma10,
    ma20 = EXCLUDED.ma20,
    return_1d = EXCLUDED.return_1d,
    amplitude = EXCLUDED.amplitude,
    volume_ratio = EXCLUDED.volume_ratio,
    amount_ratio = EXCLUDED.amount_ratio,
    volatility_20d = EXCLUDED.volatility_20d,
    close_position = EXCLUDED.close_position,
    features = t_stock_factor_daily.features || EXCLUDED.features;

INSERT INTO t_stock_factor_minute (
    stock_code, bar_time, source, vwap, minute_return, volume_spike_ratio,
    intraday_strength, features, created_at
)
SELECT
    stock_code, bar_time, source, vwap, minute_return, volume_spike_ratio,
    intraday_strength,
    features || jsonb_build_object('migrated_from', 'stock-analysis.stock_factor_minute'),
    created_at
FROM stock_factor_minute
ON CONFLICT (stock_code, bar_time, source) DO UPDATE SET
    vwap = EXCLUDED.vwap,
    minute_return = EXCLUDED.minute_return,
    volume_spike_ratio = EXCLUDED.volume_spike_ratio,
    intraday_strength = EXCLUDED.intraday_strength,
    features = t_stock_factor_minute.features || EXCLUDED.features;

INSERT INTO t_technical_indicator_snapshot (
    stock_code, snapshot_time, source, last_price, change_pct, intraday_strength,
    volume_score, trend_score, factor_payload, created_at
)
SELECT
    stock_code, snapshot_time, source, last_price, change_pct, intraday_strength,
    volume_score, trend_score,
    factor_payload || jsonb_build_object('migrated_from', 'stock-analysis.technical_indicator_snapshot'),
    created_at
FROM technical_indicator_snapshot
ON CONFLICT (stock_code, snapshot_time, source) DO UPDATE SET
    last_price = EXCLUDED.last_price,
    change_pct = EXCLUDED.change_pct,
    intraday_strength = EXCLUDED.intraday_strength,
    volume_score = EXCLUDED.volume_score,
    trend_score = EXCLUDED.trend_score,
    factor_payload = t_technical_indicator_snapshot.factor_payload || EXCLUDED.factor_payload;

SELECT 't_stock' AS table_name, count(*) FROM t_stock
UNION ALL SELECT 't_daily_bar', count(*) FROM t_daily_bar
UNION ALL SELECT 't_minute_bar', count(*) FROM t_minute_bar
UNION ALL SELECT 't_quote_snapshot', count(*) FROM t_quote_snapshot
UNION ALL SELECT 't_stock_factor_daily', count(*) FROM t_stock_factor_daily
UNION ALL SELECT 't_stock_factor_minute', count(*) FROM t_stock_factor_minute
UNION ALL SELECT 't_technical_indicator_snapshot', count(*) FROM t_technical_indicator_snapshot;
