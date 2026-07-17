-- stock-center 历史回填任务入库模式收口
-- Safe to re-run. It only updates scheduler job metadata.

UPDATE t_scheduler_job
SET
    parameter_schema = jsonb_set(
        COALESCE(parameter_schema, '{}'::jsonb)
        || '{
          "ingest_mode": {
            "label": "入库模式",
            "type": "string",
            "default": "append_safe",
            "required": false,
            "options": ["append_safe", "rebuild"],
            "description": "append_safe 幂等补缺，不重复入库；rebuild 会先删除目标范围内的本类数据再重建。"
          }
        }'::jsonb,
        '{only_missing,description}',
        '"兼容参数：append_safe 模式下为 true 表示只补缺失或跳过完整日期；rebuild 模式会忽略它。建议优先使用入库模式。"'::jsonb,
        true
    ),
    default_payload = COALESCE(default_payload, '{}'::jsonb) || '{"ingest_mode":"append_safe"}'::jsonb,
    metadata = COALESCE(metadata, '{}'::jsonb) || '{"source":"36-backfill-ingest-mode.sql","ingest_mode_supported":true}'::jsonb,
    updated_at = now()
WHERE job_code IN (
    'backfill_stock_daily_bars',
    'backfill_stock_daily_basic',
    'backfill_stock_moneyflow',
    'backfill_daily_factors',
    'backfill_sector_factors'
);
