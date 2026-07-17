# Tushare `stock.reference`

Provider 只返回 Tushare 原始字段；调用方决定映射、raw landing 与入库。

## `dividend`

- 官方文档：[doc_id=103](https://tushare.pro/document/2?doc_id=103)
- 积分门槛：`2000`（confirmed）
- 当前状态：`documented`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `ts_code` | string | 否 | - | - |
| `ann_date` | date | 否 | - | - |
| `record_date` | date | 否 | - | - |
| `ex_date` | date | 否 | - | - |
| `imp_ann_date` | date | 否 | - | - |

### 出参

该接口的返回字段尚未完成官方逐字段确认；Provider 仍完整保留上游 `fields/items`，请以官方文档为准。

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("dividend", {'ts_code': '600519.SH'}))
# response.records 保持 Tushare 原始字段
```

## `pledge_detail`

- 官方文档：[doc_id=111](https://tushare.pro/document/2?doc_id=111)
- 积分门槛：`2000`（confirmed）
- 当前状态：`documented`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `ts_code` | string | 是 | - | - |

### 出参

该接口的返回字段尚未完成官方逐字段确认；Provider 仍完整保留上游 `fields/items`，请以官方文档为准。

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("pledge_detail", {'ts_code': '600519.SH'}))
# response.records 保持 Tushare 原始字段
```

## `pledge_stat`

- 官方文档：[doc_id=110](https://tushare.pro/document/2?doc_id=110)
- 积分门槛：`2000`（confirmed）
- 当前状态：`documented`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `ts_code` | string | 是 | - | - |

### 出参

该接口的返回字段尚未完成官方逐字段确认；Provider 仍完整保留上游 `fields/items`，请以官方文档为准。

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("pledge_stat", {'ts_code': '600519.SH'}))
# response.records 保持 Tushare 原始字段
```

## `repurchase`

- 官方文档：[doc_id=124](https://tushare.pro/document/2?doc_id=124)
- 积分门槛：`2000`（confirmed）
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

response = await transport.request(TushareApiRequest("repurchase", {'ts_code': '600519.SH'}))
# response.records 保持 Tushare 原始字段
```

## `share_float`

- 官方文档：[doc_id=160](https://tushare.pro/document/2?doc_id=160)
- 积分门槛：`2000`（confirmed）
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

response = await transport.request(TushareApiRequest("share_float", {'ts_code': '600519.SH'}))
# response.records 保持 Tushare 原始字段
```

## `stk_holdernumber`

- 官方文档：[doc_id=166](https://tushare.pro/document/2?doc_id=166)
- 积分门槛：`2000`（confirmed）
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

response = await transport.request(TushareApiRequest("stk_holdernumber", {'ts_code': '600519.SH'}))
# response.records 保持 Tushare 原始字段
```

## `stk_holdertrade`

- 官方文档：[doc_id=175](https://tushare.pro/document/2?doc_id=175)
- 积分门槛：`2000`（confirmed）
- 当前状态：`documented`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `ts_code` | string | 否 | - | - |
| `ann_date` | date | 否 | - | - |
| `start_date` | date | 否 | - | - |
| `end_date` | date | 否 | - | - |
| `trade_type` | string | 否 | IN, DE | - |
| `holder_type` | string | 否 | - | - |

### 出参

该接口的返回字段尚未完成官方逐字段确认；Provider 仍完整保留上游 `fields/items`，请以官方文档为准。

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("stk_holdertrade", {'ts_code': '600519.SH', 'start_date': '20260601', 'end_date': '20260622'}))
# response.records 保持 Tushare 原始字段
```

## `top10_floatholders`

- 官方文档：[doc_id=102](https://tushare.pro/document/2?doc_id=102)
- 积分门槛：`2000`（confirmed）
- 当前状态：`documented`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `ts_code` | string | 是 | - | - |
| `period` | date | 是 | - | - |
| `ann_date` | date | 否 | - | - |

### 出参

该接口的返回字段尚未完成官方逐字段确认；Provider 仍完整保留上游 `fields/items`，请以官方文档为准。

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("top10_floatholders", {'ts_code': '600519.SH', 'period': '20251231'}))
# response.records 保持 Tushare 原始字段
```

## `top10_holders`

- 官方文档：[doc_id=101](https://tushare.pro/document/2?doc_id=101)
- 积分门槛：`2000`（confirmed）
- 当前状态：`documented`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `ts_code` | string | 是 | - | - |
| `period` | date | 是 | - | - |
| `ann_date` | date | 否 | - | - |

### 出参

该接口的返回字段尚未完成官方逐字段确认；Provider 仍完整保留上游 `fields/items`，请以官方文档为准。

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("top10_holders", {'ts_code': '600519.SH', 'period': '20251231'}))
# response.records 保持 Tushare 原始字段
```
