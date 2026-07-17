-- Normalize t_stock status for weekly stock basic sync.
-- BSE/BJ stocks are kept as master-data rows but excluded from stock-center
-- active universe, stock pools, daily close ingestion, and detail enrichment.
-- Safe to re-run. Historical market facts are not deleted.

BEGIN;

UPDATE t_stock
SET
    status = 'excluded',
    metadata = coalesce(metadata, '{}'::jsonb) || jsonb_build_object(
        'excluded_from_daily_universe', true,
        'excluded_reason', 'BSE/BJ excluded from stock-center universe',
        'status_normalized_by', '27-stock-basic-status-normalization.sql',
        'status_normalized_at', now()
    ),
    updated_at = now()
WHERE
    upper(coalesce(exchange, '')) IN ('BJ', 'BSE')
    OR stock_code LIKE '4%'
    OR stock_code LIKE '8%'
    OR stock_code LIKE '920%';

UPDATE t_stock
SET
    status = 'suspended',
    metadata = coalesce(metadata, '{}'::jsonb) || jsonb_build_object(
        'status_normalized_by', '27-stock-basic-status-normalization.sql',
        'status_normalized_at', now(),
        'legacy_status', 'paused'
    ),
    updated_at = now()
WHERE status = 'paused'
  AND (
      upper(coalesce(exchange, '')) IN ('SH', 'SZ', 'SSE', 'SZSE')
      OR stock_code LIKE '0%'
      OR stock_code LIKE '3%'
      OR stock_code LIKE '6%'
  );

DELETE FROM t_stock_pool_member member
USING t_stock stock
WHERE member.stock_code = stock.stock_code
  AND stock.status = 'excluded'
  AND (
      upper(coalesce(stock.exchange, '')) IN ('BJ', 'BSE')
      OR stock.stock_code LIKE '4%'
      OR stock.stock_code LIKE '8%'
      OR stock.stock_code LIKE '920%'
  );

UPDATE t_scheduler_job
SET
    description = '每周同步沪深 A 股基础资料，Tushare 为状态最高优先级来源；北交所/BJ/BSE 仅保留为 excluded 主数据，不进入股票池和每日沉淀。',
    parameter_schema = jsonb_set(
        COALESCE(parameter_schema, '{}'::jsonb),
        '{source}',
        '{"label":"主数据源","type":"string","default":"tushare","required":false,"options":["tushare","akshare","mootdx"],"description":"Tushare 为状态最高优先级来源；AkShare/MooTDX fallback 只补沪深 active 列表，不覆盖 excluded/delisted/suspended。"}'::jsonb,
        true
    ),
    metadata = COALESCE(metadata, '{}'::jsonb)
        || '{"stock_status_policy":"active/suspended/delisted for SH/SZ; excluded for BJ/BSE"}'::jsonb,
    updated_at = now()
WHERE job_code = 'sync_stock_basic';

COMMIT;
