# TDX vs AkShare vs DB 行情数据能力盘点

## 数据资产保护原则

`stock-center` 迁移自 `stock-analysis`，不能为了“最小实现”丢失已有资产。参考库最近盘点的关键资产包括：

| 表 | 行数 | 迁移要求 |
| --- | ---: | --- |
| `stock_basic` | 5528 | 迁移到 `t_stock`。 |
| `daily_bar` | 1610890 | 迁移到 `t_daily_bar`，尤其保留 `akshare_qfq`。 |
| `minute_bar` | 1146240 | 迁移到 `t_minute_bar`，主要来源 `mootdx`。 |
| `quote_snapshot` | 6780 | 迁移到 `t_quote_snapshot`。 |
| `stock_factor_daily` | 44549 | 迁移到 `t_stock_factor_daily`，Derived 层保留旧结果。 |
| `stock_factor_minute` | 834480 | 迁移到 `t_stock_factor_minute`，Derived 层保留旧结果。 |
| `technical_indicator_snapshot` | 3480 | 迁移到 `t_technical_indicator_snapshot` 或提供可验证重建。 |
| `trade_calendar` | 1826 | 迁移到 `t_trade_calendar`。 |

## Provider 能力矩阵

| 数据能力 | MooTDX/通达信 | AkShare | Tushare Pro（当前审计 Token） | 新系统策略 |
| --- | --- | --- | --- | --- |
| 实时 quote、五档盘口 | 强，主源。 | `stock_zh_a_spot_em`、`stock_bid_ask_em` 可补充。 | 不在本阶段范围。 | `t_quote_snapshot`，默认 `mootdx -> akshare`。 |
| 日 K/历史行情 | 可查近期/终端 K 线。 | 强，支持历史和复权。 | `daily` 及 `daily_basic/adj_factor` 提供日线、估值与复权因子。 | `tushare -> akshare -> mootdx`。 |
| 分钟线 | 强，实时/当日分时。 | 可补历史分钟。 | `idx_mins` 支持指数历史分钟；股票实时/分钟仍不替代 MooTDX。 | `t_minute_bar`，默认 `mootdx -> akshare`。 |
| 分笔成交 | 支持 `transaction/transactions`，适合实时展示。 | `stock_zh_a_tick_tx_js` 可 fallback。 | 不在本阶段范围。 | `t_tick_trade`，已接入 `/query/ticks`。 |
| 股票基础资料 | 股票列表可 fallback。 | 强，上市、退市、行业、地区。 | `stock_basic` 可覆盖上市、退市、暂停列表。 | `tushare -> akshare -> mootdx`。 |
| 财务/F10/除权除息 | 有 `finance/F10/xdxr`。 | fallback。 | 三大报表、财务指标、分红写入新 Canonical 表，完整字段保留 JSONB。 | `tushare -> akshare`。 |
| 板块/概念/行业 | 支持 `block` fallback。 | fallback。 | `index_classify/index_member_all` 保留 SW2021；`ths_index/ths_member` 为同花顺概念/行业主源。 | 同花顺与申万分类体系并存，不互相覆盖。 |
| 指数/成分股 | 支持指数 K 线 fallback。 | 成分、权重、行情更完整，主源。 | `index_*`、`sw_daily`、`ci_daily/ci_index_member`、`daily_info` 已登记并完成 Token 审计。 | 现有查询链保持兼容；后续按业务需要增加 Canonical 映射。 |
| 资金流 | 不适合作主源。 | 主源，覆盖个股、行业、概念资金流。 | `moneyflow`、`moneyflow_hsgt`、`hsgt_top10` 已登记并审计。 | `t_stock_fund_flow_daily/t_sector_fund_flow_daily`，`hsgt_top10` 后续独立事实表。 |
| 龙虎榜 | 不适合作主源。 | 主源，覆盖事件和席位明细。 | `top_list/top_inst` 已登记并审计。 | `t_lhb_event/t_lhb_seat_detail`，现有 QueryService 映射不变。 |
| 公告 | 不适合作主源。 | 主源，覆盖巨潮/公告类接口。 | `anns_d` 已登记并审计。 | `t_announcement`，现有 QueryService 映射不变。 |
| 涨跌停池/融资融券 | 不适合作主源。 | 主源。 | `stk_limit/limit_list_d/margin/margin_detail` 已登记并审计。 | 专题同步任务按需映射到既有 Canonical 表。 |

## Query Contract

所有行情查询统一走 `MarketDataQueryService`：

- `db_first`：先查数据库，缺失再按 provider chain 补。
- `provider_first`：先查外部源，成功后写库。
- `db_only`：只查数据库。
- `provider_only`：只查外部源，不写 canonical 表，但写 `t_provider_raw_record`。
- `refresh`：强制刷新并 upsert canonical 表。

统一返回 `resolved_source`、`fallback_used`、`attempted_engines`、`missing_ranges`、`staleness`、`raw_ref`、`persisted` 和 `errors`。

## TushareProvider

`python-back/app/modules/market_data/tushare/transport.py` 使用 Tushare Pro HTTP 协议，不依赖 SDK。Token 只从配置中心 `market_data/tushare_pro` 的加密 `token` 值池读取，不从 `.env` 读取。运行时根据优先级、权重和最近使用时间选择 Token，并保持 Token 与其专属 `endpoint_url` 成组切换。

Tushare Provider 的内部契约为 `TushareApiRequest -> TushareApiResponse`：Provider 只校验目录、注入 Token、发送 HTTP 请求并返回 Tushare 原始 records/payload。股票代码转换、单位换算、Canonical 映射、raw landing 和入库由 `tushare_mappers.py`、`MarketDataQueryService` 或 `MarketDataSyncService` 负责。A 股 API 名称、参数、字段和审计样例统一登记在 `tushare/catalog/`；`tushare_provider.py` 仅保留兼容导出，禁止新增业务逻辑。

当前 Catalog 已登记 58 个股票与指数 A 股接口，并在 2026-06-23 对当前 Token 池完成 58/58 成功审计。完整结果见 `docs/providers/tushare/audit-baseline.md`。已纳入既有 provider chain 或手动专题同步的接口：

- `stock_basic`、`daily`、`daily_basic`、`adj_factor`、`trade_cal`
- `index_classify/index_member_all`，以及 `ths_index/ths_member`
- `index_basic/index_daily/index_weight`、`moneyflow`、`top_list`、`anns_d`
- 三大报表、`fina_indicator`、`dividend`、融资融券、涨跌停与股东专题走手动调度任务。

10,000 积分一般覆盖上述常用接口，但实际启用仍以接口调用结果为准。配置页面和 provider 验证命令只执行一次 `daily` 连通性检查，不再自动盘点所有接口权限：

```bash
cd python-back
python scripts/check_market_data_providers.py --provider tushare --stock-code 600519
```

完整 A 股目录权限审计使用：

```bash
python scripts/audit_tushare_a_share_catalog.py --all
```
