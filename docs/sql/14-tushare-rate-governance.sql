-- Shared Tushare Token rate-governance defaults. Safe to re-run.

INSERT INTO t_config_option (
    system_config_id, option_key, option_name, value_type, option_value, default_value,
    is_required, is_enabled, description, metadata
)
SELECT
    config_row.id, item.option_key, item.option_name, item.value_type, item.option_value,
    item.default_value, item.is_required, true, item.description,
    '{"source":"tushare-rate-governance"}'::jsonb
FROM t_system_config config_row
CROSS JOIN (
    VALUES
        ('interactive_max_wait_seconds', '交互限流最大等待秒数', 'number', '3'::jsonb, '3'::jsonb, true, 'Maximum local rate-gate wait for interactive requests.'),
        ('scheduler_max_wait_seconds', '调度限流最大等待秒数', 'number', '1800'::jsonb, '1800'::jsonb, true, 'Maximum local rate-gate wait for scheduler work; job timeout remains the final bound.'),
        ('retry_backoff_seconds', '网络重试退避秒数', 'number', '1'::jsonb, '1'::jsonb, false, 'Base backoff for transport retries; rate-limit cooldown uses cooldown_seconds.')
) AS item(option_key, option_name, value_type, option_value, default_value, is_required, description)
WHERE config_row.category_code = 'market_data'
  AND config_row.config_code = 'tushare_pro'
ON CONFLICT (system_config_id, option_key) DO UPDATE SET
    option_name = EXCLUDED.option_name,
    default_value = EXCLUDED.default_value,
    is_required = EXCLUDED.is_required,
    description = EXCLUDED.description,
    metadata = t_config_option.metadata || EXCLUDED.metadata,
    updated_at = now();
