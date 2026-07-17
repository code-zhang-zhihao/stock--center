# Tushare `stock.market`

Provider 只返回 Tushare 原始字段；调用方决定映射、raw landing 与入库。

## `adj_factor`

- 官方文档：[doc_id=28](https://tushare.pro/document/2?doc_id=28)
- 积分门槛：`2000`（confirmed）
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
| `adj_factor` | string | - |

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("adj_factor", {'ts_code': '600519.SH', 'start_date': '20260613', 'end_date': '20260622'}))
# response.records 保持 Tushare 原始字段
```

## `daily`

- 官方文档：[doc_id=27](https://tushare.pro/document/2?doc_id=27)
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
| `open` | string | - |
| `high` | string | - |
| `low` | string | - |
| `close` | string | - |
| `pre_close` | string | - |
| `change` | string | - |
| `pct_chg` | string | - |
| `vol` | string | - |
| `amount` | string | - |

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("daily", {'ts_code': '600519.SH', 'start_date': '20260613', 'end_date': '20260622'}))
# response.records 保持 Tushare 原始字段
```

## `daily_basic`

- 官方文档：[doc_id=32](https://tushare.pro/document/2?doc_id=32)
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
| `turnover_rate` | string | - |
| `volume_ratio` | string | - |
| `pe` | string | - |
| `pb` | string | - |
| `total_share` | string | - |
| `float_share` | string | - |
| `total_mv` | string | - |
| `circ_mv` | string | - |

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("daily_basic", {'ts_code': '600519.SH', 'start_date': '20260613', 'end_date': '20260622'}))
# response.records 保持 Tushare 原始字段
```

## `monthly`

- 官方文档：[doc_id=145](https://tushare.pro/document/2?doc_id=145)
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
| `open` | string | - |
| `high` | string | - |
| `low` | string | - |
| `close` | string | - |
| `pre_close` | string | - |
| `change` | string | - |
| `pct_chg` | string | - |
| `vol` | string | - |
| `amount` | string | - |

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("monthly", {'ts_code': '600519.SH', 'start_date': '20250101', 'end_date': '20260622'}))
# response.records 保持 Tushare 原始字段
```

## `stk_factor`

- 官方文档：[doc_id=296](https://tushare.pro/document/2?doc_id=296)
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

该接口的返回字段尚未完成官方逐字段确认；Provider 仍完整保留上游 `fields/items`，请以官方文档为准。

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("stk_factor", {'ts_code': '600519.SH', 'start_date': '20260613', 'end_date': '20260622'}))
# response.records 保持 Tushare 原始字段
```

## `suspend_d`

- 官方文档：[doc_id=31](https://tushare.pro/document/2?doc_id=31)
- 积分门槛：`120`（confirmed）
- 当前状态：`documented`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `ts_code` | string | 否 | - | - |
| `trade_date` | date | 否 | - | - |
| `suspend_type` | string | 否 | S, R | - |

### 出参

该接口的返回字段尚未完成官方逐字段确认；Provider 仍完整保留上游 `fields/items`，请以官方文档为准。

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("suspend_d", {'trade_date': '20260620'}))
# response.records 保持 Tushare 原始字段
```

## `weekly`

- 官方文档：[doc_id=144](https://tushare.pro/document/2?doc_id=144)
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
| `open` | string | - |
| `high` | string | - |
| `low` | string | - |
| `close` | string | - |
| `pre_close` | string | - |
| `change` | string | - |
| `pct_chg` | string | - |
| `vol` | string | - |
| `amount` | string | - |

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("weekly", {'ts_code': '600519.SH', 'start_date': '20260501', 'end_date': '20260622'}))
# response.records 保持 Tushare 原始字段
```
