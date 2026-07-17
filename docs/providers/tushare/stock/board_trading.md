# Tushare `stock.board_trading`

Provider 只返回 Tushare 原始字段；调用方决定映射、raw landing 与入库。

## `top_inst`

- 官方文档：[doc_id=107](https://tushare.pro/document/2?doc_id=107)
- 积分门槛：`2000`（confirmed）
- 当前状态：`documented`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `trade_date` | date | 是 | - | - |
| `ts_code` | string | 否 | - | - |

### 出参

该接口的返回字段尚未完成官方逐字段确认；Provider 仍完整保留上游 `fields/items`，请以官方文档为准。

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("top_inst", {'trade_date': '20260620'}))
# response.records 保持 Tushare 原始字段
```

## `top_list`

- 官方文档：[doc_id=106](https://tushare.pro/document/2?doc_id=106)
- 积分门槛：`2000`（confirmed）
- 当前状态：`documented`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `trade_date` | date | 否 | - | - |
| `ts_code` | string | 否 | - | - |
| `start_date` | date | 否 | - | - |
| `end_date` | date | 否 | - | - |

### 出参

该接口的返回字段尚未完成官方逐字段确认；Provider 仍完整保留上游 `fields/items`，请以官方文档为准。

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("top_list", {'trade_date': '20260620'}))
# response.records 保持 Tushare 原始字段
```
