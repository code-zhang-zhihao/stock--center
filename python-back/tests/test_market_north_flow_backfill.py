from datetime import date

from app.modules.market_data.market_north_flow_backfill import (
    NORTH_FLOW_SOURCE,
    MarketNorthFlowBackfillRequest,
    _chunked,
    _map_records,
)


def test_market_north_flow_backfill_defaults_to_compact_250_day_windows():
    payload = MarketNorthFlowBackfillRequest()

    assert payload.trade_days == 250
    assert payload.request_window_trade_days == 120
    assert payload.only_missing is True


def test_market_north_flow_mapping_filters_requested_dates_and_preserves_provider_unit():
    target_date = date(2026, 7, 24)
    rows = _map_records(
        [
            {
                "trade_date": "20260724",
                "hgt": "12.5",
                "sgt": "3.2",
                "north_money": "15.7",
                "south_money": "-6.4",
            },
            {"trade_date": "20260725", "north_money": "99"},
        ],
        {target_date},
    )

    assert len(rows) == 1
    assert rows[0]["trade_date"] == target_date
    assert rows[0]["source"] == NORTH_FLOW_SOURCE
    assert rows[0]["north_money"] == 15.7
    assert rows[0]["metadata_json"]["value_unit"] == "provider_reported"


def test_market_north_flow_windows_are_trade_date_bounded():
    dates = [date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3), date(2026, 7, 6), date(2026, 7, 7)]

    assert list(_chunked(dates, 2)) == [dates[:2], dates[2:4], dates[4:]]
