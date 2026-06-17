-- stock-center LLM Coding Plan bootstrap.
-- Adds Aliyun and Volcengine Coding Plan providers/profiles to the config center.
-- This migration only writes non-secret config. Real API keys must be stored in t_secret_key.

BEGIN;

WITH llm_root AS (
    SELECT id
    FROM t_config_node
    WHERE domain = 'llm'
      AND node_code = 'llm_models'
      AND parent_id IS NULL
    LIMIT 1
),
provider_values AS (
    SELECT *
    FROM (
        VALUES
            ('aliyun_coding_plan', '阿里云百炼 Coding Plan', 30, '{"source":"stock-center-llm-coding-plan","plan_type":"coding_plan"}'::jsonb),
            ('volcengine_coding_plan', '火山方舟 Coding Plan', 40, '{"source":"stock-center-llm-coding-plan","plan_type":"coding_plan"}'::jsonb)
    ) AS v(node_code, node_name, sort_order, metadata)
),
inserted_providers AS (
    INSERT INTO t_config_node (parent_id, domain, node_code, node_name, node_type, sort_order, is_default, is_enabled, metadata)
    SELECT r.id, 'llm', v.node_code, v.node_name, 'provider', v.sort_order, false, true, v.metadata
    FROM llm_root r
    JOIN provider_values v ON true
    WHERE NOT EXISTS (
        SELECT 1
        FROM t_config_node existing
        WHERE existing.parent_id = r.id
          AND existing.domain = 'llm'
          AND existing.node_code = v.node_code
    )
    RETURNING id
)
UPDATE t_config_node n
SET
    node_name = v.node_name,
    node_type = 'provider',
    sort_order = v.sort_order,
    is_enabled = true,
    metadata = n.metadata || v.metadata,
    updated_at = now()
FROM llm_root r
JOIN provider_values v ON true
WHERE n.parent_id = r.id
  AND n.domain = 'llm'
  AND n.node_code = v.node_code;

WITH llm_root AS (
    SELECT id
    FROM t_config_node
    WHERE domain = 'llm'
      AND node_code = 'llm_models'
      AND parent_id IS NULL
    LIMIT 1
)
UPDATE t_config_node n
SET sort_order = 100, updated_at = now()
FROM llm_root r
WHERE n.parent_id = r.id
  AND n.domain = 'llm'
  AND n.node_code = 'openai_compatible';

WITH providers AS (
    SELECT p.id, p.node_code
    FROM t_config_node p
    JOIN t_config_node root ON root.id = p.parent_id
    WHERE root.domain = 'llm'
      AND root.node_code = 'llm_models'
      AND p.node_code IN ('aliyun_coding_plan', 'volcengine_coding_plan')
),
profile_values AS (
    SELECT *
    FROM (
        VALUES
            ('aliyun_coding_plan', 'aliyun_coding_default', '阿里云 Coding Plan 默认模型', 10, '{"source":"stock-center-llm-coding-plan","plan_type":"coding_plan"}'::jsonb),
            ('volcengine_coding_plan', 'volcengine_coding_default', '火山 Coding Plan 默认模型', 10, '{"source":"stock-center-llm-coding-plan","plan_type":"coding_plan"}'::jsonb)
    ) AS v(provider_code, node_code, node_name, sort_order, metadata)
),
inserted_profiles AS (
    INSERT INTO t_config_node (parent_id, domain, node_code, node_name, node_type, sort_order, is_default, is_enabled, metadata)
    SELECT p.id, 'llm', v.node_code, v.node_name, 'model', v.sort_order, false, true, v.metadata
    FROM providers p
    JOIN profile_values v ON v.provider_code = p.node_code
    WHERE NOT EXISTS (
        SELECT 1
        FROM t_config_node existing
        WHERE existing.parent_id = p.id
          AND existing.domain = 'llm'
          AND existing.node_code = v.node_code
    )
    RETURNING id
)
UPDATE t_config_node n
SET
    node_name = v.node_name,
    node_type = 'model',
    sort_order = v.sort_order,
    is_default = false,
    is_enabled = true,
    metadata = n.metadata || v.metadata,
    updated_at = now()
FROM providers p
JOIN profile_values v ON v.provider_code = p.node_code
WHERE n.parent_id = p.id
  AND n.domain = 'llm'
  AND n.node_code = v.node_code;

WITH profile_nodes AS (
    SELECT
        profile.id AS profile_id,
        provider.node_code AS provider_code,
        profile.node_code AS profile_code
    FROM t_config_node profile
    JOIN t_config_node provider ON provider.id = profile.parent_id
    JOIN t_config_node root ON root.id = provider.parent_id
    WHERE root.domain = 'llm'
      AND root.node_code = 'llm_models'
      AND provider.node_code IN ('aliyun_coding_plan', 'volcengine_coding_plan')
      AND profile.node_type IN ('model', 'profile')
),
seed_options AS (
    SELECT p.profile_id, v.option_key, v.option_name, v.value_type, v.value_json, v.default_value, v.description
    FROM profile_nodes p
    JOIN (
        VALUES
            ('aliyun_coding_plan', 'aliyun_coding_default', 'provider_code', 'Provider 编码', 'string', '"aliyun_coding_plan"'::jsonb, '"aliyun_coding_plan"'::jsonb, 'LLM provider 配置节点编码。'),
            ('aliyun_coding_plan', 'aliyun_coding_default', 'model_name', '模型名称', 'string', '"qwen3-coder-next"'::jsonb, '"qwen3-coder-next"'::jsonb, 'OpenAI-compatible chat/completions 的 model 字段。'),
            ('aliyun_coding_plan', 'aliyun_coding_default', 'api_base_url', 'API Base URL', 'string', '"https://coding.dashscope.aliyuncs.com/v1"'::jsonb, '"https://coding.dashscope.aliyuncs.com/v1"'::jsonb, '阿里云百炼 Coding Plan OpenAI-compatible API 基础地址。'),
            ('aliyun_coding_plan', 'aliyun_coding_default', 'temperature', '采样温度', 'number', '0.2'::jsonb, '0.2'::jsonb, '默认采样温度。'),
            ('aliyun_coding_plan', 'aliyun_coding_default', 'max_tokens', '最大输出 Tokens', 'number', '4096'::jsonb, '4096'::jsonb, '默认最大输出 tokens。'),
            ('aliyun_coding_plan', 'aliyun_coding_default', 'timeout_seconds', '调用超时秒数', 'number', '60'::jsonb, '60'::jsonb, 'LLM HTTP 调用超时时间。'),
            ('aliyun_coding_plan', 'aliyun_coding_default', 'response_format', '默认响应格式', 'string', '"text"'::jsonb, '"text"'::jsonb, '默认响应格式：text 或 json。'),
            ('aliyun_coding_plan', 'aliyun_coding_default', 'system_prompt', '系统提示词', 'string', '"你是 A 股量化研究助手。只能基于输入上下文分析，不允许编造缺失数据。"'::jsonb, '"你是 A 股量化研究助手。只能基于输入上下文分析，不允许编造缺失数据。"'::jsonb, '默认系统提示词。'),
            ('aliyun_coding_plan', 'aliyun_coding_default', 'max_context_chars', '最大上下文字数', 'number', '32000'::jsonb, '32000'::jsonb, '固定上下文包序列化后的最大字符数。'),

            ('volcengine_coding_plan', 'volcengine_coding_default', 'provider_code', 'Provider 编码', 'string', '"volcengine_coding_plan"'::jsonb, '"volcengine_coding_plan"'::jsonb, 'LLM provider 配置节点编码。'),
            ('volcengine_coding_plan', 'volcengine_coding_default', 'model_name', '模型名称', 'string', '"ark-code-latest"'::jsonb, '"ark-code-latest"'::jsonb, 'OpenAI-compatible chat/completions 的 model 字段。'),
            ('volcengine_coding_plan', 'volcengine_coding_default', 'api_base_url', 'API Base URL', 'string', '"https://ark.cn-beijing.volces.com/api/coding/v3"'::jsonb, '"https://ark.cn-beijing.volces.com/api/coding/v3"'::jsonb, '火山方舟 Coding Plan OpenAI-compatible API 基础地址。'),
            ('volcengine_coding_plan', 'volcengine_coding_default', 'temperature', '采样温度', 'number', '0.2'::jsonb, '0.2'::jsonb, '默认采样温度。'),
            ('volcengine_coding_plan', 'volcengine_coding_default', 'max_tokens', '最大输出 Tokens', 'number', '4096'::jsonb, '4096'::jsonb, '默认最大输出 tokens。'),
            ('volcengine_coding_plan', 'volcengine_coding_default', 'timeout_seconds', '调用超时秒数', 'number', '60'::jsonb, '60'::jsonb, 'LLM HTTP 调用超时时间。'),
            ('volcengine_coding_plan', 'volcengine_coding_default', 'response_format', '默认响应格式', 'string', '"text"'::jsonb, '"text"'::jsonb, '默认响应格式：text 或 json。'),
            ('volcengine_coding_plan', 'volcengine_coding_default', 'system_prompt', '系统提示词', 'string', '"你是 A 股量化研究助手。只能基于输入上下文分析，不允许编造缺失数据。"'::jsonb, '"你是 A 股量化研究助手。只能基于输入上下文分析，不允许编造缺失数据。"'::jsonb, '默认系统提示词。'),
            ('volcengine_coding_plan', 'volcengine_coding_default', 'max_context_chars', '最大上下文字数', 'number', '32000'::jsonb, '32000'::jsonb, '固定上下文包序列化后的最大字符数。')
    ) AS v(provider_code, profile_code, option_key, option_name, value_type, value_json, default_value, description)
        ON p.provider_code = v.provider_code AND p.profile_code = v.profile_code
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
    profile_id,
    option_key,
    option_name,
    value_type,
    value_json,
    default_value,
    '{}'::jsonb,
    option_key IN ('provider_code', 'model_name', 'api_base_url'),
    true,
    description,
    '{"source": "stock-center-llm-coding-plan"}'::jsonb
FROM seed_options
ON CONFLICT (config_node_id, option_key) DO UPDATE SET
    option_name = EXCLUDED.option_name,
    value_type = EXCLUDED.value_type,
    value_json = EXCLUDED.value_json,
    default_value = EXCLUDED.default_value,
    validation_rules = EXCLUDED.validation_rules,
    is_required = EXCLUDED.is_required,
    is_enabled = EXCLUDED.is_enabled,
    description = EXCLUDED.description,
    metadata = EXCLUDED.metadata,
    version = t_config_option.version + 1,
    updated_at = now();

COMMIT;
