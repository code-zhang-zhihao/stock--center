from __future__ import annotations

from typing import Any

from app.modules.market_data.tushare.contracts import TushareApiRequest, TushareApiResponse


class TushareCategoryClient:
    """Raw category facade; every method maps directly to one catalogued API."""

    def __init__(self, transport, api_names: set[str]) -> None:
        self._transport = transport
        self._api_names = api_names

    def __getattr__(self, api_name: str):
        if api_name not in self._api_names:
            raise AttributeError(api_name)

        async def invoke(*, fields: tuple[str, ...] = (), **params: Any) -> TushareApiResponse:
            return await self._transport.request(TushareApiRequest(api_name=api_name, params=params, fields=fields))

        return invoke


class TushareRawClient:
    """Official-directory raw-only facade, for example ``stock.market.daily``."""

    def __init__(self, transport) -> None:
        self.transport = transport
        self.stock = type("StockApi", (), {
            "basic": TushareCategoryClient(transport, {"stock_basic", "trade_cal", "stock_company", "namechange", "new_share"}),
            "market": TushareCategoryClient(transport, {"daily", "weekly", "monthly", "daily_basic", "adj_factor", "stk_factor", "stk_factor_pro", "suspend_d"}),
            "financial": TushareCategoryClient(transport, {"income", "balancesheet", "cashflow", "fina_indicator", "forecast", "express", "fina_audit", "fina_mainbz", "disclosure_date"}),
            "reference": TushareCategoryClient(transport, {"dividend", "share_float", "repurchase", "pledge_stat", "pledge_detail", "stk_holdernumber", "top10_holders", "top10_floatholders", "stk_holdertrade"}),
            "featured": TushareCategoryClient(transport, {"stk_limit", "limit_list_d", "anns_d", "ths_hot", "cyq_perf", "cyq_chips"}),
            "margin": TushareCategoryClient(transport, {"margin", "margin_detail"}),
            "fund_flow": TushareCategoryClient(transport, {"moneyflow", "moneyflow_hsgt", "hsgt_top10", "hk_hold", "moneyflow_cnt_ths", "moneyflow_ind_ths"}),
            "board_trading": TushareCategoryClient(transport, {"top_list", "top_inst"}),
        })()
        self.index = type("IndexApi", (), {
            "basic": TushareCategoryClient(transport, {"index_basic", "index_classify", "ths_index"}),
            "market": TushareCategoryClient(transport, {"index_daily", "index_weekly", "index_monthly", "index_dailybasic", "idx_mins", "ths_daily", "index_global", "idx_factor_pro"}),
            "component": TushareCategoryClient(transport, {"index_weight", "index_member_all", "ths_member"}),
            "sw_industry": TushareCategoryClient(transport, {"sw_daily"}),
            "citic_industry": TushareCategoryClient(transport, {"ci_index_member", "ci_daily"}),
            "market_statistics": TushareCategoryClient(transport, {"daily_info"}),
        })()

    async def request(self, request: TushareApiRequest) -> TushareApiResponse:
        return await self.transport.request(request)
