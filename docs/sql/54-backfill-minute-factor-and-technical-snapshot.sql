-- 历史分钟因子与技术快照回填任务说明更新
-- Safe to re-run. It changes scheduler metadata only; no market fact row is changed.

UPDATE t_scheduler_job
SET
    job_name = '历史分钟因子与技术快照回填',
    description = '按股票池和交易日区间读取 canonical 日线、分钟线与因子表，重算 t_stock_factor_minute 和 t_technical_indicator_snapshot；不调用外部 Provider。append_safe 只补缺失快照；rebuild 会先删除目标范围旧分钟因子和技术快照再重算，适用于因子公式升级。',
    parameter_schema = jsonb_set(
        parameter_schema,
        '{pool_code,description}',
        to_jsonb('指定需要重算分钟因子技术快照的股票池；all_a_share 表示沪深 active 动态全市场。'::text),
        true
    ),
    metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object(
        'source', '54-backfill-minute-factor-and-technical-snapshot.sql',
        'factor_kind', 'minute_factor_and_technical_snapshot',
        'formula_rebuild_supported', true
    ),
    updated_at = now()
WHERE job_code = 'backfill_technical_snapshots';
