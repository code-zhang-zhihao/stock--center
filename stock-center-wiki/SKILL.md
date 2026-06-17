---
name: stock-center-wiki
description: Maintain the stock-center project wiki and enforce synchronization when migrating or changing stock-center code, database schema, market data providers, query contracts, scheduler jobs, Skill/LLM integration, or frontend behavior.
---

# Stock Center Wiki Maintainer

## Core Rule

Treat `stock-center-wiki/` as the project memory layer. Before changing `stock-center`, read:

1. `stock-center-wiki/00-开始这里.md`
2. `stock-center-wiki/01-阅读路径.md`
3. The task-specific page under `20-核心流程/`, `30-模块地图/`, or `50-变更手册/`

After any behavior, schema, API, provider, scheduler, Skill, LLM, frontend, or migration change, update the relevant wiki page.

## Final Response Requirement

Final responses for this project should include one of:

```text
Wiki sync: updated - stock-center-wiki/...
```

or:

```text
Wiki sync: no update needed - <reason>
```

## Writing Rules

- Wiki content is Chinese.
- Preserve code names, table names, paths, provider names, API paths, and config keys in English.
- Never write real secrets, API keys, database passwords, or webhooks into wiki.
- `stock-analysis` is a reference source only; new implementation belongs in `stock-center`.
