from app.modules.market_data.tushare.catalog.common import api, fields, p


SPECS = (
    api("index_weight", "index.component", 96, min_points=2000, params=(p("index_code", True), p("trade_date", value_type="date"), p("start_date", value_type="date"), p("end_date", value_type="date")), output_fields=fields("index_code", "con_code", "trade_date", "weight"), audit_params={"index_code": "000001.SH", "start_date": "20260201", "end_date": "20260622"}, status=frozenset({"documented", "called_by_business", "persisted"}), allow_extra_params=True),
    api("index_member_all", "index.component", 335, min_points=2000, params=(p("l1_code"), p("l2_code"), p("l3_code"), p("ts_code"), p("is_new", enum=("Y", "N"))), audit_params={"l1_code": "110000", "is_new": "Y"}, status=frozenset({"documented", "called_by_business", "persisted"}), allow_extra_params=True),
    api("ths_member", "index.component", 261, min_points=6000, params=(p("ts_code", True),), audit_params={"ts_code": "885001.TI"}, status=frozenset({"documented", "called_by_business", "persisted"}), allow_extra_params=True),
)
