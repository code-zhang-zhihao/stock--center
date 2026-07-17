-- Use row-level write batching for historical stock moneyflow backfill.
-- Safe to re-run. It only updates scheduler metadata and does not modify fact tables or run history.

UPDATE t_scheduler_job
SET
    description = '按股票池循环调用 Tushare moneyflow 接口，安全补齐 t_stock_fund_flow_daily 历史个股资金流；金额统一按元入库，不触发策略。Tushare 仍按单股完整日期区间请求，数据库写入按行数分批提交。',
    parameter_schema = (COALESCE(parameter_schema, '{}'::jsonb) - 'max_date_span_days')
        || jsonb_build_object(
            'max_upsert_rows_per_commit',
            jsonb_build_object(
                'label', '单次提交最大行数',
                'type', 'number',
                'default', 5000,
                'required', false,
                'min', 100,
                'max', 50000,
                'description', '只限制每次数据库事务最多提交多少行；Tushare 仍按单股完整 start_date/end_date 区间请求。'
            )
        ),
    default_payload = (COALESCE(default_payload, '{}'::jsonb) - 'max_date_span_days')
        || jsonb_build_object('max_upsert_rows_per_commit', 5000),
    metadata = COALESCE(metadata, '{}'::jsonb)
        || jsonb_build_object(
            'source', '48-backfill-moneyflow-row-batch.sql',
            'moneyflow_row_batching', true,
            'moneyflow_date_chunking', false
        ),
    updated_at = now()
WHERE job_code = 'backfill_stock_moneyflow';

COMMENT ON TABLE t_scheduler_job IS 'Scheduler job definitions. Historical stock moneyflow backfill requests full per-stock date ranges and batches database writes by row count.';
