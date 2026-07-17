from app.modules.market_data.tushare.catalog.common import api, fields, p


_RANGE = (p("ts_code"), p("trade_date", value_type="date"), p("start_date", value_type="date"), p("end_date", value_type="date"))
_BARS = fields("ts_code", "trade_date", "close", "open", "high", "low", "pre_close", "change", "pct_chg", "vol", "amount")
SPECS = (
    api("index_daily", "index.market", 95, min_points=120, params=_RANGE, output_fields=_BARS, audit_params={"ts_code": "000001.SH", "start_date": "20260613", "end_date": "20260622"}, status=frozenset({"documented", "called_by_business", "persisted"}), allow_extra_params=True),
    api("index_weekly", "index.market", 171, min_points=120, params=_RANGE, output_fields=_BARS, audit_params={"ts_code": "000001.SH", "start_date": "20260501", "end_date": "20260622"}, allow_extra_params=True),
    api("index_monthly", "index.market", 172, min_points=120, params=_RANGE, output_fields=_BARS, audit_params={"ts_code": "000001.SH", "start_date": "20250101", "end_date": "20260622"}, allow_extra_params=True),
    api("index_dailybasic", "index.market", 128, min_points=2000, params=_RANGE, output_fields=fields("ts_code", "trade_date", "total_mv", "float_mv", "total_share", "float_share", "free_share", "turnover_rate", "turnover_rate_f", "pe", "pe_ttm", "pb"), audit_params={"ts_code": "000001.SH", "start_date": "20260613", "end_date": "20260622"}, status=frozenset({"documented", "called_by_business", "persisted"}), allow_extra_params=True),
    api("idx_mins", "index.market", 419, min_points=None, point_status="unknown", params=(p("ts_code", True), p("freq", True, enum=("1min", "5min", "15min", "30min", "60min")), p("start_date", value_type="datetime"), p("end_date", value_type="datetime")), output_fields=fields("ts_code", "trade_time", "open", "close", "high", "low", "vol", "amount"), audit_params={"ts_code": "000001.SH", "freq": "5min", "start_date": "2026-06-20 09:30:00", "end_date": "2026-06-20 15:00:00"}),
    api("ths_daily", "index.market", 260, min_points=6000, params=_RANGE[:1] + _RANGE[1:], audit_params={"ts_code": "885001.TI", "start_date": "20260613", "end_date": "20260622"}, status=frozenset({"documented", "called_by_business", "persisted"}), allow_extra_params=True),
    api("index_global", "index.market", 211, min_points=2000, params=_RANGE, audit_params={"ts_code": "XIN9", "start_date": "20260613", "end_date": "20260622"}, allow_extra_params=True),
    api("idx_factor_pro", "index.market", 358, min_points=5000, params=_RANGE, output_fields=fields("ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "change", "pct_change", "vol", "amount"), audit_params={"ts_code": "000001.SH", "start_date": "20260613", "end_date": "20260622"}, allow_extra_params=True),
)
