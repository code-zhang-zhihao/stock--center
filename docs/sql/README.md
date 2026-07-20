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
11. `11-sector-component-current-snapshot.sql`：更新板块同步任务为当前快照模式；完整快照才物理删除缺失关联，部分结果不删除。
12. `12-tushare-pro-a-share.sql`：新增 `market_data/tushare_pro` 固定配置、加密 Token 池参数、A 股扩展 Canonical 事实表以及默认禁用的 Tushare 专题同步任务。
13. `13-tushare-token-endpoint.sql`：为 Tushare Token 增加可选的专属 API URL；为空时继续使用 `tushare_pro` 的全局 `api_url`。
14. `14-tushare-rate-governance.sql`：补齐 Tushare 交互与调度的共享限流等待、网络退避参数。
15. `15-stock-pool-center.sql`：创建 `t_stock_pool/t_stock_pool_member`，并 seed 候选观察、重点监控、持仓监控、断板反包四个系统池。
16. `16-daily-market-close-ingest.sql`：增加动态 `all_a_share` 股票范围，将分钟线/分钟因子迁为按交易日分区表，并 seed 全市场每日收盘数据沉淀任务；其中 EOD quote 设计已由 `45` 废弃。
17. `17-market-volume-bigint-fix.sql`：将行情成交量列修正为 `BIGINT`，兼容早期数据库中仍为 `INTEGER` 的旧列，避免全市场 Tushare 日线写入时成交量超出 int32 范围。
18. `18-market-partition-owner-fix.sql`：将分钟线和分钟因子分区父表及现有子分区 owner 调整为应用账号 `stock_analysis_app`，并预建 `2026-06-26` 分区用于收盘任务恢复。
19. `19-daily-close-ingest-batching.sql`：更新旧 `daily_market_close_ingest` 的调度参数，增加分钟线/收盘快照批次大小；其中收盘快照批次参数已由 `45` 废弃。
20. `20-market-partition-identity-fix.sql`：补齐 `t_minute_bar/t_stock_factor_minute` 分区父表 `id` 的 identity/default 生成器，消除批量插入时 `id` 无默认值的风险。
21. `21-daily-close-canonical-consolidation.sql`：收口每日量化沉淀为 canonical 单业务事实，补齐北向持股和板块因子表，并隐藏废弃的 Tushare 专题同步任务。
22. `22-complete-daily-close-factors.sql`：补齐每日收盘沉淀的个股资金因子和板块聚合因子定义，只更新 `t_factor_definition`，不改表结构。
23. `23-exclude-bse-from-daily-universe.sql`：将北交所/BSE 股票标记为 `excluded`，并清理股票池成员里的北交关联；历史行情事实不删除。
24. `24-daily-close-technical-chip-global.sql`：补齐每日收盘沉淀的专业技术因子、筹码胜率、市场交易统计和指数每日指标表，扩展 `daily_basic` 字段。
25. `25-daily-close-index-fallback-and-north-hold-deprecate.sql`：更新每日收盘任务元数据，关闭日度北向 A 股持股默认沉淀，并说明核心指数日线 fallback 链路。
26. `26-split-daily-close-ingest.sql`：将旧 `daily_market_close_ingest` 拆分为核心、增强、修复三段任务，并删除 `cyq_chips` 筹码分布明细业务表。
27. `27-stock-basic-status-normalization.sql`：收口每周股票基础资料同步状态口径，北交所/BJ/BSE 统一为 `excluded`，不进入沪深 active universe。
28. `28-trade-calendar-sync-job.sql`：新增 `sync_trade_calendar` 调度任务，沿用旧项目 `chinese_calendar` 规则生成 CN 交易日历。
29. `29-stock-daily-backfill-job.sql`：新增 `backfill_stock_daily_bars` 历史日 K 回填任务，按股票池调用 Tushare `daily` 安全补齐 `t_daily_bar`。
30. `30-daily-close-enrichment-concurrency.sql`：为 `daily_close_enrichment_ingest` 和 `daily_close_repair_ingest` 补充增强块并发、`cyq_perf` worker 和分批提交参数。
31. `31-provider-standardization-and-remove-cyq-batch.sql`：首批 Provider 标准化配套脚本，移除增强/修复任务中的 `cyq_perf` 全市场批量沉淀参数，仅保留历史筹码胜率表。
32. `32-normalize-stock-moneyflow-yuan.sql`：将历史 Tushare 个股资金流从万元口径归一到元，并写入单位迁移 metadata；已由新 adapter 写入元口径的行不会重复乘数。
33. `33-refresh-stock-fund-factor-ratios.sql`：资金流单位归一后，刷新 `t_stock_factor_daily.features` 中的资金净流入与资金占比字段。
34. `34-stock-daily-basic-moneyflow-backfill-jobs.sql`：新增 `backfill_stock_daily_basic` 和 `backfill_stock_moneyflow` 两个历史初始化回填任务，按股票池逐股区间调用 Tushare 并安全补齐日频估值/流动性和个股资金流。
35. `35-factor-backfill-jobs.sql`：新增 `backfill_daily_factors` 和 `backfill_sector_factors` 两个历史因子回填任务，只读 canonical/derived 表重算因子，不调用外部 Provider。
36. `36-backfill-ingest-mode.sql`：为历史事实/因子回填任务统一增加 `ingest_mode=append_safe|rebuild`，明确安全补缺和目标范围重建两种模式。
37. `37-data-assets-inspection-indexes.sql`：为数据中心巡检补充按 `trade_date`/快照时间前导的索引，避免最新交易日和快照时间查询扫大表。
38. `38-stock-basic-delisted-name-normalization.sql`：修正股票主数据中名称已为 `退市*` 但仍被标记为 `active` 的行，并从股票池成员关系中移除这些退市股。
39. `39-index-catalog-sync-job.sql`：新增 `sync_index_catalog` 调度任务，低频同步核心指数基础资料和指数成分股，补齐 `t_index_basic/t_index_component`。
40. `40-index-component-current-master.sql`：将 `t_index_component` 从按日期/source 保留快照收口为当前主数据，唯一键改为 `index_code + stock_code`。
41. `41-index-weight-lookback-months.sql`：清理 `t_index_component` 旧快照口径冗余唯一约束，并为 `sync_index_catalog` 增加 `weight_lookback_months=3` 参数，Tushare `index_weight` 默认查询最近 3 个自然月并取最新完整权重日期。
42. `42-data-asset-health-cache.sql`：seed `refresh_data_asset_health` 定时刷新任务；数据中心健康度缓存写入 Redis，不创建 PostgreSQL 缓存表。
43. `43-redis-cache-data-source.sql`：新增或补齐 `market_data/redis_cache` 数据源配置对象；Redis URL 作为加密 `redis_url` 敏感值维护，非敏感缓存参数写入 `t_config_option`。该脚本可重复执行，当前会启用 `data_asset_cache_ttl_seconds` 作为数据中心缓存默认 TTL，并补齐 `default_cache_ttl_seconds`、`data_asset_summary_ttl_seconds`、`data_asset_daily_health_ttl_seconds`。
44. `44-backfill-append-safe-enforcement.sql`：强制历史个股日线、daily basic、资金流回填任务默认 `ingest_mode=append_safe` 且 `only_missing=true`，防止重复手动运行时制造重复事实。
45. `45-deprecate-eod-quote-snapshot.sql`：废弃 EOD quote 作为 daily canonical 事实和数据中心完整性项；保留历史 `t_quote_snapshot` 行但不再由每日核心沉淀任务写入。
46. `46-technical-snapshot-backfill-job.sql`：新增 `backfill_technical_snapshots` 调度任务，按股票池和交易日区间重算技术快照，只读 canonical/derived 表，不调用外部 Provider。
47. `47-backfill-moneyflow-date-span-guard.sql`：历史过渡脚本，曾为 `backfill_stock_moneyflow` 增加日期分片参数；实际口径已由 `48` 改为按写库行数分批。
48. `48-backfill-moneyflow-row-batch.sql`：修正历史个股资金流回填为“单股完整区间请求 + 数据库按行数分批提交”，避免日期分片放大 Tushare 请求次数。
49. `49-stock-technical-factor-pro-backfill-job.sql`：新增 `backfill_stock_technical_factor_pro` 历史专业技术因子回填任务，按股票池逐股区间调用 Tushare `stk_factor_pro`，安全补齐 `t_stock_technical_factor_daily`。
50. `50-daily-factor-backfill-date-workers.sql`：历史版本，为 `backfill_daily_factors` 增加过交易日级并发参数；已由 51 替代。
51. `51-daily-factor-backfill-window-batching.sql`：历史版本，将 `backfill_daily_factors` 调整为连续交易日窗口批处理；已由 52 的 PostgreSQL 集合计算替代。
52. `52-daily-factor-backfill-set-based.sql`：历史日频因子回填改为 PostgreSQL 集合计算，移除 Python 计算和时间窗口并发参数，保留交易日窗口与受控数据库股票分片大小。
53. `53-realtime-market-runtime.sql`：新增 `market_data/realtime_market` 固定配置，seed MooTDX 全市场 Quote 与优先股票分钟线实时缓存参数；数据只写 Redis/内存，不写 PostgreSQL 日频事实。
54. `54-backfill-minute-factor-and-technical-snapshot.sql`：将 `backfill_technical_snapshots` 收口为历史分钟因子与技术快照回填；`rebuild` 会同时重算 `t_stock_factor_minute` 和 `t_technical_indicator_snapshot`，用于公式升级后的可控修复。
55. `55-data-asset-history-pipelines.sql`：建立历史初始化入口基线。新增 `t_stock_factor_daily.ma30/ma60` 和 `t_index_factor_daily`，seed 个股/板块/指数各“日频事实 + 日频因子”两段任务，并删除被替换的 7 条旧任务定义；历史运行日志保留。
56. `56-sector-history-range-backfill.sql`：修正历史板块日频事实任务参数。`ths_daily` 改为逐板块一次完整日期区间请求，默认 12 个板块 worker；板块资金流默认使用已实测验证的 20 交易日窗口和 2 个窗口 worker。
57. `57-stock-history-limit-events.sql`：将 `limit_list_d/suspend_d` 按交易日全市场查询阶段加入 `backfill_stock_daily_facts`，补齐 `t_limit_event_daily` 的历史涨跌停与停牌事件；把旧 `Z` 池归一为 `limit_break`，并兼容特定历史区间 U 池标志为空但带 `up_stat` 的响应。

## 产品化初始化规划

当前 01-56 是开发期演进 SQL，适合追踪架构变更，但不适合作为最终产品部署入口。下一轮数据库收敛需要生成：

```text
docs/sql/init.sql
docs/sql/db-init.sql
```

目标：

- `init.sql` 创建完整 schema、表、索引、字段 comment、基础 seed、配置对象 seed 和调度任务 seed。
- `db-init.sql` 作为部署入口，负责扩展、schema 权限、公共函数和调用/包含 `init.sql`。
- 旧增量脚本迁入 `docs/sql/migrations/` 或 `docs/sql/archive/`，保留升级路径和历史说明。
- 新环境只执行一到两个 SQL 入口即可完成初始化。
- 已废弃任务、旧配置树、`cyq_chips` 明细和 `cyq_perf` 全市场批量沉淀不应进入最终初始化入口。

字段和指标的标准化规则见 `stock-center-wiki/70-规划/量化字段标准化与初始化沉淀规划.md`。

## 迁移建议

直接沿用原 `stock-analysis` 数据库。行情与量化数据表继续采用只新增不删除策略；配置中心 v2 例外，它会在校验通过后删除旧配置表，避免运行时继续依赖旧递归树。

`13-tushare-token-endpoint.sql` 包含 `ALTER TABLE`，需要使用 `t_config_value` 的表所有者或具备等效 DDL 权限的数据库账号执行。它只新增可空列，不会改写既有 Token 的密文、fingerprint、优先级或状态。

`16-daily-market-close-ingest.sql` 会将既有 `t_minute_bar` 和 `t_stock_factor_minute` 改名为对应的 `*_legacy` 表后再迁入新分区表；旧表不会删除。执行前应备份数据库，并在迁移完成后对 legacy 与新表的行数做核对。

如果数据库是在 `t_daily_bar.volume_hand/volume_share` 仍为 `INTEGER` 的早期脚本上创建的，执行 `16` 后还需要执行 `17-market-volume-bigint-fix.sql`，否则全市场 `daily` 可能因单只股票成交量超过 PostgreSQL int32 上限而失败。

`18-market-partition-owner-fix.sql` 必须由 `postgres` 或当前分区父表 owner 执行。后端应用账号需要成为 `t_minute_bar/t_stock_factor_minute` 分区体系 owner，才能在每日收盘任务中自动创建当天分区并清理过期分区。

`19-daily-close-ingest-batching.sql` 只更新调度任务元数据，不修改行情事实表。已执行过 `16` 的数据库曾用它展示 `minute_batch_size` 和 `quote_batch_size` 参数；后续 `45` 会废弃 EOD quote，因此新环境不应再把 `quote_batch_size` 作为常规参数。

如果收盘任务出现 SQLAlchemy 告警：`Column 't_minute_bar.id' ... no Python-side or server-side default generator`，需要执行 `20-market-partition-identity-fix.sql`。同时后端 ORM 已将这两张分区父表的 `id` 标记为 `autoincrement=True`。

`21-daily-close-canonical-consolidation.sql` 会把 `t_daily_bar/t_stock_daily_basic/t_stock_fund_flow_daily/t_sector_fund_flow_daily/t_sector_bar/t_index_bar/t_lhb_event/t_limit_event_daily` 从按 `source` 共存调整为单业务事实。脚本会先把被归并的旧多源行写入 `t_canonical_source_conflict_backup`，再删除 canonical 中的重复行并重建唯一约束。

`22-complete-daily-close-factors.sql` 不依赖额外 DDL 权限，只登记新的因子口径。执行后收盘沉淀体系会从 canonical 表计算个股资金占比、连续流入、横截面资金强度，以及板块上涨家数、涨停家数、资金流窗口、波动率和异动标签。

`23-exclude-bse-from-daily-universe.sql` 用于把当前量化 universe 固定为沪深 active 股票。它只更新 `t_stock.status` 和删除股票池成员关系，不清理已沉淀的历史事实表。

`24-daily-close-technical-chip-global.sql` 需要在补齐 Tushare `stk_factor_pro/cyq_perf/daily_info/index_dailybasic` 能力后执行。它不会删除旧数据；`cyq_perf` 作为筹码摘要事实保留，`cyq_chips` 明细不再作为业务沉淀入口。

`25-daily-close-index-fallback-and-north-hold-deprecate.sql` 只更新旧 `daily_market_close_ingest` 的调度 metadata。执行后，手动运行表单会默认关闭 `sync_north_hold`；核心指数日线由代码执行 `Tushare index_daily -> AkShare stock_zh_index_daily_em -> MooTDX index` fallback，canonical 仍按 `index_code + trade_date` 单事实 upsert。

`26-split-daily-close-ingest.sql` 是破坏式清理脚本，会 `DROP TABLE IF EXISTS t_stock_chip_distribution_daily`。执行后，调度页面应使用 `daily_close_core_ingest`、`daily_close_enrichment_ingest`、`daily_close_repair_ingest`；旧 `daily_market_close_ingest` 会被隐藏并禁用。

`27-stock-basic-status-normalization.sql` 可重复执行。执行后，`sync_stock_basic` 的状态口径固定为：沪深 `L/P/D` 分别对应 `active/suspended/delisted`，北交所/BJ/BSE 和 `4/8/920` 代码段统一为 `excluded`。脚本只更新 `t_stock` 和股票池成员关系，不删除历史行情事实。

`28-trade-calendar-sync-job.sql` 只写入调度任务定义，不改表结构。任务运行时依赖 Python 包 `chinesecalendar`，生成规则与旧项目一致：日期为周一到周五且 `chinese_calendar.is_workday(date)` 为真时记为开市日，并补齐前后交易日。

`29-stock-daily-backfill-job.sql` 只写入调度任务定义，不改表结构。任务默认禁用并仅手动运行；适合先用小股票池和 `max_stocks` 验证，再扩展到 `all_a_share`。回填只写 `t_daily_bar`，不计算因子、不拉分钟线、不触发每日收盘沉淀。

`30-daily-close-enrichment-concurrency.sql` 只更新调度任务元数据，不改表结构。执行后，增强与修复任务会显示 `enrichment_block_concurrency`、`chip_perf_workers` 和 `chip_perf_commit_stock_batch_size`；实际请求仍走配置中心 Tushare Token 池和共享限流，不会绕过官方频率限制。后续规划中，`cyq_perf` 将从全市场每日增强沉淀移除，因此最终 `init.sql/db-init.sql` 不应继续 seed 相关批量参数。

`31-provider-standardization-and-remove-cyq-batch.sql` 是对 `30` 的收口脚本。执行后，`daily_close_enrichment_ingest` 和 `daily_close_repair_ingest` 的调度表单不再出现 `chip_*`、`sync_chip_perf` 或 `calculate_chip_factors`；`t_stock_chip_perf_daily` 不删除，只作为历史/实验数据表保留。

`32-normalize-stock-moneyflow-yuan.sql` 和 `33-refresh-stock-fund-factor-ratios.sql` 应连续执行。执行前后可用：

```bash
cd python-back
.venv/bin/python scripts/audit_stock_moneyflow_units.py --sample-limit 5
```

确认 `legacy_ten_thousand_yuan_candidate=0`，并抽样检查 `main_net_ratio` 不再出现旧万元/元混算导致的异常放大。

`34-stock-daily-basic-moneyflow-backfill-jobs.sql` 只写入调度任务定义，不改事实表结构。执行后需要 reload Scheduler。两个任务默认禁用并仅手动运行，建议先使用 `pool_code=all_a_share,max_stocks=1,start_date=end_date` 做 smoke，再扩展到股票池或全市场。它们复用 Tushare adapter 的日期、字段和单位映射；`backfill_stock_moneyflow` 写入 `t_stock_fund_flow_daily` 时金额已统一为元。

`35-factor-backfill-jobs.sql` 只写入调度任务定义，不改事实表结构。执行后需要 reload Scheduler。`backfill_daily_factors` 按股票池和交易日区间读取 `t_daily_bar/t_stock_fund_flow_daily/t_stock_technical_factor_daily` 重算 `t_stock_factor_daily`；`backfill_sector_factors` 按交易日区间读取板块、成分股和资金流 canonical 表重算 `t_sector_factor_daily`。两者默认 `only_missing=true`，不会触发 Tushare、MooTDX、AkShare 或 Skill。

`36-backfill-ingest-mode.sql` 只更新调度任务元数据，不改事实表结构。执行后五个历史回填任务都支持 `ingest_mode`：`append_safe` 为默认安全模式，依赖唯一键和 upsert 幂等补缺，不会重复入库；`rebuild` 会先删除目标股票池/日期范围内的本类事实或因子，再重新拉取或重算。`only_missing` 保留为兼容参数，`rebuild` 模式会忽略它。

`37-data-assets-inspection-indexes.sql` 需要由对应表 owner 或 `postgres` 执行。它不修改业务表字段和数据，只补数据中心读取最新交易日和快照时间所需的巡检索引，包含 `t_minute_bar/t_stock_factor_minute` 分区表的 `trade_date` 前导索引。主数据表如 `t_stock/t_sector_basic/t_sector_component` 不要求按 `updated_at/created_at` 建巡检索引，数据中心只展示它们的业务计数和关系覆盖。

`38-stock-basic-delisted-name-normalization.sql` 可重复执行。它只修正 `t_stock.status` 和股票池成员关系，不删除历史行情事实。后端 `sync_stock_basic` 同步逻辑也会把名称以 `退市` 开头的沪深股票归为 `delisted`，避免 Tushare `list_status=L` 但展示名称已退市时重新进入 active universe。

`39-index-catalog-sync-job.sql` 只写入调度任务定义，不改事实表结构。执行后需要 reload Scheduler。任务默认禁用，建议先手动运行默认核心指数集合：基础资料会写入 `t_index_basic`，成分型指数会写入 `t_index_component`；Tushare 失败或返回空时可按参数启用 AkShare fallback。

`40-index-component-current-master.sql` 会删除 `t_index_component` 中同一 `index_code + stock_code` 的历史重复行，并把唯一键调整为当前主数据口径。执行后指数成分同步与板块成分类似：本次完整结果中不存在的旧成分会被物理删除，`effective_date` 仅表示纳入或权重生效日期，不再作为快照维度。

`41-index-weight-lookback-months.sql` 会删除 `t_index_component_index_code_stock_code_effective_date_sour_key` 这个旧快照口径冗余唯一约束，并更新调度任务元数据。它需要由 `t_index_component` owner 或 `postgres` 执行。建议在 `40` 执行完成后执行并 reload Scheduler；之后 `sync_index_catalog` 会默认用最近 3 个自然月窗口调用 Tushare `index_weight`，并取最新完整权重日期入库。

`42-data-asset-health-cache.sql` 只写入 `refresh_data_asset_health` 调度任务定义，不创建 PostgreSQL 缓存表。数据中心健康度缓存使用 Redis，需配置 Redis Cache 数据源或 `.env` Redis 兜底。缓存为空或 Redis 不可用时后端会回退即时计算。执行后建议手动运行一次 `refresh_data_asset_health` 或调用 `POST /api/v1/data-assets/refresh?snapshot_key=all&async=true` 预热缓存，然后 reload Scheduler。

`43-redis-cache-data-source.sql` 只写入配置中心 seed，不创建 Redis 相关业务表。执行后可在“系统设置中心 > 数据源 > Redis Cache”中新增 `redis_url` 敏感值，例如 `redis://:password@host:6379/0`；运行时优先读取配置中心，未配置或配置不可用时回退 `.env`，再回退本地内存缓存。Redis 连接测试只执行一次 `PING`，不会暴露 URL 明文。Redis TTL 采用数据中心默认和专属项：`data_asset_cache_ttl_seconds` 是数据中心默认 TTL，`data_asset_summary_ttl_seconds` 和 `data_asset_daily_health_ttl_seconds` 可分别覆盖总览和完整性缓存，`default_cache_ttl_seconds` 预留给后续其他缓存族。

`44-backfill-append-safe-enforcement.sql` 只更新 `t_scheduler_job` 元数据，不修改事实表和旧运行记录。它用于兜底确保 `backfill_stock_daily_bars/backfill_stock_daily_basic/backfill_stock_moneyflow` 三个历史事实入库任务默认走安全补缺：任务会按 `stock_code + trade_date` 查询已有日期，过滤掉已存在记录，再通过唯一键 upsert 写库。若需要重建某一范围，才显式选择 `ingest_mode=rebuild`。

`45-deprecate-eod-quote-snapshot.sql` 只更新调度任务元数据和 `t_quote_snapshot` 注释，不删除历史快照数据。执行后 `daily_close_core_ingest` 不再展示或使用 `sync_eod_quote/quote_batch_size`；盘后唯一价格事实改为 `t_daily_bar`，技术快照从 `t_daily_bar + t_minute_bar + 因子表` 生成，数据中心完整性也不再检查 `t_quote_snapshot(snapshot_kind='eod')`。

`46-technical-snapshot-backfill-job.sql` 只写入 `backfill_technical_snapshots` 调度任务定义，不改事实表结构。执行后需要 reload Scheduler。该任务按股票池和交易日区间读取 canonical 日线、分钟线与因子表，重算 `t_technical_indicator_snapshot`；默认 `ingest_mode=append_safe`，不会重复入库。它用于修复技术快照漏算或历史回填，不调用外部 Provider、不拉行情。

`47-backfill-moneyflow-date-span-guard.sql` 是历史过渡脚本，曾把资金流回填按日期分片。后续判断发现 Tushare `moneyflow(ts_code,start_date,end_date)` 本身可以一次拉取单股多年区间，真正需要控制的是数据库写入事务大小，因此新环境应继续执行 `48` 覆盖该口径。

`48-backfill-moneyflow-row-batch.sql` 只更新 `backfill_stock_moneyflow` 调度任务元数据，不修改资金流事实表和历史运行记录。执行后手动运行表单会出现 `max_upsert_rows_per_commit`，默认 5000 行；Tushare 仍按单股完整 `start_date/end_date` 区间请求，后端只在入库时按行数分批 commit，避免一次事务过大造成数据库压力。

`49-stock-technical-factor-pro-backfill-job.sql` 只写入 `backfill_stock_technical_factor_pro` 调度任务定义，不改事实表结构。该任务按股票池逐股调用 `stk_factor_pro(ts_code,start_date,end_date)`，把 Tushare 专业技术因子原始集写入 `t_stock_technical_factor_daily.factors`。它不直接写 `t_stock_factor_daily`；历史专业因子补齐后，需要再运行 `backfill_daily_factors`，由本地因子计算器把常用指标摘要合并到 `features.tushare_technical`。

`50-daily-factor-backfill-date-workers.sql` 是已执行的历史元数据调整。后续必须继续执行 `51-daily-factor-backfill-window-batching.sql`，由它移除旧 `factor_date_workers` 并写入当前参数。

`51-daily-factor-backfill-window-batching.sql` 是已执行的历史元数据调整，不改事实表结构。它曾使用 Python 股票批次和时间窗口并发；当前运行方式以 52 为准。

`52-daily-factor-backfill-set-based.sql` 取代 51 的运行方式：`backfill_daily_factors` 每个连续交易日窗口在 PostgreSQL 内用窗口函数和 `INSERT ... SELECT` 计算，避免把重叠日线、资金流和完整专业技术 JSONB 反复传到 Python。为避免单条全市场 CTE 占满云端数据库内存，窗口会按 `sql_stock_chunk_size`（默认 200）分成独立提交的集合计算分片。`append_safe` 仍只插入缺失因子，`rebuild` 仍先删除指定股票池和日期窗口后重算。执行本 SQL 后 reload Scheduler。

`55-data-asset-history-pipelines.sql` 建立历史初始化任务基线，必须在 `54` 之后执行。它用 `backfill_stock_daily_facts/backfill_stock_daily_factors/backfill_sector_daily_facts/backfill_sector_daily_factors/backfill_index_daily_facts/backfill_index_daily_factors` 替换旧历史任务定义；旧 `29/34/35/46/49/50/51/52/54` 仍保留为升级历史，不代表当前可执行任务名。随后执行 `56`、`57`、reload Scheduler，并按 `docs/wiki/20-核心流程/历史数据资产初始化.md` 先做最小范围 smoke。

`56-sector-history-range-backfill.sql` 只更新 `backfill_sector_daily_facts` 的调度参数和说明，不改事实表。旧实现按交易日请求 `ths_daily`，当全量日期查询返回空时会退化成每日逐板块串行请求。新实现按板块代码请求一次完整 `start_date/end_date` 区间，每个板块完成后立即提交；执行 `56` 后 reload Scheduler。

`57-stock-history-limit-events.sql` 不改表结构；它更新 `backfill_stock_daily_facts` 的调度参数，并幂等归一 `t_limit_event_daily` 的旧通用事件：metadata 明确标识为 Tushare `Z` 池的行转为 `limit_break`；类别为空但带 `up_stat` 的历史 U 池行转为 `limit_up`。事件阶段对每个交易日各调用一次 `limit_list_d` 和 `suspend_d`，按目标股票池过滤后 Upsert；成功日期在 `t_provider_raw_record` 留完成标记，`append_safe + only_missing=true` 重跑时会跳过。执行 `57` 后 reload Scheduler。
