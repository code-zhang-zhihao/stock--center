# TdxQuant 本地客户端探测

`TdxQuant` 是通达信官方客户端提供的本地量化数据服务，不等同于当前的 `MooTDX` 公共服务器 Provider。

探测器会强制直连本地/指定数据机地址，不继承系统 HTTP 代理，避免 `127.0.0.1:17709` 被代理错误转发。

## 前置条件

1. 安装并启动支持 TQ 的通达信金融终端、量化模拟版或专业研究版。
2. 确认本机 TQ HTTP 服务监听 `127.0.0.1:17709`；默认不能从未启动客户端的 `stock-center` 后端直接获得数据。
3. 在后端目录执行：

```bash
cd python-back
.venv/bin/python scripts/probe_tdxquant.py --check-pricevol
```

远程数据机可以显式指定 URL：

```bash
.venv/bin/python scripts/probe_tdxquant.py --endpoint http://192.168.1.10:17709/ --check-pricevol
```

## 探测范围

- `get_market_snapshot`：样本实时快照及五档买卖盘字段。
- `get_market_data(period=1d)`：批量日 K、成交量、成交额。
- `get_market_data(period=1m)`：指定股票最近 240 根分钟线。
- `get_stock_list(market=5)`：A 股证券目录能力。
- `get_sector_list`：板块目录能力。
- `get_pricevol`：可选探测官方新增批量价格/成交量接口；不同客户端版本的参数/返回形状以实际探测为准。

探测器只输出经过裁剪的字段、状态和耗时，不保存原始数据，不写 Redis、PostgreSQL 或 `t_provider_raw_record`。

## 采用门槛

接入 `RealtimeMarketService` 前必须至少证明：

1. 样本快照包含 `Buyp/Buyv/Sellp/Sellv` 五档字段。
2. 200 只样本快照可稳定取得，且连续盘中探测无明显缺失。
3. A 股目录、分钟 K 线和服务端返回的字段/单位已记录在探测报告中。
4. 全市场方案必须实测后确定：优先验证 `get_pricevol` 是否可承担批量价量，再决定是否将 `get_market_snapshot` 用于全市场或仅重点股票。
