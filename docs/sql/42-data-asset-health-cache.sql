-- 数据中心健康度 Redis 缓存调度任务
-- 缓存数据写入 Redis，不在 PostgreSQL 创建缓存表。

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
    'refresh_data_asset_health',
    '刷新数据中心健康度缓存',
    'data_assets',
    '定时刷新数据中心 summary 与 daily-health 冷频巡检 Redis 缓存，页面默认读缓存，避免打开页面时扫描大表。',
    '{
      "days": {
        "label": "完整性交易日数",
        "type": "number",
        "default": 3,
        "required": false,
        "min": 1,
        "max": 15,
        "description": "刷新最近多少个交易日的数据完整性矩阵。默认 3 天，避免巡检扫大表过慢。"
      }
    }'::jsonb,
    'cron',
    '*/30 * * * *',
    'Asia/Shanghai',
    '{"days":3}'::jsonb,
    1,
    300,
    300,
    1,
    60,
    true,
    true,
    false,
    '{"source":"stock-center-bootstrap","phase":"data_assets","cache_backend":"redis","cache_keys":["summary","daily_health"]}'::jsonb
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
    is_enabled = EXCLUDED.is_enabled,
    is_hidden = EXCLUDED.is_hidden,
    metadata = EXCLUDED.metadata,
    updated_at = now();
