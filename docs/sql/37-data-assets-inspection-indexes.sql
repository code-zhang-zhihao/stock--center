-- Data asset inspection indexes.
-- These indexes make "latest trade date" and dashboard inspection queries avoid full table scans.

CREATE INDEX IF NOT EXISTS idx_t_daily_bar_trade_date_desc
    ON t_daily_bar (trade_date DESC);

CREATE INDEX IF NOT EXISTS idx_t_stock_daily_basic_trade_date_desc
    ON t_stock_daily_basic (trade_date DESC);

CREATE INDEX IF NOT EXISTS idx_t_stock_fund_flow_daily_trade_date_desc
    ON t_stock_fund_flow_daily (trade_date DESC);

CREATE INDEX IF NOT EXISTS idx_t_limit_event_daily_trade_date_desc
    ON t_limit_event_daily (trade_date DESC);

CREATE INDEX IF NOT EXISTS idx_t_lhb_event_trade_date_desc
    ON t_lhb_event (trade_date DESC);

CREATE INDEX IF NOT EXISTS idx_t_index_bar_trade_date_desc
    ON t_index_bar (trade_date DESC);

CREATE INDEX IF NOT EXISTS idx_t_index_daily_basic_trade_date_desc
    ON t_index_daily_basic (trade_date DESC);

CREATE INDEX IF NOT EXISTS idx_t_market_daily_stat_trade_date_desc
    ON t_market_daily_stat (trade_date DESC);

CREATE INDEX IF NOT EXISTS idx_t_sector_bar_trade_date_desc
    ON t_sector_bar (trade_date DESC);

CREATE INDEX IF NOT EXISTS idx_t_sector_fund_flow_daily_trade_date_desc
    ON t_sector_fund_flow_daily (trade_date DESC);

CREATE INDEX IF NOT EXISTS idx_t_stock_technical_factor_daily_trade_date_desc
    ON t_stock_technical_factor_daily (trade_date DESC);

CREATE INDEX IF NOT EXISTS idx_t_stock_factor_daily_trade_date_desc
    ON t_stock_factor_daily (trade_date DESC);

CREATE INDEX IF NOT EXISTS idx_t_sector_factor_daily_trade_date_desc
    ON t_sector_factor_daily (trade_date DESC);

CREATE INDEX IF NOT EXISTS idx_t_minute_bar_trade_date_desc
    ON t_minute_bar (trade_date DESC);

CREATE INDEX IF NOT EXISTS idx_t_stock_factor_minute_trade_date_desc
    ON t_stock_factor_minute (trade_date DESC);

CREATE INDEX IF NOT EXISTS idx_t_quote_snapshot_eod_time_desc
    ON t_quote_snapshot (quote_time DESC)
    WHERE snapshot_kind = 'eod';

CREATE INDEX IF NOT EXISTS idx_t_technical_indicator_snapshot_time_desc
    ON t_technical_indicator_snapshot (snapshot_time DESC);
