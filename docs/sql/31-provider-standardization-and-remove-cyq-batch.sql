-- Provider standardization first batch and remove full-market cyq_perf batch ingestion.
-- Safe to re-run. This script only patches scheduler metadata and table comments.

BEGIN;

UPDATE t_scheduler_job
SET
    description = '晚间沉淀更新较晚的增强事实：专业技术因子、龙虎榜席位、市场统计、指数每日指标、板块资金流，并重算增强因子；不再批量沉淀 cyq_perf。',
    parameter_schema = (
        COALESCE(parameter_schema, '{}'::jsonb)
        - 'sync_chip_perf'
        - 'chip_universe'
        - 'chip_limit_stocks'
        - 'chip_start_date'
        - 'chip_end_date'
        - 'calculate_chip_factors'
        - 'chip_perf_workers'
        - 'chip_perf_commit_stock_batch_size'
        - 'sync_eod_quote'
        - 'quote_batch_size'
    ),
    default_payload = (
        COALESCE(default_payload, '{}'::jsonb)
        - 'sync_chip_perf'
        - 'chip_universe'
        - 'chip_limit_stocks'
        - 'chip_start_date'
        - 'chip_end_date'
        - 'calculate_chip_factors'
        - 'chip_perf_workers'
        - 'chip_perf_commit_stock_batch_size'
        - 'sync_eod_quote'
        - 'quote_batch_size'
    ) || '{
        "sync_daily": false,
        "sync_daily_basic": false,
        "sync_stock_technical_factor_pro": true,
        "sync_stock_moneyflow": false,
        "sync_stock_limit_status": false,
        "sync_lhb": true,
        "sync_index_bars": false,
        "sync_index_daily_basic": true,
        "sync_north_hold": false,
        "sync_market_stats": true,
        "sync_sector_bars": false,
        "sync_sector_moneyflow": true,
        "sync_minute": false,
        "calculate_daily_factors": true,
        "calculate_minute_factors": false,
        "calculate_technical_snapshot": false,
        "calculate_stock_fund_factors": true,
        "calculate_external_technical_factors": true,
        "calculate_sector_factors": true,
        "fail_on_enrichment_error": false,
        "enrichment_block_concurrency": 4,
        "ingest_mode": "append_safe"
    }'::jsonb,
    metadata = COALESCE(metadata, '{}'::jsonb)
        || '{"cyq_perf_batch_ingest_removed": true, "provider_standardization_batch": 1, "source": "31-provider-standardization-and-remove-cyq-batch.sql"}'::jsonb,
    updated_at = now()
WHERE job_code = 'daily_close_enrichment_ingest';

UPDATE t_scheduler_job
SET
    description = '次日滚动修复最近交易日的晚到增强数据缺口，并重算受影响因子；不再修复 cyq_perf。',
    parameter_schema = (
        COALESCE(parameter_schema, '{}'::jsonb)
        - 'sync_chip_perf'
        - 'chip_universe'
        - 'chip_limit_stocks'
        - 'chip_start_date'
        - 'chip_end_date'
        - 'calculate_chip_factors'
        - 'chip_perf_workers'
        - 'chip_perf_commit_stock_batch_size'
    ),
    default_payload = (
        COALESCE(default_payload, '{}'::jsonb)
        - 'sync_chip_perf'
        - 'chip_universe'
        - 'chip_limit_stocks'
        - 'chip_start_date'
        - 'chip_end_date'
        - 'calculate_chip_factors'
        - 'chip_perf_workers'
        - 'chip_perf_commit_stock_batch_size'
    ) || '{
        "repair_trade_days": 3,
        "enrichment_block_concurrency": 4,
        "fail_on_enrichment_error": false
    }'::jsonb,
    metadata = COALESCE(metadata, '{}'::jsonb)
        || '{"cyq_perf_batch_ingest_removed": true, "provider_standardization_batch": 1, "source": "31-provider-standardization-and-remove-cyq-batch.sql"}'::jsonb,
    updated_at = now()
WHERE job_code = 'daily_close_repair_ingest';

COMMENT ON TABLE t_stock_chip_perf_daily IS '历史/实验筹码胜率摘要表。cyq_perf 不再作为每日全市场批量沉淀入口；后续仅作为个股详情按需查询候选能力。';

COMMIT;
