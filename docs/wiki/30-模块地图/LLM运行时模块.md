# LLM运行时模块
<!-- wiki-migration -->

## 相关源码

- `python-back/app/modules/llm_runtime/schemas.py`
- `python-back/app/modules/llm_runtime/repository.py`
- `python-back/app/modules/llm_runtime/providers.py`
- `python-back/app/modules/llm_runtime/context.py`
- `python-back/app/modules/llm_runtime/service.py`
- `docs/sql/08-config-center-v2-rebuild.sql`

## 当前边界

`llm_runtime` 是内部 Python service，不暴露 `/api/v1/llm` API。它用于后续行情分析、公告分析、策略解释等服务内部调用。

第一版采用固定上下文包：

- 后端先调用本地 `MarketDataQueryService` 组装数据。
- LLM 只接收上下文 JSON 和用户问题。
- 不做模型主动 tool-calling。
- 不接入 Skill；Skill Runtime 已作为独立内部服务迁移，LLM 后续如需调用 Skill 需要单独增加 adapter 或 tool-calling 规划。
- 不让大模型直接访问本地 HTTP 服务或公网。

## 配置来源

LLM 配置来自配置中心 v2：

```text
llm
  kimi_llm
  kimi_llm_32k
  deepseek_chat
  aliyun_coding_plan
  volcengine_coding_plan
  openai_compatible
```

`docs/sql/08-config-center-v2-rebuild.sql` 写入非敏感 options：

- `provider_code`
- `model_name`
- `api_base_url`
- `temperature`
- `max_tokens`
- `timeout_seconds`
- `response_format`
- `system_prompt`
- `max_context_chars`

真实 Key 必须通过 `t_config_value` 写入，不允许写入 SQL 或 wiki。

当前默认模型配置：

| Provider | Profile | Model | API Base URL |
| --- | --- | --- | --- |
| Config | Model | API Base URL |
| --- | --- | --- |
| `kimi_llm` | `moonshot-v1-8k` | `https://api.moonshot.cn/v1` |
| `kimi_llm_32k` | `moonshot-v1-32k` | `https://api.moonshot.cn/v1` |
| `deepseek_chat` | `deepseek-chat` | `https://api.deepseek.com` |
| `aliyun_coding_plan` | `qwen3-coder-next` | `https://coding.dashscope.aliyuncs.com/v1` |
| `volcengine_coding_plan` | `ark-code-latest` | `https://ark.cn-beijing.volces.com/api/coding/v3` |
| `openai_compatible` | `gpt-4o-mini` | 需要手动配置 |

未指定 `config_code` 时使用 `llm` 分类中 `is_default=true` 的配置。阿里云百炼 Coding Plan 和火山方舟 Coding Plan 均走 OpenAI-compatible `/chat/completions`。

## 调用能力

`LlmRuntimeService` 提供：

- `chat()`：直接调用 OpenAI-compatible chat/completions。
- `analyze_with_context()`：先构建固定上下文包，再请求 LLM 分析。
- `analyze_json()`：强制 JSON 响应格式的分析快捷方法。

支持的上下文块：

- `stock_basic`
- `daily_bars`
- `minute_bars`
- `quote`
- `sectors`
- `fund_flow`
- `lhb`
- `announcements`
- `indicators`

## 安全规则

- Key 从 `t_config_value` 读取并用 `CONFIG_MASTER_KEY` 解密。
- 响应和日志不返回明文 Key 或 `encrypted_secret`。
- 日志写入 `t_runtime_call_log`，`domain="llm"`。
- `request_summary` 只保存消息数量、上下文块、字符长度等摘要。
- `response_summary` 只保存 usage、内容预览和 JSON 解析状态。
- 默认不使用 `refresh/provider_first/provider_only` 作为上下文查询模式，除非调用方显式允许。

## 验证

```bash
cd python-back
source .venv/bin/activate
python -m compileall app
```

数据库验证：

```sql
select count(*)
from t_config_option o
join t_system_config c on c.id = o.system_config_id
where c.category_code = 'llm';
```

执行 `08-config-center-v2-rebuild.sql` 后，LLM 配置对象预期为 6 个。

OpenAPI 验证：

- 不应出现 `/api/v1/llm`。
- 配置中心和行情接口数量不应减少。

Skill 验证：

- 不应出现 `/api/v1/skills`。
- LLM 当前调用链不应主动触发 `SkillRuntimeService`。
