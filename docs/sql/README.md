# SQL 目录

所有数据库 SQL 统一放在本目录，避免 `docs/` 根目录混杂。

## 执行顺序

1. `01-schema.sql`：在原数据库中创建 Raw、Canonical、Derived 三层 `t_` 表和字段备注。
2. `02-stock-analysis-migration-mapping.sql`：从旧 `stock-analysis` 表迁移数据到新 `t_` 表。
3. `03-quant-data-capabilities.sql`：补齐资金流、龙虎榜、公告、因子定义等核心量化数据表，并给 `t_tick_trade` 增加 upsert 所需唯一约束。
4. `04-config-center.sql`：旧版配置中心递归树迁移脚本，仅作为历史来源和 v2 迁移输入。
5. `05-llm-runtime-bootstrap.sql`：旧版 LLM profile options seed，仅作为历史来源和 v2 迁移输入。
6. `06-llm-coding-plan.sql`：旧版 Coding Plan profile seed，仅作为历史来源和 v2 迁移输入。
7. `07-config-center-ui-seed.sql`：旧版 Notification UI options seed，仅作为历史来源和 v2 迁移输入。
8. `08-config-center-v2-rebuild.sql`：配置中心 v2 破坏式重建脚本，创建 `t_system_config/t_config_value/t_config_option`，迁移旧配置资产并删除旧配置表。
9. `09-scheduler-center.sql`：调度中心底座脚本，创建 `t_scheduler_job/t_scheduler_job_run`，只内置隐藏的 `scheduler_noop` 验证任务。
10. `10-market-data-sync-jobs.sql`：写入 `sync_sector_catalog` 和 `sync_stock_basic` 两个行情基础事实同步任务，默认禁用，先手动验证。

## 迁移建议

直接沿用原 `stock-analysis` 数据库。行情与量化数据表继续采用只新增不删除策略；配置中心 v2 例外，它会在校验通过后删除旧配置表，避免运行时继续依赖旧递归树。
