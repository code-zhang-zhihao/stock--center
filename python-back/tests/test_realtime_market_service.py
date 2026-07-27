import asyncio
from datetime import date, datetime, time, timezone

from app.modules.realtime_market.schemas import RealtimeBlockMeta, RealtimeSettings
from app.modules.realtime_market.service import RealtimeMarketService
from app.modules.market_data.providers import MootdxProvider


def test_minute_policy_keeps_guaranteed_targets_and_rotates_remaining_capacity():
    service = RealtimeMarketService()
    candidate_codes = [f"6{code:05d}" for code in range(5, 505)]
    service._active_codes = ["600001", "600002", "600003", "600004", *candidate_codes]
    service._pools = {
        "holding": {
            "pool_code": "holding", "pool_name": "持仓", "pool_type": "system", "stock_codes": ["600001", "600002"],
            "realtime_policy": {"is_enabled": True, "priority": 0, "quote_lane": "hot", "minute_lane": "guaranteed"},
        },
        "focus": {
            "pool_code": "focus", "pool_name": "重点", "pool_type": "system", "stock_codes": ["600003"],
            "realtime_policy": {"is_enabled": True, "priority": 10, "quote_lane": "hot", "minute_lane": "guaranteed"},
        },
        "candidate": {
            "pool_code": "candidate", "pool_name": "候选", "pool_type": "system", "stock_codes": candidate_codes,
            "realtime_policy": {"is_enabled": True, "priority": 20, "quote_lane": "hot", "minute_lane": "rotating"},
        },
    }
    service._page_targets = {"600004": 9_999_999_999.0}
    settings = RealtimeSettings(minute_guaranteed_target_count=200, minute_registered_target_limit=500)

    _, first, first_plan = service._minute_target_plan(settings)
    _, second, second_plan = service._minute_target_plan(settings)
    first_codes = [item["stock_code"] for item in first]
    second_codes = [item["stock_code"] for item in second]

    assert len(first) == 200
    assert first_codes[:4] == ["600001", "600002", "600003", "600004"]
    assert second_codes[:4] == first_codes[:4]
    assert first_codes[4:] != second_codes[4:]
    assert first_plan["guaranteed_selected_count"] == 4
    assert first_plan["rotating_selected_count"] == 196
    assert second_plan["rotating_selected_count"] == 196


def test_minute_registration_never_falls_back_to_unrelated_active_universe():
    service = RealtimeMarketService()
    service._active_codes = [f"6{code:05d}" for code in range(1, 601)]
    settings = RealtimeSettings(minute_guaranteed_target_count=200, minute_registered_target_limit=500)

    registered, selected, plan = service._minute_target_plan(settings)

    assert registered == []
    assert selected == []
    assert plan["unregistered_count"] == 0


def test_realtime_target_merges_all_pool_memberships_with_explainable_effective_policy():
    service = RealtimeMarketService()
    service._active_codes = ["600001"]
    service._stock_names = {"600001": "测试股"}
    service._pools = {
        "candidate": {
            "pool_code": "candidate", "pool_name": "候选", "pool_type": "system", "stock_codes": ["600001"],
            "realtime_policy": {"is_enabled": True, "priority": 20, "quote_lane": "hot", "minute_lane": "rotating"},
        },
        "holding": {
            "pool_code": "holding", "pool_name": "持仓", "pool_type": "system", "stock_codes": ["600001"],
            "realtime_policy": {"is_enabled": True, "priority": 0, "quote_lane": "hot", "minute_lane": "guaranteed"},
        },
    }

    targets = service._realtime_targets(RealtimeSettings(strong_candidate_limit=0))

    assert len(targets) == 1
    target = targets[0]
    assert target["reason"] == "pool:holding"
    assert target["priority"] == 0
    assert target["quote_lane"] == "hot"
    assert target["minute_lane"] == "guaranteed"
    assert {item["pool_code"] for item in target["memberships"]} == {"holding", "candidate"}


def test_strong_watch_candidates_only_come_from_the_latest_full_market_round():
    service = RealtimeMarketService()
    service._active_codes = ["600001", "600002"]
    # An older direct page quote must not promote itself as a market-wide
    # strong stock after the next universe round has been accepted.
    service._quotes = {
        "600001": {"stock_code": "600001", "change_pct": 9.0, "amount_yuan": 1_000_000},
    }
    service._market_round_quotes = {
        "600002": {"stock_code": "600002", "change_pct": 2.0, "amount_yuan": 2_000_000},
    }

    targets = service._realtime_targets(RealtimeSettings(strong_candidate_limit=1))

    assert [item["stock_code"] for item in targets] == ["600002"]
    assert targets[0]["reason"] == "strong"


def test_minute_guaranteed_overflow_is_explicit_and_never_silently_dropped():
    service = RealtimeMarketService()
    codes = [f"6{code:05d}" for code in range(1, 251)]
    service._active_codes = codes
    service._pools = {
        "holding": {
            "pool_code": "holding", "pool_name": "持仓", "pool_type": "system", "stock_codes": codes,
            "realtime_policy": {"is_enabled": True, "priority": 0, "quote_lane": "hot", "minute_lane": "guaranteed"},
        },
    }

    registered, selected, plan = service._minute_target_plan(
        RealtimeSettings(minute_guaranteed_target_count=200, minute_registered_target_limit=500, strong_candidate_limit=0)
    )

    assert len(registered) == 250
    assert len(selected) == 200
    assert plan == {
        "guaranteed_selected_count": 200,
        "guaranteed_overflow_count": 50,
        "rotating_selected_count": 0,
        "unregistered_count": 0,
    }


def test_market_overview_uses_only_the_current_full_market_round():
    service = RealtimeMarketService()
    service._active_codes = ["600001", "600002"]
    service._quotes = {
        "600001": {"stock_code": "600001", "change_pct": 1.0, "amount_yuan": 1},
        "600002": {"stock_code": "600002", "change_pct": 2.0, "amount_yuan": 1},
        # This is a retained, older page-watch quote and must not leak into
        # the aggregate of a newly accepted full-market provider round.
        "600003": {"stock_code": "600003", "change_pct": 9.0, "amount_yuan": 1},
    }
    current_round = {
        "600001": {"stock_code": "600001", "change_pct": -1.0, "amount_yuan": 10, "source": "tickflow"},
        "600002": {"stock_code": "600002", "change_pct": 3.0, "amount_yuan": 20, "source": "tickflow"},
    }

    overview = service._build_market_overview("round-current", current_round)

    assert overview["round_id"] == "round-current"
    assert overview["items"]["quote_count"] == 2
    assert overview["items"]["average_change_pct"] == 1.0
    assert overview["items"]["median_change_pct"] == 1.0
    assert overview["items"]["total_amount_yuan"] == 30
    assert overview["items"]["limit_events"]["available"] is False


def test_market_overview_combines_live_structure_with_completed_daily_ma_reference():
    service = RealtimeMarketService()
    service._active_codes = ["600001", "600002"]
    service._daily_factor_trade_date = date(2026, 7, 24)
    service._daily_factor_reference = {
        "600001": {"ma5": 10.0, "ma20": 10.5, "ma60": 10.8},
        "600002": {"ma5": 7.5, "ma20": 7.5, "ma60": 7.5},
    }
    current_round = {
        "600001": {
            "stock_code": "600001", "last_price": 11.0, "open_price": 10.0, "high_price": 11.0, "low_price": 9.0,
            "change_pct": 2.0, "amount_yuan": 100.0, "volume_hand": 300.0,
        },
        "600002": {
            "stock_code": "600002", "last_price": 7.0, "open_price": 8.0, "high_price": 8.0, "low_price": 7.0,
            "change_pct": -2.0, "amount_yuan": 200.0, "volume_hand": 100.0,
        },
    }

    overview = service._build_market_overview("round-current", current_round)

    trend = overview["items"]["daily_factor_trend"]
    assert trend["available"] is True
    assert trend["reference_trade_date"] == "2026-07-24"
    assert trend["ma5"] == {"above_count": 1, "comparable_count": 2, "above_pct": 50.0}
    assert trend["above_all"] == {"above_count": 1, "comparable_count": 2, "above_pct": 50.0}
    assert overview["items"]["intraday_structure"] == {
        "open_comparable_count": 2,
        "above_open_count": 1,
        "below_open_count": 1,
        "range_comparable_count": 2,
        "at_high_count": 1,
        "at_low_count": 1,
    }
    assert overview["items"]["top_amount"][0]["stock_code"] == "600002"
    assert overview["items"]["top_volume"][0]["stock_code"] == "600001"


def test_post_close_structure_builds_ladder_only_from_completed_limit_events():
    target_date = date(2026, 7, 24)
    raw = {
        "trade_date": target_date,
        "trade_dates": [target_date, date(2026, 7, 23), date(2026, 7, 22), date(2026, 7, 21)],
        "active_count": 4,
        "daily_bar_count": 4,
        "limit_event_complete": True,
        "completion_capabilities": ["daily_market_close_stock_limit"],
        "events": [
            {"stock_code": "600001", "stock_name": "三连板", "trade_date": target_date, "event_type": "limit_up", "first_time": time(9, 31), "open_count": 0},
            {"stock_code": "600001", "stock_name": "三连板", "trade_date": date(2026, 7, 23), "event_type": "limit_up"},
            {"stock_code": "600001", "stock_name": "三连板", "trade_date": date(2026, 7, 22), "event_type": "limit_up"},
            {"stock_code": "600002", "stock_name": "二连板", "trade_date": target_date, "event_type": "limit_up", "first_time": time(9, 40), "open_count": 1},
            {"stock_code": "600002", "stock_name": "二连板", "trade_date": date(2026, 7, 23), "event_type": "limit_up"},
            {"stock_code": "600003", "stock_name": "首板", "trade_date": target_date, "event_type": "limit_up", "first_time": time(9, 25), "open_count": 0},
            {"stock_code": "600004", "stock_name": "炸板", "trade_date": target_date, "event_type": "limit_break", "open_count": 3, "turnover_amount": 200_000_000},
            {"stock_code": "600005", "stock_name": "跌停", "trade_date": target_date, "event_type": "limit_down"},
        ],
    }

    structure = RealtimeMarketService._build_post_close_structure(raw)

    assert structure["available"] is True
    assert structure["trade_date"] == "2026-07-24"
    assert structure["daily_bar_coverage_pct"] == 100.0
    assert structure["summary"] == {
        "limit_up_count": 3,
        "limit_down_count": 1,
        "limit_break_count": 1,
        "seal_rate_pct": 75.0,
        "highest_board_count": 3,
        "highest_board_stock_count": 1,
    }
    assert [(item["board_count"], item["stocks"][0]["stock_name"]) for item in structure["ladders"]] == [
        (3, "三连板"),
        (2, "二连板"),
        (1, "首板"),
    ]
    assert structure["limit_breaks"][0]["stock_name"] == "炸板"
    assert structure["limit_breaks"][0]["open_count"] == 3


def test_post_close_structure_does_not_treat_unfinished_zero_event_date_as_zero_limit_market():
    structure = RealtimeMarketService._build_post_close_structure(
        {
            "trade_date": date(2026, 7, 24),
            "trade_dates": [date(2026, 7, 24)],
            "active_count": 2,
            "daily_bar_count": 2,
            "limit_event_complete": False,
            "completion_capabilities": [],
            "events": [],
        }
    )

    assert structure["available"] is False
    assert structure["reason"] == "limit_event_ingest_incomplete"
    assert structure["summary"] is None


def test_concept_strength_exposes_explainable_heat_and_intraday_rank_delta():
    service = RealtimeMarketService()
    codes = [f"60000{index}" for index in range(1, 7)]
    sector_codes = [f"C{index}" for index in range(1, 7)]
    service._active_codes = codes
    service._sector_info = {
        sector_code: {
            "sector_code": sector_code,
            "sector_name": f"概念{index}",
            "sector_type": "concept",
            "source": "tushare",
        }
        for index, sector_code in enumerate(sector_codes, start=1)
    }
    service._sector_members = {sector_code: [code] for sector_code, code in zip(sector_codes, codes)}

    first_round = {
        code: {"stock_code": code, "stock_name": code, "change_pct": float(3 - index), "amount_yuan": 10_000_000}
        for index, code in enumerate(codes, start=1)
    }
    service._market_overview = service._build_market_overview("first", first_round)
    service._sector_strength = service._build_sector_strength("first", first_round)
    service._record_market_history("first")

    first = service._sector_strength["C1"]
    assert first["rank"] == 1
    assert first["confidence"] == "high"
    assert set(first["heat_breakdown"]) == {"change", "breadth", "limit", "liquidity"}
    assert first["leader"]["stock_code"] == "600001"
    assert first["laggard"]["stock_code"] == "600001"

    second_round = {
        code: {"stock_code": code, "stock_name": code, "change_pct": float(index - 4), "amount_yuan": 10_000_000}
        for index, code in enumerate(codes, start=1)
    }
    service._market_overview = service._build_market_overview("second", second_round)
    service._sector_strength = service._build_sector_strength("second", second_round)
    service._record_market_history("second")

    assert service._sector_strength["C6"]["rank"] == 1
    assert service._sector_strength["C6"]["rank_change"] == 5
    assert len(service._market_timeline) == 2
    assert any(item["event_type"] == "concept_rank_up" for item in service._market_events)
    assert all(item["round_id"] == "second" for item in service._market_events)


def test_tickflow_rate_budgets_use_ninety_percent_of_purchased_limits():
    service = RealtimeMarketService()
    service._configure_rate_budgets(
        {
            "quote_symbol_requests_per_minute": 60,
            "quote_universe_requests_per_minute": 20,
            "depth_batch_requests_per_minute": 60,
            "realtime_safety_ratio": 0.9,
        }
    )

    assert service._rate_budgets["quote_symbols"].safe_limit == 54
    assert service._rate_budgets["quote_universe"].safe_limit == 18
    assert service._rate_budgets["depth_batch"].safe_limit == 54
    assert service._warm_quote_symbol_capacity(RealtimeSettings()) == 1200


def test_realtime_block_status_reports_cache_age_at_read_time():
    fresh = RealtimeBlockMeta(block="market", finished_at=datetime.now(timezone.utc), cache_freshness_seconds=0)

    rendered = RealtimeMarketService._block_with_freshness(fresh)

    assert rendered.cache_freshness_seconds is not None
    assert 0 <= rendered.cache_freshness_seconds <= 1


def test_minute_features_do_not_invent_amount_or_vwap():
    features = RealtimeMarketService._minute_features(
        [
            {"price": 10.0, "volume_share": 100},
            {"price": 10.1, "volume_share": 200},
            {"price": 10.2, "volume_share": 300},
        ]
    )

    assert features["minute_return_1m"] == 0.9901
    assert features["vwap"] is None
    assert features["amount_based_features_available"] is False
    assert features["minute_volume"] == 300


def test_stock_cache_meta_marks_empty_cache_and_disabled_runtime():
    service = RealtimeMarketService()
    errors = service._stock_cache_errors("600519", RealtimeSettings(enabled=False))

    assert errors == ["realtime_runtime_disabled"]
    service._settings = RealtimeSettings(enabled=True)
    assert service._stock_cache_errors("600519", service._settings) == ["realtime_cache_miss"]


def test_on_demand_fetch_fills_individual_quote_and_minute_cache(monkeypatch):
    class QuoteProvider:
        async def quote(self, stock_code):
            return {
                "stock_code": stock_code,
                "quote_time": __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                "last_price": 10.2,
                "pre_close_price": 10.0,
                "change_amount": 0.2,
                "change_pct": 2.0,
                "open_price": 10.0,
                "high_price": 10.3,
                "low_price": 9.9,
                "volume_hand": 100,
                "amount_yuan": 100000,
            }, []

        def close(self):
            pass

    class MinuteProvider:
        async def minute_bars(self, stock_code):
            return [{
                "stock_code": stock_code,
                "bar_time": __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                "price": 10.2,
                "volume_hand": 100,
                "volume_share": 10000,
                "amount_yuan": None,
            }], []

        def close(self):
            pass

    async def run() -> None:
        service = RealtimeMarketService()
        async def ensure_provider_pools(_settings):
            return None

        service._ensure_provider_pools = ensure_provider_pools
        service._new_quote_provider = lambda _provider_code: QuoteProvider()
        service._new_minute_provider = lambda: MinuteProvider()
        service._is_continuous_market_session = lambda _now: True
        service._persist_minute_cache = lambda *_args, **_kwargs: asyncio.sleep(0)
        service._leader_active = True
        async def fake_key(*parts):
            return ":".join(parts)
        async def ignore_cache_write(*_args, **_kwargs):
            return True
        monkeypatch.setattr("app.modules.realtime_market.service.redis_client.key", fake_key)
        monkeypatch.setattr("app.modules.realtime_market.service.redis_client.set_json", ignore_cache_write)
        result = await service._fetch_stock_on_demand("600519", RealtimeSettings(enabled=True))

        assert result == "on_demand"
        assert service._quotes["600519"]["last_price"] == 10.2
        assert service._minute_meta_by_stock["600519"]["status"] == "available"
        assert len(service._minutes["600519"]) == 1

    asyncio.run(run())


def test_on_demand_cache_miss_does_not_spend_quota_from_a_follower_instance():
    async def run() -> None:
        service = RealtimeMarketService()

        async def not_leader(_settings):
            return False

        async def no_shared_cache(_code):
            return None

        service._acquire_leader = not_leader
        service._hydrate_stock_cache = no_shared_cache
        service._new_quote_provider = lambda _provider_code: (_ for _ in ()).throw(AssertionError("follower must not create a provider"))

        result = await service._fetch_stock_on_demand("600519", RealtimeSettings(enabled=True))

        assert result == "shared_cache"
        assert "owned by another runtime instance" in service._on_demand_errors["600519"]

    asyncio.run(run())


def test_empty_quote_batch_is_a_degraded_input_not_a_successful_round(monkeypatch):
    class EmptyQuoteProvider:
        async def quote_batch(self, stock_codes):
            return [], []

    async def run() -> None:
        service = RealtimeMarketService()
        service._active_codes = ["600519"]
        service._quote_providers = [EmptyQuoteProvider()]
        async def ensure_provider_pools(_settings):
            return None
        service._ensure_provider_pools = ensure_provider_pools
        rows, errors, transport_failed = await service._fetch_quotes(RealtimeSettings(quote_provider_pool_size=1))
        assert rows == []
        assert errors == ["quote_batch[600519..600519]: no_quote_data"]
        assert transport_failed is False

    asyncio.run(run())


def test_decision_target_pool_preserves_overflow_in_warm_watch_list():
    service = RealtimeMarketService()
    candidate_codes = [f"6{code:05d}" for code in range(1, 251)]
    service._active_codes = candidate_codes
    service._stock_names = {code: code for code in candidate_codes}
    service._pools = {
        "candidate": {
            "pool_code": "candidate",
            "pool_name": "候选",
            "pool_type": "system",
            "stock_codes": candidate_codes,
            "realtime_policy": {"is_enabled": True, "priority": 20, "quote_lane": "hot", "minute_lane": "rotating"},
        },
    }
    service._quotes = {code: {"stock_code": code, "change_pct": index / 100, "amount_yuan": 1_000_000} for index, code in enumerate(candidate_codes)}

    hot, warm = service._build_decision_targets(RealtimeSettings(decision_target_limit=200))

    assert len(hot) == 200
    assert len(warm) == 50
    assert {item["stock_code"] for item in hot}.isdisjoint({item["stock_code"] for item in warm})
    assert all(item["reason"] == "pool:candidate" for item in [*hot, *warm])


def test_mootdx_quote_retries_next_server_when_first_response_is_empty():
    provider = MootdxProvider()
    attempts: list[str] = []

    class Client:
        def __init__(self, label: str) -> None:
            self.label = label

    provider._server_candidates = lambda: [("first", ("127.0.0.1", 1)), ("second", ("127.0.0.1", 2))]
    provider._quote_client = lambda *, server=None, bestip=None: Client("first" if server[1] == 1 else "second")
    provider._close_client = lambda: setattr(provider, "_client", None)

    def operation(client):
        attempts.append(client.label)
        return [] if client.label == "first" else [{"code": "600519"}]

    result = provider._call_quotes(operation, require_records=True)
    assert result == [{"code": "600519"}]
    assert attempts == ["first", "second"]
