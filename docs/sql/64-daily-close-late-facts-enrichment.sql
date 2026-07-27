-- Move late-published limit events and sector daily bars to the 21:30 stage.
-- Safe to re-run. It changes scheduler definitions only; no market facts are deleted.

BEGIN;

UPDATE t_scheduler_job
SET
    description = '18:00 并行沉淀个股日线、daily_basic、资金流和核心指数；使用 PostgreSQL 集合计算日频基础因子和技术快照。涨跌停/炸板与板块日线延后至 21:30 增强阶段。',
    default_payload = jsonb_set(
        jsonb_set(COALESCE(default_payload, '{}'::jsonb), '{sync_stock_limit_status}', 'false'::jsonb, true),
        '{sync_sector_bars}',
        'false'::jsonb,
        true
    ),
    metadata = COALESCE(metadata, '{}'::jsonb)
        || '{"stage":"core","pipeline_version":5,"late_facts_moved_to_enrichment":true,"source":"64-daily-close-late-facts-enrichment.sql"}'::jsonb,
    updated_at = now()
WHERE job_code = 'daily_close_core_ingest';

UPDATE t_scheduler_job
SET
    description = '21:30 并行沉淀涨跌停/炸板与停复牌、板块日线、专业技术因子、龙虎榜、指数每日指标、市场统计和板块资金流；daily_info 未发布时记为 deferred。',
    default_payload = jsonb_set(
        jsonb_set(COALESCE(default_payload, '{}'::jsonb), '{sync_stock_limit_status}', 'true'::jsonb, true),
        '{sync_sector_bars}',
        'true'::jsonb,
        true
    ),
    metadata = COALESCE(metadata, '{}'::jsonb)
        || '{"stage":"enrichment","pipeline_version":5,"late_fact_blocks":["stock_limit_status","sector_bars"],"sector_bar_batch_size":500,"source":"64-daily-close-late-facts-enrichment.sql"}'::jsonb,
    updated_at = now()
WHERE job_code = 'daily_close_enrichment_ingest';

COMMIT;
