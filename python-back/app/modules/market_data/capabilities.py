from dataclasses import dataclass


@dataclass(frozen=True)
class CapabilityDefinition:
    capability_code: str
    category: str
    normalized_table: str | None
    default_engines: tuple[str, ...]
    refresh_frequency: str
    can_generate_factor: bool
    description: str


CAPABILITIES: dict[str, CapabilityDefinition] = {
    "stock_basic": CapabilityDefinition("stock_basic", "basic_fact", "t_stock", ("akshare", "mootdx"), "daily", False, "股票基础资料"),
    "daily_bars": CapabilityDefinition("daily_bars", "market_fact", "t_daily_bar", ("akshare", "mootdx"), "daily", True, "股票日线行情"),
    "minute_bars": CapabilityDefinition("minute_bars", "market_fact", "t_minute_bar", ("mootdx", "akshare"), "intraday", True, "股票分钟行情"),
    "quote": CapabilityDefinition("quote", "market_fact", "t_quote_snapshot", ("mootdx", "akshare"), "realtime", True, "股票实时行情与盘口"),
    "ticks": CapabilityDefinition("ticks", "market_fact", "t_tick_trade", ("mootdx", "akshare"), "realtime", True, "分笔成交"),
    "sectors": CapabilityDefinition("sectors", "basic_fact", "t_sector_basic", ("akshare", "mootdx"), "daily", False, "板块/概念/行业基础信息"),
    "sector_components": CapabilityDefinition(
        "sector_components", "basic_fact", "t_sector_component", ("akshare", "mootdx"), "daily", True, "板块/概念/行业成分股"
    ),
    "stock_sectors": CapabilityDefinition("stock_sectors", "basic_fact", "t_sector_component", ("database",), "daily", True, "股票所属板块/概念/行业"),
    "sector_bars": CapabilityDefinition("sector_bars", "market_fact", "t_sector_bar", ("akshare",), "daily", True, "板块/概念/行业行情"),
    "indexes": CapabilityDefinition("indexes", "basic_fact", "t_index_basic", ("akshare",), "daily", False, "指数基础信息"),
    "index_components": CapabilityDefinition("index_components", "basic_fact", "t_index_component", ("akshare",), "daily", True, "指数成分股"),
    "index_bars": CapabilityDefinition("index_bars", "market_fact", "t_index_bar", ("akshare", "mootdx"), "daily", True, "指数行情"),
    "fund_flow": CapabilityDefinition("fund_flow", "event_fact", "t_stock_fund_flow_daily", ("akshare",), "daily", True, "个股或板块资金流"),
    "lhb": CapabilityDefinition("lhb", "event_fact", "t_lhb_event", ("akshare",), "daily", True, "龙虎榜事件和席位明细"),
    "announcements": CapabilityDefinition("announcements", "event_fact", "t_announcement", ("akshare",), "daily", True, "公告事件"),
    "indicators": CapabilityDefinition("indicators", "derived_factor", None, ("database",), "on_demand", False, "量化指标查询"),
}


def capability_definition(capability_code: str) -> CapabilityDefinition:
    return CAPABILITIES[capability_code]
