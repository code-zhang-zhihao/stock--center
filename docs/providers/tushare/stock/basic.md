# Tushare `stock.basic`

Provider 只返回 Tushare 原始字段；调用方决定映射、raw landing 与入库。

## `namechange`

- 官方文档：[doc_id=100](https://tushare.pro/document/2?doc_id=100)
- 积分门槛：`120`（confirmed）
- 当前状态：`documented`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `ts_code` | string | 是 | - | - |
| `start_date` | date | 否 | - | - |
| `end_date` | date | 否 | - | - |

### 出参

该接口的返回字段尚未完成官方逐字段确认；Provider 仍完整保留上游 `fields/items`，请以官方文档为准。

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("namechange", {'ts_code': '600519.SH'}))
# response.records 保持 Tushare 原始字段
```

## `new_share`

- 官方文档：[doc_id=123](https://tushare.pro/document/2?doc_id=123)
- 积分门槛：`120`（confirmed）
- 当前状态：`documented`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `start_date` | date | 否 | - | - |
| `end_date` | date | 否 | - | - |

### 出参

该接口的返回字段尚未完成官方逐字段确认；Provider 仍完整保留上游 `fields/items`，请以官方文档为准。

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("new_share", {'start_date': '20260601', 'end_date': '20260622'}))
# response.records 保持 Tushare 原始字段
```

## `stock_basic`

- 官方文档：[doc_id=25](https://tushare.pro/document/2?doc_id=25)
- 积分门槛：`120`（confirmed）
- 当前状态：`called_by_business, documented, persisted`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `ts_code` | string | 否 | - | - |
| `name` | string | 否 | - | - |
| `exchange` | string | 否 | , SSE, SZSE, BSE | - |
| `market` | string | 否 | - | - |
| `list_status` | string | 否 | L, D, P | - |
| `is_hs` | string | 否 | N, H, S | - |

### 出参

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ts_code` | string | - |
| `symbol` | string | - |
| `name` | string | - |
| `area` | string | - |
| `industry` | string | - |
| `market` | string | - |
| `list_date` | string | - |
| `delist_date` | string | - |
| `list_status` | string | - |

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("stock_basic", {'ts_code': '600519.SH', 'list_status': 'L'}))
# response.records 保持 Tushare 原始字段
```

## `stock_company`

- 官方文档：[doc_id=112](https://tushare.pro/document/2?doc_id=112)
- 积分门槛：`120`（confirmed）
- 当前状态：`documented`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `ts_code` | string | 否 | - | - |
| `exchange` | string | 否 | SSE, SZSE, BSE | - |

### 出参

该接口的返回字段尚未完成官方逐字段确认；Provider 仍完整保留上游 `fields/items`，请以官方文档为准。

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("stock_company", {'ts_code': '600519.SH'}))
# response.records 保持 Tushare 原始字段
```

## `trade_cal`

- 官方文档：[doc_id=26](https://tushare.pro/document/2?doc_id=26)
- 积分门槛：`120`（confirmed）
- 当前状态：`called_by_business, documented, persisted`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `exchange` | string | 否 | SSE, SZSE, BSE | - |
| `cal_date` | date | 否 | - | - |
| `start_date` | date | 否 | - | - |
| `end_date` | date | 否 | - | - |
| `is_open` | string | 否 | 0, 1 | - |

### 出参

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `exchange` | string | - |
| `cal_date` | string | - |
| `is_open` | string | - |
| `pretrade_date` | string | - |

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("trade_cal", {'exchange': 'SSE', 'start_date': '20260613', 'end_date': '20260622'}))
# response.records 保持 Tushare 原始字段
```
