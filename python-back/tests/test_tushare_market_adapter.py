from datetime import date

from app.modules.market_data.tushare.adapters import TushareMarketAdapter


def test_index_daily_adapter_converts_amount_to_yuan():
    adapter = TushareMarketAdapter()

    result = adapter.map_index_daily(
        [
            {
                "ts_code": "000001.SH",
                "trade_date": "20260701",
                "open": 3000,
                "high": 3010,
                "low": 2990,
                "close": 3005,
                "pct_chg": 0.5,
                "vol": 123,
                "amount": 456.7,
            }
        ],
        trade_date=date(2026, 7, 1),
        index_codes={"000001"},
    )

    assert result.raw_count == 1
    assert result.mapped_count == 1
    row = result.rows[0]
    assert row["index_code"] == "000001"
    assert row["amount_yuan"] == 456700
    assert row["metadata_json"]["unit_normalized"] == "yuan"


def test_index_daily_range_adapter_keeps_all_dates_in_requested_window():
    adapter = TushareMarketAdapter()

    result = adapter.map_index_daily_range(
        [
            {"ts_code": "000300.SH", "trade_date": "20260701", "close": 3900, "amount": 10},
            {"ts_code": "000300.SH", "trade_date": "20260702", "close": 3910, "amount": 20},
            {"ts_code": "000905.SH", "trade_date": "20260702", "close": 6000, "amount": 30},
        ],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 2),
        index_codes={"000300"},
    )

    assert result.raw_count == 3
    assert result.mapped_count == 2
    assert [row["trade_date"] for row in result.rows] == [date(2026, 7, 1), date(2026, 7, 2)]
    assert result.rows[-1]["amount_yuan"] == 20000


def test_sector_moneyflow_adapter_converts_amounts_to_yuan():
    adapter = TushareMarketAdapter()

    result = adapter.map_sector_moneyflow(
        [
            {
                "ts_code": "885001.TI",
                "trade_date": "20260701",
                "name": "测试概念",
                "net_buy_amount": 1,
                "net_sell_amount": 0.5,
                "net_amount": 0.5,
                "pct_change": 2.3,
            }
        ],
        api_name="moneyflow_cnt_ths",
        sector_type="concept",
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 1),
        sector_map={"885001.TI": {"sector_code": "ths_concept_885001.TI", "sector_name": "测试概念", "sector_type": "concept"}},
    )

    assert result.raw_count == 1
    assert result.mapped_count == 1
    row = result.rows[0]
    assert row["sector_code"] == "ths_concept_885001.TI"
    assert row["net_buy_amount"] == 10000
    assert row["net_sell_amount"] == 5000
    assert row["main_net_inflow"] == 5000
    assert row["metadata_json"]["unit_normalized"] == "yuan"


def test_ths_daily_range_adapter_keeps_all_rows_in_requested_window():
    adapter = TushareMarketAdapter()

    result = adapter.map_ths_daily_range(
        [
            {"ts_code": "885001.TI", "trade_date": "20260701", "close": 100, "amount": 10},
            {"ts_code": "885001.TI", "trade_date": "20260702", "close": 101, "amount": 20},
            {"ts_code": "885001.TI", "trade_date": "20260630", "close": 99, "amount": 5},
            {"ts_code": "999999.TI", "trade_date": "20260702", "close": 1, "amount": 1},
        ],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 2),
        sector_map={
            "885001.TI": {
                "sector_code": "ths_concept_885001.TI",
                "sector_name": "测试概念",
                "sector_type": "concept",
            }
        },
    )

    assert result.raw_count == 4
    assert result.mapped_count == 2
    assert [row["trade_date"] for row in result.rows] == [date(2026, 7, 1), date(2026, 7, 2)]
    assert result.rows[-1]["amount_yuan"] == 20000
    assert result.request_range == {"start_date": "2026-07-01", "end_date": "2026-07-02"}


def test_top_list_adapter_converts_amounts_to_yuan_and_filters_universe():
    adapter = TushareMarketAdapter()

    result = adapter.map_top_list(
        [
            {
                "ts_code": "600519.SH",
                "trade_date": "20260701",
                "name": "贵州茅台",
                "reason": "日涨幅偏离值达7%",
                "amount": 10,
                "l_buy": 2,
                "l_sell": 1,
                "net_amount": 1,
            },
            {"ts_code": "830001.BJ", "trade_date": "20260701", "reason": "ignored"},
        ],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 1),
        universe={"600519"},
    )

    assert result.raw_count == 2
    assert result.mapped_count == 1
    row = result.rows[0]
    assert row["stock_code"] == "600519"
    assert row["turnover_amount"] == 100000
    assert row["buy_amount"] == 20000
    assert row["sell_amount"] == 10000
    assert row["net_buy_amount"] == 10000
