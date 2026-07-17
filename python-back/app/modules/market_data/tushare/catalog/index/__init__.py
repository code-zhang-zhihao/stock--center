from app.modules.market_data.tushare.catalog.index.basic import SPECS as BASIC_SPECS
from app.modules.market_data.tushare.catalog.index.component import SPECS as COMPONENT_SPECS
from app.modules.market_data.tushare.catalog.index.citic_industry import SPECS as CITIC_INDUSTRY_SPECS
from app.modules.market_data.tushare.catalog.index.market import SPECS as MARKET_SPECS
from app.modules.market_data.tushare.catalog.index.market_statistics import SPECS as MARKET_STATISTICS_SPECS
from app.modules.market_data.tushare.catalog.index.sw_industry import SPECS as SW_INDUSTRY_SPECS

SPECS = BASIC_SPECS + MARKET_SPECS + COMPONENT_SPECS + SW_INDUSTRY_SPECS + CITIC_INDUSTRY_SPECS + MARKET_STATISTICS_SPECS
