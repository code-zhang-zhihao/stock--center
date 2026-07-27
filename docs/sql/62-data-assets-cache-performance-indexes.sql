-- 数据中心缓存预热性能索引
--
-- 必须由以下事实表 owner 在 psql/数据库管理工具中逐条执行。
-- CREATE INDEX CONCURRENTLY 不能放在显式事务或 migration runner 的事务中执行。
-- 本脚本不删除业务数据，不包含 VACUUM FULL。

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_t_daily_bar_trade_date_stock_code
    ON t_daily_bar (trade_date DESC, stock_code);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_t_stock_daily_basic_trade_date_stock_code
    ON t_stock_daily_basic (trade_date DESC, stock_code);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_t_stock_fund_flow_daily_trade_date_stock_code
    ON t_stock_fund_flow_daily (trade_date DESC, stock_code);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_t_stock_technical_factor_daily_trade_date_stock_code
    ON t_stock_technical_factor_daily (trade_date DESC, stock_code);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_t_stock_factor_daily_trade_date_stock_code_source
    ON t_stock_factor_daily (trade_date DESC, stock_code, source);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_t_limit_event_daily_trade_date_type_stock_code
    ON t_limit_event_daily (trade_date DESC, event_type, stock_code);

-- 历史回填或大批量更新后刷新规划器统计信息。
-- 可与上方索引命令分开执行；不回收文件系统空间。
ANALYZE t_daily_bar;
ANALYZE t_stock_daily_basic;
ANALYZE t_stock_fund_flow_daily;
ANALYZE t_stock_technical_factor_daily;
ANALYZE t_stock_factor_daily;
ANALYZE t_limit_event_daily;
