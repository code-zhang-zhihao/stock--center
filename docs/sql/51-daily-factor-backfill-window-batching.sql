-- stock-center 历史个股日频因子回填窗口批处理参数
-- Safe to re-run. It only updates scheduler job metadata.

UPDATE t_scheduler_job
SET
    description = '按股票池和交易日区间批量读取 canonical 日线、资金流和专业技术因子，按连续交易日窗口重算 t_stock_factor_daily；不调用外部 Provider。',
    parameter_schema = (COALESCE(parameter_schema, '{}'::jsonb) - 'factor_date_workers')
        || jsonb_build_object(
            'factor_window_trade_days',
            jsonb_build_object(
                'label', '回填时间窗口（交易日）',
                'type', 'number',
                'default', 20,
                'required', false,
                'min', 5,
                'max', 60,
                'description', '一次读取多少个连续交易日的重叠日线、资金流与专业技术因子；窗口内复用历史数据，避免按日重复扫描。'
            ),
            'factor_window_workers',
            jsonb_build_object(
                'label', '时间窗口并发数',
                'type', 'number',
                'default', 1,
                'required', false,
                'min', 1,
                'max', 2,
                'description', '同时处理多少个时间窗口。云端 PostgreSQL 默认建议 1；数据库吞吐稳定时可设为 2。'
            )
        ),
    default_payload = (COALESCE(default_payload, '{}'::jsonb) - 'factor_date_workers')
        || jsonb_build_object(
            'factor_window_trade_days', 20,
            'factor_window_workers', 1
        ),
    metadata = ((COALESCE(metadata, '{}'::jsonb) - 'date_level_concurrency') - 'default_factor_date_workers')
        || jsonb_build_object(
            'source', '51-daily-factor-backfill-window-batching.sql',
            'window_batching', true,
            'default_factor_window_trade_days', 20,
            'default_factor_window_workers', 1
        ),
    updated_at = now()
WHERE job_code = 'backfill_daily_factors';
