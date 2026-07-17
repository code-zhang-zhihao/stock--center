# Tushare `index.market`

Provider 只返回 Tushare 原始字段；调用方决定映射、raw landing 与入库。

## `idx_factor_pro`

- 官方文档：[doc_id=358](https://tushare.pro/document/2?doc_id=358)
- 积分门槛：`5000`（confirmed）
- 当前状态：`documented`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `ts_code` | string | 否 | - | - |
| `trade_date` | date | 否 | - | - |
| `start_date` | date | 否 | - | - |
| `end_date` | date | 否 | - | - |

### 出参

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ts_code` | string | - |
| `trade_date` | string | - |
| `open` | string | - |
| `high` | string | - |
| `low` | string | - |
| `close` | string | - |
| `pre_close` | string | - |
| `change` | string | - |
| `pct_change` | string | - |
| `vol` | string | - |
| `amount` | string | - |

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("idx_factor_pro", {'ts_code': '000001.SH', 'start_date': '20260613', 'end_date': '20260622'}))
# response.records 保持 Tushare 原始字段
```

## `idx_mins`

- 官方文档：[doc_id=419](https://tushare.pro/document/2?doc_id=419)
- 积分门槛：`unknown`（unknown）
- 当前状态：`documented`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `ts_code` | string | 是 | - | - |
| `freq` | string | 是 | 1min, 5min, 15min, 30min, 60min | - |
| `start_date` | datetime | 否 | - | - |
| `end_date` | datetime | 否 | - | - |

### 出参

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ts_code` | string | - |
| `trade_time` | string | - |
| `open` | string | - |
| `close` | string | - |
| `high` | string | - |
| `low` | string | - |
| `vol` | string | - |
| `amount` | string | - |

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("idx_mins", {'ts_code': '000001.SH', 'freq': '5min', 'start_date': '2026-06-20 09:30:00', 'end_date': '2026-06-20 15:00:00'}))
# response.records 保持 Tushare 原始字段
```

## `index_daily`

- 官方文档：[doc_id=95](https://tushare.pro/document/2?doc_id=95)
- 积分门槛：`120`（confirmed）
- 当前状态：`called_by_business, documented, persisted`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `ts_code` | string | 否 | - | - |
| `trade_date` | date | 否 | - | - |
| `start_date` | date | 否 | - | - |
| `end_date` | date | 否 | - | - |

### 出参

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ts_code` | string | - |
| `trade_date` | string | - |
| `close` | string | - |
| `open` | string | - |
| `high` | string | - |
| `low` | string | - |
| `pre_close` | string | - |
| `change` | string | - |
| `pct_chg` | string | - |
| `vol` | string | - |
| `amount` | string | - |

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("index_daily", {'ts_code': '000001.SH', 'start_date': '20260613', 'end_date': '20260622'}))
# response.records 保持 Tushare 原始字段
```

## `index_dailybasic`

- 官方文档：[doc_id=128](https://tushare.pro/document/2?doc_id=128)
- 积分门槛：`2000`（confirmed）
- 当前状态：`documented`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `ts_code` | string | 否 | - | - |
| `trade_date` | date | 否 | - | - |
| `start_date` | date | 否 | - | - |
| `end_date` | date | 否 | - | - |

### 出参

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ts_code` | string | - |
| `trade_date` | string | - |
| `total_mv` | string | - |
| `float_mv` | string | - |
| `total_share` | string | - |
| `float_share` | string | - |
| `free_share` | string | - |
| `turnover_rate` | string | - |
| `turnover_rate_f` | string | - |
| `pe` | string | - |
| `pe_ttm` | string | - |
| `pb` | string | - |

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("index_dailybasic", {'ts_code': '000001.SH', 'start_date': '20260613', 'end_date': '20260622'}))
# response.records 保持 Tushare 原始字段
```

## `index_global`

- 官方文档：[doc_id=211](https://tushare.pro/document/2?doc_id=211)
- 积分门槛：`2000`（confirmed）
- 当前状态：`documented`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `ts_code` | string | 否 | - | - |
| `trade_date` | date | 否 | - | - |
| `start_date` | date | 否 | - | - |
| `end_date` | date | 否 | - | - |

### 出参

该接口的返回字段尚未完成官方逐字段确认；Provider 仍完整保留上游 `fields/items`，请以官方文档为准。

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("index_global", {'ts_code': 'XIN9', 'start_date': '20260613', 'end_date': '20260622'}))
# response.records 保持 Tushare 原始字段
```

## `index_monthly`

- 官方文档：[doc_id=172](https://tushare.pro/document/2?doc_id=172)
- 积分门槛：`120`（confirmed）
- 当前状态：`documented`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `ts_code` | string | 否 | - | - |
| `trade_date` | date | 否 | - | - |
| `start_date` | date | 否 | - | - |
| `end_date` | date | 否 | - | - |

### 出参

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ts_code` | string | - |
| `trade_date` | string | - |
| `close` | string | - |
| `open` | string | - |
| `high` | string | - |
| `low` | string | - |
| `pre_close` | string | - |
| `change` | string | - |
| `pct_chg` | string | - |
| `vol` | string | - |
| `amount` | string | - |

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("index_monthly", {'ts_code': '000001.SH', 'start_date': '20250101', 'end_date': '20260622'}))
# response.records 保持 Tushare 原始字段
```

## `index_weekly`

- 官方文档：[doc_id=171](https://tushare.pro/document/2?doc_id=171)
- 积分门槛：`120`（confirmed）
- 当前状态：`documented`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `ts_code` | string | 否 | - | - |
| `trade_date` | date | 否 | - | - |
| `start_date` | date | 否 | - | - |
| `end_date` | date | 否 | - | - |

### 出参

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ts_code` | string | - |
| `trade_date` | string | - |
| `close` | string | - |
| `open` | string | - |
| `high` | string | - |
| `low` | string | - |
| `pre_close` | string | - |
| `change` | string | - |
| `pct_chg` | string | - |
| `vol` | string | - |
| `amount` | string | - |

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("index_weekly", {'ts_code': '000001.SH', 'start_date': '20260501', 'end_date': '20260622'}))
# response.records 保持 Tushare 原始字段
```

## `ths_daily`

- 官方文档：[doc_id=260](https://tushare.pro/document/2?doc_id=260)
- 积分门槛：`6000`（confirmed）
- 当前状态：`called_by_business, documented, persisted`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `ts_code` | string | 否 | - | - |
| `trade_date` | date | 否 | - | - |
| `start_date` | date | 否 | - | - |
| `end_date` | date | 否 | - | - |

### 出参

该接口的返回字段尚未完成官方逐字段确认；Provider 仍完整保留上游 `fields/items`，请以官方文档为准。

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("ths_daily", {'ts_code': '885001.TI', 'start_date': '20260613', 'end_date': '20260622'}))
# response.records 保持 Tushare 原始字段
```
