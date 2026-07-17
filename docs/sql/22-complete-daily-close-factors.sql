-- 每日收盘沉淀因子完整版补齐。
-- 只登记/更新因子定义，不新增表、不删除旧数据。

BEGIN;

INSERT INTO t_factor_definition (
    factor_code,
    factor_name,
    factor_group,
    frequency,
    source_table,
    compute_method,
    is_rebuildable,
    metadata
)
VALUES
    (
        'main_net_ratio',
        '主力净流入成交额占比',
        'fund_flow',
        'daily',
        't_stock_factor_daily.features',
        't_stock_fund_flow_daily.main_net_inflow 按 Tushare 万元口径先乘 10000 转元，再除以 t_daily_bar.amount_yuan * 100。',
        TRUE,
        '{"source":"daily_market_close_ingest","calculator":"StockFundFactorCalculator"}'::jsonb
    ),
    (
        'super_large_net_ratio',
        '超大单净流入成交额占比',
        'fund_flow',
        'daily',
        't_stock_factor_daily.features',
        't_stock_fund_flow_daily.super_large_net_inflow 按 Tushare 万元口径先乘 10000 转元，再除以 t_daily_bar.amount_yuan * 100。',
        TRUE,
        '{"source":"daily_market_close_ingest","calculator":"StockFundFactorCalculator"}'::jsonb
    ),
    (
        'big_order_net_ratio',
        '大单净流入成交额占比',
        'fund_flow',
        'daily',
        't_stock_factor_daily.features',
        't_stock_fund_flow_daily.big_order_net_inflow 按 Tushare 万元口径先乘 10000 转元，再除以 t_daily_bar.amount_yuan * 100。',
        TRUE,
        '{"source":"daily_market_close_ingest","calculator":"StockFundFactorCalculator"}'::jsonb
    ),
    (
        'continuous_main_inflow_days',
        '连续主力净流入天数',
        'fund_flow',
        'daily',
        't_stock_factor_daily.features',
        '从当前交易日向前统计 main_net_inflow > 0 的连续可用交易日数量。',
        TRUE,
        '{"source":"daily_market_close_ingest","calculator":"StockFundFactorCalculator"}'::jsonb
    ),
    (
        'main_net_inflow_3d',
        '近 3 日主力净流入',
        'fund_flow',
        'daily',
        't_stock_factor_daily.features',
        '近 3 个可用交易日 main_net_inflow 求和；历史不足时照常计算并在 features.fund_factor_missing_windows 标记。',
        TRUE,
        '{"source":"daily_market_close_ingest","calculator":"StockFundFactorCalculator"}'::jsonb
    ),
    (
        'main_net_inflow_5d',
        '近 5 日主力净流入',
        'fund_flow',
        'daily',
        't_stock_factor_daily.features',
        '近 5 个可用交易日 main_net_inflow 求和；历史不足时照常计算并在 features.fund_factor_missing_windows 标记。',
        TRUE,
        '{"source":"daily_market_close_ingest","calculator":"StockFundFactorCalculator"}'::jsonb
    ),
    (
        'main_net_inflow_10d',
        '近 10 日主力净流入',
        'fund_flow',
        'daily',
        't_stock_factor_daily.features',
        '近 10 个可用交易日 main_net_inflow 求和；历史不足时照常计算并在 features.fund_factor_missing_windows 标记。',
        TRUE,
        '{"source":"daily_market_close_ingest","calculator":"StockFundFactorCalculator"}'::jsonb
    ),
    (
        'fund_strength_percentile',
        '当日资金强度横截面分位',
        'fund_flow',
        'daily',
        't_stock_factor_daily.features',
        '同一交易日全市场 main_net_inflow 横截面分位，范围 0-100。',
        TRUE,
        '{"source":"daily_market_close_ingest","calculator":"StockFundFactorCalculator","scope":"cross_section"}'::jsonb
    ),
    (
        'sector_net_inflow_3d',
        '板块近 3 日净流入',
        'sector_fund_flow',
        'daily',
        't_sector_factor_daily',
        '近 3 个可用交易日 t_sector_fund_flow_daily.main_net_inflow 求和。',
        TRUE,
        '{"source":"daily_market_close_ingest","calculator":"SectorFactorCalculator"}'::jsonb
    ),
    (
        'sector_net_inflow_5d',
        '板块近 5 日净流入',
        'sector_fund_flow',
        'daily',
        't_sector_factor_daily',
        '近 5 个可用交易日 t_sector_fund_flow_daily.main_net_inflow 求和。',
        TRUE,
        '{"source":"daily_market_close_ingest","calculator":"SectorFactorCalculator"}'::jsonb
    ),
    (
        'sector_net_inflow_10d',
        '板块近 10 日净流入',
        'sector_fund_flow',
        'daily',
        't_sector_factor_daily',
        '近 10 个可用交易日 t_sector_fund_flow_daily.main_net_inflow 求和。',
        TRUE,
        '{"source":"daily_market_close_ingest","calculator":"SectorFactorCalculator"}'::jsonb
    ),
    (
        'sector_continuous_inflow_days',
        '板块连续净流入天数',
        'sector_fund_flow',
        'daily',
        't_sector_factor_daily',
        '从当前交易日向前统计板块 main_net_inflow > 0 的连续可用交易日数量。',
        TRUE,
        '{"source":"daily_market_close_ingest","calculator":"SectorFactorCalculator"}'::jsonb
    ),
    (
        'sector_rising_stock_count',
        '板块上涨成分数',
        'sector_component',
        'daily',
        't_sector_factor_daily',
        '按当前有效成分股聚合 t_daily_bar.change_pct > 0 的股票数量。',
        TRUE,
        '{"source":"daily_market_close_ingest","calculator":"SectorFactorCalculator"}'::jsonb
    ),
    (
        'sector_limit_up_stock_count',
        '板块涨停成分数',
        'sector_component',
        'daily',
        't_sector_factor_daily',
        '按当前有效成分股聚合 t_limit_event_daily.event_type = limit_up 的股票数量。',
        TRUE,
        '{"source":"daily_market_close_ingest","calculator":"SectorFactorCalculator"}'::jsonb
    ),
    (
        'sector_average_change_pct',
        '板块成分平均涨跌幅',
        'sector_component',
        'daily',
        't_sector_factor_daily',
        '按当前有效成分股聚合 t_daily_bar.change_pct 的算术平均值。',
        TRUE,
        '{"source":"daily_market_close_ingest","calculator":"SectorFactorCalculator"}'::jsonb
    ),
    (
        'sector_volatility_20d',
        '板块 20 日波动率',
        'sector_market',
        'daily',
        't_sector_factor_daily',
        '最近 20 个可用交易日 t_sector_bar.change_pct 总体标准差。',
        TRUE,
        '{"source":"daily_market_close_ingest","calculator":"SectorFactorCalculator"}'::jsonb
    ),
    (
        'sector_net_inflow_stock_ratio',
        '板块净流入成分占比',
        'sector_fund_flow',
        'daily',
        't_sector_factor_daily.features',
        '当前有效成分中 main_net_inflow > 0 的股票数量 / 有资金流成分数量 * 100。',
        TRUE,
        '{"source":"daily_market_close_ingest","calculator":"SectorFactorCalculator"}'::jsonb
    ),
    (
        'sector_volume_anomaly_ratio',
        '板块放量异动比',
        'sector_market',
        'daily',
        't_sector_factor_daily.features',
        '当日板块成交额 / 前 5 个可用交易日板块成交额均值。',
        TRUE,
        '{"source":"daily_market_close_ingest","calculator":"SectorFactorCalculator"}'::jsonb
    ),
    (
        'sector_tags',
        '板块异动标签',
        'sector_signal',
        'daily',
        't_sector_factor_daily.tags',
        '基于板块放量、强度、连续流入和逆势流入生成：放量异动、强度异动、持续流入、逆势异动。',
        TRUE,
        '{"source":"daily_market_close_ingest","calculator":"SectorFactorCalculator"}'::jsonb
    )
ON CONFLICT (factor_code) DO UPDATE SET
    factor_name = EXCLUDED.factor_name,
    factor_group = EXCLUDED.factor_group,
    frequency = EXCLUDED.frequency,
    source_table = EXCLUDED.source_table,
    compute_method = EXCLUDED.compute_method,
    is_rebuildable = EXCLUDED.is_rebuildable,
    metadata = t_factor_definition.metadata || EXCLUDED.metadata,
    updated_at = now();

COMMIT;
