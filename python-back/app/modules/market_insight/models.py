from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Float, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MarketSentimentDaily(Base):
    """Versioned, reproducible daily market-state calculation.

    The row stores both the result and its factual inputs.  A later algorithm
    version creates a separate row rather than overwriting the historical v1
    score used by a report or a strategy evaluation.
    """

    __tablename__ = "t_market_sentiment_daily"
    __table_args__ = (
        UniqueConstraint(
            "trade_date",
            "universe_code",
            "calculation_version",
            name="uq_t_market_sentiment_daily_business",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    universe_code: Mapped[str] = mapped_column(String(80), nullable=False)
    calculation_version: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    sentiment_score: Mapped[float | None] = mapped_column(Float)
    stage_code: Mapped[str | None] = mapped_column(String(40))
    components: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    coverage: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    source_facts: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
