from app.modules.market_data.tushare.catalog.common import api, p


SPECS = (
    api("top_list", "stock.board_trading", 106, min_points=2000, params=(p("trade_date", value_type="date"), p("ts_code"), p("start_date", value_type="date"), p("end_date", value_type="date")), audit_params={"trade_date": "20260620"}, allow_extra_params=True),
    api("top_inst", "stock.board_trading", 107, min_points=2000, params=(p("trade_date", True, "date"), p("ts_code")), audit_params={"trade_date": "20260620"}, allow_extra_params=True),
)
