-- Realtime market runtime configuration.
-- Safe to re-run. It adds a fixed non-sensitive market_data/realtime_market config item.
-- Redis connection settings remain owned by market_data/redis_cache.

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
    'realtime_market',
    '实时行情运行时',
    'MooTDX 实时 quote 与受控分钟线缓存。实时数据只写 Redis/内存，不写日频 canonical 表。',
    40,
    false,
    true,
    '{"source":"realtime-market-runtime","provider":"mootdx","cache":"redis_or_memory"}'::jsonb
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
    true,
    true,
    item.description,
    '{"source":"realtime-market-runtime"}'::jsonb
FROM t_system_config sc
CROSS JOIN (
    VALUES
      ('enabled', '启用实时行情运行时', 'boolean', 'false'::jsonb, 'false'::jsonb, 'Only when enabled does the FastAPI background runtime poll external realtime providers during market sessions.'),
      ('full_market_interval_seconds', '全市场 Quote 刷新秒数', 'number', '60'::jsonb, '60'::jsonb, 'MooTDX full-market quote refresh interval. The first release should not be set below 60 seconds.'),
      ('quote_batch_size', 'Quote 单批股票数', 'number', '80'::jsonb, '80'::jsonb, 'MooTDX quote_batch hard safety limit. Values above 80 may be silently truncated.'),
      ('quote_provider_pool_size', 'Quote Provider 连接数', 'number', '2'::jsonb, '2'::jsonb, 'Independent MooTDX provider instances used by full-market quote batches.'),
      ('minute_provider_pool_size', '分钟线 Provider 连接数', 'number', '4'::jsonb, '4'::jsonb, 'Independent MooTDX provider instances used by target minute(symbol) requests.'),
      ('minute_refresh_interval_seconds', '分钟线刷新秒数', 'number', '60'::jsonb, '60'::jsonb, 'Target minute-line refresh interval.'),
      ('minute_guaranteed_target_count', '每分钟保障股票数', 'number', '200'::jsonb, '200'::jsonb, 'Highest-priority targets that receive a real minute-line refresh every minute.'),
      ('minute_registered_target_limit', '分钟线登记上限', 'number', '500'::jsonb, '500'::jsonb, 'Maximum watched minute-line targets. Targets beyond the guaranteed range rotate by priority.'),
      ('strong_candidate_limit', '强势候选数量', 'number', '80'::jsonb, '80'::jsonb, 'Quote-ranked strong candidates added after holding, focus and active page targets.'),
      ('stale_after_seconds', '实时数据过期秒数', 'number', '180'::jsonb, '180'::jsonb, 'Quotes older than this threshold are labeled stale instead of being treated as current.'),
      ('round_failure_threshold', 'Quote 轮次失败阈值', 'number', '0.05'::jsonb, '0.05'::jsonb, 'When failed quote batches exceed this ratio, retain the previous cache and mark the round degraded.'),
      ('reference_refresh_seconds', '主数据映射刷新秒数', 'number', '600'::jsonb, '600'::jsonb, 'Refresh active-stock, stock-pool and sector-component references from PostgreSQL at this interval.'),
      ('cache_ttl_seconds', '实时 Quote 缓存 TTL 秒数', 'number', '180'::jsonb, '180'::jsonb, 'TTL for current quote, market breadth, sector-strength and pool-summary cache keys.')
) AS item(option_key, option_name, value_type, option_value, default_value, description)
WHERE sc.category_code = 'market_data' AND sc.config_code = 'realtime_market'
ON CONFLICT (system_config_id, option_key) DO UPDATE SET
    option_name = EXCLUDED.option_name,
    value_type = EXCLUDED.value_type,
    default_value = EXCLUDED.default_value,
    is_required = EXCLUDED.is_required,
    description = EXCLUDED.description,
    metadata = t_config_option.metadata || EXCLUDED.metadata,
    updated_at = now();

DO $$
BEGIN
    BEGIN
        COMMENT ON TABLE t_system_config IS 'System configuration objects, including market_data runtime settings such as tushare_pro, redis_cache and realtime_market.';
    EXCEPTION WHEN insufficient_privilege THEN
        RAISE NOTICE 'Skipping t_system_config table comment because current role is not the table owner';
    END;
END $$;
