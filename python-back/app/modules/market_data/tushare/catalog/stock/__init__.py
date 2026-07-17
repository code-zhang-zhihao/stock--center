from app.modules.market_data.tushare.catalog.stock.basic import SPECS as BASIC_SPECS
from app.modules.market_data.tushare.catalog.stock.board_trading import SPECS as BOARD_TRADING_SPECS
from app.modules.market_data.tushare.catalog.stock.featured import SPECS as FEATURED_SPECS
from app.modules.market_data.tushare.catalog.stock.financial import SPECS as FINANCIAL_SPECS
from app.modules.market_data.tushare.catalog.stock.fund_flow import SPECS as FUND_FLOW_SPECS
from app.modules.market_data.tushare.catalog.stock.margin import SPECS as MARGIN_SPECS
from app.modules.market_data.tushare.catalog.stock.market import SPECS as MARKET_SPECS
from app.modules.market_data.tushare.catalog.stock.reference import SPECS as REFERENCE_SPECS

SPECS = BASIC_SPECS + MARKET_SPECS + FINANCIAL_SPECS + REFERENCE_SPECS + FEATURED_SPECS + MARGIN_SPECS + FUND_FLOW_SPECS + BOARD_TRADING_SPECS
