from app.modules.realtime_market.a_share_limit import AShareLimitPriceService


def test_main_board_limit_prices_round_to_the_a_share_tick():
    result = AShareLimitPriceService().calculate(
        stock_code="000017",
        exchange="SZ",
        pre_close_price=10.58,
        last_price=9.52,
        is_new_listing_first_five_open_days=False,
    )

    assert result["available"] is True
    assert result["board"] == "main"
    assert result["limit_ratio_pct"] == 10.0
    assert result["limit_up"] == 11.64
    assert result["limit_down"] == 9.52
    assert result["is_limit_down"] is True
    assert result["change_amount"] == -1.06
    assert result["change_pct"] == -10.018904


def test_low_priced_security_moves_at_least_one_tick():
    result = AShareLimitPriceService().calculate(
        stock_code="600001",
        exchange="SH",
        pre_close_price="0.04",
        last_price="0.04",
        is_new_listing_first_five_open_days=False,
    )

    assert result["limit_up"] == 0.05
    assert result["limit_down"] == 0.03


def test_board_rules_cover_star_gem_and_bse():
    service = AShareLimitPriceService()
    for stock_code, exchange, expected_board, expected_ratio in (
        ("688170", "SH", "star", 20.0),
        ("300300", "SZ", "gem", 20.0),
        ("920001", "BJ", "bse", 30.0),
    ):
        result = service.calculate(
            stock_code=stock_code,
            exchange=exchange,
            pre_close_price=10,
            last_price=10,
            is_new_listing_first_five_open_days=False,
        )
        assert result["board"] == expected_board
        assert result["limit_ratio_pct"] == expected_ratio


def test_new_listing_and_unknown_listing_state_do_not_fabricate_limits():
    service = AShareLimitPriceService()
    for listing_state, reason in ((True, "new_listing_first_five_open_days"), (None, "listing_limit_status_unavailable")):
        result = service.calculate(
            stock_code="600001",
            exchange="SH",
            pre_close_price=10,
            last_price=10,
            is_new_listing_first_five_open_days=listing_state,
        )
        assert result["available"] is False
        assert result["reason"] == reason
