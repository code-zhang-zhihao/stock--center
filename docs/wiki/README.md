# stock-center Wiki

## 能力导航

| 需要了解的能力 | Wiki 页面 |
| --- | --- |
| 项目定位与边界 | [项目概览](00-项目概览.md) |
| 系统分层与核心数据流 | [技术架构](10-技术架构.md) |
| 历史数据资产、表关系、执行顺序与并发 | [历史数据资产初始化](20-核心流程/历史数据资产初始化.md) |
| 行情查询契约 | [行情数据查询契约](20-核心流程/行情数据查询契约.md) |
| 行情模块实现 | [行情数据模块](30-模块地图/行情数据模块.md) |
| 盘后情绪事实与阶段 | [市场洞察模块](30-模块地图/市场洞察模块.md) |
| 调度任务与运行规则 | [调度中心模块](30-模块地图/调度中心模块.md) |
| 数据库表与 SQL 顺序 | [数据库表索引](30-模块地图/数据库表索引.md) |
| 重要兼容性与迁移变化 | [变更记录](80-变更记录.md) |
| 当前实现状态 | [已实现规划](70-规划/已实现规划.md) |

## 模块到源码

| 模块/能力 | 源码目录 | 主要入口 | 职责 | Wiki 页面 |
| --- | --- | --- | --- | --- |
| 行情与历史事实 | `python-back/app/modules/market_data/` | `scheduler_handlers.py`、`history_backfill.py`、`entity_history_backfill.py` | 主数据同步、个股/板块/指数日频事实回填与 canonical 入库。 | [行情数据模块](30-模块地图/行情数据模块.md)、[历史数据资产初始化](20-核心流程/历史数据资产初始化.md) |
| 因子计算 | `python-back/app/modules/indicator_engine/` | `backfill.py`、`repository.py`、`service.py` | 个股/板块/指数因子和技术快照计算。 | [历史数据资产初始化](20-核心流程/历史数据资产初始化.md) |
| 市场洞察 | `python-back/app/modules/market_insight/` | `service.py`、`scheduler_handlers.py` | 从已完成日频事实计算版本化市场情绪分和阶段；不调用 Provider 或 LLM。 | [市场洞察模块](30-模块地图/市场洞察模块.md) |
| 数据资产巡检 | `python-back/app/modules/data_assets/` | `service.py` | 表级健康、覆盖率、生产任务与缓存。 | [数据库表索引](30-模块地图/数据库表索引.md) |
| 实时研究底座 | `python-back/app/modules/realtime_market/` | `service.py`、`tickflow_runtime.py` | TickFlow REST Quote/五档、MooTDX 分钟线、Redis 租约与市场/题材/行业/股票池聚合；市场总览从同轮缓存派生盘中宽度、题材热度与短期事件流，不做自动交易。 | [实时数据能力规划](70-规划/实时数据能力规划.md) |
| 调度中心 | `python-back/app/modules/scheduler_center/` | `service.py`、`runtime.py`、`handlers.py` | 定义、触发、限时、重试、运行日志与取消。 | [调度中心模块](30-模块地图/调度中心模块.md) |
| 管理后台 | `web-admin/src/` | `router/index.ts` | 数据中心、实时市场总览、盘后市场复盘、任务中心、板块与个股行情页面。 | [前端配置中心模块](30-模块地图/前端配置中心模块.md) |
| 数据库演进 | `docs/sql/` | `README.md`、`55-data-asset-history-pipelines.sql`、`58-daily-close-four-stage-pipeline.sql` | Schema、索引、历史任务和每日四级流水线升级顺序。 | [数据库表索引](30-模块地图/数据库表索引.md) |

## 推荐阅读顺序

1. [项目概览](00-项目概览.md)
2. [技术架构](10-技术架构.md)
3. [历史数据资产初始化](20-核心流程/历史数据资产初始化.md)
4. [行情数据模块](30-模块地图/行情数据模块.md)
5. [市场洞察模块](30-模块地图/市场洞察模块.md)
6. [调度中心模块](30-模块地图/调度中心模块.md)
7. [数据库表索引](30-模块地图/数据库表索引.md)

最后一次基于代码核验：2026-07-28。
