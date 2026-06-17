# stock-center

`stock-center` 是从 `stock-analysis` 迁移升级的新项目。当前阶段先实现行情与数据引擎底座：保护旧库已有数据资产，统一数据库、MooTDX 和 AkShare 的查询契约，再逐步迁移策略、Skill、LLM 和前端能力。

## 当前结构

- `python-back/`：新的 FastAPI 后端。
- `web-admin/`：新的 Vue3 配置中心前端，当前只实现 Search、LLM、Notification 与 Key 配置管理。
- `docs/`：数据库 SQL、能力盘点和迁移设计文档。
- `stock-center-wiki/`：项目 wiki 和 AI 协作管理规则。
- `python-back/.env.example`：后端运行所需环境变量模板。

关键文档：

- `docs/market-data-provider-capability-matrix.md`：TDX、AkShare、DB 能力盘点。
- `docs/sql/01-schema.sql`：Raw、Canonical、Derived 三层表结构和字段备注。
- `docs/sql/02-stock-analysis-migration-mapping.sql`：旧库迁移映射模板。
- `docs/sql/08-config-center-v2-rebuild.sql`：配置中心 v2 重建脚本，迁移 Search、LLM、Notification 和 Key 配置。
- `docs/existing-database-migration-runbook.md`：原数据库新增 `t_` 表并迁移的执行手册。
- `docs/startup-guide.md`：后端启动、Provider 验证和 API smoke test。
- `python-back/.env.example`：数据库连接池、CORS、配置缓存参数模板；MooTDX 使用代码内置默认值。

## 第一阶段目标

行情查询统一走 `MarketDataQueryService`：

- `query_mode=db_first`：先查数据库，缺失或过期再按 provider chain 补。
- `query_mode=provider_first`：先查外部源，成功后写库。
- `query_mode=db_only`：只查数据库。
- `query_mode=provider_only`：只查外部源，不写规范表，但保留 raw landing。
- `query_mode=refresh`：强制刷新并 upsert。

默认引擎顺序：

- 股票基础资料、日线：`akshare -> mootdx`
- 分钟线、quote：`mootdx -> akshare`

## 参考源

迁移参考项目：

```text
/Volumes/TiPro9000/projects/archived/stock-analysis
```

不要直接在参考项目中实现新架构；所有迁移后的代码和文档应落在当前 `stock-center` 仓库。

## 本地启动草案

```bash
cd /Volumes/TiPro9000/projects/archived/stock-center/python-back
cp .env.example .env
# DATABASE_URL 使用原 stock-analysis 数据库，执行 docs/sql/01-schema.sql 创建 t_ 表
# 配置中心执行 docs/sql/08-config-center-v2-rebuild.sql 后再启动新版配置前端
# CONFIG_MASTER_KEY 使用本机真实值，不要提交到仓库
cd ..
./start.sh
```

首次安装并启动前后端：

```bash
cd /Volumes/TiPro9000/projects/archived/stock-center
./start.sh --install
```

默认访问：

- 后端：`http://127.0.0.1:8000`
- 前端：`http://127.0.0.1:8080`

如只需要后端：

```bash
./start.sh --backend-only
```
