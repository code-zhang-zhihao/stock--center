from app.modules.market_data.sync_service import MarketDataSyncService


def test_delisted_stock_name_markers_are_strict() -> None:
    assert MarketDataSyncService._is_delisted_stock_name("退市创兴") is True
    assert MarketDataSyncService._is_delisted_stock_name("国华退") is True
    assert MarketDataSyncService._is_delisted_stock_name("普利退(退)") is True
    assert MarketDataSyncService._is_delisted_stock_name("示例股份（退）") is True

    assert MarketDataSyncService._is_delisted_stock_name("退役科技") is False
    assert MarketDataSyncService._is_delisted_stock_name("进退有度") is False
    assert MarketDataSyncService._is_delisted_stock_name("") is False


def test_tushare_active_row_with_delisted_name_is_normalized_before_upsert() -> None:
    service = object.__new__(MarketDataSyncService)
    rows, delisted_codes = service._normalize_stock_basic_rows(
        "tushare",
        [
            {
                "stock_code": "000004",
                "stock_name": "国华退",
                "exchange": "SZ",
                "status": "L",
                "metadata_json": {"provider_list_status": "L"},
            }
        ],
        set(),
    )

    assert len(rows) == 1
    assert rows[0]["status"] == "delisted"
    assert rows[0]["metadata_json"]["status_normalized_reason"] == "name_marker_delisted"
    assert rows[0]["metadata_json"]["provider_status_before_name_check"] == "active"
    assert delisted_codes == {"000004"}
