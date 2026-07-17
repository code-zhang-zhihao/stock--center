from app.modules.market_data.tushare.catalog.index import SPECS as INDEX_SPECS
from app.modules.market_data.tushare.catalog.stock import SPECS as STOCK_SPECS
from app.modules.market_data.tushare.contracts import TushareApiSpec


def build_catalog() -> dict[str, TushareApiSpec]:
    catalog: dict[str, TushareApiSpec] = {}
    for spec in STOCK_SPECS + INDEX_SPECS:
        if spec.api_name in catalog:
            raise RuntimeError(f"Duplicate Tushare catalog API: {spec.api_name}")
        catalog[spec.api_name] = spec
    return catalog


TUSHARE_A_SHARE_CATALOG = build_catalog()
