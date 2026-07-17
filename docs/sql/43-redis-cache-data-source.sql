-- Redis cache data source configuration.
-- Safe to re-run. It adds the fixed market_data/redis_cache config item and non-sensitive options.
-- The actual Redis URL should be added from System Settings > Data Sources as an encrypted value_kind=redis_url.
-- TTL policy:
-- - data_asset_cache_ttl_seconds is the data-center default TTL.
-- - default_cache_ttl_seconds is the fallback for future cache families.
-- - data_asset_summary_ttl_seconds controls the data-center asset summary cache.
-- - data_asset_daily_health_ttl_seconds controls the data-center daily-health cache.

INSERT INTO t_system_config (
    category_code,
    config_code,
    config_name,
    description,
    sort_order,
    is_default,
    is_enabled,
    metadata
)
VALUES (
    'market_data',
    'redis_cache',
    'Redis Cache',
    'Optional Redis cache for data-center cold metrics and future reusable runtime caches. Redis URL is stored as encrypted redis_url value.',
    20,
    false,
    true,
    '{"source":"redis-cache-bootstrap","runtime":"app.core.redis_client"}'::jsonb
)
ON CONFLICT (category_code, config_code) DO UPDATE SET
    config_name = EXCLUDED.config_name,
    description = EXCLUDED.description,
    sort_order = EXCLUDED.sort_order,
    metadata = t_system_config.metadata || EXCLUDED.metadata,
    updated_at = now();

INSERT INTO t_config_option (
    system_config_id,
    option_key,
    option_name,
    value_type,
    option_value,
    default_value,
    is_required,
    is_enabled,
    description,
    metadata
)
SELECT
    sc.id,
    item.option_key,
    item.option_name,
    item.value_type,
    item.option_value,
    item.default_value,
    item.is_required,
    true,
    item.description,
    '{"source":"redis-cache-bootstrap"}'::jsonb
FROM t_system_config sc
CROSS JOIN (
    VALUES
      ('cache_backend', '缓存后端', 'string', '"auto"'::jsonb, '"auto"'::jsonb, true, 'auto uses Redis when a Redis URL exists and falls back to in-process memory; redis requires Redis URL; memory forces local memory cache.'),
      ('redis_key_prefix', 'Redis Key 前缀', 'string', '"stock-center"'::jsonb, '"stock-center"'::jsonb, true, 'Prefix for keys written by stock-center, for example stock-center:data-assets:summary.'),
      ('redis_socket_timeout_seconds', 'Redis 连接超时秒数', 'number', '3'::jsonb, '3'::jsonb, true, 'Socket connect/read timeout for Redis operations.'),
      ('data_asset_cache_enabled', '启用数据中心缓存', 'boolean', 'true'::jsonb, 'true'::jsonb, true, 'Whether data center summary and daily-health read/write cache.'),
      ('data_asset_cache_ttl_seconds', '数据中心缓存 TTL 秒数', 'number', '1800'::jsonb, '1800'::jsonb, true, 'Default TTL for data center caches. Specific data center cache TTL options override this value.'),
      ('default_cache_ttl_seconds', '默认缓存 TTL 秒数', 'number', '1800'::jsonb, '1800'::jsonb, true, 'Fallback TTL for cache families without a specific TTL option.'),
      ('data_asset_summary_ttl_seconds', '数据中心总览 TTL 秒数', 'number', '1800'::jsonb, '1800'::jsonb, true, 'TTL for the data center asset summary snapshot.'),
      ('data_asset_daily_health_ttl_seconds', '数据完整性 TTL 秒数', 'number', '900'::jsonb, '900'::jsonb, true, 'TTL for the data center daily health snapshot.')
) AS item(option_key, option_name, value_type, option_value, default_value, is_required, description)
WHERE sc.category_code = 'market_data' AND sc.config_code = 'redis_cache'
ON CONFLICT (system_config_id, option_key) DO UPDATE SET
    option_name = EXCLUDED.option_name,
    value_type = EXCLUDED.value_type,
    default_value = EXCLUDED.default_value,
    is_required = EXCLUDED.is_required,
    description = EXCLUDED.description,
    metadata = t_config_option.metadata || EXCLUDED.metadata,
    updated_at = now();

UPDATE t_config_option opt
SET
    is_enabled = true,
    description = 'Default TTL for data center caches. Specific data center cache TTL options override this value.',
    metadata = (opt.metadata - 'deprecated' - 'replaced_by') || '{"source":"redis-cache-bootstrap","ttl_role":"data_asset_default"}'::jsonb,
    updated_at = now()
FROM t_system_config sc
WHERE opt.system_config_id = sc.id
  AND sc.category_code = 'market_data'
  AND sc.config_code = 'redis_cache'
  AND opt.option_key = 'data_asset_cache_ttl_seconds';

DO $$
BEGIN
    BEGIN
        COMMENT ON TABLE t_system_config IS 'System configuration objects, including search, llm, notification and market_data data sources such as tushare_pro and redis_cache.';
    EXCEPTION WHEN insufficient_privilege THEN
        RAISE NOTICE 'Skipping t_system_config table comment because current role is not the table owner';
    END;
END $$;
