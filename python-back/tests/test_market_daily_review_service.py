from datetime import date

from app.modules.market_insight.report_service import _board_counts, _build_sector_heat_rows, _percentile_scores, _sector_context_for_stock


def test_concept_heat_is_ranked_from_canonical_component_metrics() -> None:
    trade_date = date(2026, 7, 27)
    rows, lookup = _build_sector_heat_rows(
        target_dates=[trade_date],
        sentiment_status={trade_date: True},
        calculation_version="v1",
        metrics_by_date={
            trade_date: [
                {
                    "sector_code": "ths_concept_a",
                    "sector_name": "强势概念",
                    "priced_component_count": 10,
                    "rising_stock_count": 9,
                    "falling_stock_count": 1,
                    "average_change_pct": 4.0,
                    "median_change_pct": 3.8,
                    "limit_up_stock_count": 3,
                    "fund_flow_stock_count": 10,
                    "main_net_inflow": 100.0,
                },
                {
                    "sector_code": "ths_concept_b",
                    "sector_name": "普通概念",
                    "priced_component_count": 10,
                    "rising_stock_count": 4,
                    "falling_stock_count": 5,
                    "average_change_pct": 0.4,
                    "median_change_pct": 0.2,
                    "limit_up_stock_count": 0,
                    "fund_flow_stock_count": 10,
                    "main_net_inflow": 10.0,
                },
            ]
        },
    )

    assert len(rows) == 2
    assert rows[0]["sector_code"] == "ths_concept_a"
    assert rows[0]["status"] == "ready"
    assert rows[0]["heat_rank"] == 1
    assert rows[0]["heat_score"] == 97.5
    assert rows[0]["source_facts"]["sector_definition"].endswith("不使用 ths_daily 作为热度输入")
    assert lookup[(trade_date, "ths_concept_a")]["heat_rank"] == 1


def test_concept_heat_stays_pending_when_market_facts_are_pending() -> None:
    trade_date = date(2026, 7, 27)
    rows, _ = _build_sector_heat_rows(
        target_dates=[trade_date],
        sentiment_status={trade_date: False},
        calculation_version="v1",
        metrics_by_date={
            trade_date: [
                {
                    "sector_code": "ths_concept_a",
                    "sector_name": "待完成概念",
                    "priced_component_count": 3,
                    "rising_stock_count": 3,
                    "falling_stock_count": 0,
                    "average_change_pct": 1.0,
                    "median_change_pct": 1.0,
                    "limit_up_stock_count": 0,
                    "fund_flow_stock_count": 0,
                    "main_net_inflow": None,
                }
            ]
        },
    )

    assert rows[0]["status"] == "pending"
    assert rows[0]["heat_score"] is None
    assert rows[0]["coverage"]["unavailable_reasons"] == ["market_sentiment_pending"]


def test_limit_up_board_count_resets_when_a_prior_event_day_is_not_complete() -> None:
    dates = [date(2026, 7, 23), date(2026, 7, 24), date(2026, 7, 27)]
    counts = _board_counts(
        dates,
        {
            dates[0]: {"000001"},
            dates[1]: {"000001"},
            dates[2]: {"000001"},
        },
        {
            dates[0]: {"daily_market_close_stock_limit"},
            dates[1]: set(),
            dates[2]: {"daily_market_close_stock_limit"},
        },
    )

    assert counts[(dates[0], "000001")] == 1
    assert (dates[1], "000001") not in counts
    assert counts[(dates[2], "000001")] == 1


def test_limit_up_sector_context_only_keeps_current_day_hot_concepts() -> None:
    trade_date = date(2026, 7, 27)
    context = _sector_context_for_stock(
        trade_date=trade_date,
        memberships=[
            {"sector_code": "a", "sector_name": "A", "start_date": None, "end_date": None},
            {"sector_code": "expired", "sector_name": "已失效", "start_date": None, "end_date": date(2026, 7, 24)},
        ],
        heat_lookup={(trade_date, "a"): {"sector_code": "a", "sector_name": "A", "heat_score": 90.0, "heat_rank": 1}},
    )

    assert context == [{"sector_code": "a", "sector_name": "A", "heat_score": 90.0, "heat_rank": 1}]


def test_equal_concept_inputs_receive_the_same_percentile_score() -> None:
    assert _percentile_scores({"a": 1.0, "b": 1.0, "c": 3.0}) == {
        "a": 25.0,
        "b": 25.0,
        "c": 100.0,
    }
