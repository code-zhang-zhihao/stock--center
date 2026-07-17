# Tushare `stock.financial`

Provider 只返回 Tushare 原始字段；调用方决定映射、raw landing 与入库。

## `balancesheet`

- 官方文档：[doc_id=36](https://tushare.pro/document/2?doc_id=36)
- 积分门槛：`2000`（confirmed）
- 当前状态：`documented`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `ts_code` | string | 否 | - | - |
| `ann_date` | date | 否 | - | - |
| `start_date` | date | 否 | - | - |
| `end_date` | date | 否 | - | - |
| `period` | date | 否 | - | - |
| `report_type` | string | 否 | - | - |
| `comp_type` | string | 否 | - | - |

### 出参

该接口的返回字段尚未完成官方逐字段确认；Provider 仍完整保留上游 `fields/items`，请以官方文档为准。

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("balancesheet", {'ts_code': '600519.SH', 'period': '20251231'}))
# response.records 保持 Tushare 原始字段
```

## `cashflow`

- 官方文档：[doc_id=44](https://tushare.pro/document/2?doc_id=44)
- 积分门槛：`2000`（confirmed）
- 当前状态：`documented`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `ts_code` | string | 否 | - | - |
| `ann_date` | date | 否 | - | - |
| `start_date` | date | 否 | - | - |
| `end_date` | date | 否 | - | - |
| `period` | date | 否 | - | - |
| `report_type` | string | 否 | - | - |
| `comp_type` | string | 否 | - | - |

### 出参

该接口的返回字段尚未完成官方逐字段确认；Provider 仍完整保留上游 `fields/items`，请以官方文档为准。

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("cashflow", {'ts_code': '600519.SH', 'period': '20251231'}))
# response.records 保持 Tushare 原始字段
```

## `disclosure_date`

- 官方文档：[doc_id=161](https://tushare.pro/document/2?doc_id=161)
- 积分门槛：`2000`（confirmed）
- 当前状态：`documented`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `ts_code` | string | 否 | - | - |
| `end_date` | date | 否 | - | - |
| `pre_date` | date | 否 | - | - |
| `actual_date` | date | 否 | - | - |

### 出参

该接口的返回字段尚未完成官方逐字段确认；Provider 仍完整保留上游 `fields/items`，请以官方文档为准。

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("disclosure_date", {'ts_code': '600519.SH'}))
# response.records 保持 Tushare 原始字段
```

## `express`

- 官方文档：[doc_id=46](https://tushare.pro/document/2?doc_id=46)
- 积分门槛：`2000`（confirmed）
- 当前状态：`documented`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `ts_code` | string | 否 | - | - |
| `ann_date` | date | 否 | - | - |
| `start_date` | date | 否 | - | - |
| `end_date` | date | 否 | - | - |
| `period` | date | 否 | - | - |

### 出参

该接口的返回字段尚未完成官方逐字段确认；Provider 仍完整保留上游 `fields/items`，请以官方文档为准。

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("express", {'ts_code': '600519.SH', 'period': '20251231'}))
# response.records 保持 Tushare 原始字段
```

## `fina_audit`

- 官方文档：[doc_id=80](https://tushare.pro/document/2?doc_id=80)
- 积分门槛：`2000`（confirmed）
- 当前状态：`documented`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `ts_code` | string | 否 | - | - |
| `ann_date` | date | 否 | - | - |
| `start_date` | date | 否 | - | - |
| `end_date` | date | 否 | - | - |
| `period` | date | 否 | - | - |

### 出参

该接口的返回字段尚未完成官方逐字段确认；Provider 仍完整保留上游 `fields/items`，请以官方文档为准。

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("fina_audit", {'ts_code': '600519.SH', 'period': '20251231'}))
# response.records 保持 Tushare 原始字段
```

## `fina_indicator`

- 官方文档：[doc_id=79](https://tushare.pro/document/2?doc_id=79)
- 积分门槛：`2000`（confirmed）
- 当前状态：`documented`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `ts_code` | string | 否 | - | - |
| `ann_date` | date | 否 | - | - |
| `start_date` | date | 否 | - | - |
| `end_date` | date | 否 | - | - |
| `period` | date | 否 | - | - |

### 出参

该接口的返回字段尚未完成官方逐字段确认；Provider 仍完整保留上游 `fields/items`，请以官方文档为准。

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("fina_indicator", {'ts_code': '600519.SH', 'period': '20251231'}))
# response.records 保持 Tushare 原始字段
```

## `fina_mainbz`

- 官方文档：[doc_id=81](https://tushare.pro/document/2?doc_id=81)
- 积分门槛：`2000`（confirmed）
- 当前状态：`documented`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `ts_code` | string | 否 | - | - |
| `period` | date | 否 | - | - |
| `type` | string | 否 | P, D | - |
| `start_date` | date | 否 | - | - |
| `end_date` | date | 否 | - | - |

### 出参

该接口的返回字段尚未完成官方逐字段确认；Provider 仍完整保留上游 `fields/items`，请以官方文档为准。

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("fina_mainbz", {'ts_code': '600519.SH', 'period': '20251231'}))
# response.records 保持 Tushare 原始字段
```

## `forecast`

- 官方文档：[doc_id=45](https://tushare.pro/document/2?doc_id=45)
- 积分门槛：`2000`（confirmed）
- 当前状态：`documented`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `ts_code` | string | 否 | - | - |
| `ann_date` | date | 否 | - | - |
| `start_date` | date | 否 | - | - |
| `end_date` | date | 否 | - | - |
| `period` | date | 否 | - | - |
| `type` | string | 否 | - | - |

### 出参

该接口的返回字段尚未完成官方逐字段确认；Provider 仍完整保留上游 `fields/items`，请以官方文档为准。

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("forecast", {'ts_code': '600519.SH', 'period': '20251231'}))
# response.records 保持 Tushare 原始字段
```

## `income`

- 官方文档：[doc_id=33](https://tushare.pro/document/2?doc_id=33)
- 积分门槛：`2000`（confirmed）
- 当前状态：`documented`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `ts_code` | string | 否 | - | - |
| `ann_date` | date | 否 | - | - |
| `start_date` | date | 否 | - | - |
| `end_date` | date | 否 | - | - |
| `period` | date | 否 | - | - |
| `report_type` | string | 否 | - | - |
| `comp_type` | string | 否 | - | - |

### 出参

该接口的返回字段尚未完成官方逐字段确认；Provider 仍完整保留上游 `fields/items`，请以官方文档为准。

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("income", {'ts_code': '600519.SH', 'period': '20251231'}))
# response.records 保持 Tushare 原始字段
```
