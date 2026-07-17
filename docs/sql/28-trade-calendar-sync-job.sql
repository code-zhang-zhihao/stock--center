-- Seed trade calendar sync job.
-- The handler follows the legacy stock-analysis rule:
-- is_open = weekday and chinese_calendar.is_workday(date).
-- Safe to re-run. It only creates/updates the scheduler job definition.

INSERT INTO t_scheduler_job (
    job_code,
    job_name,
    job_type,
    description,
    parameter_schema,
    trigger_type,
    cron_expr,
    timezone,
    default_payload,
    max_instances,
    misfire_grace_seconds,
    timeout_seconds,
    retry_count,
    retry_interval_seconds,
    is_enabled,
    is_system,
    is_hidden,
    metadata
)
VALUES (
    'sync_trade_calendar',
    '同步交易日历',
    'market_data',
    '按旧项目 chinese_calendar 规则生成并同步 CN 交易日历；为空年份默认同步当前年份。',
    '{
      "year":{"label":"同步年份","type":"number","required":false,"description":"生成并同步哪一年的 CN 交易日历；为空时使用当前年份。","min":1990,"max":2100},
      "market":{"label":"市场","type":"string","default":"CN","required":false,"options":["CN"],"description":"当前 A 股流程固定使用 CN。"},
      "mode":{"label":"写入模式","type":"string","default":"upsert","required":false,"options":["upsert","rebuild"],"description":"upsert 会增量覆盖同年日期；rebuild 会先删除该年再重建。"},
      "source":{"label":"来源","type":"string","default":"chinese_calendar","required":false,"description":"沿用旧项目逻辑：周一到周五且 chinese_calendar 判断为中国法定工作日即开市。"}
    }'::jsonb,
    'cron',
    '0 7 1 1 *',
    'Asia/Shanghai',
    '{"year":null,"market":"CN","mode":"upsert","source":"chinese_calendar"}'::jsonb,
    1,
    1800,
    600,
    0,
    300,
    false,
    false,
    false,
    '{"source":"stock-center-bootstrap","migrated_from":"stock-analysis","phase":"market_data_master_data","calendar_rule":"weekday_and_chinese_calendar_workday"}'::jsonb
)
ON CONFLICT (job_code) DO UPDATE SET
    job_name = EXCLUDED.job_name,
    job_type = EXCLUDED.job_type,
    description = EXCLUDED.description,
    parameter_schema = EXCLUDED.parameter_schema,
    trigger_type = EXCLUDED.trigger_type,
    cron_expr = EXCLUDED.cron_expr,
    timezone = EXCLUDED.timezone,
    default_payload = EXCLUDED.default_payload,
    max_instances = EXCLUDED.max_instances,
    misfire_grace_seconds = EXCLUDED.misfire_grace_seconds,
    timeout_seconds = EXCLUDED.timeout_seconds,
    retry_count = EXCLUDED.retry_count,
    retry_interval_seconds = EXCLUDED.retry_interval_seconds,
    is_hidden = EXCLUDED.is_hidden,
    metadata = EXCLUDED.metadata,
    updated_at = now();
