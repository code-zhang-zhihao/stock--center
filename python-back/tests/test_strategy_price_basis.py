from sqlalchemy import func
from sqlalchemy.dialects import postgresql

from app.modules.market_data.models import DailyBar, StockFactorDaily
from app.modules.strategy_center.repository import (
    _factor_basis_price,
    _prior_daily_window_aggregate,
)


def _postgres_sql(expression) -> str:
    return " ".join(
        str(expression.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})).split()
    ).lower()


def test_strategy_price_prefers_official_qfq_factor_and_falls_back_to_daily_bar():
    sql = _postgres_sql(
        _factor_basis_price(
            StockFactorDaily.close_qfq,
            DailyBar.close_price,
        )
    )

    assert "coalesce(t_stock_factor_daily.close_qfq, t_daily_bar.close_price)" in sql


def test_prior_price_window_uses_the_same_official_qfq_basis():
    sql = _postgres_sql(_prior_daily_window_aggregate("high_price", func.max))

    assert "prior_factor_high_price.high_qfq" in sql
    assert "prior_high_price.high_price" in sql
    assert "prior_factor_high_price.stock_code = prior_high_price.stock_code" in sql
