from datetime import date

from app.modules.market_data.tushare.adapters import TushareStockDailyAdapter


def test_daily_adapter_normalizes_units_and_fields():
    adapter = TushareStockDailyAdapter()

    result = adapter.map_daily(
        [
            {
                "ts_code": "600519.SH",
                "trade_date": "20260701",
                "open": 100,
                "high": 110,
                "low": 99,
                "close": 108,
                "pre_close": 98,
                "change": 10,
                "pct_chg": 10.2041,
                "vol": 123,
                "amount": 456.7,
            }
        ],
        trade_date=date(2026, 7, 1),
        universe={"600519"},
    )

    assert result.raw_count == 1
    assert result.mapped_count == 1
    row = result.rows[0]
    assert row["stock_code"] == "600519"
    assert row["volume_hand"] == 123
    assert row["volume_share"] == 12300
    assert row["amount_yuan"] == 456700
    assert row["change_pct"] == 10.2041
    assert row["metadata_json"]["unit_conversions"]["daily.amount"] == "thousand_yuan -> yuan"


def test_daily_basic_adapter_maps_existing_table_fields():
    adapter = TushareStockDailyAdapter()

    result = adapter.map_daily_basic(
        [
            {
                "ts_code": "000001.SZ",
                "trade_date": "20260701",
                "close": 12.3,
                "turnover_rate": 1.2,
                "turnover_rate_f": 1.4,
                "volume_ratio": 0.8,
                "pe": 5.6,
                "pe_ttm": 5.7,
                "pb": 0.9,
                "ps": 1.1,
                "ps_ttm": 1.2,
                "dv_ratio": 3.0,
                "dv_ttm": 3.2,
                "total_share": 100,
                "float_share": 80,
                "free_share": 70,
                "total_mv": 12345,
                "circ_mv": 9876,
                "limit_status": "0",
            }
        ],
        trade_date=date(2026, 7, 1),
        universe={"000001"},
    )

    assert result.mapped_count == 1
    row = result.rows[0]
    assert row["stock_code"] == "000001"
    assert row["close_price"] == 12.3
    assert row["turnover_rate"] == 1.2
    assert row["limit_status"] == 0


def test_moneyflow_adapter_converts_ten_thousand_yuan_to_yuan():
    adapter = TushareStockDailyAdapter()

    result = adapter.map_moneyflow(
        [
            {
                "ts_code": "002281.SZ",
                "trade_date": "20260701",
                "buy_sm_amount": 1,
                "sell_sm_amount": 0.5,
                "buy_md_amount": 2,
                "sell_md_amount": 1,
                "buy_lg_amount": 3,
                "sell_lg_amount": 1,
                "buy_elg_amount": 4,
                "sell_elg_amount": 1.5,
                "net_mf_amount": 4.5,
            }
        ],
        trade_date=date(2026, 7, 1),
        universe={"002281"},
    )

    assert result.raw_count == 1
    assert result.mapped_count == 1
    row = result.rows[0]
    assert row["stock_code"] == "002281"
    assert row["main_net_inflow"] == 45000
    assert row["small_buy_amount"] == 10000
    assert row["small_net_inflow"] == 5000
    assert row["big_order_net_inflow"] == 20000
    assert row["super_large_net_inflow"] == 25000
    assert row["metadata_json"]["unit_conversions"]["moneyflow.*_amount"] == "ten_thousand_yuan -> yuan"
