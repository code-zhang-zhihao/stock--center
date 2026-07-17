-- Normalize historical Tushare stock moneyflow rows to yuan.
-- Safe to re-run. It skips rows that already carry adapter normalization metadata.

BEGIN;

WITH legacy_rows AS (
    SELECT id
    FROM t_stock_fund_flow_daily
    WHERE source = 'tushare:moneyflow'
      AND COALESCE(metadata->>'unit_normalized', '') <> 'yuan'
      AND COALESCE(metadata#>>'{unit_conversions,moneyflow.*_amount}', '') <> 'ten_thousand_yuan -> yuan'
)
UPDATE t_stock_fund_flow_daily target
SET
    main_net_inflow = target.main_net_inflow * 10000,
    big_order_net_inflow = target.big_order_net_inflow * 10000,
    super_large_net_inflow = target.super_large_net_inflow * 10000,
    medium_net_inflow = target.medium_net_inflow * 10000,
    small_net_inflow = target.small_net_inflow * 10000,
    small_buy_amount = target.small_buy_amount * 10000,
    small_sell_amount = target.small_sell_amount * 10000,
    medium_buy_amount = target.medium_buy_amount * 10000,
    medium_sell_amount = target.medium_sell_amount * 10000,
    large_buy_amount = target.large_buy_amount * 10000,
    large_sell_amount = target.large_sell_amount * 10000,
    super_large_buy_amount = target.super_large_buy_amount * 10000,
    super_large_sell_amount = target.super_large_sell_amount * 10000,
    metadata = COALESCE(target.metadata, '{}'::jsonb)
        || '{
            "unit_normalized": "yuan",
            "migrated_from_unit": "ten_thousand_yuan",
            "unit_migration_sql": "32-normalize-stock-moneyflow-yuan.sql"
        }'::jsonb,
    updated_at = now()
FROM legacy_rows
WHERE target.id = legacy_rows.id;

UPDATE t_stock_fund_flow_daily
SET
    metadata = COALESCE(metadata, '{}'::jsonb)
        || '{
            "unit_normalized": "yuan",
            "source_unit": "ten_thousand_yuan",
            "unit_migration_sql": "32-normalize-stock-moneyflow-yuan.sql"
        }'::jsonb,
    updated_at = now()
WHERE source = 'tushare:moneyflow'
  AND COALESCE(metadata->>'unit_normalized', '') <> 'yuan'
  AND COALESCE(metadata#>>'{unit_conversions,moneyflow.*_amount}', '') = 'ten_thousand_yuan -> yuan';

COMMIT;
