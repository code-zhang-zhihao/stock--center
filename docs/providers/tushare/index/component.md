# Tushare `index.component`

Provider 只返回 Tushare 原始字段；调用方决定映射、raw landing 与入库。

## `index_member_all`

- 官方文档：[doc_id=335](https://tushare.pro/document/2?doc_id=335)
- 积分门槛：`2000`（confirmed）
- 当前状态：`called_by_business, documented, persisted`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `l1_code` | string | 否 | - | - |
| `l2_code` | string | 否 | - | - |
| `l3_code` | string | 否 | - | - |
| `ts_code` | string | 否 | - | - |
| `is_new` | string | 否 | Y, N | - |

### 出参

该接口的返回字段尚未完成官方逐字段确认；Provider 仍完整保留上游 `fields/items`，请以官方文档为准。

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("index_member_all", {'l1_code': '110000', 'is_new': 'Y'}))
# response.records 保持 Tushare 原始字段
```

## `index_weight`

- 官方文档：[doc_id=96](https://tushare.pro/document/2?doc_id=96)
- 积分门槛：`2000`（confirmed）
- 当前状态：`called_by_business, documented, persisted`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `index_code` | string | 是 | - | - |
| `trade_date` | date | 否 | - | - |
| `start_date` | date | 否 | - | - |
| `end_date` | date | 否 | - | - |

### 出参

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `index_code` | string | - |
| `con_code` | string | - |
| `trade_date` | string | - |
| `weight` | string | - |

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("index_weight", {'index_code': '000001.SH', 'start_date': '20260201', 'end_date': '20260622'}))
# response.records 保持 Tushare 原始字段
```

## `ths_member`

- 官方文档：[doc_id=261](https://tushare.pro/document/2?doc_id=261)
- 积分门槛：`6000`（confirmed）
- 当前状态：`called_by_business, documented, persisted`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `ts_code` | string | 是 | - | - |

### 出参

该接口的返回字段尚未完成官方逐字段确认；Provider 仍完整保留上游 `fields/items`，请以官方文档为准。

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("ths_member", {'ts_code': '885001.TI'}))
# response.records 保持 Tushare 原始字段
```
