BEGIN;

UPDATE t_scheduler_job
SET description = '从 2021-01-01 开始按交易日窗口、股票分片并发组装 QFQ 标准因子；额外读取约 250 个交易日预热数据。技术快照由 API 动态生成，不再落库。',
    default_payload = COALESCE(default_payload, '{}'::jsonb)
        || '{"calculation_workers":2}'::jsonb,
    parameter_schema = COALESCE(parameter_schema, '{}'::jsonb)
        || jsonb_build_object(
            'calculation_workers',
            jsonb_build_object(
                'label', '数据库计算 worker 数',
                'type', 'number',
                'default', 2,
                'required', false,
                'min', 1,
                'max', 4,
                'description', '同一日期窗口并行计算的股票分片数；每个 worker 使用独立数据库会话，默认 2。'
            )
        ),
    metadata = COALESCE(metadata, '{}'::jsonb)
        || '{"v2_window_backfill":true,"fund_percentile_refresh":"once_per_window"}'::jsonb,
    updated_at = now()
WHERE job_code = 'backfill_stock_daily_factors';

COMMIT;
