# Tushare `index.market_statistics`

Provider 只返回 Tushare 原始字段；调用方决定映射、raw landing 与入库。

## `daily_info`

- 官方文档：[doc_id=215](https://tushare.pro/document/2?doc_id=215)
- 积分门槛：`600`（confirmed）
- 当前状态：`documented`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `trade_date` | date | 否 | - | - |
| `ts_code` | string | 否 | - | - |
| `exchange` | string | 否 | SH, SZ | - |
| `start_date` | date | 否 | - | - |
| `end_date` | date | 否 | - | - |

### 出参

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `trade_date` | string | - |
| `ts_code` | string | - |
| `ts_name` | string | - |
| `com_count` | string | - |
| `total_share` | string | - |
| `float_share` | string | - |
| `total_mv` | string | - |
| `float_mv` | string | - |
| `amount` | string | - |
| `vol` | string | - |
| `trans_count` | string | - |
| `pe` | string | - |
| `tr` | string | - |
| `exchange` | string | - |

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("daily_info", {'trade_date': '20260620', 'exchange': 'SH'}))
# response.records 保持 Tushare 原始字段
```
