# 启动与验证指南

## 默认启动

首次安装依赖：

```bash
cd /Volumes/TiPro9000/projects/archived/stock-center
./start.sh --install
```

确认 `python-back/.env` 已配置：

```env
DATABASE_URL=postgresql+asyncpg://<user>:<password>@<host>:5432/<原stock-analysis数据库>
CONFIG_MASTER_KEY=<复用原项目本机值>
DATABASE_CONNECT_TIMEOUT_SECONDS=10
DATABASE_SSL=auto
```

`DATABASE_SSL` 支持 `auto`、`disable`、`require`。云端 PostgreSQL 出现 asyncpg SSL 握手断开时，可先运行诊断脚本判断哪种模式可用：

```bash
cd /Volumes/TiPro9000/projects/archived/stock-center/python-back
source .venv/bin/activate
python scripts/check_database_connection.py
```

日常启动：

```bash
cd /Volumes/TiPro9000/projects/archived/stock-center
./start.sh
```

访问：

- API：`http://127.0.0.1:8000`
- Swagger：`http://127.0.0.1:8000/docs`
- Health：`http://127.0.0.1:8000/api/v1/health`
- DB Health：`http://127.0.0.1:8000/api/v1/health/db`
- 前端：`http://127.0.0.1:8080`

脚本默认同时启动后端和 `web-admin` 前端。后端日志写入 `logs/backend-*.log`，前端日志写入 `logs/frontend-*.log`。

`/api/v1/health` 只表示后端进程已启动；数据库连接请查看 `/api/v1/health/db`。当 `SCHEDULER_ENABLED=true` 但数据库暂时不可连时，后端仍会启动，调度器状态会在 `/api/v1/scheduler/status` 中显示错误。

只启动后端：

```bash
./start.sh --backend-only
```

## 通达信与 AkShare Provider 验证

不依赖数据库，直接验证外部 provider：

```bash
cd /Volumes/TiPro9000/projects/archived/stock-center/python-back
source .venv/bin/activate
python scripts/check_market_data_providers.py --stock-code 600519 --provider all
```

只验证通达信/MooTDX：

```bash
python scripts/check_market_data_providers.py --stock-code 600519 --provider mootdx
```

只验证 AkShare：

```bash
python scripts/check_market_data_providers.py --stock-code 600519 --provider akshare
```

结果中 `ok=true` 且 quote、minute、daily 至少有一类数据，即说明 provider 基本可用。通达信在非交易时段可能 quote 或分钟数据较少，此时优先看 `daily_count`、`quote_raw_count` 和错误信息。MooTDX 不读取环境变量，代码会从自带 `HQ_HOSTS` 中按顺序尝试候选服务器。

如果 AkShare 返回 `ProxyError`、`RemoteDisconnected` 或东财域名 `push2.eastmoney.com` 连接失败，优先检查服务器代理、出口网络、防火墙和云厂商安全组；这类错误通常表示外部数据源网络不可达。

## API 验证

启动后端后，用 API 验证查询链：

```bash
curl "http://127.0.0.1:8000/api/v1/health"

curl "http://127.0.0.1:8000/api/v1/market-data/query/quote?stock_code=600519&query_mode=provider_first&engine_priority=mootdx&engine_priority=akshare"

curl "http://127.0.0.1:8000/api/v1/market-data/query/daily-bars?stock_code=600519&query_mode=db_first&limit=10"

curl "http://127.0.0.1:8000/api/v1/market-data/query/minute-bars?stock_code=600519&query_mode=provider_first&engine_priority=mootdx&engine_priority=akshare&limit=10"
```

返回 `meta.resolved_source`、`meta.fallback_used`、`meta.raw_ref` 可用于判断实际使用了哪个 provider，以及 raw landing 是否写入 `t_provider_raw_record`。

## 股票池中心

先在原 PostgreSQL 数据库执行：

```bash
psql "${DATABASE_URL/postgresql+asyncpg/postgresql}" -f docs/sql/15-stock-pool-center.sql
```

执行后重启后端，确认四个系统池已初始化：

```bash
curl "http://127.0.0.1:8000/api/v1/stock-pools"
curl "http://127.0.0.1:8000/api/v1/stock-pools/candidate/members?page=1&page_size=20"
```

股票池成员仅接受已同步到 `t_stock` 的无后缀股票代码。未知代码会返回 `unknown_codes`，整批不会写入。前端入口为 `http://127.0.0.1:8080/stock-pools`。

## 前端

`web-admin/` 当前只实现配置中心，不包含行情、策略、Skill 或 LLM 调试页面。

首次安装前后端依赖：

```bash
cd /Volumes/TiPro9000/projects/archived/stock-center
./start.sh --install
```

日常同时启动前后端：

```bash
./start.sh
```

访问：

- 前端：`http://127.0.0.1:8080`
- 后端：`http://127.0.0.1:8000`

前端 API 地址由 `web-admin/.env` 控制：

```env
VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1
```

前端静态验证：

```bash
cd /Volumes/TiPro9000/projects/archived/stock-center/web-admin
npm run typecheck
npm run build
```
