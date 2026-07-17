# Tushare `stock.margin`

Provider 只返回 Tushare 原始字段；调用方决定映射、raw landing 与入库。

## `margin`

- 官方文档：[doc_id=58](https://tushare.pro/document/2?doc_id=58)
- 积分门槛：`2000`（confirmed）
- 当前状态：`documented`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `trade_date` | date | 否 | - | - |
| `exchange_id` | string | 否 | SSE, SZSE, BSE | - |

### 出参

该接口的返回字段尚未完成官方逐字段确认；Provider 仍完整保留上游 `fields/items`，请以官方文档为准。

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("margin", {'trade_date': '20260620', 'exchange_id': 'SSE'}))
# response.records 保持 Tushare 原始字段
```

## `margin_detail`

- 官方文档：[doc_id=59](https://tushare.pro/document/2?doc_id=59)
- 积分门槛：`2000`（confirmed）
- 当前状态：`documented`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `trade_date` | date | 否 | - | - |
| `ts_code` | string | 否 | - | - |

### 出参

该接口的返回字段尚未完成官方逐字段确认；Provider 仍完整保留上游 `fields/items`，请以官方文档为准。

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("margin_detail", {'ts_code': '600519.SH', 'trade_date': '20260620'}))
# response.records 保持 Tushare 原始字段
```
