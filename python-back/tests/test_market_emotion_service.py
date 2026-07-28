from datetime import date
from types import SimpleNamespace

from app.modules.market_insight.emotion_service import (
    MarketEmotionService,
    _auxiliary_state,
    _forward_validation,
    _is_one_word_limit,
    _primary_stage,
    _rolling_percentile,
    default_emotion_parameters,
    validate_emotion_model_parameters,
)


def test_emotion_default_scorecards_and_stage_thresholds_are_publishable():
    validate_emotion_model_parameters(default_emotion_parameters())


def test_emotion_rejects_unbalanced_scorecard_and_unsorted_stages():
    parameters = default_emotion_parameters()
    parameters["short_term"]["north_money"] = 5
    try:
        validate_emotion_model_parameters(parameters)
    except ValueError as exc:
        assert "权重必须合计 100" in str(exc)
    else:
        raise AssertionError("unbalanced card must not be accepted")

    parameters = default_emotion_parameters()
    parameters["stage_thresholds"]["active"] = 45
    try:
        validate_emotion_model_parameters(parameters)
    except ValueError as exc:
        assert "阶段阈值" in str(exc)
    else:
        raise AssertionError("unordered stages must not be accepted")


def test_percentile_uses_midrank_and_reverse_direction():
    assert _rolling_percentile(2, [1, 2, 2, 3], direction="positive") == 50
    assert _rolling_percentile(2, [1, 2, 2, 3], direction="negative") == 50
    assert _rolling_percentile(3, [1, 2, 2, 3], direction="negative") == 12.5


def test_one_word_board_requires_all_declared_conditions():
    assert _is_one_word_limit({"limit_price": 10, "open_price": 10, "open_count": 0}) is True
    assert _is_one_word_limit({"limit_price": 10, "open_price": 9.9, "open_count": 0}) is False
    assert _is_one_word_limit({"limit_price": 10, "open_price": 10, "open_count": None}) is False


def test_cycle_priority_and_auxiliary_divergence_evidence():
    stage, evidence = _primary_stage(
        short_score=22,
        risk_score=30,
        raw={"natural_limit_up_count": 1, "qualified_limit_down_count": 5},
        previous_short_scores=[30, 28],
        thresholds=default_emotion_parameters()["stage_thresholds"],
    )
    assert stage == "ice_point"
    assert evidence[0]["rule"] == "ice_point"

    auxiliary, aux_evidence = _auxiliary_state(
        raw={"limit_break_rate": 43, "qualified_limit_down_count": 1, "natural_limit_up_count": 3},
        short_score=62,
        previous_short_scores=[80, 78],
    )
    assert auxiliary == "divergence"
    assert "炸板率 43.0%" in aux_evidence[0]["detail"]


def test_calibration_forward_validation_is_separate_from_score_inputs():
    dates = [date(2026, 7, 20), date(2026, 7, 21), date(2026, 7, 22), date(2026, 7, 23)]
    validation = _forward_validation(
        rows=[
            {"trade_date": dates[0], "status": "ready", "short_term_score": 75},
            {"trade_date": dates[1], "status": "ready", "short_term_score": 35},
            {"trade_date": dates[2], "status": "pending", "short_term_score": None},
            {"trade_date": dates[3], "status": "ready", "short_term_score": 80},
        ],
        target_dates=dates,
        raw_by_date={
            dates[1]: {"up_ratio_pct": 66, "core_index_trend": 1.2},
            dates[2]: {"up_ratio_pct": 40, "core_index_trend": -0.8},
            dates[3]: {"up_ratio_pct": 70, "core_index_trend": 0.5},
        },
    )
    assert validation["t_plus_1"]["sample_count"] == 2
    assert validation["t_plus_1"]["high_short_score_average_breadth_pct"] == 66
    assert validation["t_plus_3"]["sample_count"] == 1
    assert "不参与" in validation["note"]


async def test_baseline_progress_serializes_trade_dates_for_jsonb():
    class Repository:
        values = None
        committed = False

        async def update_emotion_model(self, _model, values):
            self.values = values

        async def commit(self):
            self.committed = True

    repository = Repository()
    service = MarketEmotionService(repository)

    await service._set_baseline_progress(
        SimpleNamespace(),
        phase="loading_inputs",
        first_trade_date=date(2025, 7, 16),
        last_trade_date=date(2026, 7, 27),
    )

    assert repository.values == {
        "status": "calibrating",
        "calibration_summary": {
            "status": "running",
            "phase": "loading_inputs",
            "first_trade_date": "2025-07-16",
            "last_trade_date": "2026-07-27",
        },
    }
    assert repository.committed is True


async def test_emotion_read_allows_full_calibration_curve_but_bounds_history_limit():
    model = SimpleNamespace(
        model_code="test_model",
        model_name="测试模型",
        status="ready",
        percentile_window_days=120,
        minimum_history_days=60,
        baseline_trade_days=250,
        parameter_json={},
        calibration_summary={},
        published_at=None,
        updated_at=None,
    )
    row = SimpleNamespace(
        trade_date=date(2026, 7, 27),
        model_code="test_model",
        status="ready",
        short_term_score=70.0,
        market_risk_on_score=60.0,
        primary_stage_code="active",
        auxiliary_state_code="trial",
        metrics={},
        scorecards={},
        stage_evidence=[],
        coverage={},
        parameter_snapshot={},
        external_confirmations={},
        calculated_at=None,
    )

    class Repository:
        history_limit = None

        async def get_emotion_model(self, _model_code):
            return model

        async def emotion_daily(self, **_kwargs):
            return row

        async def emotion_history(self, *, model_code, limit):
            assert model_code == "test_model"
            self.history_limit = limit
            return [row]

    repository = Repository()
    payload = await MarketEmotionService(repository).read(model_code="test_model", history_limit=5000)

    assert repository.history_limit == 1000
    assert payload["trend"] == [
        {
            "trade_date": "2026-07-27",
            "short_term_score": 70.0,
            "market_risk_on_score": 60.0,
            "primary_stage_code": "active",
            "auxiliary_state_code": "trial",
            "status": "ready",
        }
    ]
