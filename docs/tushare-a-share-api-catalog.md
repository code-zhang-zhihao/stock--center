# Tushare Pro A 股接口目录

`python-back/app/modules/market_data/tushare/catalog/` 是项目内 Tushare Pro A 股 API 的唯一传输契约来源，按官网的股票数据、指数专题目录拆分。`tushare_catalog.py` 只保留旧导入路径兼容层。

每个条目包含 API 名称、分类、官方 `doc_id` 链接、积分确认状态、输入参数、已确认输出字段和安全审计参数。完整调用文档由脚本生成到 `docs/providers/tushare/`；Provider 只根据该目录发起原始请求，字段映射、单位换算、raw landing 和 Canonical 入库属于调用方。

常用命令：

```bash
cd python-back
.venv/bin/python scripts/audit_tushare_a_share_catalog.py --api daily
.venv/bin/python scripts/audit_tushare_a_share_catalog.py --category stock.financial
.venv/bin/python scripts/audit_tushare_a_share_catalog.py --all
```

`--all` 会实际调用每个安全样例、写入 `t_runtime_call_log`，并将详细 JSON 输出到 gitignore 的 `python-back/data/audits/`。仅应在显式权限审计时执行；配置页面的 Token 测试仍只调用一次 `daily`。
