-- stock-center config center migration.
-- Adds a recursive configuration tree, typed options, secret key pools, relations, and runtime logs.
-- This migration only creates new t_ tables and bootstrap rows. It does not delete or modify legacy tables.

CREATE TABLE IF NOT EXISTS t_config_node (
    id BIGSERIAL PRIMARY KEY,
    parent_id BIGINT REFERENCES t_config_node(id) ON DELETE CASCADE,
    domain VARCHAR(40) NOT NULL,
    node_code VARCHAR(120) NOT NULL,
    node_name VARCHAR(200) NOT NULL,
    node_type VARCHAR(40) NOT NULL,
    description TEXT,
    sort_order INTEGER NOT NULL DEFAULT 100,
    is_default BOOLEAN NOT NULL DEFAULT false,
    is_enabled BOOLEAN NOT NULL DEFAULT true,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_t_config_node_root_code
    ON t_config_node(domain, node_code)
    WHERE parent_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_t_config_node_parent_code
    ON t_config_node(parent_id, node_code)
    WHERE parent_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_t_config_node_domain_parent ON t_config_node(domain, parent_id, sort_order, id);
CREATE INDEX IF NOT EXISTS idx_t_config_node_enabled ON t_config_node(domain, is_enabled, node_type);

CREATE TABLE IF NOT EXISTS t_config_option (
    id BIGSERIAL PRIMARY KEY,
    config_node_id BIGINT NOT NULL REFERENCES t_config_node(id) ON DELETE CASCADE,
    option_key VARCHAR(120) NOT NULL,
    option_name VARCHAR(200) NOT NULL,
    value_type VARCHAR(40) NOT NULL DEFAULT 'string',
    value_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    default_value JSONB,
    validation_rules JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_required BOOLEAN NOT NULL DEFAULT false,
    is_enabled BOOLEAN NOT NULL DEFAULT true,
    version INTEGER NOT NULL DEFAULT 1,
    description TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_config_option_node_key UNIQUE (config_node_id, option_key)
);

CREATE INDEX IF NOT EXISTS idx_t_config_option_node_enabled ON t_config_option(config_node_id, is_enabled);

CREATE TABLE IF NOT EXISTS t_secret_key (
    id BIGSERIAL PRIMARY KEY,
    config_node_id BIGINT NOT NULL REFERENCES t_config_node(id) ON DELETE CASCADE,
    key_name VARCHAR(160) NOT NULL,
    key_type VARCHAR(40) NOT NULL DEFAULT 'api_key',
    encrypted_secret TEXT NOT NULL,
    secret_fingerprint VARCHAR(64) NOT NULL,
    env_var_name VARCHAR(120),
    priority INTEGER NOT NULL DEFAULT 100,
    weight INTEGER NOT NULL DEFAULT 100,
    status VARCHAR(40) NOT NULL DEFAULT 'active',
    failure_count INTEGER NOT NULL DEFAULT 0,
    last_used_at TIMESTAMPTZ,
    cooldown_until TIMESTAMPTZ,
    is_default BOOLEAN NOT NULL DEFAULT false,
    is_enabled BOOLEAN NOT NULL DEFAULT true,
    description TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_t_secret_key_node_status ON t_secret_key(config_node_id, key_type, is_enabled, status, priority);
CREATE INDEX IF NOT EXISTS idx_t_secret_key_fingerprint ON t_secret_key(secret_fingerprint);

CREATE TABLE IF NOT EXISTS t_config_relation (
    id BIGSERIAL PRIMARY KEY,
    source_node_id BIGINT NOT NULL REFERENCES t_config_node(id) ON DELETE CASCADE,
    target_node_id BIGINT NOT NULL REFERENCES t_config_node(id) ON DELETE CASCADE,
    relation_type VARCHAR(60) NOT NULL,
    priority INTEGER NOT NULL DEFAULT 100,
    weight INTEGER NOT NULL DEFAULT 100,
    is_enabled BOOLEAN NOT NULL DEFAULT true,
    description TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_config_relation_business UNIQUE (source_node_id, target_node_id, relation_type)
);

CREATE INDEX IF NOT EXISTS idx_t_config_relation_source_type ON t_config_relation(source_node_id, relation_type, is_enabled, priority);
CREATE INDEX IF NOT EXISTS idx_t_config_relation_target_type ON t_config_relation(target_node_id, relation_type, is_enabled);

CREATE TABLE IF NOT EXISTS t_runtime_call_log (
    id BIGSERIAL PRIMARY KEY,
    trace_id VARCHAR(80) NOT NULL,
    domain VARCHAR(40) NOT NULL,
    config_node_id BIGINT REFERENCES t_config_node(id) ON DELETE SET NULL,
    secret_key_id BIGINT REFERENCES t_secret_key(id) ON DELETE SET NULL,
    capability VARCHAR(120),
    call_type VARCHAR(60) NOT NULL,
    status VARCHAR(40) NOT NULL,
    request_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_code VARCHAR(120),
    error_message TEXT,
    latency_ms INTEGER,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_t_runtime_call_log_trace ON t_runtime_call_log(trace_id);
CREATE INDEX IF NOT EXISTS idx_t_runtime_call_log_node_time ON t_runtime_call_log(config_node_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_t_runtime_call_log_domain_status ON t_runtime_call_log(domain, status, started_at DESC);

COMMENT ON TABLE t_config_node IS '配置中心：递归配置树节点，管理 Search、LLM、Notification 等配置域。';
COMMENT ON COLUMN t_config_node.id IS '主键 ID。';
COMMENT ON COLUMN t_config_node.parent_id IS '父节点 ID，允许递归多层配置树。';
COMMENT ON COLUMN t_config_node.domain IS '配置域：search、llm、notification 等。';
COMMENT ON COLUMN t_config_node.node_code IS '节点编码，同一父节点下唯一。';
COMMENT ON COLUMN t_config_node.node_name IS '节点展示名称。';
COMMENT ON COLUMN t_config_node.node_type IS '节点类型：group、provider、model、channel、profile、instance 等。';
COMMENT ON COLUMN t_config_node.description IS '节点说明。';
COMMENT ON COLUMN t_config_node.sort_order IS '排序值，越小越靠前。';
COMMENT ON COLUMN t_config_node.is_default IS '是否为同级默认节点。';
COMMENT ON COLUMN t_config_node.is_enabled IS '是否启用该节点。';
COMMENT ON COLUMN t_config_node.metadata IS '扩展信息，例如迁移来源、运行策略。';
COMMENT ON COLUMN t_config_node.created_at IS '创建时间。';
COMMENT ON COLUMN t_config_node.updated_at IS '更新时间。';

COMMENT ON TABLE t_config_option IS '配置中心：绑定到配置节点的非敏感配置项。';
COMMENT ON COLUMN t_config_option.id IS '主键 ID。';
COMMENT ON COLUMN t_config_option.config_node_id IS '所属配置节点 ID。';
COMMENT ON COLUMN t_config_option.option_key IS '配置项编码，同一节点下唯一。';
COMMENT ON COLUMN t_config_option.option_name IS '配置项展示名称。';
COMMENT ON COLUMN t_config_option.value_type IS '值类型：string、number、boolean、json、array 等。';
COMMENT ON COLUMN t_config_option.value_json IS '当前配置值，JSON 格式保存。';
COMMENT ON COLUMN t_config_option.default_value IS '默认值，JSON 格式保存。';
COMMENT ON COLUMN t_config_option.validation_rules IS '校验规则，例如范围、枚举、正则。';
COMMENT ON COLUMN t_config_option.is_required IS '是否必填。';
COMMENT ON COLUMN t_config_option.is_enabled IS '是否启用该配置项。';
COMMENT ON COLUMN t_config_option.version IS '配置项版本号，每次覆盖更新递增。';
COMMENT ON COLUMN t_config_option.description IS '配置项说明。';
COMMENT ON COLUMN t_config_option.metadata IS '扩展信息，例如迁移来源。';
COMMENT ON COLUMN t_config_option.created_at IS '创建时间。';
COMMENT ON COLUMN t_config_option.updated_at IS '更新时间。';

COMMENT ON TABLE t_secret_key IS '配置中心：敏感密钥池，保存 API Key、Webhook、SMTP Password、Cookie、Token 等密文。';
COMMENT ON COLUMN t_secret_key.id IS '主键 ID。';
COMMENT ON COLUMN t_secret_key.config_node_id IS '所属配置节点 ID。';
COMMENT ON COLUMN t_secret_key.key_name IS '密钥名称，用于展示和区分用途。';
COMMENT ON COLUMN t_secret_key.key_type IS '密钥类型：api_key、webhook_url、smtp_password、cookie、token、credential_json 等。';
COMMENT ON COLUMN t_secret_key.encrypted_secret IS '使用 CONFIG_MASTER_KEY 加密后的密文。';
COMMENT ON COLUMN t_secret_key.secret_fingerprint IS '密钥指纹，用于识别密钥且不泄露明文。';
COMMENT ON COLUMN t_secret_key.env_var_name IS '兼容旧系统的环境变量名。';
COMMENT ON COLUMN t_secret_key.priority IS '选择优先级，越小越优先。';
COMMENT ON COLUMN t_secret_key.weight IS '同优先级下的轮询权重。';
COMMENT ON COLUMN t_secret_key.status IS '密钥状态：active、cooldown、invalid、disabled 等。';
COMMENT ON COLUMN t_secret_key.failure_count IS '连续或累计失败次数。';
COMMENT ON COLUMN t_secret_key.last_used_at IS '最近一次使用时间。';
COMMENT ON COLUMN t_secret_key.cooldown_until IS '冷却截止时间，冷却期间不参与选择。';
COMMENT ON COLUMN t_secret_key.is_default IS '是否为默认密钥。';
COMMENT ON COLUMN t_secret_key.is_enabled IS '是否启用该密钥。';
COMMENT ON COLUMN t_secret_key.description IS '密钥说明，不允许填写明文。';
COMMENT ON COLUMN t_secret_key.metadata IS '扩展信息，例如迁移来源。';
COMMENT ON COLUMN t_secret_key.created_at IS '创建时间。';
COMMENT ON COLUMN t_secret_key.updated_at IS '更新时间。';

COMMENT ON TABLE t_config_relation IS '配置中心：配置节点之间的非树形关系，例如 fallback、uses_key_pool、uses_model、notifies_via。';
COMMENT ON COLUMN t_config_relation.id IS '主键 ID。';
COMMENT ON COLUMN t_config_relation.source_node_id IS '关系源节点 ID。';
COMMENT ON COLUMN t_config_relation.target_node_id IS '关系目标节点 ID。';
COMMENT ON COLUMN t_config_relation.relation_type IS '关系类型：fallback_to、uses_key_pool、uses_model、notifies_via 等。';
COMMENT ON COLUMN t_config_relation.priority IS '关系优先级，越小越优先。';
COMMENT ON COLUMN t_config_relation.weight IS '同优先级下权重。';
COMMENT ON COLUMN t_config_relation.is_enabled IS '是否启用该关系。';
COMMENT ON COLUMN t_config_relation.description IS '关系说明。';
COMMENT ON COLUMN t_config_relation.metadata IS '扩展信息，例如迁移来源。';
COMMENT ON COLUMN t_config_relation.created_at IS '创建时间。';
COMMENT ON COLUMN t_config_relation.updated_at IS '更新时间。';

COMMENT ON TABLE t_runtime_call_log IS '配置中心：Search、LLM、Notification 等运行时调用日志。';
COMMENT ON COLUMN t_runtime_call_log.id IS '主键 ID。';
COMMENT ON COLUMN t_runtime_call_log.trace_id IS '调用链追踪 ID。';
COMMENT ON COLUMN t_runtime_call_log.domain IS '配置域：search、llm、notification 等。';
COMMENT ON COLUMN t_runtime_call_log.config_node_id IS '本次调用使用的配置节点 ID。';
COMMENT ON COLUMN t_runtime_call_log.secret_key_id IS '本次调用使用的密钥 ID。';
COMMENT ON COLUMN t_runtime_call_log.capability IS '能力编码，例如 news_search、llm_chat、feishu_notify。';
COMMENT ON COLUMN t_runtime_call_log.call_type IS '调用类型：search、llm、notification、test_key 等。';
COMMENT ON COLUMN t_runtime_call_log.status IS '调用状态：success、failed、skipped 等。';
COMMENT ON COLUMN t_runtime_call_log.request_summary IS '请求摘要，不保存敏感明文。';
COMMENT ON COLUMN t_runtime_call_log.response_summary IS '响应摘要，不保存敏感明文。';
COMMENT ON COLUMN t_runtime_call_log.error_code IS '错误编码。';
COMMENT ON COLUMN t_runtime_call_log.error_message IS '错误信息。';
COMMENT ON COLUMN t_runtime_call_log.latency_ms IS '调用耗时，单位毫秒。';
COMMENT ON COLUMN t_runtime_call_log.started_at IS '调用开始时间。';
COMMENT ON COLUMN t_runtime_call_log.finished_at IS '调用结束时间。';
COMMENT ON COLUMN t_runtime_call_log.metadata IS '扩展信息。';
COMMENT ON COLUMN t_runtime_call_log.created_at IS '创建时间。';

WITH root AS (
    INSERT INTO t_config_node (parent_id, domain, node_code, node_name, node_type, sort_order, metadata)
    VALUES
        (NULL, 'search', 'search_models', '搜索模型', 'group', 10, '{"source": "stock-center-bootstrap"}'::jsonb),
        (NULL, 'llm', 'llm_models', 'LLM 模型', 'group', 20, '{"source": "stock-center-bootstrap"}'::jsonb),
        (NULL, 'notification', 'notification_channels', '通知渠道', 'group', 30, '{"source": "stock-center-bootstrap"}'::jsonb)
    ON CONFLICT DO NOTHING
    RETURNING id, domain, node_code
),
all_roots AS (
    SELECT id, domain, node_code FROM root
    UNION
    SELECT id, domain, node_code
    FROM t_config_node
    WHERE parent_id IS NULL AND node_code IN ('search_models', 'llm_models', 'notification_channels')
),
providers AS (
    INSERT INTO t_config_node (parent_id, domain, node_code, node_name, node_type, sort_order, metadata)
    SELECT r.id, v.domain, v.node_code, v.node_name, v.node_type, v.sort_order, '{"source": "stock-center-bootstrap"}'::jsonb
    FROM all_roots r
    JOIN (
        VALUES
            ('search', 'search_models', 'kimi_search', 'Kimi Search', 'provider', 10),
            ('search', 'search_models', 'miaoxiang_search', '妙想搜索', 'provider', 20),
            ('search', 'search_models', 'iwencai_search', '问财搜索', 'provider', 30),
            ('llm', 'llm_models', 'kimi_llm', 'Kimi LLM', 'provider', 10),
            ('llm', 'llm_models', 'deepseek_llm', 'DeepSeek LLM', 'provider', 20),
            ('llm', 'llm_models', 'openai_compatible', 'OpenAI Compatible', 'provider', 30),
            ('notification', 'notification_channels', 'feishu', '飞书通知', 'channel', 10),
            ('notification', 'notification_channels', 'email', '邮件通知', 'channel', 20),
            ('notification', 'notification_channels', 'webhook', 'Webhook 通知', 'channel', 30)
    ) AS v(domain, root_code, node_code, node_name, node_type, sort_order)
        ON r.domain = v.domain AND r.node_code = v.root_code
    ON CONFLICT DO NOTHING
    RETURNING id, domain, node_code
),
all_providers AS (
    SELECT id, domain, node_code FROM providers
    UNION
    SELECT n.id, n.domain, n.node_code
    FROM t_config_node n
    JOIN t_config_node p ON p.id = n.parent_id
    WHERE p.node_code IN ('search_models', 'llm_models', 'notification_channels')
),
profiles AS (
    INSERT INTO t_config_node (parent_id, domain, node_code, node_name, node_type, sort_order, is_default, metadata)
    SELECT p.id, v.domain, v.node_code, v.node_name, v.node_type, v.sort_order, v.is_default, '{"source": "stock-center-bootstrap"}'::jsonb
    FROM all_providers p
    JOIN (
        VALUES
            ('search', 'kimi_search', 'default', '默认 Kimi Search', 'profile', 10, true),
            ('search', 'kimi_search', 'backup', '备用 Kimi Search', 'profile', 20, false),
            ('search', 'miaoxiang_search', 'default', '默认妙想搜索', 'profile', 10, true),
            ('search', 'iwencai_search', 'default', '默认问财搜索', 'profile', 10, true),
            ('llm', 'kimi_llm', 'moonshot_v1_8k', 'Moonshot v1 8K', 'model', 10, true),
            ('llm', 'kimi_llm', 'moonshot_v1_32k', 'Moonshot v1 32K', 'model', 20, false),
            ('llm', 'deepseek_llm', 'deepseek_chat', 'DeepSeek Chat', 'model', 10, true),
            ('llm', 'openai_compatible', 'default', 'OpenAI Compatible 默认模型', 'model', 10, true),
            ('notification', 'feishu', 'default_bot', '默认飞书机器人', 'instance', 10, true),
            ('notification', 'feishu', 'trade_alert_bot', '交易提醒飞书机器人', 'instance', 20, false),
            ('notification', 'feishu', 'risk_alert_bot', '风控提醒飞书机器人', 'instance', 30, false),
            ('notification', 'email', 'default_smtp', '默认 SMTP', 'instance', 10, true),
            ('notification', 'email', 'ops_smtp', '运维 SMTP', 'instance', 20, false),
            ('notification', 'webhook', 'default_webhook', '默认 Webhook', 'instance', 10, true)
    ) AS v(domain, parent_code, node_code, node_name, node_type, sort_order, is_default)
        ON p.domain = v.domain AND p.node_code = v.parent_code
    ON CONFLICT DO NOTHING
    RETURNING id
)
SELECT 1;
