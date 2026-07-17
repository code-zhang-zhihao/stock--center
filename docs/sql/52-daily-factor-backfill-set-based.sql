-- stock-center 历史个股日频因子回填改为 PostgreSQL 集合计算。
-- Safe to re-run. It only updates scheduler job metadata.
-- The runtime calculates one continuous trade-date window with INSERT .. SELECT;
-- it no longer has Python-side factor calculation or application-level window workers.
-- PostgreSQL work is deliberately split into bounded stock chunks at runtime.

UPDATE t_scheduler_job
SET
    description = '按股票池和交易日区间在 PostgreSQL 内批量计算 canonical 日线、资金流和专业技术因子，写入 t_stock_factor_daily；不调用外部 Provider。',
    parameter_schema = ((COALESCE(parameter_schema, '{}'::jsonb) - 'batch_size') - 'factor_window_workers')
        || jsonb_build_object(
            'factor_window_trade_days',
            jsonb_build_object(
                'label', '回填时间窗口（交易日）',
                'type', 'number',
                'default', 20,
                'required', false,
                'min', 5,
                'max', 60,
                'description', '每个窗口由 PostgreSQL 一次性计算并入库。窗口越大，单次数据库负载越高；默认 20 个交易日适合云端 PostgreSQL。'
            ),
            'sql_stock_chunk_size',
            jsonb_build_object(
                'label', '数据库分片股票数',
                'type', 'number',
                'default', 200,
                'required', false,
                'min', 50,
                'max', 500,
                'description', '每个 PostgreSQL 集合计算分片包含的股票数。默认 200，避免单条全市场 SQL 占用过多云端数据库内存；每个分片独立提交，append_safe 可安全续跑。'
            )
        ),
    default_payload = ((COALESCE(default_payload, '{}'::jsonb) - 'batch_size') - 'factor_window_workers')
        || jsonb_build_object('factor_window_trade_days', 20, 'sql_stock_chunk_size', 200),
    metadata = ((COALESCE(metadata, '{}'::jsonb) - 'default_factor_window_workers') - 'window_batching')
        || jsonb_build_object(
            'source', '52-daily-factor-backfill-set-based.sql',
            'compute_mode', 'postgres_set_based',
            'default_factor_window_trade_days', 20
        ),
    updated_at = now()
WHERE job_code = 'backfill_daily_factors';
