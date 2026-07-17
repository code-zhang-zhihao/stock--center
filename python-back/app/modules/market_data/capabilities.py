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
    tushare_api_name: str | None = None
    tushare_min_points: int | None = None


CAPABILITIES: dict[str, CapabilityDefinition] = {
    "stock_basic": CapabilityDefinition("stock_basic", "basic_fact", "t_stock", ("tushare", "akshare", "mootdx"), "daily", False, "股票基础资料", "stock_basic"),
    "daily_bars": CapabilityDefinition("daily_bars", "market_fact", "t_daily_bar", ("tushare", "akshare", "mootdx"), "daily", True, "股票日线行情", "daily"),
    "minute_bars": CapabilityDefinition("minute_bars", "market_fact", "t_minute_bar", ("mootdx", "akshare"), "intraday", True, "股票分钟行情"),
    "quote": CapabilityDefinition("quote", "market_fact", None, ("mootdx", "akshare"), "realtime", False, "股票实时行情与盘口；不作为 daily canonical 持久化事实"),
    "ticks": CapabilityDefinition("ticks", "market_fact", "t_tick_trade", ("mootdx", "akshare"), "realtime", True, "分笔成交"),
    "sectors": CapabilityDefinition("sectors", "basic_fact", "t_sector_basic", ("tushare", "akshare", "mootdx"), "daily", False, "板块/概念/行业基础信息", "ths_index", 6000),
    "sector_components": CapabilityDefinition(
        "sector_components", "basic_fact", "t_sector_component", ("tushare", "akshare", "mootdx"), "daily", True, "板块/概念/行业成分股", "ths_member", 6000
    ),
    "stock_sectors": CapabilityDefinition("stock_sectors", "basic_fact", "t_sector_component", ("database",), "daily", True, "股票所属板块/概念/行业"),
    "sector_bars": CapabilityDefinition("sector_bars", "market_fact", "t_sector_bar", ("akshare",), "daily", True, "板块/概念/行业行情"),
    "indexes": CapabilityDefinition("indexes", "basic_fact", "t_index_basic", ("tushare", "akshare"), "daily", False, "指数基础信息", "index_basic"),
    "index_components": CapabilityDefinition("index_components", "basic_fact", "t_index_component", ("tushare", "akshare"), "daily", True, "指数成分股", "index_weight"),
    "index_bars": CapabilityDefinition("index_bars", "market_fact", "t_index_bar", ("tushare", "akshare", "mootdx"), "daily", True, "指数行情", "index_daily"),
    "fund_flow": CapabilityDefinition("fund_flow", "event_fact", "t_stock_fund_flow_daily", ("tushare", "akshare"), "daily", True, "个股或板块资金流", "moneyflow"),
    "lhb": CapabilityDefinition("lhb", "event_fact", "t_lhb_event", ("tushare", "akshare"), "daily", True, "龙虎榜事件和席位明细", "top_list"),
    "announcements": CapabilityDefinition("announcements", "event_fact", "t_announcement", ("tushare", "akshare"), "daily", True, "公告事件", "anns_d"),
    "indicators": CapabilityDefinition("indicators", "derived_factor", None, ("database",), "on_demand", False, "量化指标查询"),
}


def capability_definition(capability_code: str) -> CapabilityDefinition:
    return CAPABILITIES[capability_code]
