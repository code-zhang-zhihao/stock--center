from app.modules.market_data.tushare.catalog.common import api, p


SPECS = (
    api("sw_daily", "index.sw_industry", 327, min_points=2000, params=(p("ts_code"), p("trade_date", value_type="date"), p("start_date", value_type="date"), p("end_date", value_type="date")), audit_params={"ts_code": "801010.SI", "start_date": "20260613", "end_date": "20260622"}, allow_extra_params=True),
)
