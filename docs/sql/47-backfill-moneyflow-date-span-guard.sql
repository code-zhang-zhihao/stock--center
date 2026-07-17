-- Add date chunking metadata for historical stock moneyflow backfill.
-- Safe to re-run. It only updates scheduler metadata and does not modify fact tables or run history.

UPDATE t_scheduler_job
SET
    description = '按股票池循环调用 Tushare moneyflow 接口，安全补齐 t_stock_fund_flow_daily 历史个股资金流；金额统一按元入库，不触发策略。全市场历史资金流数据量较大，长区间会按日期分片执行，降低单块写入压力。',
    parameter_schema = COALESCE(parameter_schema, '{}'::jsonb)
        || jsonb_build_object(
            'max_date_span_days',
            jsonb_build_object(
                'label', '日期分片天数',
                'type', 'number',
                'default', 370,
                'required', false,
                'min', 1,
                'max', 3660,
                'description', '资金流全市场历史回填数据量较大；总区间可超过该值，任务会按此天数自动切片依次执行。'
            )
        ),
    default_payload = COALESCE(default_payload, '{}'::jsonb)
        || jsonb_build_object('max_date_span_days', 370),
    metadata = COALESCE(metadata, '{}'::jsonb)
        || jsonb_build_object(
            'source', '47-backfill-moneyflow-date-span-guard.sql',
            'moneyflow_date_chunking', true,
            'recommended_chunking', '默认按约一年分片执行全市场历史资金流回填'
        ),
    updated_at = now()
WHERE job_code = 'backfill_stock_moneyflow';

COMMENT ON TABLE t_scheduler_job IS 'Scheduler job definitions. Historical stock moneyflow backfill uses date chunking to avoid oversized all-market runs.';
