# Tushare `stock.featured`

Provider 只返回 Tushare 原始字段；调用方决定映射、raw landing 与入库。

## `anns_d`

- 官方文档：[doc_id=395](https://tushare.pro/document/2?doc_id=395)
- 积分门槛：`10000`（confirmed）
- 当前状态：`documented`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `ts_code` | string | 否 | - | - |
| `ann_date` | date | 否 | - | - |
| `start_date` | date | 否 | - | - |
| `end_date` | date | 否 | - | - |

### 出参

该接口的返回字段尚未完成官方逐字段确认；Provider 仍完整保留上游 `fields/items`，请以官方文档为准。

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("anns_d", {'ts_code': '600519.SH', 'start_date': '20260613', 'end_date': '20260622'}))
# response.records 保持 Tushare 原始字段
```

## `limit_list_d`

- 官方文档：[doc_id=298](https://tushare.pro/document/2?doc_id=298)
- 积分门槛：`8000`（confirmed）
- 当前状态：`documented`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `trade_date` | date | 是 | - | - |
| `ts_code` | string | 否 | - | - |
| `limit` | string | 否 | U, D | - |

### 出参

该接口的返回字段尚未完成官方逐字段确认；Provider 仍完整保留上游 `fields/items`，请以官方文档为准。

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("limit_list_d", {'trade_date': '20260620'}))
# response.records 保持 Tushare 原始字段
```

## `stk_limit`

- 官方文档：[doc_id=183](https://tushare.pro/document/2?doc_id=183)
- 积分门槛：`5000`（confirmed）
- 当前状态：`documented`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `ts_code` | string | 否 | - | - |
| `trade_date` | date | 否 | - | - |

### 出参

该接口的返回字段尚未完成官方逐字段确认；Provider 仍完整保留上游 `fields/items`，请以官方文档为准。

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("stk_limit", {'ts_code': '600519.SH', 'trade_date': '20260620'}))
# response.records 保持 Tushare 原始字段
```

## `ths_hot`

- 官方文档：[doc_id=320](https://tushare.pro/document/2?doc_id=320)
- 积分门槛：`6000`（confirmed）
- 当前状态：`documented`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `trade_date` | date | 否 | - | - |
| `ts_code` | string | 否 | - | - |
| `market` | string | 否 | 热股, ETF, 可转债, 行业板块, 概念板块, 期货, 港股, 热基, 美股 | - |
| `is_new` | string | 否 | Y, N | - |

### 出参

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `trade_date` | string | - |
| `data_type` | string | - |
| `ts_code` | string | - |
| `ts_name` | string | - |
| `rank` | string | - |
| `pct_change` | string | - |
| `current_price` | string | - |
| `concept` | string | - |
| `rank_reason` | string | - |
| `hot` | string | - |
| `rank_time` | string | - |

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("ths_hot", {'market': '概念板块', 'is_new': 'Y'}))
# response.records 保持 Tushare 原始字段
```
