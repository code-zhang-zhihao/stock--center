-- TickFlow realtime quote capability.
-- Safe to re-run. This script does not alter historical market data or minute bars.
-- Before enabling realtime_market with quote_provider=tickflow, add and test an
-- active TickFlow API key in System Settings > Data Sources > TickFlow.

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
    'tickflow',
    'TickFlow',
    'TickFlow 实时 Quote 数据源。仅提供实时行情报价；实时分钟线继续由 MooTDX 获取。',
    35,
    false,
    true,
    '{"source":"tickflow-realtime-quote","capabilities":["quote"],"minute_provider":"mootdx"}'::jsonb
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
    '{"source":"tickflow-realtime-quote"}'::jsonb
FROM t_system_config sc
CROSS JOIN (
    VALUES
      ('timeout_seconds', '请求超时秒数', 'number', '10'::jsonb, '10'::jsonb, 'TickFlow Quote HTTP request timeout. A value-specific API URL may override the SDK default endpoint.'),
      ('api_url', '默认 API URL', 'string', 'null'::jsonb, 'null'::jsonb, 'Optional TickFlow API endpoint override. Leave null to use the official SDK default endpoint.')
) AS item(option_key, option_name, value_type, option_value, default_value, description)
WHERE sc.category_code = 'market_data' AND sc.config_code = 'tickflow'
ON CONFLICT (system_config_id, option_key) DO UPDATE SET
    option_name = EXCLUDED.option_name,
    value_type = EXCLUDED.value_type,
    default_value = EXCLUDED.default_value,
    is_required = EXCLUDED.is_required,
    description = EXCLUDED.description,
    metadata = t_config_option.metadata || EXCLUDED.metadata,
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
    '{"source":"tickflow-realtime-quote"}'::jsonb
FROM t_system_config sc
CROSS JOIN (
    VALUES
      ('quote_provider', '实时 Quote 数据源', 'string', '"tickflow"'::jsonb, '"tickflow"'::jsonb, 'TickFlow supplies realtime quotes. MooTDX remains the separate realtime minute-bar provider.')
) AS item(option_key, option_name, value_type, option_value, default_value, description)
WHERE sc.category_code = 'market_data' AND sc.config_code = 'realtime_market'
ON CONFLICT (system_config_id, option_key) DO UPDATE SET
    option_name = EXCLUDED.option_name,
    value_type = EXCLUDED.value_type,
    option_value = EXCLUDED.option_value,
    default_value = EXCLUDED.default_value,
    is_required = EXCLUDED.is_required,
    description = EXCLUDED.description,
    metadata = t_config_option.metadata || EXCLUDED.metadata,
    updated_at = now();

UPDATE t_system_config
SET
    description = 'TickFlow 实时 Quote 与 MooTDX 实时分钟线的分源缓存运行时。实时数据只写 Redis/内存，不写日频 canonical 表。',
    metadata = metadata || '{"quote_provider":"tickflow","minute_provider":"mootdx","cache":"redis_or_memory"}'::jsonb,
    updated_at = now()
WHERE category_code = 'market_data' AND config_code = 'realtime_market';

UPDATE t_config_option option_row
SET
    option_name = '全市场 Quote 刷新秒数',
    description = 'TickFlow 全市场 Quote 刷新间隔；分钟线由独立的 MooTDX 链路控制。',
    updated_at = now()
FROM t_system_config sc
WHERE option_row.system_config_id = sc.id
  AND sc.category_code = 'market_data'
  AND sc.config_code = 'realtime_market'
  AND option_row.option_key = 'full_market_interval_seconds';

UPDATE t_config_option option_row
SET
    option_name = 'Quote 单批股票数',
    description = 'TickFlow 单次批量 Quote 的股票数。保持在 1-80，以控制单次响应大小和失败影响范围。',
    updated_at = now()
FROM t_system_config sc
WHERE option_row.system_config_id = sc.id
  AND sc.category_code = 'market_data'
  AND sc.config_code = 'realtime_market'
  AND option_row.option_key = 'quote_batch_size';

UPDATE t_config_option option_row
SET
    option_name = 'Quote Provider 连接数',
    description = 'TickFlow Quote Provider 实例数；与 MooTDX 分钟线连接池独立。',
    updated_at = now()
FROM t_system_config sc
WHERE option_row.system_config_id = sc.id
  AND sc.category_code = 'market_data'
  AND sc.config_code = 'realtime_market'
  AND option_row.option_key = 'quote_provider_pool_size';

