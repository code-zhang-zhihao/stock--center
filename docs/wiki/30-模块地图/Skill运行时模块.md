# Skill运行时模块
<!-- wiki-migration -->

## 相关源码

- `python-back/app/modules/skill_runtime/registry.py`
- `python-back/app/modules/skill_runtime/capabilities.py`
- `python-back/app/modules/skill_runtime/runner.py`
- `python-back/app/modules/skill_runtime/service.py`
- `python-back/app/modules/skill_runtime/normalizer.py`
- `python-back/app/modules/skill_runtime/schemas.py`
- `python-back/resources/skills/`
- `python-back/data/skill_outputs/`

## 当前边界

`skill_runtime` 是内部 Python service，不暴露 `/api/v1/skills` API。它只负责运行旧项目迁移来的项目内 Skill 资源、做 family 级 Key 注入、执行超时控制、结果归档和 fallback 链路，不写具体业务分析逻辑。

Skill 本体第一阶段仍使用代码内注册表，不进入配置表。配置中心只复用 `search` 配置对象的 Key 池能力：

```text
search
  miaoxiang_search
  iwencai_search
  kimi_search
```

## 资源目录

旧项目资源已迁移到：

```text
python-back/resources/skills/
  mx-skills/
  skills/
```

输出归档目录：

```text
python-back/data/skill_outputs/{skill_code}/{trace_id}/skill-result.json
```

`python-back/data/` 不进入 git。

## 注册表规则

`SkillRegistry` 维护静态 `SkillSpec`：

- `code`：内部调用使用的唯一编码。
- `family`：`miaoxiang`、`hithink`、`kimi`、`generic`。
- `capabilities`：该 Skill 可参与的能力链。
- `entrypoint`：相对 `resources/skills` 的入口文件。
- `runtime`：`python` 或 `node`。
- `args_style`：不同旧 Skill 的命令行参数风格。
- `key_env`：需要注入的环境变量名。

第一阶段注册 27 个 Skill，覆盖妙想、问财、公告、新闻、研报和 Kimi Web Search。

## Key 规则

| family | 运行时兼容变量 | 配置对象 |
| --- | --- | --- |
| `miaoxiang` | `EM_API_KEY` | `search/miaoxiang_search` |
| `hithink` | `IWENCAI_API_KEY` | `search/iwencai_search` |
| `kimi` | `MOONSHOT_API_KEY` | `search/kimi_search` |
| `generic` | 无 | 不读取 Key |

运行时只读取 `active + enabled + 未 cooldown` 的 `api_key`。Key 按 `priority/weight/last_used_at` 排序；如果某个 Key 出现鉴权、失效、限额等错误，会标记失败并尝试下一个 active Key。Key 只注入子进程环境变量，不写入 stdout、stderr、日志或结果文件。

如果需要 Key 但配置中心没有可用 Key，返回 `skill_key_missing`。

旧项目 Key 迁移后，当前 family Key 池状态应至少包含：

- `miaoxiang_search`：旧妙想系列 provider 的多 Key 池。
- `iwencai_search`：旧问财系列 provider 的 Key。
- `kimi_search`：旧 `kimi_web_search` 的 Key。

迁移脚本为 `python-back/scripts/migrate_legacy_provider_keys.py`，脚本只迁移密文和指纹，不输出明文。

## 执行链路

`SkillRuntimeService` 提供：

- `list_skills()`：列出注册表中的 Skill。
- `run_skill()`：运行指定 Skill。
- `run_capability_chain()`：按 `capabilities.py` 中的顺序运行 fallback 链。

`SkillRunner` 负责：

- 检查 entrypoint 是否存在。
- 构造旧 Skill 对应命令行参数。
- 创建受控子进程。
- 注入必要环境变量。
- 控制 timeout。
- 捕获并截断 stdout/stderr。
- 解析 stdout JSON。
- 收集输出文件。
- 写入 `skill-result.json`。

## Capability Chain

第一阶段固定的能力链包括：

- `news_search`
- `announcement_search`
- `event_search`
- `report_search`
- `finance_data_query`
- `market_data_query`
- `stock_screening`
- `macro_query`
- `industry_query`
- `business_query`
- `management_query`
- `basic_info_query`
- `index_query`
- `fund_query`
- `stock_diagnosis`
- `hotspot_discovery`
- `topic_research`
- `earnings_review`
- `assistant_query`

`run_capability_chain()` 只负责顺序尝试和 fallback，不根据结果做策略判断。

## 日志

调用日志写入 `t_runtime_call_log`：

- `domain="skill"`
- `call_type="skill_run"`
- `config_value_id` 记录使用的敏感值 ID
- `capability` 记录调用能力
- `request_summary` 只记录 Skill、family 和 query 摘要
- `response_summary` 记录成功状态、耗时、归一化摘要和文件数

日志不得保存明文 Key。

## 与 LLM 的关系

第一阶段 LLM 不主动调用 Skill。后续如要让 LLM 使用 Skill，需要新增 `SkillContextProvider` 或 tool-calling runtime，并明确工具白名单、参数校验、调用预算和审计规则。

## 验证

```bash
cd python-back
source .venv/bin/activate
python -m compileall app
```

静态验证要求：

- `resources/skills` 目录存在。
- 注册表中所有 entrypoint 文件存在。
- Skill code 不重复。
- capability chain 引用的 Skill 都能在注册表找到。
- OpenAPI 不出现 `/api/v1/skills`。
