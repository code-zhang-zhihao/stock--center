from app.modules.market_data.tushare.catalog.common import api, fields, p


SPECS = (
    api("index_basic", "index.basic", 94, min_points=120, params=(p("ts_code"), p("name"), p("market", enum=("SSE", "SZSE", "CSI", "CICC", "SW", "MSCI", "OTH")), p("publisher"), p("category")), output_fields=fields("ts_code", "name", "market", "publisher", "category", "base_date", "base_point", "list_date", "weight_rule", "desc", "exp_date"), audit_params={"market": "SSE"}, status=frozenset({"documented", "called_by_business", "persisted"}), allow_extra_params=True),
    api("index_classify", "index.basic", 181, min_points=2000, params=(p("index_code"), p("level"), p("src", enum=("SW2021", "SW2014", "CI", "CSI", "SSE", "SZSE"))), audit_params={"src": "SW2021"}, status=frozenset({"documented", "called_by_business", "persisted"}), allow_extra_params=True),
    api("ths_index", "index.basic", 259, min_points=6000, params=(p("ts_code"), p("exchange", enum=("A",)), p("type", enum=("N", "I", "G"))), audit_params={"exchange": "A", "type": "N"}, status=frozenset({"documented", "called_by_business", "persisted"}), allow_extra_params=True),
)
