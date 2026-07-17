-- Tushare Token-specific API endpoint override.
-- Existing values keep endpoint_url = NULL and continue to use the system default api_url.

ALTER TABLE t_config_value
    ADD COLUMN IF NOT EXISTS endpoint_url TEXT;

DO $$
BEGIN
    COMMENT ON COLUMN t_config_value.endpoint_url IS
        'Non-sensitive API endpoint override for this config value. Only market_data/tushare_pro token values may use it; NULL falls back to the config-level api_url.';
EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'Skipping t_config_value.endpoint_url comment because current role is not the table owner';
END $$;

UPDATE t_config_option option_row
SET
    option_name = '默认 API URL',
    description = '未设置专属 API URL 的 Tushare Token 使用此入口。',
    updated_at = now()
FROM t_system_config config_row
WHERE option_row.system_config_id = config_row.id
  AND config_row.category_code = 'market_data'
  AND config_row.config_code = 'tushare_pro'
  AND option_row.option_key = 'api_url';
