-- stock-center LLM runtime bootstrap.
-- Seeds non-secret LLM profile options into the existing config center tables.
-- This migration does not create tables and never writes real API keys.

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
      AND profile.node_type IN ('model', 'profile')
),
seed_options AS (
    SELECT p.profile_id, v.option_key, v.option_name, v.value_type, v.value_json, v.default_value, v.description
    FROM profile_nodes p
    JOIN (
        VALUES
            ('kimi_llm', 'moonshot_v1_8k', 'provider_code', 'Provider 编码', 'string', '"kimi_llm"'::jsonb, '"kimi_llm"'::jsonb, 'LLM provider 配置节点编码。'),
            ('kimi_llm', 'moonshot_v1_8k', 'model_name', '模型名称', 'string', '"moonshot-v1-8k"'::jsonb, '"moonshot-v1-8k"'::jsonb, 'OpenAI-compatible chat/completions 的 model 字段。'),
            ('kimi_llm', 'moonshot_v1_8k', 'api_base_url', 'API Base URL', 'string', '"https://api.moonshot.cn/v1"'::jsonb, '"https://api.moonshot.cn/v1"'::jsonb, 'OpenAI-compatible API 基础地址。'),
            ('kimi_llm', 'moonshot_v1_8k', 'temperature', '采样温度', 'number', '0.2'::jsonb, '0.2'::jsonb, '默认采样温度。'),
            ('kimi_llm', 'moonshot_v1_8k', 'max_tokens', '最大输出 Tokens', 'number', '2048'::jsonb, '2048'::jsonb, '默认最大输出 tokens。'),
            ('kimi_llm', 'moonshot_v1_8k', 'timeout_seconds', '调用超时秒数', 'number', '60'::jsonb, '60'::jsonb, 'LLM HTTP 调用超时时间。'),
            ('kimi_llm', 'moonshot_v1_8k', 'response_format', '默认响应格式', 'string', '"text"'::jsonb, '"text"'::jsonb, '默认响应格式：text 或 json。'),
            ('kimi_llm', 'moonshot_v1_8k', 'system_prompt', '系统提示词', 'string', '"你是 A 股量化研究助手。只能基于输入上下文分析，不允许编造缺失数据。"'::jsonb, '"你是 A 股量化研究助手。只能基于输入上下文分析，不允许编造缺失数据。"'::jsonb, '默认系统提示词。'),
            ('kimi_llm', 'moonshot_v1_8k', 'max_context_chars', '最大上下文字数', 'number', '16000'::jsonb, '16000'::jsonb, '固定上下文包序列化后的最大字符数。'),

            ('kimi_llm', 'moonshot_v1_32k', 'provider_code', 'Provider 编码', 'string', '"kimi_llm"'::jsonb, '"kimi_llm"'::jsonb, 'LLM provider 配置节点编码。'),
            ('kimi_llm', 'moonshot_v1_32k', 'model_name', '模型名称', 'string', '"moonshot-v1-32k"'::jsonb, '"moonshot-v1-32k"'::jsonb, 'OpenAI-compatible chat/completions 的 model 字段。'),
            ('kimi_llm', 'moonshot_v1_32k', 'api_base_url', 'API Base URL', 'string', '"https://api.moonshot.cn/v1"'::jsonb, '"https://api.moonshot.cn/v1"'::jsonb, 'OpenAI-compatible API 基础地址。'),
            ('kimi_llm', 'moonshot_v1_32k', 'temperature', '采样温度', 'number', '0.2'::jsonb, '0.2'::jsonb, '默认采样温度。'),
            ('kimi_llm', 'moonshot_v1_32k', 'max_tokens', '最大输出 Tokens', 'number', '4096'::jsonb, '4096'::jsonb, '默认最大输出 tokens。'),
            ('kimi_llm', 'moonshot_v1_32k', 'timeout_seconds', '调用超时秒数', 'number', '60'::jsonb, '60'::jsonb, 'LLM HTTP 调用超时时间。'),
            ('kimi_llm', 'moonshot_v1_32k', 'response_format', '默认响应格式', 'string', '"text"'::jsonb, '"text"'::jsonb, '默认响应格式：text 或 json。'),
            ('kimi_llm', 'moonshot_v1_32k', 'system_prompt', '系统提示词', 'string', '"你是 A 股量化研究助手。只能基于输入上下文分析，不允许编造缺失数据。"'::jsonb, '"你是 A 股量化研究助手。只能基于输入上下文分析，不允许编造缺失数据。"'::jsonb, '默认系统提示词。'),
            ('kimi_llm', 'moonshot_v1_32k', 'max_context_chars', '最大上下文字数', 'number', '32000'::jsonb, '32000'::jsonb, '固定上下文包序列化后的最大字符数。'),

            ('deepseek_llm', 'deepseek_chat', 'provider_code', 'Provider 编码', 'string', '"deepseek_llm"'::jsonb, '"deepseek_llm"'::jsonb, 'LLM provider 配置节点编码。'),
            ('deepseek_llm', 'deepseek_chat', 'model_name', '模型名称', 'string', '"deepseek-chat"'::jsonb, '"deepseek-chat"'::jsonb, 'OpenAI-compatible chat/completions 的 model 字段。'),
            ('deepseek_llm', 'deepseek_chat', 'api_base_url', 'API Base URL', 'string', '"https://api.deepseek.com"'::jsonb, '"https://api.deepseek.com"'::jsonb, 'OpenAI-compatible API 基础地址。'),
            ('deepseek_llm', 'deepseek_chat', 'temperature', '采样温度', 'number', '0.2'::jsonb, '0.2'::jsonb, '默认采样温度。'),
            ('deepseek_llm', 'deepseek_chat', 'max_tokens', '最大输出 Tokens', 'number', '2048'::jsonb, '2048'::jsonb, '默认最大输出 tokens。'),
            ('deepseek_llm', 'deepseek_chat', 'timeout_seconds', '调用超时秒数', 'number', '60'::jsonb, '60'::jsonb, 'LLM HTTP 调用超时时间。'),
            ('deepseek_llm', 'deepseek_chat', 'response_format', '默认响应格式', 'string', '"text"'::jsonb, '"text"'::jsonb, '默认响应格式：text 或 json。'),
            ('deepseek_llm', 'deepseek_chat', 'system_prompt', '系统提示词', 'string', '"你是 A 股量化研究助手。只能基于输入上下文分析，不允许编造缺失数据。"'::jsonb, '"你是 A 股量化研究助手。只能基于输入上下文分析，不允许编造缺失数据。"'::jsonb, '默认系统提示词。'),
            ('deepseek_llm', 'deepseek_chat', 'max_context_chars', '最大上下文字数', 'number', '16000'::jsonb, '16000'::jsonb, '固定上下文包序列化后的最大字符数。'),

            ('openai_compatible', 'default', 'provider_code', 'Provider 编码', 'string', '"openai_compatible"'::jsonb, '"openai_compatible"'::jsonb, 'LLM provider 配置节点编码。'),
            ('openai_compatible', 'default', 'model_name', '模型名称', 'string', '"gpt-4o-mini"'::jsonb, '"gpt-4o-mini"'::jsonb, 'OpenAI-compatible chat/completions 的 model 字段。'),
            ('openai_compatible', 'default', 'api_base_url', 'API Base URL', 'string', '""'::jsonb, '""'::jsonb, 'OpenAI-compatible API 基础地址，需要按实际服务填写。'),
            ('openai_compatible', 'default', 'temperature', '采样温度', 'number', '0.2'::jsonb, '0.2'::jsonb, '默认采样温度。'),
            ('openai_compatible', 'default', 'max_tokens', '最大输出 Tokens', 'number', '2048'::jsonb, '2048'::jsonb, '默认最大输出 tokens。'),
            ('openai_compatible', 'default', 'timeout_seconds', '调用超时秒数', 'number', '60'::jsonb, '60'::jsonb, 'LLM HTTP 调用超时时间。'),
            ('openai_compatible', 'default', 'response_format', '默认响应格式', 'string', '"text"'::jsonb, '"text"'::jsonb, '默认响应格式：text 或 json。'),
            ('openai_compatible', 'default', 'system_prompt', '系统提示词', 'string', '"你是 A 股量化研究助手。只能基于输入上下文分析，不允许编造缺失数据。"'::jsonb, '"你是 A 股量化研究助手。只能基于输入上下文分析，不允许编造缺失数据。"'::jsonb, '默认系统提示词。'),
            ('openai_compatible', 'default', 'max_context_chars', '最大上下文字数', 'number', '16000'::jsonb, '16000'::jsonb, '固定上下文包序列化后的最大字符数。')
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
    option_key IN ('provider_code', 'model_name'),
    true,
    description,
    '{"source": "stock-center-llm-bootstrap"}'::jsonb
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
