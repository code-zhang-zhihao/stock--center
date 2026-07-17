from app.modules.market_data.tushare.catalog.common import api, p


_FINANCIAL = (p("ts_code"), p("ann_date", value_type="date"), p("start_date", value_type="date"), p("end_date", value_type="date"), p("period", value_type="date"))
_AUDIT = {"ts_code": "600519.SH", "period": "20251231"}
SPECS = (
    api("income", "stock.financial", 33, min_points=2000, params=_FINANCIAL + (p("report_type"), p("comp_type")), audit_params=_AUDIT, allow_extra_params=True),
    api("balancesheet", "stock.financial", 36, min_points=2000, params=_FINANCIAL + (p("report_type"), p("comp_type")), audit_params=_AUDIT, allow_extra_params=True),
    api("cashflow", "stock.financial", 44, min_points=2000, params=_FINANCIAL + (p("report_type"), p("comp_type")), audit_params=_AUDIT, allow_extra_params=True),
    api("fina_indicator", "stock.financial", 79, min_points=2000, params=_FINANCIAL, audit_params=_AUDIT, allow_extra_params=True),
    api("forecast", "stock.financial", 45, min_points=2000, params=_FINANCIAL + (p("type"),), audit_params=_AUDIT, allow_extra_params=True),
    api("express", "stock.financial", 46, min_points=2000, params=_FINANCIAL, audit_params=_AUDIT, allow_extra_params=True),
    api("fina_audit", "stock.financial", 80, min_points=2000, params=_FINANCIAL, audit_params=_AUDIT, allow_extra_params=True),
    api("fina_mainbz", "stock.financial", 81, min_points=2000, params=(p("ts_code"), p("period", value_type="date"), p("type", enum=("P", "D")), p("start_date", value_type="date"), p("end_date", value_type="date")), audit_params=_AUDIT, allow_extra_params=True),
    api("disclosure_date", "stock.financial", 161, min_points=2000, params=(p("ts_code"), p("end_date", value_type="date"), p("pre_date", value_type="date"), p("actual_date", value_type="date")), audit_params={"ts_code": "600519.SH"}, allow_extra_params=True),
)
