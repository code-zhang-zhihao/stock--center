from app.modules.market_data.tushare_catalog import TushareApiRequest, TUSHARE_A_SHARE_CATALOG, validate_tushare_request


def test_current_provider_apis_are_catalogued() -> None:
    expected = {"stock_basic", "daily", "trade_cal", "index_classify", "index_member_all", "ths_index", "ths_member", "index_basic", "index_daily", "index_weight", "moneyflow", "hsgt_top10", "top_list", "anns_d", "daily_basic", "stk_factor_pro", "cyq_perf", "cyq_chips", "adj_factor", "income", "balancesheet", "cashflow", "fina_indicator", "dividend", "margin", "margin_detail", "limit_list_d", "stk_holdernumber", "top10_holders", "daily_info", "index_dailybasic", "sw_daily", "ci_index_member", "ci_daily"}
    assert expected <= set(TUSHARE_A_SHARE_CATALOG)


def test_catalog_is_split_into_official_stock_and_index_categories() -> None:
    assert TUSHARE_A_SHARE_CATALOG["moneyflow"].category == "stock.fund_flow"
    assert TUSHARE_A_SHARE_CATALOG["daily_info"].category == "index.market_statistics"
    assert TUSHARE_A_SHARE_CATALOG["daily_info"].doc_url.endswith("doc_id=215")


def test_catalog_normalizes_dates_and_checks_required_parameters() -> None:
    request = validate_tushare_request(TushareApiRequest("daily", {"ts_code": "600519.SH", "start_date": "20260613", "end_date": "20260622"}, ("ts_code", "close")))
    assert request.params["start_date"] == "20260613"
    try:
        validate_tushare_request(TushareApiRequest("limit_list_d", {}))
    except ValueError as exc:
        assert "trade_date" in str(exc)
    else:
        raise AssertionError("required parameters must be rejected")
