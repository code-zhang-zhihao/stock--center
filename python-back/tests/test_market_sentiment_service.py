from datetime import date

from app.modules.market_insight.service import MarketSentimentService


class FakeMarketInsightRepository:
    def __init__(self, *, completion: dict[date, set[str]], active_stock_count: int = 100):
        self.dates = [
            date(2026, 7, 14), date(2026, 7, 15), date(2026, 7, 16),
            date(2026, 7, 17), date(2026, 7, 20), date(2026, 7, 21),
        ]
        self.completion = completion
        self.active_stock_count_value = active_stock_count
        self.upserted: list[dict] = []
        self.committed = False

    async def latest_daily_bar_trade_date(self):
        return self.dates[-1]

    async def open_trade_dates_between(self, *, start_date, end_date):
        return [item for item in self.dates if start_date <= item <= end_date]

    async def active_stock_count(self):
        return self.active_stock_count_value

    async def daily_bar_metrics(self, dates):
        return {
            item: {
                "daily_bar_count": 100,
                "up_count": 55 if item != self.dates[-1] else 90,
                "down_count": 35 if item != self.dates[-1] else 8,
                "flat_count": 10 if item != self.dates[-1] else 2,
                "average_change_pct": 0.6 if item != self.dates[-1] else 2.8,
                "median_change_pct": 0.4 if item != self.dates[-1] else 3.0,
                "total_amount_yuan": 100.0 if item != self.dates[-1] else 140.0,
            }
            for item in dates
        }

    async def limit_event_metrics(self, dates):
        return {
            item: {
                "limit_up_count": 3 if item >= self.dates[-3] else 1,
                "limit_down_count": 0,
                "limit_break_count": 0,
            }
            for item in dates
        }

    async def limit_up_codes(self, dates):
        return {
            item: {"600001", "600002", "600003"} if item >= self.dates[-3] else {"600010"}
            for item in dates
        }

    async def limit_event_completion_capabilities(self, dates):
        return {item: self.completion.get(item, set()) for item in dates}

    async def previous_limit_up_premiums(self, dates):
        return {item: {"stock_count": 3, "average_change_pct": 2.0} for item in dates}

    async def sentiment_scores_before(self, **_kwargs):
        return [78.0, 72.0]

    async def upsert_sentiments(self, rows):
        self.upserted = rows
        return len(rows)

    async def commit(self):
        self.committed = True


async def test_market_sentiment_refuses_to_score_without_complete_daily_facts():
    target_date = date(2026, 7, 21)
    repository = FakeMarketInsightRepository(completion={})
    # A low coverage input must be treated exactly like an unfinished event
    # ingest: record the reason but never invent a zero or neutral score.
    metrics = await repository.daily_bar_metrics(repository.dates)
    metrics[target_date]["daily_bar_count"] = 90
    repository.daily_bar_metrics = lambda dates: _return({item: metrics[item] for item in dates})

    result = await MarketSentimentService(repository).calculate(trade_date=target_date)

    assert result.ready_count == 0
    assert result.pending_count == 1
    row = repository.upserted[0]
    assert row["status"] == "pending"
    assert row["sentiment_score"] is None
    assert row["stage_code"] == "pending"
    assert row["coverage"]["unavailable_reasons"] == [
        "daily_bar_coverage_below_threshold",
        "limit_event_ingest_incomplete",
    ]


async def test_market_sentiment_records_auditable_components_and_main_up_stage():
    target_date = date(2026, 7, 21)
    repository = FakeMarketInsightRepository(
        completion={
            date(2026, 7, 17): {"daily_market_close_stock_limit"},
            date(2026, 7, 20): {"daily_market_close_stock_limit"},
            target_date: {"daily_market_close_stock_limit"},
        },
    )

    result = await MarketSentimentService(repository).calculate(trade_date=target_date)

    assert result.ready_count == 1
    row = repository.upserted[0]
    assert row["status"] == "ready"
    assert row["sentiment_score"] == 90.9
    assert row["stage_code"] == "main_up"
    assert row["metrics"]["highest_board_count"] == 3
    assert row["metrics"]["amount_vs_5d_average"] == 1.4
    assert row["components"]["breadth"] == {
        "label": "上涨扩散",
        "weight": 0.30,
        "raw_value": 90.0,
        "score": 90.0,
        "available": True,
        "formula": "上涨家数 ÷ active 股票数 × 100",
    }
    assert repository.committed is True


async def _return(value):
    return value
