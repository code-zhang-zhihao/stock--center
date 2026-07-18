-- 修正历史板块日频事实回填的调度参数：板块日 K 逐板块完整区间请求，资金流使用已验证的 20 交易日窗口。
-- Safe to re-run. This migration updates scheduler metadata only.

BEGIN;

UPDATE t_scheduler_job
SET description = '逐板块完整日期区间回填 Tushare ths_daily，概念/行业资金流按已验证的 20 交易日窗口批量查询。',
    parameter_schema = '{"start_date":{"label":"开始日期","type":"string","default":"2024-01-01","required":true},"end_date":{"label":"结束日期","type":"string","required":false},"ingest_mode":{"label":"入库模式","type":"string","default":"append_safe","required":false,"options":["append_safe","rebuild"]},"max_sectors":{"label":"板块数量上限","type":"number","required":false,"min":1},"workers":{"label":"板块日 K worker 数","type":"number","default":12,"required":false,"min":1,"max":20},"moneyflow_workers":{"label":"资金流窗口 worker 数","type":"number","default":2,"required":false,"min":1,"max":4},"moneyflow_window_trade_days":{"label":"资金流区间交易日数","type":"number","default":20,"required":false,"min":1,"max":20},"fail_fast":{"label":"遇错立即失败","type":"boolean","default":false,"required":false}}'::jsonb,
    default_payload = '{"start_date":"2024-01-01","end_date":null,"ingest_mode":"append_safe","max_sectors":null,"workers":12,"moneyflow_workers":2,"moneyflow_window_trade_days":20,"fail_fast":false}'::jsonb,
    metadata = COALESCE(metadata, '{}'::jsonb) || '{"source":"56-sector-history-range-backfill.sql","sector_bar_request_mode":"sector_date_range","moneyflow_range_verified_trade_days":20}'::jsonb,
    updated_at = now()
WHERE job_code = 'backfill_sector_daily_facts';

COMMIT;
