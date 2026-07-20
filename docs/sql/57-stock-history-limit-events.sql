-- 将涨跌停/停牌事件纳入历史个股日频事实流水线；按交易日调用全市场接口，避免逐股票放大请求。
-- Safe to re-run. Existing Tushare Z-pool events and null-flag U-pool events are normalized.

BEGIN;

DELETE FROM t_limit_event_daily AS legacy
USING t_limit_event_daily AS canonical
WHERE legacy.stock_code = canonical.stock_code
  AND legacy.trade_date = canonical.trade_date
  AND legacy.event_type = 'limit_event'
  AND canonical.event_type = 'limit_break'
  AND upper(COALESCE(legacy.metadata #>> '{raw,limit}', legacy.metadata #>> '{raw,limit_type}', '')) = 'Z';

UPDATE t_limit_event_daily
SET event_type = 'limit_break'
WHERE event_type = 'limit_event'
  AND upper(COALESCE(metadata #>> '{raw,limit}', metadata #>> '{raw,limit_type}', '')) = 'Z';

DELETE FROM t_limit_event_daily AS legacy
USING t_limit_event_daily AS canonical
WHERE legacy.stock_code = canonical.stock_code
  AND legacy.trade_date = canonical.trade_date
  AND legacy.event_type = 'limit_event'
  AND canonical.event_type = 'limit_up'
  AND legacy.source = 'tushare:limit_list_d'
  AND COALESCE(legacy.metadata #>> '{raw,limit}', legacy.metadata #>> '{raw,limit_type}', '') = ''
  AND COALESCE(legacy.metadata #>> '{raw,up_stat}', '') <> '';

UPDATE t_limit_event_daily
SET event_type = 'limit_up'
WHERE event_type = 'limit_event'
  AND source = 'tushare:limit_list_d'
  AND COALESCE(metadata #>> '{raw,limit}', metadata #>> '{raw,limit_type}', '') = ''
  AND COALESCE(metadata #>> '{raw,up_stat}', '') <> '';

UPDATE t_scheduler_job
SET description = '依次按股票池逐股区间调用 Tushare daily、daily_basic、moneyflow、stk_factor_pro，并按交易日调用 limit_list_d、suspend_d；不拉历史分钟线。',
    parameter_schema = parameter_schema || jsonb_build_object(
        'include_limit_events', jsonb_build_object(
            'label', '回填涨跌停与停牌事件',
            'type', 'boolean',
            'default', TRUE,
            'required', FALSE,
            'description', '开启后按交易日调用 limit_list_d 和 suspend_d，写入 t_limit_event_daily。'
        ),
        'event_workers', jsonb_build_object(
            'label', '事件交易日 worker 数',
            'type', 'number',
            'default', 4,
            'required', FALSE,
            'min', 1,
            'max', 8,
            'description', '涨跌停/停牌事件按交易日查询的并发数；每个交易日各请求两个全市场接口。'
        )
    ),
    default_payload = default_payload || '{"include_limit_events":true,"event_workers":4}'::jsonb,
    metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object(
        'source', '57-stock-history-limit-events.sql',
        'pipeline_version', 3,
        'limit_event_request_mode', 'trade_date_market_wide',
        'limit_event_completion_marker', 't_provider_raw_record'
    ),
    updated_at = now()
WHERE job_code = 'backfill_stock_daily_facts';

COMMIT;
