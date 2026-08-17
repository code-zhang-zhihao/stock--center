-- Bound historical sector-factor calculation by trade-date windows.
-- Run after 79 cut-over and before the historical sector-factor backfill.
-- This script only updates scheduler metadata; it does not modify factor rows.

\set ON_ERROR_STOP on

BEGIN;

UPDATE t_scheduler_job
SET description = '按真实板块行情交易日、20 日窗口集合计算板块趋势、资金、成分广度、事件和前 5 龙头；窗口独立提交并支持进度续跑。',
    parameter_schema = (coalesce(parameter_schema, '{}'::jsonb) - 'batch_size' - 'only_missing' - 'calculation_workers')
        || jsonb_build_object(
            'only_missing', jsonb_build_object(
                'label', '只补缺失日期（兼容）',
                'type', 'boolean',
                'default', false,
                'required', false,
                'description', '保留用于兼容旧运行记录；板块窗口会幂等刷新目标日期，以补齐部分字段并重建受限龙头。'
            ),
            'factor_window_trade_days', jsonb_build_object(
                'label', '回填时间窗口（交易日）',
                'type', 'number',
                'default', 20,
                'required', false,
                'min', 5,
                'max', 60,
                'description', '每个窗口一次性组装板块趋势、资金、成分广度、事件和龙头；默认 20。'
            ),
            'calculation_workers', jsonb_build_object(
                'label', '窗口计算 worker 数',
                'type', 'number',
                'default', 2,
                'required', false,
                'min', 1,
                'max', 4,
                'description', '并行处理互不重叠的日期窗口；运行时最高使用 2，避免大表聚合互相争用。'
            )
        ),
    default_payload = (coalesce(default_payload, '{}'::jsonb) - 'batch_size')
        || jsonb_build_object(
            'start_date', '2024-01-01',
            'end_date', null,
            'ingest_mode', 'append_safe',
            'only_missing', false,
            'factor_window_trade_days', 20,
            'calculation_workers', 2,
            'fail_fast', false
        ),
    updated_at = now()
WHERE job_code = 'backfill_sector_daily_factors';

COMMIT;

SELECT job_code, default_payload, parameter_schema
FROM t_scheduler_job
WHERE job_code = 'backfill_sector_daily_factors';
