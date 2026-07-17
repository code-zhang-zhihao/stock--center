from app.modules.market_data.tushare.catalog.common import api, fields, p


SPECS = (
    api("daily_info", "index.market_statistics", 215, min_points=600, params=(p("trade_date", value_type="date"), p("ts_code"), p("exchange", enum=("SH", "SZ")), p("start_date", value_type="date"), p("end_date", value_type="date")), output_fields=fields("trade_date", "ts_code", "ts_name", "com_count", "total_share", "float_share", "total_mv", "float_mv", "amount", "vol", "trans_count", "pe", "tr", "exchange"), audit_params={"trade_date": "20260620", "exchange": "SH"}, status=frozenset({"documented", "called_by_business", "persisted"})),
)
