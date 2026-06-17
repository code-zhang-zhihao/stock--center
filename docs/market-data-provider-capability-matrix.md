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

| 数据能力 | MooTDX/通达信 | AkShare | 新系统策略 |
| --- | --- | --- | --- |
| 实时 quote、五档盘口 | 强，主源。 | `stock_zh_a_spot_em`、`stock_bid_ask_em` 可补充。 | `t_quote_snapshot`，默认 `mootdx -> akshare`。 |
| 日 K/历史行情 | 可查近期/终端 K 线。 | 强，支持历史和复权。 | `t_daily_bar`，默认 `akshare -> mootdx`。 |
| 分钟线 | 强，实时/当日分时。 | 可补历史分钟。 | `t_minute_bar`，默认 `mootdx -> akshare`。 |
| 分笔成交 | 支持 `transaction/transactions`，适合实时展示。 | `stock_zh_a_tick_tx_js` 可 fallback。 | `t_tick_trade`，已接入 `/query/ticks`。 |
| 股票基础资料 | 股票列表可 fallback。 | 强，上市、退市、行业、地区。 | `t_stock`，默认 `akshare -> mootdx`。 |
| 财务/F10/除权除息 | 有 `finance/F10/xdxr`。 | 强，三表、摘要、指标。 | `t_financial_statement`、`t_corporate_action`，先 raw landing。 |
| 板块/概念/行业 | 支持 `block` fallback。 | 更完整，主源。 | `t_sector_basic/t_sector_component/t_sector_bar`，已接入 sector 系列接口。 |
| 指数/成分股 | 支持指数 K 线 fallback。 | 成分、权重、行情更完整，主源。 | `t_index_basic/t_index_component/t_index_bar`，已接入 index 系列接口。 |
| 资金流 | 不适合作主源。 | 主源，覆盖个股、行业、概念资金流。 | `t_stock_fund_flow_daily/t_sector_fund_flow_daily`，已接入 `/query/fund-flow`。 |
| 龙虎榜 | 不适合作主源。 | 主源，覆盖事件和席位明细。 | `t_lhb_event/t_lhb_seat_detail`，已接入 `/query/lhb`。 |
| 公告 | 不适合作主源。 | 主源，覆盖巨潮/公告类接口。 | `t_announcement`，已接入 `/query/announcements`。 |
| 涨跌停池/融资融券 | 不适合作主源。 | 主源。 | 后续按同一 capability registry 增量接入。 |

## Query Contract

所有行情查询统一走 `MarketDataQueryService`：

- `db_first`：先查数据库，缺失再按 provider chain 补。
- `provider_first`：先查外部源，成功后写库。
- `db_only`：只查数据库。
- `provider_only`：只查外部源，不写 canonical 表，但写 `t_provider_raw_record`。
- `refresh`：强制刷新并 upsert canonical 表。

统一返回 `resolved_source`、`fallback_used`、`attempted_engines`、`missing_ranges`、`staleness`、`raw_ref`、`persisted` 和 `errors`。
