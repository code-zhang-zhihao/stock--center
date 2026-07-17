from app.modules.market_data.tushare.catalog.common import api, fields, p


SPECS = (
    api("stk_limit", "stock.featured", 183, min_points=5000, params=(p("ts_code"), p("trade_date", value_type="date")), audit_params={"ts_code": "600519.SH", "trade_date": "20260620"}, allow_extra_params=True),
    api("limit_list_d", "stock.featured", 298, min_points=8000, params=(p("trade_date", True, "date"), p("ts_code"), p("limit", enum=("U", "D"))), audit_params={"trade_date": "20260620"}, allow_extra_params=True),
    api("anns_d", "stock.featured", 395, min_points=10000, params=(p("ts_code"), p("ann_date", value_type="date"), p("start_date", value_type="date"), p("end_date", value_type="date")), audit_params={"ts_code": "600519.SH", "start_date": "20260613", "end_date": "20260622"}, allow_extra_params=True),
    api("ths_hot", "stock.featured", 320, min_points=6000, params=(p("trade_date", value_type="date"), p("ts_code"), p("market", enum=("热股", "ETF", "可转债", "行业板块", "概念板块", "期货", "港股", "热基", "美股")), p("is_new", enum=("Y", "N"))), output_fields=fields("trade_date", "data_type", "ts_code", "ts_name", "rank", "pct_change", "current_price", "concept", "rank_reason", "hot", "rank_time"), audit_params={"market": "概念板块", "is_new": "Y"}),
    api("cyq_perf", "stock.featured", 293, min_points=5000, params=(p("ts_code", True), p("trade_date", value_type="date"), p("start_date", value_type="date"), p("end_date", value_type="date")), output_fields=fields("ts_code", "trade_date", "his_low", "his_high", "cost_5pct", "cost_15pct", "cost_50pct", "cost_85pct", "cost_95pct", "weight_avg", "winner_rate"), audit_params={"ts_code": "600519.SH", "start_date": "20260613", "end_date": "20260622"}, status=frozenset({"documented", "called_by_business", "persisted"})),
    api("cyq_chips", "stock.featured", 294, min_points=5000, params=(p("ts_code", True), p("trade_date", value_type="date"), p("start_date", value_type="date"), p("end_date", value_type="date")), output_fields=fields("ts_code", "trade_date", "price", "percent"), audit_params={"ts_code": "600519.SH", "start_date": "20260613", "end_date": "20260622"}, status=frozenset({"documented"})),
)
