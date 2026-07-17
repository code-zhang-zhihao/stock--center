from app.modules.market_data.tushare.catalog.common import api, fields, p


SPECS = (
    api("stock_basic", "stock.basic", 25, min_points=120, params=(p("ts_code"), p("name"), p("exchange", enum=("", "SSE", "SZSE", "BSE")), p("market"), p("list_status", enum=("L", "D", "P")), p("is_hs", enum=("N", "H", "S"))), output_fields=fields("ts_code", "symbol", "name", "area", "industry", "market", "list_date", "delist_date", "list_status"), audit_params={"ts_code": "600519.SH", "list_status": "L"}, status=frozenset({"documented", "called_by_business", "persisted"})),
    api("trade_cal", "stock.basic", 26, min_points=120, params=(p("exchange", enum=("SSE", "SZSE", "BSE")), p("cal_date", value_type="date"), p("start_date", value_type="date"), p("end_date", value_type="date"), p("is_open", enum=("0", "1"))), output_fields=fields("exchange", "cal_date", "is_open", "pretrade_date"), audit_params={"exchange": "SSE", "start_date": "20260613", "end_date": "20260622"}, status=frozenset({"documented", "called_by_business", "persisted"})),
    api("stock_company", "stock.basic", 112, min_points=120, params=(p("ts_code"), p("exchange", enum=("SSE", "SZSE", "BSE"))), audit_params={"ts_code": "600519.SH"}, allow_extra_params=True),
    api("namechange", "stock.basic", 100, min_points=120, params=(p("ts_code", True), p("start_date", value_type="date"), p("end_date", value_type="date")), audit_params={"ts_code": "600519.SH"}, allow_extra_params=True),
    api("new_share", "stock.basic", 123, min_points=120, params=(p("start_date", value_type="date"), p("end_date", value_type="date")), audit_params={"start_date": "20260601", "end_date": "20260622"}, allow_extra_params=True),
)
