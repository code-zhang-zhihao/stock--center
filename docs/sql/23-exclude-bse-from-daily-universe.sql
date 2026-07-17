-- 将北交所股票排除出当前日常量化 universe。
-- 只调整股票主数据状态和股票池成员关系，不删除历史行情/资金流/因子事实。

BEGIN;

UPDATE t_stock
SET
    status = 'excluded',
    metadata = coalesce(metadata, '{}'::jsonb) || jsonb_build_object(
        'excluded_from_daily_universe', true,
        'excluded_reason', 'BSE/BJ is out of current stock-center A-share quant universe',
        'excluded_at', now()
    ),
    updated_at = now()
WHERE status = 'active'
  AND (
    upper(coalesce(exchange, '')) IN ('BJ', 'BSE')
    OR stock_code LIKE '8%'
    OR stock_code LIKE '920%'
  );

DELETE FROM t_stock_pool_member member
USING t_stock stock
WHERE member.stock_code = stock.stock_code
  AND stock.status = 'excluded'
  AND (
    upper(coalesce(stock.exchange, '')) IN ('BJ', 'BSE')
    OR stock.stock_code LIKE '8%'
    OR stock.stock_code LIKE '920%'
  );

COMMIT;
