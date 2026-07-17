from app.modules.market_data.tushare.catalog.common import api, p


SPECS = (
    api("ci_index_member", "index.citic_industry", 373, min_points=2000, params=(p("index_code"), p("ts_code"), p("is_new", enum=("Y", "N"))), audit_params={"index_code": "CI005001.WI"}, allow_extra_params=True),
    api("ci_daily", "index.citic_industry", 308, min_points=2000, params=(p("ts_code"), p("trade_date", value_type="date"), p("start_date", value_type="date"), p("end_date", value_type="date")), audit_params={"ts_code": "CI005001.WI", "start_date": "20260613", "end_date": "20260622"}, allow_extra_params=True),
)
