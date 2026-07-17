from app.modules.market_data.tushare.catalog.common import api, fields, p


_DATE_RANGE = (p("ts_code"), p("trade_date", value_type="date"), p("start_date", value_type="date"), p("end_date", value_type="date"))
_BARS = fields("ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount")
SPECS = (
    api("daily", "stock.market", 27, min_points=120, params=_DATE_RANGE, output_fields=_BARS, audit_params={"ts_code": "600519.SH", "start_date": "20260613", "end_date": "20260622"}, status=frozenset({"documented", "called_by_business", "persisted"})),
    api("weekly", "stock.market", 144, min_points=120, params=_DATE_RANGE, output_fields=_BARS, audit_params={"ts_code": "600519.SH", "start_date": "20260501", "end_date": "20260622"}),
    api("monthly", "stock.market", 145, min_points=120, params=_DATE_RANGE, output_fields=_BARS, audit_params={"ts_code": "600519.SH", "start_date": "20250101", "end_date": "20260622"}),
    api("daily_basic", "stock.market", 32, min_points=120, params=_DATE_RANGE, output_fields=fields("ts_code", "trade_date", "close", "turnover_rate", "turnover_rate_f", "volume_ratio", "pe", "pe_ttm", "pb", "ps", "ps_ttm", "dv_ratio", "dv_ttm", "total_share", "float_share", "free_share", "total_mv", "circ_mv", "limit_status"), audit_params={"ts_code": "600519.SH", "start_date": "20260613", "end_date": "20260622"}, status=frozenset({"documented", "called_by_business", "persisted"})),
    api("adj_factor", "stock.market", 28, min_points=2000, params=_DATE_RANGE, output_fields=fields("ts_code", "trade_date", "adj_factor"), audit_params={"ts_code": "600519.SH", "start_date": "20260613", "end_date": "20260622"}, status=frozenset({"documented", "called_by_business", "persisted"})),
    api("stk_factor", "stock.market", 296, min_points=5000, params=_DATE_RANGE, audit_params={"ts_code": "600519.SH", "start_date": "20260613", "end_date": "20260622"}, allow_extra_params=True),
    api("stk_factor_pro", "stock.market", 328, min_points=5000, params=_DATE_RANGE, audit_params={"ts_code": "600519.SH", "start_date": "20260613", "end_date": "20260622"}, status=frozenset({"documented", "called_by_business", "persisted"}), allow_extra_params=True),
    api("suspend_d", "stock.market", 31, min_points=120, params=(p("ts_code"), p("trade_date", value_type="date"), p("suspend_type", enum=("S", "R"))), audit_params={"trade_date": "20260620"}, allow_extra_params=True),
)
