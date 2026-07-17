-- Refresh stock fund-flow factor fields after moneyflow unit normalization.
-- Safe to re-run. It only rewrites fund-flow fields inside t_stock_factor_daily.features.

BEGIN;

UPDATE t_stock_factor_daily factor
SET features = COALESCE(factor.features, '{}'::jsonb)
    || jsonb_build_object(
        'fund_flow_available', true,
        'main_net_inflow', flow.main_net_inflow,
        'main_net_ratio', CASE
            WHEN daily.amount_yuan IS NULL OR daily.amount_yuan = 0 OR flow.main_net_inflow IS NULL THEN NULL
            ELSE flow.main_net_inflow / daily.amount_yuan
        END,
        'big_order_net_inflow', flow.big_order_net_inflow,
        'big_order_net_ratio', CASE
            WHEN daily.amount_yuan IS NULL OR daily.amount_yuan = 0 OR flow.big_order_net_inflow IS NULL THEN NULL
            ELSE flow.big_order_net_inflow / daily.amount_yuan
        END,
        'super_large_net_inflow', flow.super_large_net_inflow,
        'super_large_net_ratio', CASE
            WHEN daily.amount_yuan IS NULL OR daily.amount_yuan = 0 OR flow.super_large_net_inflow IS NULL THEN NULL
            ELSE flow.super_large_net_inflow / daily.amount_yuan
        END,
        'fund_factor_unit_refreshed', true,
        'fund_factor_unit_refresh_sql', '33-refresh-stock-fund-factor-ratios.sql'
    )
FROM t_stock_fund_flow_daily flow
JOIN t_daily_bar daily
  ON daily.stock_code = flow.stock_code
 AND daily.trade_date = flow.trade_date
WHERE factor.stock_code = flow.stock_code
  AND factor.trade_date = flow.trade_date
  AND flow.source = 'tushare:moneyflow'
  AND flow.metadata->>'unit_normalized' = 'yuan';

COMMIT;
