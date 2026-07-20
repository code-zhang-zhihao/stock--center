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


def test_limit_event_adapter_maps_market_events_and_filters_universe():
    adapter = TushareStockDailyAdapter()

    result = adapter.map_limit_events(
        [
            {
                "ts_code": "600519.SH",
                "trade_date": "20260701",
                "limit": "U",
                "close": 110,
                "limit_price": 110,
                "amount": 123456,
                "first_time": "93209",
                "last_time": "100009",
                "open_times": 0,
            },
            {
                "ts_code": "000001.SZ",
                "trade_date": "20260701",
                "limit": "D",
            },
        ],
        trade_date=date(2026, 7, 1),
        universe={"600519"},
    )

    assert result.raw_count == 2
    assert result.mapped_count == 1
    assert result.rows[0]["stock_code"] == "600519"
    assert result.rows[0]["event_type"] == "limit_up"
    assert result.rows[0]["first_time"].isoformat() == "09:32:09"
    assert result.rows[0]["last_time"].isoformat() == "10:00:09"
    assert result.rows[0]["open_count"] == 0
    assert result.rows[0]["source"] == "tushare:limit_list_d"


def test_limit_event_adapter_maps_broken_limit_pool():
    result = TushareStockDailyAdapter().map_limit_events(
        [{"ts_code": "000001.SZ", "trade_date": "20260701", "limit": "Z"}],
        trade_date=date(2026, 7, 1),
    )

    assert result.rows[0]["event_type"] == "limit_break"


def test_limit_event_adapter_treats_missing_flag_with_up_stat_as_limit_up():
    result = TushareStockDailyAdapter().map_limit_events(
        [
            {
                "ts_code": "000716.SZ",
                "trade_date": "20251216",
                "limit": None,
                "pct_chg": 10.05,
                "fd_amount": 73292292,
                "up_stat": "1/1",
                "first_time": "93142",
            }
        ],
        trade_date=date(2025, 12, 16),
    )

    assert result.rows[0]["event_type"] == "limit_up"


def test_suspend_event_adapter_accepts_suspend_date():
    adapter = TushareStockDailyAdapter()

    result = adapter.map_suspend_events(
        [{"ts_code": "000001.SZ", "suspend_date": "20260701", "suspend_type": "S"}],
        trade_date=date(2026, 7, 1),
        universe={"000001"},
    )

    assert result.mapped_count == 1
    assert result.rows[0]["event_type"] == "suspend"
    assert result.rows[0]["source"] == "tushare:suspend_d"
