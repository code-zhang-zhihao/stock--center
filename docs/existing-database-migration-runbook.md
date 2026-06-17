# 原数据库新增 t_ 表迁移手册

## 结论

当前阶段不新建 PostgreSQL 数据库，直接沿用原 `stock-analysis` 数据库。

为了避免和旧表冲突，新系统表统一使用 `t_` 前缀，例如：

- 旧表 `stock_basic` -> 新表 `t_stock`
- 旧表 `daily_bar` -> 新表 `t_daily_bar`
- 旧表 `minute_bar` -> 新表 `t_minute_bar`
- 旧表 `quote_snapshot` -> 新表 `t_quote_snapshot`
- 旧表 `stock_factor_daily` -> 新表 `t_stock_factor_daily`
- 旧表 `stock_factor_minute` -> 新表 `t_stock_factor_minute`
- 旧表 `technical_indicator_snapshot` -> 新表 `t_technical_indicator_snapshot`

旧表不删除、不改名，作为迁移来源和回滚保障。

## 执行顺序

1. 使用原数据库连接信息配置 `python-back/.env`。

```env
DATABASE_URL=postgresql+asyncpg://<user>:<password>@<host>:5432/<old_database>
CONFIG_MASTER_KEY=<复用原项目本机值>
```

2. 在原数据库执行新表 schema。

```bash
psql -h <host> -p 5432 -U <user> -d <old_database> -f docs/sql/01-schema.sql
```

3. 从旧表迁移到新 `t_` 表。

```bash
psql -h <host> -p 5432 -U <user> -d <old_database> -f docs/sql/02-stock-analysis-migration-mapping.sql
```

4. 校验新表数据量。

```sql
SELECT count(*) FROM t_stock;
SELECT source, count(*) FROM t_daily_bar GROUP BY source ORDER BY count(*) DESC;
SELECT source, count(*) FROM t_minute_bar GROUP BY source ORDER BY count(*) DESC;
SELECT source, count(*) FROM t_quote_snapshot GROUP BY source ORDER BY count(*) DESC;
SELECT source, count(*) FROM t_stock_factor_daily GROUP BY source ORDER BY count(*) DESC;
SELECT source, count(*) FROM t_stock_factor_minute GROUP BY source ORDER BY count(*) DESC;
SELECT source, count(*) FROM t_technical_indicator_snapshot GROUP BY source ORDER BY count(*) DESC;
```

## 回滚

如果迁移结果不符合预期，可以只删除新 `t_` 表。旧表仍然保留，不影响原系统。

```sql
DROP TABLE IF EXISTS
    t_provider_raw_record,
    t_stock,
    t_trade_calendar,
    t_daily_bar,
    t_minute_bar,
    t_quote_snapshot,
    t_tick_trade,
    t_financial_statement,
    t_corporate_action,
    t_sector_basic,
    t_sector_component,
    t_sector_bar,
    t_index_basic,
    t_index_component,
    t_index_bar,
    t_stock_factor_daily,
    t_stock_factor_minute,
    t_technical_indicator_snapshot
CASCADE;
```
