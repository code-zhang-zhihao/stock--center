# AI协作规则
<!-- wiki-migration -->

## 必读

任何修改前先读：

- `stock-center-wiki/00-开始这里.md`
- `stock-center-wiki/01-阅读路径.md`
- 任务相关页面

Claude Code 使用项目内 skill：

```text
.claude/skills/stock-center-wiki-maintainer/SKILL.md
```

该 skill 是 `stock-center-wiki/` 的 Claude Code 入口，不是运行时代码。

## 必须同步 wiki 的情况

- 改 API 路径或响应字段。
- 改数据库表、字段、索引或 SQL。
- 改 Provider、fallback、query mode 或字段映射。
- 从 `stock-analysis` 迁移业务逻辑。
- 新增调度、Skill、LLM 或前端行为。

## 最终回复

最终回复必须说明：

```text
Wiki sync: updated - stock-center-wiki/...
```

或：

```text
Wiki sync: no update needed - <reason>
```
