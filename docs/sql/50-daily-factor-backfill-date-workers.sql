-- stock-center 历史个股日频因子回填交易日并发参数
-- Safe to re-run. It only updates scheduler job metadata.

UPDATE t_scheduler_job
SET
    description = '按股票池和交易日区间读取 canonical 日线、资金流和专业技术因子，受控并发重算 t_stock_factor_daily；不调用外部 Provider。',
    parameter_schema = COALESCE(parameter_schema, '{}'::jsonb)
        || jsonb_build_object(
            'factor_date_workers',
            jsonb_build_object(
                'label', '交易日并发数',
                'type', 'number',
                'default', 2,
                'required', false,
                'min', 1,
                'max', 8,
                'description', '并发计算多少个交易日；每个 worker 使用独立数据库 session，仍按 batch_size 分批计算股票。'
            )
        ),
    default_payload = COALESCE(default_payload, '{}'::jsonb)
        || jsonb_build_object('factor_date_workers', 2),
    metadata = COALESCE(metadata, '{}'::jsonb)
        || jsonb_build_object(
            'source', '50-daily-factor-backfill-date-workers.sql',
            'date_level_concurrency', true,
            'default_factor_date_workers', 2
        ),
    updated_at = now()
WHERE job_code = 'backfill_daily_factors';
