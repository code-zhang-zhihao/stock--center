from app.modules.market_data.tushare.catalog.common import api, p


SPECS = (
    api("dividend", "stock.reference", 103, min_points=2000, params=(p("ts_code"), p("ann_date", value_type="date"), p("record_date", value_type="date"), p("ex_date", value_type="date"), p("imp_ann_date", value_type="date")), audit_params={"ts_code": "600519.SH"}, allow_extra_params=True),
    api("share_float", "stock.reference", 160, min_points=2000, params=(p("ts_code"), p("ann_date", value_type="date"), p("start_date", value_type="date"), p("end_date", value_type="date")), audit_params={"ts_code": "600519.SH"}, allow_extra_params=True),
    api("repurchase", "stock.reference", 124, min_points=2000, params=(p("ts_code"), p("ann_date", value_type="date"), p("start_date", value_type="date"), p("end_date", value_type="date")), audit_params={"ts_code": "600519.SH"}, allow_extra_params=True),
    api("pledge_stat", "stock.reference", 110, min_points=2000, params=(p("ts_code", True),), audit_params={"ts_code": "600519.SH"}, allow_extra_params=True),
    api("pledge_detail", "stock.reference", 111, min_points=2000, params=(p("ts_code", True),), audit_params={"ts_code": "600519.SH"}, allow_extra_params=True),
    api("stk_holdernumber", "stock.reference", 166, min_points=2000, params=(p("ts_code"), p("ann_date", value_type="date"), p("start_date", value_type="date"), p("end_date", value_type="date")), audit_params={"ts_code": "600519.SH"}, allow_extra_params=True),
    api("top10_holders", "stock.reference", 101, min_points=2000, params=(p("ts_code", True), p("period", True, "date"), p("ann_date", value_type="date")), audit_params={"ts_code": "600519.SH", "period": "20251231"}, allow_extra_params=True),
    api("top10_floatholders", "stock.reference", 102, min_points=2000, params=(p("ts_code", True), p("period", True, "date"), p("ann_date", value_type="date")), audit_params={"ts_code": "600519.SH", "period": "20251231"}, allow_extra_params=True),
    api("stk_holdertrade", "stock.reference", 175, min_points=2000, params=(p("ts_code"), p("ann_date", value_type="date"), p("start_date", value_type="date"), p("end_date", value_type="date"), p("trade_type", enum=("IN", "DE")), p("holder_type")), audit_params={"ts_code": "600519.SH", "start_date": "20260601", "end_date": "20260622"}, allow_extra_params=True),
)
