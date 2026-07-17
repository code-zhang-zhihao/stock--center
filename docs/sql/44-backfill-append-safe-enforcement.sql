-- Enforce append_safe defaults for historical stock fact backfill jobs.
-- Safe to re-run. It only updates scheduler metadata and does not modify fact tables or run history.

UPDATE t_scheduler_job
SET
    parameter_schema = COALESCE(parameter_schema, '{}'::jsonb)
        || jsonb_build_object(
            'ingest_mode',
            jsonb_build_object(
                'label', '入库模式',
                'type', 'string',
                'default', 'append_safe',
                'required', false,
                'options', jsonb_build_array('append_safe', 'rebuild'),
                'description', 'append_safe 幂等补缺，不重复入库；rebuild 会先删除目标股票池和日期范围内的本类数据再重建。'
            ),
            'only_missing',
            jsonb_build_object(
                'label', '只补缺失',
                'type', 'boolean',
                'default', true,
                'required', false,
                'description', 'append_safe 模式下为 true 表示只补缺失交易日；rebuild 模式会忽略它。'
            )
        ),
    default_payload = COALESCE(default_payload, '{}'::jsonb)
        || jsonb_build_object('ingest_mode', 'append_safe', 'only_missing', true),
    metadata = COALESCE(metadata, '{}'::jsonb)
        || jsonb_build_object('source', '44-backfill-append-safe-enforcement.sql', 'append_safe_enforced', true),
    updated_at = now()
WHERE job_code IN (
    'backfill_stock_daily_bars',
    'backfill_stock_daily_basic',
    'backfill_stock_moneyflow'
);

COMMENT ON TABLE t_scheduler_job IS 'Scheduler job definitions. Historical stock fact backfill jobs default to append_safe to avoid duplicate canonical facts.';
