---
name: stock-center-wiki-maintainer
description: Maintain the stock-center project wiki and enforce wiki synchronization when changing backend code, Vue frontend, SQL, database schema, market data providers, query contracts, scheduler jobs, config center, LLM runtime, Skill runtime, migrations, or project architecture.
license: MIT
metadata:
  author: stock-center
  version: "1.0"
---

# Stock Center Wiki Maintainer

## Core Rule

Treat `stock-center-wiki/` as the project memory layer. Before changing or reviewing `stock-center`, read the wiki entrypoints and the task-specific page.

Always start with:

```text
stock-center-wiki/00-开始这里.md
stock-center-wiki/01-阅读路径.md
```

Then read the task-specific page:

| Task | Read |
| --- | --- |
| Overall architecture or migration | `stock-center-wiki/10-系统总览/系统地图.md` |
| Market data query/provider/schema behavior | `stock-center-wiki/20-核心流程/行情数据查询契约.md`, `stock-center-wiki/30-模块地图/行情数据模块.md` |
| Database or SQL changes | `stock-center-wiki/30-模块地图/数据库表索引.md` |
| Config center, Search, LLM, Notification, keys | `stock-center-wiki/30-模块地图/配置中心模块.md` |
| LLM runtime | `stock-center-wiki/30-模块地图/LLM运行时模块.md` |
| Skill runtime | `stock-center-wiki/30-模块地图/Skill运行时模块.md` |
| Scheduler jobs | `stock-center-wiki/30-模块地图/调度中心模块.md` |
| Vue frontend/admin pages | `stock-center-wiki/30-模块地图/前端配置中心模块.md` |
| Migrating from `stock-analysis` | `stock-center-wiki/50-变更手册/迁移自stock-analysis.md` |
| AI collaboration rules | `stock-center-wiki/60-AI协作规范/AI协作规则.md` |

## Update Rule

After any behavior, API, schema, SQL, provider, fallback, scheduler, Skill, LLM, frontend, migration, startup, or architecture change, update the relevant page in `stock-center-wiki/`.

Do not update wiki for pure formatting-only changes unless the formatting change affects how future agents understand the project.

## Project Boundaries

- `stock-analysis` is only a reference source.
- New implementation belongs in `stock-center`.
- Database assets are first-priority assets; do not delete or narrow migrated data to make an implementation simpler.
- New SQL belongs under `docs/sql/`.
- Do not write real secrets, API keys, database passwords, webhook URLs, or tokens into the wiki.

## Final Response Requirement

Final responses for this project must include one of:

```text
Wiki sync: updated - stock-center-wiki/...
```

or:

```text
Wiki sync: no update needed - <reason>
```

## Writing Rules

- Write wiki content in Chinese.
- Preserve code names, table names, API paths, provider names, config keys, and file paths in English.
- Prefer concise project memory over long implementation transcripts.
- Record decisions, boundaries, contracts, and validation commands that future agents need.
