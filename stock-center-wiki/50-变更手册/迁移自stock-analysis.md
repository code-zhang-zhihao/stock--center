# 迁移自stock-analysis

## 原则

`stock-analysis` 只作为参考，不在其中继续实现新架构。迁移步骤：

1. 先读取旧代码和旧 wiki，确认能力和数据资产。
2. 在 `stock-center` 重新设计契约、表和模块边界。
3. 搬迁逻辑时优先搬字段映射和业务事实，不复制旧耦合结构。
4. 新能力必须同步 `stock-center-wiki`。

## 当前参考点

- 旧行情模块：`stock-analysis/python-api/app/modules/market_data/`
- 旧股票基础资料同步：`stock-analysis/python-api/app/modules/market_universe/`
- 旧配置模块：`stock-analysis/python-api/app/modules/system_config/`
- 旧 Provider/Key 模块：`stock-analysis/python-api/app/modules/provider_runtime/`
- 旧 LLM 模块：`stock-analysis/python-api/app/modules/llm_runtime/`
- 旧 Skill 资源：`stock-analysis/python-api/resources/skills/`
- 旧 Skill 模块：`stock-analysis/python-api/app/modules/skill_runtime/`
- 旧 Notification 模块：`stock-analysis/python-api/app/modules/notification/`
- 旧数据库：`stock-analysis/docs/database-*.sql`
- 旧 wiki：`stock-analysis/docs/wiki/`

详细迁移计划见 `docs/migration-from-stock-analysis.md`。

原数据库新增 `t_` 表迁移的执行手册见 `docs/existing-database-migration-runbook.md`。

## 配置中心迁移边界

配置中心 v2 只迁移 Search、LLM、Notification 和 Key：

- 旧 `provider` 映射为 `t_system_config`。
- 旧 `provider_key` 映射为 `t_config_value`。
- 旧 `llm_model_profile` 映射为 `t_system_config` 和 `t_config_option`。
- 旧 notification 配置映射为 `notification/feishu|email|webhook`。
- 旧 `provider_capability_route` 和配置 relation 不再迁入运行时模型。

旧 `skill_runtime` 的静态 Skill Registry 思路已迁移为新项目内部 `skill_runtime`。Skill 本体仍不进入配置中心；只通过配置中心复用 `search` 分类下的 family 级 Key 池。

## LLM 运行时迁移边界

旧 `llm_runtime` 的 OpenAI-compatible 调用、JSON 解析、usage 记录和错误日志思路可以参考，但新项目不恢复旧 `llm_model_profile` 独立表。新 `llm_runtime` 从配置中心 v2 读取 LLM 配置对象、options 和 Key，并把日志写入 `t_runtime_call_log`。

当前已迁移到配置中心的 LLM 配置对象：

- `kimi_llm`
- `kimi_llm_32k`
- `deepseek_chat`
- `aliyun_coding_plan`
- `volcengine_coding_plan`
- `openai_compatible`

阿里云百炼 Coding Plan 使用 `https://coding.dashscope.aliyuncs.com/v1` 和默认模型 `qwen3-coder-next`。火山方舟 Coding Plan 使用 `https://ark.cn-beijing.volces.com/api/coding/v3` 和默认模型 `ark-code-latest`。未指定 LLM 时读取 `llm` 分类的默认配置对象。

旧 `agent_tool_runtime` 的工具白名单思路暂不迁移为 tool-calling。第一版 LLM 分析只使用后端固定上下文包；Skill 和模型主动工具调用后续单独规划。

## Skill 运行时迁移边界

已迁移旧项目内 Skill 资源到 `python-back/resources/skills/`，并新增 `python-back/app/modules/skill_runtime/` 作为内部服务封装。

迁移内容：

- 妙想系列 Skill 资源。
- 问财系列 Skill 资源。
- 公告、新闻、研报和 Kimi Web Search 资源。
- 静态 Skill 注册表。
- 受控子进程执行、timeout、stdout/stderr 捕获、输出文件归档。
- capability fallback 链。
- `t_runtime_call_log` 审计日志。

不迁移内容：

- 旧业务调度。
- 旧策略分析。
- 市场情绪等业务计算。
- `/api/v1/skills` 对外 API。
- LLM 主动 tool-calling。

Key 规则：

- `miaoxiang` family 使用 `EM_API_KEY`，来自 `search_models/miaoxiang_search`。
- `hithink` family 使用 `IWENCAI_API_KEY`，来自 `search_models/iwencai_search`。
- `kimi` family 使用 `MOONSHOT_API_KEY`，来自 `search_models/kimi_search`。
- `generic` family 不读取 Key。

## 旧 Key 迁移

旧项目 `provider_key` 表使用 `CONFIG_MASTER_KEY` 加密保存业务 Key：

- `encrypted_key`：Fernet 密文。
- `secret_fingerprint`：明文 sha256 前 16 位。
- `status/is_enabled/priority/weight/cooldown_until`：Key 池选择状态。

新项目使用 `docs/sql/08-config-center-v2-rebuild.sql` 或 `python-back/scripts/migrate_legacy_provider_keys.py` 将旧 Key 迁移到 `t_config_value`。当新旧 `CONFIG_MASTER_KEY` 一致时，脚本会保留旧密文并可用 `--verify-decrypt` 校验指纹。

已确认映射：

- `mx_finance_search` -> `t_system_config(search, miaoxiang_search)`。
- `announcement_search` -> `t_system_config(search, iwencai_search)`。
- `kimi_web_search` -> `t_system_config(search, kimi_search)`。
- `aliyun_coding_plan` -> `t_system_config(llm, aliyun_coding_plan)`。

当前没有旧 `volcengine_coding_plan` Key；新系统只创建节点和 profile。

## 调度与基础资料同步迁移边界

旧项目“每周同步股票基础资料”的思路已迁移到新项目 `market_data` 模块，但不复制旧调度耦合结构。

已迁移：

- `sync_stock_basic`：每周同步 A 股基础资料，AkShare 主源，MooTDX fallback。
- `sync_sector_catalog`：每日同步概念/行业板块目录，并维护板块与股票关联。
- 两个任务写入 `t_scheduler_job`，默认 disabled，先手动验证。
- 任务运行日志写入 `t_scheduler_job_run`。
- Provider 原始响应通过 `t_provider_raw_record` 留痕。

不迁移：

- 旧 `scheduled_job` 表中的具体任务行。
- 旧业务调度器对行情、策略、通知的直接耦合。
- 旧市场情绪、策略扫描等业务任务。

新项目规则：

- 调度中心只负责触发、并发、日志和状态。
- 行情同步业务由 `MarketDataSyncService` 编排。
- 同步任务默认 `retry_count=0`，避免手动验证时外部源失败后长时间等待重试。
