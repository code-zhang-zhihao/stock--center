-- stock-center config center v2 rebuild.
-- Replaces the old recursive config tree with fixed config items, value pools, and options.
-- Execute after backing up the database. This migration preserves encrypted values and fingerprints.

BEGIN;

DO $$
BEGIN
    IF to_regclass('public.t_config_node') IS NULL
       AND to_regclass('public.t_secret_key') IS NULL
       AND to_regclass('public.provider_key') IS NULL
       AND to_regclass('public.t_system_config') IS NOT NULL
    THEN
        RAISE EXCEPTION 'config center v2 appears to be already rebuilt; old config tables are not present';
    END IF;
END $$;

DO $$
BEGIN
    IF to_regclass('public.t_config_option') IS NOT NULL
       AND EXISTS (
           SELECT 1 FROM information_schema.columns
           WHERE table_schema = 'public' AND table_name = 't_config_option' AND column_name = 'config_node_id'
       )
       AND to_regclass('public.t_config_option_legacy_v1') IS NULL
    THEN
        ALTER TABLE t_config_option RENAME TO t_config_option_legacy_v1;
    END IF;

    IF to_regclass('public.t_runtime_call_log') IS NOT NULL
       AND EXISTS (
           SELECT 1 FROM information_schema.columns
           WHERE table_schema = 'public' AND table_name = 't_runtime_call_log' AND column_name = 'config_node_id'
       )
       AND to_regclass('public.t_runtime_call_log_legacy_v1') IS NULL
    THEN
        ALTER TABLE t_runtime_call_log RENAME TO t_runtime_call_log_legacy_v1;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS t_system_config (
    id BIGSERIAL PRIMARY KEY,
    category_code VARCHAR(40) NOT NULL,
    config_code VARCHAR(120) NOT NULL,
    config_name VARCHAR(200) NOT NULL,
    description TEXT,
    sort_order INTEGER NOT NULL DEFAULT 100,
    is_default BOOLEAN NOT NULL DEFAULT false,
    is_enabled BOOLEAN NOT NULL DEFAULT true,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_system_config_category_code UNIQUE (category_code, config_code)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_t_system_config_category_default
    ON t_system_config(category_code)
    WHERE is_default = true;
CREATE INDEX IF NOT EXISTS idx_t_system_config_category_enabled ON t_system_config(category_code, is_enabled, sort_order);

CREATE TABLE IF NOT EXISTS t_config_value (
    id BIGSERIAL PRIMARY KEY,
    system_config_id BIGINT NOT NULL REFERENCES t_system_config(id) ON DELETE CASCADE,
    value_name VARCHAR(160) NOT NULL,
    value_kind VARCHAR(40) NOT NULL DEFAULT 'api_key',
    encrypted_value TEXT NOT NULL,
    fingerprint VARCHAR(64) NOT NULL,
    priority INTEGER NOT NULL DEFAULT 100,
    weight INTEGER NOT NULL DEFAULT 100,
    status VARCHAR(40) NOT NULL DEFAULT 'active',
    failure_count INTEGER NOT NULL DEFAULT 0,
    last_used_at TIMESTAMPTZ,
    cooldown_until TIMESTAMPTZ,
    is_enabled BOOLEAN NOT NULL DEFAULT true,
    description TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_t_config_value_config_status
    ON t_config_value(system_config_id, value_kind, is_enabled, status, priority);
CREATE INDEX IF NOT EXISTS idx_t_config_value_fingerprint ON t_config_value(fingerprint);
CREATE UNIQUE INDEX IF NOT EXISTS uq_t_config_value_config_kind_fingerprint
    ON t_config_value(system_config_id, value_kind, fingerprint);

CREATE TABLE IF NOT EXISTS t_config_option (
    id BIGSERIAL PRIMARY KEY,
    system_config_id BIGINT NOT NULL REFERENCES t_system_config(id) ON DELETE CASCADE,
    option_key VARCHAR(120) NOT NULL,
    option_name VARCHAR(200) NOT NULL,
    value_type VARCHAR(40) NOT NULL DEFAULT 'string',
    option_value JSONB,
    default_value JSONB,
    is_required BOOLEAN NOT NULL DEFAULT false,
    is_enabled BOOLEAN NOT NULL DEFAULT true,
    description TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_t_config_option_config_key UNIQUE (system_config_id, option_key)
);

CREATE INDEX IF NOT EXISTS idx_t_config_option_config_enabled ON t_config_option(system_config_id, is_enabled);

CREATE TABLE IF NOT EXISTS t_runtime_call_log (
    id BIGSERIAL PRIMARY KEY,
    trace_id VARCHAR(80) NOT NULL,
    domain VARCHAR(40) NOT NULL,
    system_config_id BIGINT REFERENCES t_system_config(id) ON DELETE SET NULL,
    config_value_id BIGINT REFERENCES t_config_value(id) ON DELETE SET NULL,
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
CREATE INDEX IF NOT EXISTS idx_t_runtime_call_log_config_time ON t_runtime_call_log(system_config_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_t_runtime_call_log_domain_status ON t_runtime_call_log(domain, status, started_at DESC);

COMMENT ON TABLE t_system_config IS '配置中心 v2：固定配置对象，例如问财、妙想、Kimi、DeepSeek、飞书、邮箱。';
COMMENT ON COLUMN t_system_config.id IS '主键 ID。';
COMMENT ON COLUMN t_system_config.category_code IS '配置分类编码：search、llm、notification。';
COMMENT ON COLUMN t_system_config.config_code IS '配置对象编码，同一分类下唯一，由后端运行时固定约定。';
COMMENT ON COLUMN t_system_config.config_name IS '配置对象展示名称。';
COMMENT ON COLUMN t_system_config.description IS '配置对象说明。';
COMMENT ON COLUMN t_system_config.sort_order IS '排序值，越小越靠前。';
COMMENT ON COLUMN t_system_config.is_default IS '是否为该分类默认配置；每个分类最多一个默认项。';
COMMENT ON COLUMN t_system_config.is_enabled IS '是否启用该配置对象。';
COMMENT ON COLUMN t_system_config.metadata IS '扩展信息，不保存敏感明文。';
COMMENT ON COLUMN t_system_config.created_at IS '创建时间。';
COMMENT ON COLUMN t_system_config.updated_at IS '更新时间。';

COMMENT ON TABLE t_config_value IS '配置中心 v2：配置对象下的敏感值池，保存 API Key、Webhook URL、Token、Password 等密文。';
COMMENT ON COLUMN t_config_value.id IS '主键 ID。';
COMMENT ON COLUMN t_config_value.system_config_id IS '所属配置对象 ID。';
COMMENT ON COLUMN t_config_value.value_name IS '敏感值名称，用于展示和区分用途。';
COMMENT ON COLUMN t_config_value.value_kind IS '敏感值类型：api_key、webhook_url、token、password、smtp_password、credential_json 等。';
COMMENT ON COLUMN t_config_value.encrypted_value IS '使用 CONFIG_MASTER_KEY 加密后的密文。';
COMMENT ON COLUMN t_config_value.fingerprint IS '明文指纹，用于识别但不泄露明文。';
COMMENT ON COLUMN t_config_value.priority IS '选择优先级，越小越优先。';
COMMENT ON COLUMN t_config_value.weight IS '同优先级下的选择权重。';
COMMENT ON COLUMN t_config_value.status IS '状态：active、cooldown、invalid、disabled。';
COMMENT ON COLUMN t_config_value.failure_count IS '连续或累计失败次数。';
COMMENT ON COLUMN t_config_value.last_used_at IS '最近一次使用时间。';
COMMENT ON COLUMN t_config_value.cooldown_until IS '冷却截止时间，冷却期内不参与选择。';
COMMENT ON COLUMN t_config_value.is_enabled IS '是否启用。';
COMMENT ON COLUMN t_config_value.description IS '说明，不允许填写明文。';
COMMENT ON COLUMN t_config_value.metadata IS '扩展信息，例如迁移来源。';
COMMENT ON COLUMN t_config_value.created_at IS '创建时间。';
COMMENT ON COLUMN t_config_value.updated_at IS '更新时间。';

COMMENT ON TABLE t_config_option IS '配置中心 v2：配置对象下的非敏感参数，主要服务 LLM 和通知渠道。';
COMMENT ON COLUMN t_config_option.id IS '主键 ID。';
COMMENT ON COLUMN t_config_option.system_config_id IS '所属配置对象 ID。';
COMMENT ON COLUMN t_config_option.option_key IS '参数编码，同一配置对象下唯一。';
COMMENT ON COLUMN t_config_option.option_name IS '参数展示名称。';
COMMENT ON COLUMN t_config_option.value_type IS '值类型：string、number、boolean、json。';
COMMENT ON COLUMN t_config_option.option_value IS '当前参数值，JSON 格式保存。';
COMMENT ON COLUMN t_config_option.default_value IS '默认值，JSON 格式保存。';
COMMENT ON COLUMN t_config_option.is_required IS '是否必填。';
COMMENT ON COLUMN t_config_option.is_enabled IS '是否启用该参数。';
COMMENT ON COLUMN t_config_option.description IS '参数说明。';
COMMENT ON COLUMN t_config_option.metadata IS '扩展信息，不保存敏感明文。';
COMMENT ON COLUMN t_config_option.created_at IS '创建时间。';
COMMENT ON COLUMN t_config_option.updated_at IS '更新时间。';

COMMENT ON TABLE t_runtime_call_log IS '运行时调用日志，记录 Search、LLM、Notification、Skill 等内部调用摘要。';
COMMENT ON COLUMN t_runtime_call_log.id IS '主键 ID。';
COMMENT ON COLUMN t_runtime_call_log.trace_id IS '调用链追踪 ID。';
COMMENT ON COLUMN t_runtime_call_log.domain IS '调用域：config、search、llm、notification、skill 等。';
COMMENT ON COLUMN t_runtime_call_log.system_config_id IS '本次调用使用的配置对象 ID。';
COMMENT ON COLUMN t_runtime_call_log.config_value_id IS '本次调用使用的敏感值 ID。';
COMMENT ON COLUMN t_runtime_call_log.capability IS '能力编码，例如 news_search、llm_chat、feishu_notify。';
COMMENT ON COLUMN t_runtime_call_log.call_type IS '调用类型。';
COMMENT ON COLUMN t_runtime_call_log.status IS '调用状态：success、failed、skipped。';
COMMENT ON COLUMN t_runtime_call_log.request_summary IS '请求摘要，不保存敏感明文。';
COMMENT ON COLUMN t_runtime_call_log.response_summary IS '响应摘要，不保存敏感明文。';
COMMENT ON COLUMN t_runtime_call_log.error_code IS '错误编码。';
COMMENT ON COLUMN t_runtime_call_log.error_message IS '错误信息摘要。';
COMMENT ON COLUMN t_runtime_call_log.latency_ms IS '调用耗时，单位毫秒。';
COMMENT ON COLUMN t_runtime_call_log.started_at IS '调用开始时间。';
COMMENT ON COLUMN t_runtime_call_log.finished_at IS '调用结束时间。';
COMMENT ON COLUMN t_runtime_call_log.metadata IS '扩展信息。';
COMMENT ON COLUMN t_runtime_call_log.created_at IS '创建时间。';

INSERT INTO t_system_config (category_code, config_code, config_name, description, sort_order, is_default, is_enabled, metadata)
VALUES
    ('search', 'iwencai_search', '问财搜索', '问财 Skill family 共享 Key 池。', 10, false, true, '{"source":"config-center-v2"}'::jsonb),
    ('search', 'miaoxiang_search', '妙想搜索', '妙想 Skill family 共享 Key 池。', 20, false, true, '{"source":"config-center-v2"}'::jsonb),
    ('search', 'kimi_search', 'Kimi Search', 'Kimi Web Search 共享 Key 池。', 30, false, true, '{"source":"config-center-v2"}'::jsonb),
    ('llm', 'kimi_llm', 'Kimi LLM', 'Moonshot Kimi 默认 LLM。', 10, true, true, '{"source":"config-center-v2"}'::jsonb),
    ('llm', 'kimi_llm_32k', 'Kimi LLM 32K', 'Moonshot Kimi 32K LLM。', 20, false, true, '{"source":"config-center-v2"}'::jsonb),
    ('llm', 'deepseek_chat', 'DeepSeek Chat', 'DeepSeek Chat OpenAI-compatible LLM。', 30, false, true, '{"source":"config-center-v2"}'::jsonb),
    ('llm', 'aliyun_coding_plan', '阿里云 Coding Plan', '阿里云百炼 Coding Plan OpenAI-compatible LLM。', 40, false, true, '{"source":"config-center-v2"}'::jsonb),
    ('llm', 'volcengine_coding_plan', '火山 Coding Plan', '火山方舟 Coding Plan OpenAI-compatible LLM。', 50, false, true, '{"source":"config-center-v2"}'::jsonb),
    ('llm', 'openai_compatible', 'OpenAI Compatible', '自定义 OpenAI-compatible LLM。', 100, false, true, '{"source":"config-center-v2"}'::jsonb),
    ('notification', 'feishu', '飞书通知', '飞书机器人 Webhook 通知。', 10, true, true, '{"source":"config-center-v2"}'::jsonb),
    ('notification', 'email', '邮件通知', 'SMTP 邮件通知。', 20, false, true, '{"source":"config-center-v2"}'::jsonb),
    ('notification', 'webhook', '自定义 Webhook', '自定义 Webhook 通知。', 30, false, true, '{"source":"config-center-v2"}'::jsonb)
ON CONFLICT (category_code, config_code) DO UPDATE SET
    config_name = EXCLUDED.config_name,
    description = EXCLUDED.description,
    sort_order = EXCLUDED.sort_order,
    is_enabled = EXCLUDED.is_enabled,
    metadata = t_system_config.metadata || EXCLUDED.metadata,
    updated_at = now();

WITH old_values AS (
    SELECT
        sk.id AS old_value_id,
        sk.config_node_id AS old_node_id,
        sk.key_name AS value_name,
        sk.key_type AS value_kind,
        sk.encrypted_secret AS encrypted_value,
        sk.secret_fingerprint AS fingerprint,
        sk.priority,
        sk.weight,
        sk.status,
        sk.failure_count,
        sk.last_used_at,
        sk.cooldown_until,
        sk.is_enabled,
        sk.description,
        sk.metadata AS old_metadata,
        sk.env_var_name,
        sk.created_at,
        sk.updated_at,
        n.domain,
        n.node_code,
        p.node_code AS parent_code
    FROM t_secret_key sk
    JOIN t_config_node n ON n.id = sk.config_node_id
    LEFT JOIN t_config_node p ON p.id = n.parent_id
    WHERE to_regclass('public.t_secret_key') IS NOT NULL
      AND to_regclass('public.t_config_node') IS NOT NULL
),
mapped_values AS (
    SELECT
        *,
        CASE
            WHEN domain = 'search' AND node_code IN ('iwencai_search', 'miaoxiang_search', 'kimi_search') THEN node_code
            WHEN domain = 'search' AND parent_code IN ('iwencai_search', 'miaoxiang_search', 'kimi_search') THEN parent_code
            WHEN domain = 'llm' AND node_code IN ('kimi_llm', 'deepseek_llm', 'aliyun_coding_plan', 'volcengine_coding_plan', 'openai_compatible') THEN
                CASE WHEN node_code = 'deepseek_llm' THEN 'deepseek_chat' ELSE node_code END
            WHEN domain = 'llm' AND parent_code = 'kimi_llm' AND node_code = 'moonshot_v1_32k' THEN 'kimi_llm_32k'
            WHEN domain = 'llm' AND parent_code = 'kimi_llm' THEN 'kimi_llm'
            WHEN domain = 'llm' AND parent_code = 'deepseek_llm' THEN 'deepseek_chat'
            WHEN domain = 'llm' AND parent_code IN ('aliyun_coding_plan', 'volcengine_coding_plan', 'openai_compatible') THEN parent_code
            WHEN domain = 'notification' AND node_code IN ('feishu', 'email', 'webhook') THEN node_code
            WHEN domain = 'notification' AND parent_code IN ('feishu', 'email', 'webhook') THEN parent_code
            ELSE NULL
        END AS target_config_code
    FROM old_values
)
INSERT INTO t_config_value (
    system_config_id,
    value_name,
    value_kind,
    encrypted_value,
    fingerprint,
    priority,
    weight,
    status,
    failure_count,
    last_used_at,
    cooldown_until,
    is_enabled,
    description,
    metadata,
    created_at,
    updated_at
)
SELECT
    sc.id,
    mv.value_name,
    mv.value_kind,
    mv.encrypted_value,
    mv.fingerprint,
    mv.priority,
    mv.weight,
    mv.status,
    mv.failure_count,
    mv.last_used_at,
    mv.cooldown_until,
    mv.is_enabled,
    COALESCE(mv.description, 'migrated from t_secret_key'),
    COALESCE(mv.old_metadata, '{}'::jsonb) || jsonb_build_object(
        'migrated_from', 'config-center-v1.t_secret_key',
        'old_value_id', mv.old_value_id,
        'old_node_id', mv.old_node_id,
        'old_env_var_name', mv.env_var_name
    ),
    mv.created_at,
    mv.updated_at
FROM mapped_values mv
JOIN t_system_config sc ON sc.category_code = mv.domain AND sc.config_code = mv.target_config_code
WHERE mv.target_config_code IS NOT NULL
  AND NOT EXISTS (
      SELECT 1
      FROM t_config_value existing
      WHERE existing.system_config_id = sc.id
        AND existing.value_kind = mv.value_kind
        AND existing.fingerprint = mv.fingerprint
  );

WITH legacy_provider_values AS (
    SELECT
        pk.id AS old_value_id,
        p.code AS provider_code,
        pk.key_name AS value_name,
        pk.encrypted_key AS encrypted_value,
        pk.secret_fingerprint AS fingerprint,
        pk.priority,
        pk.weight,
        pk.status,
        pk.failure_count,
        pk.last_used_at,
        pk.cooldown_until,
        pk.is_enabled,
        pk.created_at,
        pk.updated_at
    FROM provider_key pk
    JOIN provider p ON p.id = pk.provider_id
    WHERE to_regclass('public.provider_key') IS NOT NULL
      AND to_regclass('public.provider') IS NOT NULL
),
mapped_provider_values AS (
    SELECT
        *,
        CASE
            WHEN provider_code IN ('mx_finance_search','mx_finance_data','mx_macro_data','mx_stocks_screener','stock_diagnosis','fund_diagnosis','stock_market_hotspot_discovery','topic_research_report','industry_research_report','stock_earnings_review','mx_financial_assistant') THEN 'search'
            WHEN provider_code IN ('hithink_astock_selector','hithink_basicinfo_query','hithink_business_query','hithink_event_query','hithink_finance_query','hithink_industry_query','hithink_insresearch_query','hithink_macro_query','hithink_management_query','hithink_market_query','hithink_sector_selector','hithink_zhishu_query','announcement_search') THEN 'search'
            WHEN provider_code = 'kimi_web_search' THEN 'search'
            WHEN provider_code IN ('kimi_llm','deepseek_llm','aliyun_coding_plan','volcengine_coding_plan','openai_compatible') THEN 'llm'
            ELSE NULL
        END AS target_category_code,
        CASE
            WHEN provider_code IN ('mx_finance_search','mx_finance_data','mx_macro_data','mx_stocks_screener','stock_diagnosis','fund_diagnosis','stock_market_hotspot_discovery','topic_research_report','industry_research_report','stock_earnings_review','mx_financial_assistant') THEN 'miaoxiang_search'
            WHEN provider_code IN ('hithink_astock_selector','hithink_basicinfo_query','hithink_business_query','hithink_event_query','hithink_finance_query','hithink_industry_query','hithink_insresearch_query','hithink_macro_query','hithink_management_query','hithink_market_query','hithink_sector_selector','hithink_zhishu_query','announcement_search') THEN 'iwencai_search'
            WHEN provider_code = 'kimi_web_search' THEN 'kimi_search'
            WHEN provider_code = 'deepseek_llm' THEN 'deepseek_chat'
            WHEN provider_code IN ('kimi_llm','aliyun_coding_plan','volcengine_coding_plan','openai_compatible') THEN provider_code
            ELSE NULL
        END AS target_config_code
    FROM legacy_provider_values
)
INSERT INTO t_config_value (
    system_config_id,
    value_name,
    value_kind,
    encrypted_value,
    fingerprint,
    priority,
    weight,
    status,
    failure_count,
    last_used_at,
    cooldown_until,
    is_enabled,
    description,
    metadata,
    created_at,
    updated_at
)
SELECT
    sc.id,
    mpv.value_name,
    'api_key',
    mpv.encrypted_value,
    mpv.fingerprint,
    mpv.priority,
    mpv.weight,
    CASE WHEN mpv.status = 'cooling_down' THEN 'cooldown' ELSE mpv.status END,
    mpv.failure_count,
    mpv.last_used_at,
    mpv.cooldown_until,
    mpv.is_enabled,
    'migrated from stock-analysis provider_key ' || mpv.provider_code,
    jsonb_build_object(
        'migrated_from', 'stock-analysis.provider_key',
        'old_value_id', mpv.old_value_id,
        'old_provider_code', mpv.provider_code
    ),
    mpv.created_at,
    mpv.updated_at
FROM mapped_provider_values mpv
JOIN t_system_config sc ON sc.category_code = mpv.target_category_code AND sc.config_code = mpv.target_config_code
WHERE mpv.target_config_code IS NOT NULL
  AND NOT EXISTS (
      SELECT 1
      FROM t_config_value existing
      WHERE existing.system_config_id = sc.id
        AND existing.value_kind = 'api_key'
        AND existing.fingerprint = mpv.fingerprint
  );

WITH old_options AS (
    SELECT
        co.id AS old_option_id,
        co.config_node_id AS old_node_id,
        co.option_key,
        co.option_name,
        co.value_type,
        co.value_json AS option_value,
        co.default_value,
        co.is_required,
        co.is_enabled,
        co.description,
        co.metadata AS old_metadata,
        co.created_at,
        co.updated_at,
        n.domain,
        n.node_code,
        p.node_code AS parent_code
    FROM t_config_option_legacy_v1 co
    JOIN t_config_node n ON n.id = co.config_node_id
    LEFT JOIN t_config_node p ON p.id = n.parent_id
    WHERE to_regclass('public.t_config_option_legacy_v1') IS NOT NULL
      AND to_regclass('public.t_config_node') IS NOT NULL
),
mapped_options AS (
    SELECT
        *,
        CASE
            WHEN domain = 'llm' AND node_code IN ('kimi_llm','aliyun_coding_plan','volcengine_coding_plan','openai_compatible') THEN node_code
            WHEN domain = 'llm' AND node_code = 'deepseek_llm' THEN 'deepseek_chat'
            WHEN domain = 'llm' AND parent_code = 'kimi_llm' AND node_code = 'moonshot_v1_32k' THEN 'kimi_llm_32k'
            WHEN domain = 'llm' AND parent_code = 'kimi_llm' THEN 'kimi_llm'
            WHEN domain = 'llm' AND parent_code = 'deepseek_llm' THEN 'deepseek_chat'
            WHEN domain = 'llm' AND parent_code IN ('aliyun_coding_plan','volcengine_coding_plan','openai_compatible') THEN parent_code
            WHEN domain = 'notification' AND node_code IN ('feishu','email','webhook') THEN node_code
            WHEN domain = 'notification' AND parent_code IN ('feishu','email','webhook') THEN parent_code
            ELSE NULL
        END AS target_config_code
    FROM old_options
)
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
    metadata,
    created_at,
    updated_at
)
SELECT
    sc.id,
    mo.option_key,
    mo.option_name,
    mo.value_type,
    mo.option_value,
    mo.default_value,
    mo.is_required,
    mo.is_enabled,
    mo.description,
    COALESCE(mo.old_metadata, '{}'::jsonb) || jsonb_build_object(
        'migrated_from', 'config-center-v1.t_config_option',
        'old_option_id', mo.old_option_id,
        'old_node_id', mo.old_node_id
    ),
    mo.created_at,
    mo.updated_at
FROM mapped_options mo
JOIN t_system_config sc ON sc.category_code = mo.domain AND sc.config_code = mo.target_config_code
WHERE mo.target_config_code IS NOT NULL
ON CONFLICT (system_config_id, option_key) DO UPDATE SET
    option_name = EXCLUDED.option_name,
    value_type = EXCLUDED.value_type,
    option_value = EXCLUDED.option_value,
    default_value = EXCLUDED.default_value,
    is_required = EXCLUDED.is_required,
    is_enabled = EXCLUDED.is_enabled,
    description = EXCLUDED.description,
    metadata = t_config_option.metadata || EXCLUDED.metadata,
    updated_at = now();

WITH option_seed AS (
    SELECT *
    FROM (
        VALUES
            ('llm','kimi_llm','provider_code','Provider 编码','string','"kimi_llm"'::jsonb,'"kimi_llm"'::jsonb,true,'LLM provider 编码。'),
            ('llm','kimi_llm','model_name','模型名称','string','"moonshot-v1-8k"'::jsonb,'"moonshot-v1-8k"'::jsonb,true,'OpenAI-compatible model 字段。'),
            ('llm','kimi_llm','api_base_url','API Base URL','string','"https://api.moonshot.cn/v1"'::jsonb,'"https://api.moonshot.cn/v1"'::jsonb,true,'Kimi API 基础地址。'),
            ('llm','kimi_llm','temperature','采样温度','number','0.2'::jsonb,'0.2'::jsonb,false,'默认采样温度。'),
            ('llm','kimi_llm','max_tokens','最大输出 Tokens','number','2048'::jsonb,'2048'::jsonb,false,'默认最大输出 tokens。'),
            ('llm','kimi_llm','timeout_seconds','调用超时秒数','number','60'::jsonb,'60'::jsonb,false,'LLM HTTP 调用超时时间。'),
            ('llm','kimi_llm','response_format','默认响应格式','string','"text"'::jsonb,'"text"'::jsonb,false,'默认响应格式：text 或 json。'),
            ('llm','kimi_llm','system_prompt','系统提示词','string','"你是 A 股量化研究助手。只能基于输入上下文分析，不允许编造缺失数据。"'::jsonb,'"你是 A 股量化研究助手。只能基于输入上下文分析，不允许编造缺失数据。"'::jsonb,false,'默认系统提示词。'),
            ('llm','kimi_llm','max_context_chars','最大上下文字数','number','16000'::jsonb,'16000'::jsonb,false,'固定上下文包最大字符数。'),

            ('llm','kimi_llm_32k','provider_code','Provider 编码','string','"kimi_llm"'::jsonb,'"kimi_llm"'::jsonb,true,'LLM provider 编码。'),
            ('llm','kimi_llm_32k','model_name','模型名称','string','"moonshot-v1-32k"'::jsonb,'"moonshot-v1-32k"'::jsonb,true,'OpenAI-compatible model 字段。'),
            ('llm','kimi_llm_32k','api_base_url','API Base URL','string','"https://api.moonshot.cn/v1"'::jsonb,'"https://api.moonshot.cn/v1"'::jsonb,true,'Kimi API 基础地址。'),
            ('llm','kimi_llm_32k','temperature','采样温度','number','0.2'::jsonb,'0.2'::jsonb,false,'默认采样温度。'),
            ('llm','kimi_llm_32k','max_tokens','最大输出 Tokens','number','4096'::jsonb,'4096'::jsonb,false,'默认最大输出 tokens。'),
            ('llm','kimi_llm_32k','timeout_seconds','调用超时秒数','number','60'::jsonb,'60'::jsonb,false,'LLM HTTP 调用超时时间。'),
            ('llm','kimi_llm_32k','response_format','默认响应格式','string','"text"'::jsonb,'"text"'::jsonb,false,'默认响应格式：text 或 json。'),
            ('llm','kimi_llm_32k','system_prompt','系统提示词','string','"你是 A 股量化研究助手。只能基于输入上下文分析，不允许编造缺失数据。"'::jsonb,'"你是 A 股量化研究助手。只能基于输入上下文分析，不允许编造缺失数据。"'::jsonb,false,'默认系统提示词。'),
            ('llm','kimi_llm_32k','max_context_chars','最大上下文字数','number','32000'::jsonb,'32000'::jsonb,false,'固定上下文包最大字符数。'),

            ('llm','deepseek_chat','provider_code','Provider 编码','string','"deepseek_llm"'::jsonb,'"deepseek_llm"'::jsonb,true,'LLM provider 编码。'),
            ('llm','deepseek_chat','model_name','模型名称','string','"deepseek-chat"'::jsonb,'"deepseek-chat"'::jsonb,true,'OpenAI-compatible model 字段。'),
            ('llm','deepseek_chat','api_base_url','API Base URL','string','"https://api.deepseek.com"'::jsonb,'"https://api.deepseek.com"'::jsonb,true,'DeepSeek API 基础地址。'),
            ('llm','deepseek_chat','temperature','采样温度','number','0.2'::jsonb,'0.2'::jsonb,false,'默认采样温度。'),
            ('llm','deepseek_chat','max_tokens','最大输出 Tokens','number','2048'::jsonb,'2048'::jsonb,false,'默认最大输出 tokens。'),
            ('llm','deepseek_chat','timeout_seconds','调用超时秒数','number','60'::jsonb,'60'::jsonb,false,'LLM HTTP 调用超时时间。'),
            ('llm','deepseek_chat','response_format','默认响应格式','string','"text"'::jsonb,'"text"'::jsonb,false,'默认响应格式：text 或 json。'),
            ('llm','deepseek_chat','system_prompt','系统提示词','string','"你是 A 股量化研究助手。只能基于输入上下文分析，不允许编造缺失数据。"'::jsonb,'"你是 A 股量化研究助手。只能基于输入上下文分析，不允许编造缺失数据。"'::jsonb,false,'默认系统提示词。'),
            ('llm','deepseek_chat','max_context_chars','最大上下文字数','number','16000'::jsonb,'16000'::jsonb,false,'固定上下文包最大字符数。'),

            ('llm','aliyun_coding_plan','provider_code','Provider 编码','string','"aliyun_coding_plan"'::jsonb,'"aliyun_coding_plan"'::jsonb,true,'LLM provider 编码。'),
            ('llm','aliyun_coding_plan','model_name','模型名称','string','"qwen3-coder-next"'::jsonb,'"qwen3-coder-next"'::jsonb,true,'OpenAI-compatible model 字段。'),
            ('llm','aliyun_coding_plan','api_base_url','API Base URL','string','"https://coding.dashscope.aliyuncs.com/v1"'::jsonb,'"https://coding.dashscope.aliyuncs.com/v1"'::jsonb,true,'阿里云 Coding Plan API 基础地址。'),
            ('llm','aliyun_coding_plan','temperature','采样温度','number','0.2'::jsonb,'0.2'::jsonb,false,'默认采样温度。'),
            ('llm','aliyun_coding_plan','max_tokens','最大输出 Tokens','number','4096'::jsonb,'4096'::jsonb,false,'默认最大输出 tokens。'),
            ('llm','aliyun_coding_plan','timeout_seconds','调用超时秒数','number','60'::jsonb,'60'::jsonb,false,'LLM HTTP 调用超时时间。'),
            ('llm','aliyun_coding_plan','response_format','默认响应格式','string','"text"'::jsonb,'"text"'::jsonb,false,'默认响应格式：text 或 json。'),
            ('llm','aliyun_coding_plan','system_prompt','系统提示词','string','"你是 A 股量化研究助手。只能基于输入上下文分析，不允许编造缺失数据。"'::jsonb,'"你是 A 股量化研究助手。只能基于输入上下文分析，不允许编造缺失数据。"'::jsonb,false,'默认系统提示词。'),
            ('llm','aliyun_coding_plan','max_context_chars','最大上下文字数','number','32000'::jsonb,'32000'::jsonb,false,'固定上下文包最大字符数。'),

            ('llm','volcengine_coding_plan','provider_code','Provider 编码','string','"volcengine_coding_plan"'::jsonb,'"volcengine_coding_plan"'::jsonb,true,'LLM provider 编码。'),
            ('llm','volcengine_coding_plan','model_name','模型名称','string','"ark-code-latest"'::jsonb,'"ark-code-latest"'::jsonb,true,'OpenAI-compatible model 字段。'),
            ('llm','volcengine_coding_plan','api_base_url','API Base URL','string','"https://ark.cn-beijing.volces.com/api/coding/v3"'::jsonb,'"https://ark.cn-beijing.volces.com/api/coding/v3"'::jsonb,true,'火山 Coding Plan API 基础地址。'),
            ('llm','volcengine_coding_plan','temperature','采样温度','number','0.2'::jsonb,'0.2'::jsonb,false,'默认采样温度。'),
            ('llm','volcengine_coding_plan','max_tokens','最大输出 Tokens','number','4096'::jsonb,'4096'::jsonb,false,'默认最大输出 tokens。'),
            ('llm','volcengine_coding_plan','timeout_seconds','调用超时秒数','number','60'::jsonb,'60'::jsonb,false,'LLM HTTP 调用超时时间。'),
            ('llm','volcengine_coding_plan','response_format','默认响应格式','string','"text"'::jsonb,'"text"'::jsonb,false,'默认响应格式：text 或 json。'),
            ('llm','volcengine_coding_plan','system_prompt','系统提示词','string','"你是 A 股量化研究助手。只能基于输入上下文分析，不允许编造缺失数据。"'::jsonb,'"你是 A 股量化研究助手。只能基于输入上下文分析，不允许编造缺失数据。"'::jsonb,false,'默认系统提示词。'),
            ('llm','volcengine_coding_plan','max_context_chars','最大上下文字数','number','32000'::jsonb,'32000'::jsonb,false,'固定上下文包最大字符数。'),

            ('llm','openai_compatible','provider_code','Provider 编码','string','"openai_compatible"'::jsonb,'"openai_compatible"'::jsonb,true,'LLM provider 编码。'),
            ('llm','openai_compatible','model_name','模型名称','string','"gpt-4o-mini"'::jsonb,'"gpt-4o-mini"'::jsonb,true,'OpenAI-compatible model 字段。'),
            ('llm','openai_compatible','api_base_url','API Base URL','string','""'::jsonb,'""'::jsonb,true,'自定义 API 基础地址。'),
            ('llm','openai_compatible','temperature','采样温度','number','0.2'::jsonb,'0.2'::jsonb,false,'默认采样温度。'),
            ('llm','openai_compatible','max_tokens','最大输出 Tokens','number','2048'::jsonb,'2048'::jsonb,false,'默认最大输出 tokens。'),
            ('llm','openai_compatible','timeout_seconds','调用超时秒数','number','60'::jsonb,'60'::jsonb,false,'LLM HTTP 调用超时时间。'),
            ('llm','openai_compatible','response_format','默认响应格式','string','"text"'::jsonb,'"text"'::jsonb,false,'默认响应格式：text 或 json。'),
            ('llm','openai_compatible','system_prompt','系统提示词','string','"你是 A 股量化研究助手。只能基于输入上下文分析，不允许编造缺失数据。"'::jsonb,'"你是 A 股量化研究助手。只能基于输入上下文分析，不允许编造缺失数据。"'::jsonb,false,'默认系统提示词。'),
            ('llm','openai_compatible','max_context_chars','最大上下文字数','number','16000'::jsonb,'16000'::jsonb,false,'固定上下文包最大字符数。'),

            ('notification','feishu','message_template','消息模板','string','"{{title}}\n{{content}}"'::jsonb,'"{{title}}\n{{content}}"'::jsonb,false,'飞书机器人默认消息模板。'),
            ('notification','feishu','webhook_url','Webhook URL','string','""'::jsonb,'""'::jsonb,true,'飞书机器人 Webhook URL。'),
            ('notification','feishu','timeout_seconds','请求超时秒数','number','10'::jsonb,'10'::jsonb,false,'飞书 Webhook 请求超时时间。'),
            ('notification','email','smtp_host','SMTP Host','string','""'::jsonb,'""'::jsonb,true,'SMTP 服务器地址。'),
            ('notification','email','smtp_port','SMTP Port','number','587'::jsonb,'587'::jsonb,true,'SMTP 服务器端口。'),
            ('notification','email','use_tls','启用 TLS','boolean','true'::jsonb,'true'::jsonb,false,'是否使用 TLS。'),
            ('notification','email','from_addr','发件地址','string','""'::jsonb,'""'::jsonb,true,'默认发件邮箱地址。'),
            ('notification','email','username','用户名','string','""'::jsonb,'""'::jsonb,false,'SMTP 登录用户名。'),
            ('notification','email','smtp_password','SMTP Password','string','""'::jsonb,'""'::jsonb,false,'SMTP 登录密码。'),
            ('notification','webhook','method','请求方法','string','"POST"'::jsonb,'"POST"'::jsonb,true,'自定义 Webhook 请求方法。'),
            ('notification','webhook','webhook_url','Webhook URL','string','""'::jsonb,'""'::jsonb,true,'自定义 Webhook URL。'),
            ('notification','webhook','token','Token','string','""'::jsonb,'""'::jsonb,false,'自定义 Webhook Token。'),
            ('notification','webhook','headers','请求头 JSON','json','{}'::jsonb,'{}'::jsonb,false,'自定义 Webhook 非敏感请求头。'),
            ('notification','webhook','timeout_seconds','请求超时秒数','number','10'::jsonb,'10'::jsonb,false,'自定义 Webhook 请求超时时间。')
    ) AS v(category_code, config_code, option_key, option_name, value_type, option_value, default_value, is_required, description)
)
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
    os.option_key,
    os.option_name,
    os.value_type,
    os.option_value,
    os.default_value,
    os.is_required,
    true,
    os.description,
    '{"source":"config-center-v2-seed","non_secret":true}'::jsonb
FROM option_seed os
JOIN t_system_config sc ON sc.category_code = os.category_code AND sc.config_code = os.config_code
ON CONFLICT (system_config_id, option_key) DO NOTHING;

DO $$
DECLARE
    search_count INTEGER;
    llm_count INTEGER;
    notification_count INTEGER;
    llm_default_count INTEGER;
    aliyun_old_count INTEGER := 0;
    aliyun_new_count INTEGER := 0;
BEGIN
    SELECT count(*) INTO search_count FROM t_system_config WHERE category_code = 'search';
    SELECT count(*) INTO llm_count FROM t_system_config WHERE category_code = 'llm';
    SELECT count(*) INTO notification_count FROM t_system_config WHERE category_code = 'notification';
    SELECT count(*) INTO llm_default_count FROM t_system_config WHERE category_code = 'llm' AND is_default = true;

    IF search_count < 3 THEN
        RAISE EXCEPTION 'config v2 validation failed: search config count %, expected >= 3', search_count;
    END IF;
    IF llm_count < 5 THEN
        RAISE EXCEPTION 'config v2 validation failed: llm config count %, expected >= 5', llm_count;
    END IF;
    IF notification_count < 3 THEN
        RAISE EXCEPTION 'config v2 validation failed: notification config count %, expected >= 3', notification_count;
    END IF;
    IF llm_default_count <> 1 THEN
        RAISE EXCEPTION 'config v2 validation failed: llm default count %, expected 1', llm_default_count;
    END IF;

    IF to_regclass('public.t_secret_key') IS NOT NULL AND to_regclass('public.t_config_node') IS NOT NULL THEN
        SELECT count(*) INTO aliyun_old_count
        FROM t_secret_key sk
        JOIN t_config_node n ON n.id = sk.config_node_id
        LEFT JOIN t_config_node p ON p.id = n.parent_id
        WHERE n.node_code = 'aliyun_coding_plan' OR p.node_code = 'aliyun_coding_plan';
    END IF;

    SELECT count(*) INTO aliyun_new_count
    FROM t_config_value cv
    JOIN t_system_config sc ON sc.id = cv.system_config_id
    WHERE sc.category_code = 'llm' AND sc.config_code = 'aliyun_coding_plan';

    IF aliyun_old_count > 0 AND aliyun_new_count = 0 THEN
        RAISE EXCEPTION 'config v2 validation failed: old aliyun_coding_plan key exists but new value missing';
    END IF;
END $$;

DROP TABLE IF EXISTS t_config_relation;
DROP TABLE IF EXISTS t_config_option_legacy_v1;
DROP TABLE IF EXISTS t_runtime_call_log_legacy_v1;
DROP TABLE IF EXISTS t_secret_key;
DROP TABLE IF EXISTS t_config_node;

COMMIT;

SELECT
    category_code,
    count(*) AS config_count,
    count(*) FILTER (WHERE is_default) AS default_count
FROM t_system_config
GROUP BY category_code
ORDER BY category_code;

SELECT
    sc.category_code,
    sc.config_code,
    count(DISTINCT cv.id) FILTER (WHERE cv.status = 'active' AND cv.is_enabled) AS active_value_count,
    count(DISTINCT co.id) AS option_count
FROM t_system_config sc
LEFT JOIN t_config_value cv ON cv.system_config_id = sc.id
LEFT JOIN t_config_option co ON co.system_config_id = sc.id
GROUP BY sc.category_code, sc.config_code, sc.sort_order
ORDER BY sc.category_code, sc.sort_order;
