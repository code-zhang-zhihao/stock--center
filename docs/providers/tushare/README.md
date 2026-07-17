# Tushare Provider 契约

本文档由 `python-back/scripts/export_tushare_catalog_docs.py` 自动生成。

- Provider 只做参数校验、Token/URL 注入、HTTP 传输和原始响应解析。
- `TushareApiResponse.records` 与上游字段一致，不包含 Canonical 字段。
- `point_status=unknown` 或未列出出参字段的接口，不能被视为已完整审计。

## 官方目录

- [index.basic](index/basic.md)
- [index.citic_industry](index/citic_industry.md)
- [index.component](index/component.md)
- [index.market](index/market.md)
- [index.market_statistics](index/market_statistics.md)
- [index.sw_industry](index/sw_industry.md)
- [stock.basic](stock/basic.md)
- [stock.board_trading](stock/board_trading.md)
- [stock.featured](stock/featured.md)
- [stock.financial](stock/financial.md)
- [stock.fund_flow](stock/fund_flow.md)
- [stock.margin](stock/margin.md)
- [stock.market](stock/market.md)
- [stock.reference](stock/reference.md)
