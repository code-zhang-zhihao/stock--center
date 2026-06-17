-- stock-center config center UI seed.
-- Adds non-secret Notification options used by the simplified Web Admin.
-- This migration is idempotent and does not write real keys, passwords, tokens, or webhook URLs.

WITH target_nodes AS (
    SELECT n.id, p.node_code AS channel_code, n.node_code AS instance_code
    FROM t_config_node n
    JOIN t_config_node p ON p.id = n.parent_id
    JOIN t_config_node r ON r.id = p.parent_id
    WHERE n.domain = 'notification'
      AND r.node_code = 'notification_channels'
      AND (
        (p.node_code = 'feishu' AND n.node_code = 'default_bot')
        OR (p.node_code = 'email' AND n.node_code = 'default_smtp')
        OR (p.node_code = 'webhook' AND n.node_code = 'default_webhook')
      )
),
seed_options AS (
    SELECT t.id AS config_node_id, v.option_key, v.option_name, v.value_type, v.value_json, v.default_value, v.is_required, v.description
    FROM target_nodes t
    JOIN (
        VALUES
            ('feishu', 'default_bot', 'message_template', '消息模板', 'string', '"{{title}}\n{{content}}"'::jsonb, '"{{title}}\n{{content}}"'::jsonb, false, '飞书机器人默认消息模板。'),
            ('feishu', 'default_bot', 'timeout_seconds', '请求超时秒数', 'number', '10'::jsonb, '10'::jsonb, false, '飞书 Webhook 请求超时时间。'),
            ('email', 'default_smtp', 'smtp_host', 'SMTP Host', 'string', '""'::jsonb, '""'::jsonb, true, 'SMTP 服务器地址。'),
            ('email', 'default_smtp', 'smtp_port', 'SMTP Port', 'number', '587'::jsonb, '587'::jsonb, true, 'SMTP 服务器端口。'),
            ('email', 'default_smtp', 'use_tls', '启用 TLS', 'boolean', 'true'::jsonb, 'true'::jsonb, false, '是否使用 TLS。'),
            ('email', 'default_smtp', 'from_addr', '发件地址', 'string', '""'::jsonb, '""'::jsonb, true, '默认发件邮箱地址。'),
            ('email', 'default_smtp', 'username', '用户名', 'string', '""'::jsonb, '""'::jsonb, false, 'SMTP 登录用户名，密码必须写入 Key 池。'),
            ('webhook', 'default_webhook', 'method', '请求方法', 'string', '"POST"'::jsonb, '"POST"'::jsonb, true, '自定义 Webhook 请求方法。'),
            ('webhook', 'default_webhook', 'headers', '请求头 JSON', 'json', '{}'::jsonb, '{}'::jsonb, false, '自定义 Webhook 非敏感请求头。认证 Token 必须写入 Key 池。'),
            ('webhook', 'default_webhook', 'timeout_seconds', '请求超时秒数', 'number', '10'::jsonb, '10'::jsonb, false, '自定义 Webhook 请求超时时间。')
    ) AS v(channel_code, instance_code, option_key, option_name, value_type, value_json, default_value, is_required, description)
      ON v.channel_code = t.channel_code AND v.instance_code = t.instance_code
)
INSERT INTO t_config_option (
    config_node_id,
    option_key,
    option_name,
    value_type,
    value_json,
    default_value,
    validation_rules,
    is_required,
    is_enabled,
    description,
    metadata
)
SELECT
    config_node_id,
    option_key,
    option_name,
    value_type,
    value_json,
    default_value,
    '{}'::jsonb,
    is_required,
    true,
    description,
    '{"source": "stock-center-config-ui-seed", "non_secret": true}'::jsonb
FROM seed_options
ON CONFLICT (config_node_id, option_key) DO UPDATE SET
    option_name = EXCLUDED.option_name,
    value_type = EXCLUDED.value_type,
    default_value = EXCLUDED.default_value,
    validation_rules = EXCLUDED.validation_rules,
    is_required = EXCLUDED.is_required,
    description = EXCLUDED.description,
    metadata = t_config_option.metadata || EXCLUDED.metadata,
    updated_at = now();
