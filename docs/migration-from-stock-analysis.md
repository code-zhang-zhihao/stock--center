# stock-analysis 到 stock-center 迁移计划

## 原则

迁移不是删表重建后只保留当前页面需要的数据。旧库中的行情、基础资料、因子、交易日历都是第一优先资产。`stock-center` 在原数据库中新增 `t_` 前缀表，并采用 Raw、Canonical、Derived 三层承接：

- Raw：外部接口原始响应落入 `t_provider_raw_record`，避免字段暂未规范化就丢失。
- Canonical：`t_stock`、`t_daily_bar`、`t_minute_bar`、`t_quote_snapshot` 等规范行情表。
- Derived：因子、技术指标、策略结果，可以从 Canonical 重算，但迁移阶段必须保留旧结果映射。

## 旧库关键资产

来自 `stock-analysis` 的当前盘点：

| 旧表 | 当前数量 | 迁移策略 |
| --- | ---: | --- |
| `stock_basic` | 5,528 | 映射到 `t_stock`，保留行业、地区、状态和原始 metadata |
| `daily_bar` | 1,610,890 | 映射到 `t_daily_bar`，重点保护 `source=akshare_qfq` 与 `adjust_mode=qfq` |
| `minute_bar` | 1,146,240 | 映射到 `t_minute_bar`，保留 `source=mootdx` 与分钟粒度 |
| `quote_snapshot` | 6,780 | 映射到 `t_quote_snapshot`，保留来源与盘口原始 payload |
| `stock_factor_daily` | 44,549 | 映射到 `t_stock_factor_daily`，并记录因子口径 |
| `stock_factor_minute` | 834,480 | 映射到 `t_stock_factor_minute`，并记录分钟因子口径 |
| `technical_indicator_snapshot` | 3,480 | 映射到 `t_technical_indicator_snapshot`，保留技术指标快照 |

## 第一批迁移顺序

1. 在原数据库执行 `docs/sql/01-schema.sql`，创建新 `t_` 表。
2. 迁移 `stock_basic -> t_stock`，以股票代码为唯一键 upsert。
3. 迁移 `daily_bar -> t_daily_bar`，以 `(stock_code, trade_date, source)` 去重，保留 `akshare_qfq`。
4. 迁移 `minute_bar -> t_minute_bar`，以 `(stock_code, bar_time, interval, source)` 去重，保留 `mootdx`。
5. 迁移 `quote_snapshot -> t_quote_snapshot`，以 `(stock_code, quote_time, source)` 去重。
6. 迁移 `stock_factor_daily`、`stock_factor_minute`、`technical_indicator_snapshot` 到 Derived 层新表。
7. 用 3 只股票做回读验证：基础资料、日线、分钟线、quote 的 `db_only` 和 `db_first` 返回一致。
8. 再开启 `provider_first` 和 `refresh`，验证外部源写库不会覆盖不同 source 的旧数据。

字段映射模板见 `docs/sql/02-stock-analysis-migration-mapping.sql`。该脚本假设旧表和新 `t_` 表在同一个数据库中。

## 推荐校验 SQL

```sql
SELECT count(*) FROM t_stock;
SELECT source, count(*) FROM t_daily_bar GROUP BY source ORDER BY count(*) DESC;
SELECT source, count(*) FROM t_minute_bar GROUP BY source ORDER BY count(*) DESC;
SELECT source, count(*) FROM t_quote_snapshot GROUP BY source ORDER BY count(*) DESC;
SELECT source, count(*) FROM t_stock_factor_daily GROUP BY source ORDER BY count(*) DESC;
SELECT source, count(*) FROM t_stock_factor_minute GROUP BY source ORDER BY count(*) DESC;
SELECT source, count(*) FROM t_technical_indicator_snapshot GROUP BY source ORDER BY count(*) DESC;
```

## 后续批次

- 第二批：财务、公司行动、板块、指数、分笔成交。
- 第三批：Skill、妙想、问财、LLM 结构化 JSON 与 fallback。
