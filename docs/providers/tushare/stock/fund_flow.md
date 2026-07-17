# Tushare `stock.fund_flow`

Provider 只返回 Tushare 原始字段；调用方决定映射、raw landing 与入库。

## `hsgt_top10`

- 官方文档：[doc_id=47](https://tushare.pro/document/2?doc_id=47)
- 积分门槛：`2000`（confirmed）
- 当前状态：`documented`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `trade_date` | date | 是 | - | - |
| `market_type` | string | 否 | 1, 3 | - |

### 出参

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `trade_date` | string | - |
| `ts_code` | string | - |
| `name` | string | - |
| `close` | string | - |
| `change` | string | - |
| `rank` | string | - |
| `market_type` | string | - |
| `amount` | string | - |
| `net_amount` | string | - |
| `buy` | string | - |
| `sell` | string | - |

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("hsgt_top10", {'trade_date': '20260620'}))
# response.records 保持 Tushare 原始字段
```

## `moneyflow`

- 官方文档：[doc_id=170](https://tushare.pro/document/2?doc_id=170)
- 积分门槛：`2000`（confirmed）
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
| `buy_sm_vol` | string | - |
| `buy_sm_amount` | string | - |
| `sell_sm_vol` | string | - |
| `sell_sm_amount` | string | - |
| `buy_md_vol` | string | - |
| `buy_md_amount` | string | - |
| `sell_md_vol` | string | - |
| `sell_md_amount` | string | - |
| `buy_lg_vol` | string | - |
| `buy_lg_amount` | string | - |
| `sell_lg_vol` | string | - |
| `sell_lg_amount` | string | - |
| `buy_elg_vol` | string | - |
| `buy_elg_amount` | string | - |
| `sell_elg_vol` | string | - |
| `sell_elg_amount` | string | - |
| `net_mf_vol` | string | - |
| `net_mf_amount` | string | - |

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("moneyflow", {'ts_code': '600519.SH', 'start_date': '20260613', 'end_date': '20260622'}))
# response.records 保持 Tushare 原始字段
```

## `moneyflow_cnt_ths`

- 官方文档：[doc_id=371](https://tushare.pro/document/2?doc_id=371)
- 积分门槛：`6000`（confirmed）
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
| `trade_date` | string | - |
| `ts_code` | string | - |
| `name` | string | - |
| `lead_stock` | string | - |
| `close_price` | string | - |
| `pct_change` | string | - |
| `industry_index` | string | - |
| `company_num` | string | - |
| `pct_change_stock` | string | - |
| `net_buy_amount` | string | - |
| `net_sell_amount` | string | - |
| `net_amount` | string | - |

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("moneyflow_cnt_ths", {'ts_code': '885748.TI', 'start_date': '20260613', 'end_date': '20260622'}))
# response.records 保持 Tushare 原始字段
```

## `moneyflow_hsgt`

- 官方文档：[doc_id=47](https://tushare.pro/document/2?doc_id=47)
- 积分门槛：`2000`（confirmed）
- 当前状态：`documented`

### 入参

| 参数 | 类型 | 必填 | 枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `trade_date` | date | 否 | - | - |
| `start_date` | date | 否 | - | - |
| `end_date` | date | 否 | - | - |

### 出参

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `trade_date` | string | - |
| `ggt_ss` | string | - |
| `ggt_sz` | string | - |
| `hgt` | string | - |
| `sgt` | string | - |
| `north_money` | string | - |
| `south_money` | string | - |

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("moneyflow_hsgt", {'start_date': '20260613', 'end_date': '20260622'}))
# response.records 保持 Tushare 原始字段
```

## `moneyflow_ind_ths`

- 官方文档：[doc_id=343](https://tushare.pro/document/2?doc_id=343)
- 积分门槛：`6000`（confirmed）
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
| `trade_date` | string | - |
| `ts_code` | string | - |
| `industry` | string | - |
| `lead_stock` | string | - |
| `close` | string | - |
| `pct_change` | string | - |
| `company_num` | string | - |
| `pct_change_stock` | string | - |
| `close_price` | string | - |
| `net_buy_amount` | string | - |
| `net_sell_amount` | string | - |
| `net_amount` | string | - |

### Raw 调用

```python
from app.modules.market_data.tushare.contracts import TushareApiRequest

response = await transport.request(TushareApiRequest("moneyflow_ind_ths", {'start_date': '20260613', 'end_date': '20260622'}))
# response.records 保持 Tushare 原始字段
```
