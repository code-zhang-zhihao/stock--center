from app.modules.market_data.tushare.catalog.common import api, p


SPECS = (
    api("margin", "stock.margin", 58, min_points=2000, params=(p("trade_date", value_type="date"), p("exchange_id", enum=("SSE", "SZSE", "BSE"))), audit_params={"trade_date": "20260620", "exchange_id": "SSE"}, allow_extra_params=True),
    api("margin_detail", "stock.margin", 59, min_points=2000, params=(p("trade_date", value_type="date"), p("ts_code")), audit_params={"ts_code": "600519.SH", "trade_date": "20260620"}, allow_extra_params=True),
)
