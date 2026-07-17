# Tushare `index.basic`

Provider 只返回 Tushare 原始字段；调用方决定映射、raw landing 与入库。

## `index_basic`

- 官方文档：[doc_id=94](https://tushare.pro/document/2?doc_id=94)
- 积分门槛：`120`（confirmed）
- 当前状态：`called_by_business, documented, persisted`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `ts_code` | string | 否 | - | - |
| `name` | string | 否 | - | - |
| `market` | string | 否 | SSE, SZSE, CSI, CICC, SW, MSCI, OTH | - |
| `publisher` | string | 否 | - | - |
| `category` | string | 否 | - | - |

### 出参

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ts_code` | string | - |
| `name` | string | - |
| `market` | string | - |
| `publisher` | string | - |
| `category` | string | - |
| `base_date` | string | - |
| `base_point` | string | - |
| `list_date` | string | - |
| `weight_rule` | string | - |
| `desc` | string | - |
| `exp_date` | string | - |

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("index_basic", {'market': 'SSE'}))
# response.records 保持 Tushare 原始字段
```

## `index_classify`

- 官方文档：[doc_id=181](https://tushare.pro/document/2?doc_id=181)
- 积分门槛：`2000`（confirmed）
- 当前状态：`called_by_business, documented, persisted`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `index_code` | string | 否 | - | - |
| `level` | string | 否 | - | - |
| `src` | string | 否 | SW2021, SW2014, CI, CSI, SSE, SZSE | - |

### 出参

该接口的返回字段尚未完成官方逐字段确认；Provider 仍完整保留上游 `fields/items`，请以官方文档为准。

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("index_classify", {'src': 'SW2021'}))
# response.records 保持 Tushare 原始字段
```

## `ths_index`

- 官方文档：[doc_id=259](https://tushare.pro/document/2?doc_id=259)
- 积分门槛：`6000`（confirmed）
- 当前状态：`called_by_business, documented, persisted`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `ts_code` | string | 否 | - | - |
| `exchange` | string | 否 | A | - |
| `type` | string | 否 | N, I, G | - |

### 出参

该接口的返回字段尚未完成官方逐字段确认；Provider 仍完整保留上游 `fields/items`，请以官方文档为准。

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("ths_index", {'exchange': 'A', 'type': 'N'}))
# response.records 保持 Tushare 原始字段
```
