CAPABILITY_CHAINS: dict[str, list[str]] = {
    "news_search": ["mx_finance_search", "news_search", "kimi_web_search"],
    "announcement_search": ["announcement_search", "mx_finance_search", "kimi_web_search"],
    "event_search": ["hithink_event_query", "mx_finance_search", "kimi_web_search"],
    "report_search": ["report_search", "hithink_insresearch_query", "mx_finance_search", "kimi_web_search"],
    "finance_data_query": ["mx_finance_data", "hithink_finance_query"],
    "market_data_query": ["hithink_market_query", "mx_finance_data"],
    "stock_screening": ["hithink_astock_selector", "mx_stocks_screener"],
    "macro_query": ["mx_macro_data", "hithink_macro_query", "kimi_web_search"],
    "industry_query": ["hithink_industry_query", "industry_research_report", "kimi_web_search"],
    "business_query": ["hithink_business_query", "kimi_web_search"],
    "management_query": ["hithink_management_query", "kimi_web_search"],
    "basic_info_query": ["hithink_basicinfo_query"],
    "index_query": ["hithink_zhishu_query"],
    "fund_query": ["fund_diagnosis", "mx_finance_data"],
    "stock_diagnosis": ["stock_diagnosis", "mx_finance_data"],
    "hotspot_discovery": ["stock_market_hotspot_discovery", "news_search", "kimi_web_search"],
    "topic_research": ["topic_research_report", "mx_finance_search", "kimi_web_search"],
    "earnings_review": ["stock_earnings_review", "mx_finance_data", "announcement_search"],
    "assistant_query": ["mx_financial_assistant"],
}


CAPABILITY_MIN_RESULTS: dict[str, int] = {
    "news_search": 3,
    "announcement_search": 3,
    "event_search": 1,
    "report_search": 1,
}
